# ITTU — Data Model & Schema (deep-dive)

> Postgres (source of truth, RLS-enforced) + Neo4j (graph projection) + custody/evidence layer,
> covering all four modules. Foundational — INFILTRATE, TRACE, TAKEDOWN, UNCOVER, and the API all
> reference these entities. Plan-only; DDL below is design sketch, not final migrations.

---

## Design principles

1. **PostgreSQL is the single source of truth.** Neo4j is a *derived projection* for graph traversal/
   analytics, kept in sync from Postgres — never authoritative, always rebuildable.
2. **Row-Level Security (RLS) on every tenant-scoped table, day one.** A missed `WHERE` must not leak
   another agency's data. RLS is the hard backstop under app-level checks.
3. **Multi-agency by design.** Tenant = `agency`. Data is agency-owned; cross-agency visibility is
   *explicit* via `case_shares` grants (never implicit).
4. **Provenance + confidence on all derived facts.** Every extracted entity, risk score, and
   correlation carries method, confidence, model/prompt version, and review status.
5. **Tamper-evident custody.** Honeypot messages and evidence are hash-chained (SHA-256, `prev_hash`)
   so any alteration is detectable — meets UU ITE Pasal 5 electronic-evidence standard.
6. **POC and LIVE data are physically separable and never mixed.** A `data_mode` enum tags every
   data-producing row; LIVE evidence views never read POC rows. In production, real-evidence stores
   run as separate DB instances (POC ≠ LIVE credentials) so demo data can never contaminate a case.
7. **UUID primary keys** (v7 preferred — time-sortable), `created_at`/`updated_at` on all tables,
   soft-delete (`deleted_at`) where retention matters. `JSONB` for semi-structured payloads.

---

## Schema domains (Postgres, one DB, module-prefixed schemas)

```
core.*        agencies, users, roles, cases (+stage), case_shares, audit_log, evidence_manifest
intel.*       personas, scam_sessions, messages, entities, syndicates, syndicate_members,
              crime_classifications                       (INFILTRATE)
chain.*       wallets, transactions, wallet_features, wallet_risk_scores, address_tags,
              graph_snapshots                             (TRACE + TAKEDOWN)
fiat.*        fiat_accounts, fiat_transactions, correlations   (TRACE / BridgeWatch)
casedata.*    bank_accounts, crypto_transfers              (case-scoped rollup, agency RLS)
action.*      action_bundles, action_documents, notifications  (UNCOVER)
```

---

## core — tenancy, identity, cases, audit

```sql
-- Tenant. type drives role templates + visibility rules.
core.agencies(
  id uuid pk, name text, type text check (type in
     ('regulator','police','bank','exchange','other')),
  onprem bool default false,             -- data-sovereignty deployments
  created_at, updated_at)

-- Users authenticate via Google OAuth → we mint our own JWT (agency_id, role claims).
core.users(
  id uuid pk, agency_id uuid fk→agencies, oauth_sub text unique, email citext unique,
  name text, role text,                  -- see RBAC below
  is_active bool, last_login_at, created_at, updated_at)

core.roles(id, name, agency_type, permissions jsonb)   -- role→permission templates

-- The investigation. The spine that ties intel, chain, fiat, and actions together.
core.cases(
  id uuid pk, agency_id uuid fk→agencies,           -- owning agency
  title text, status text check (status in ('open','active','closed','archived')),
  stage text not null default 'intake',             -- lifecycle: intake|freeze|trace|
                                                    --   takedown|report|recovery|closed
  crime_type text, summary text,
  data_mode text check (data_mode in ('poc','live')) not null,
  created_by uuid fk→users, created_at, updated_at, deleted_at)

-- EXPLICIT cross-agency sharing (e.g. bank shares a case with PPATK). No implicit visibility.
core.case_shares(
  case_id uuid fk→cases, agency_id uuid fk→agencies,   -- grantee
  access text check (access in ('read','contribute')),
  granted_by uuid fk→users, granted_at,
  primary key (case_id, agency_id))

-- Append-only. Every mutating action + evidence-affecting read. Hash-chained per agency.
core.audit_log(
  id uuid pk, agency_id uuid, actor_user_id uuid, action text, target_type text,
  target_id uuid, detail jsonb, ts timestamptz, seq bigint,
  sha256 bytea, prev_sha256 bytea)      -- tamper-evident chain

-- Per-session reproducibility manifest for court explainability.
core.evidence_manifest(
  id uuid pk, session_id uuid, case_id uuid,
  model_versions jsonb,     -- {orchestrator, extractor, classifier, stt, tts}
  prompt_versions jsonb, pipeline_config jsonb, created_at)
```

**RBAC roles** (per agency type): `regulator-analyst`, `police-investigator`, `bank-compliance`,
`exchange-compliance`, `agency-admin`, `platform-admin`. Permissions checked via FastAPI dependencies;
enforced physically by RLS.

---

## intel — INFILTRATE (honeypot intelligence)

```sql
intel.personas(                          -- our honeypot victim personas (persona pool)
  id uuid pk, name text, profile jsonb,  -- {age, occupation, tech_literacy, region, dialect,
                                         --  financial_situation, backstory, register}
  active bool, created_at)

intel.scam_sessions(
  id uuid pk, case_id uuid fk→cases null,           -- may pre-date case creation
  agency_id uuid fk→agencies, persona_id uuid fk→personas,
  channel_type text check (channel_type in ('text','voice')),
  channel text,                          -- telegram | whatsapp | forum | pstn | wa_call
  channel_ref text,                      -- scammer handle / number (itself intel)
  crime_type text, status text,          -- active | escalated | closed
  data_mode text check (data_mode in ('poc','live')) not null,
  started_at, ended_at)

-- Hash-chained conversation log. Raw is immutable; enrichment lives elsewhere.
intel.messages(
  id uuid pk, session_id uuid fk→scam_sessions, seq int,       -- per-session ordering
  direction text check (direction in ('inbound','outbound')),
  content text,                          -- text, or STT transcript for voice
  audio_ref text null,                   -- object-store key for call audio (voice)
  ts timestamptz, sha256 bytea, prev_sha256 bytea,             -- custody chain
  meta jsonb)                            -- {latency_applied, typos_injected, diarization…}

-- Every extracted entity. Never actionable until validated + reviewed.
intel.entities(
  id uuid pk, session_id uuid fk→scam_sessions, message_id uuid fk→messages,
  agency_id uuid,
  type text check (type in
     ('bank_account','crypto_wallet','phone','url','person','org','alias')),
  value text, normalized_value text,     -- E.164 phone, checksummed wallet, etc.
  chain text null,                       -- for crypto_wallet: btc|eth|tron|bsc
  bank_name text null,                   -- for bank_account: context anchor
  method text check (method in ('regex','llm','ner','human')),
  confidence numeric,                    -- 0..1
  review_status text check (review_status in ('unverified','confirmed','rejected','poisoned')),
  provenance jsonb,                      -- {turn, method_detail, validators_passed[]}
  created_at)

intel.syndicates(
  id uuid pk, agency_id uuid, label text, notes text,
  linguistic_fingerprint jsonb, created_at)

intel.syndicate_members(                 -- entities clustered into a syndicate
  syndicate_id uuid fk→syndicates, entity_id uuid fk→entities,
  link_type text, confidence numeric, primary key (syndicate_id, entity_id))

intel.crime_classifications(
  id uuid pk, session_id uuid fk→scam_sessions,
  crime_type text,                       -- investment | judol_deposit | crypto_phishing | romance
  confidence numeric, model_version text, created_at)
```

Confirmed `crypto_wallet` / `bank_account` entities flow into `chain.wallets` / `fiat.fiat_accounts`.

---

## chain — TRACE ingestion + TAKEDOWN analytics

```sql
chain.wallets(
  id uuid pk, address text, chain text check (chain in ('btc','eth','tron','bsc')),
  first_seen timestamptz, last_seen timestamptz,
  native_balance numeric, source text,   -- honeypot | iasc | manual
  data_mode text, created_at, updated_at,
  unique(address, chain))

chain.transactions(
  id uuid pk, tx_hash text, chain text, from_addr text, to_addr text,
  value numeric, token_symbol text, token_contract text,
  ts timestamptz, block_number bigint,
  data_mode text, raw jsonb,             -- normalized provider payload (ELSA-style)
  ingested_at, unique(chain, tx_hash, from_addr, to_addr))   -- idempotent ingest

chain.wallet_features(                    -- the 12 indicators (Gary's canonical set — TAKEDOWN)
  wallet_id uuid fk→wallets, computed_at timestamptz,
  tx_velocity numeric,          -- 1 transaction frequency / active day
  total_volume numeric, mean_volume numeric,   -- 2 volume
  unique_counterparties int,    -- 3
  rapid_relay_rate numeric,     -- 4 share forwarded quickly
  round_number_pct numeric,     -- 5
  fan_ratio numeric,            -- 6 fan-in/fan-out
  account_age_days int,         -- 7
  inout_ratio numeric,          -- 8
  time_entropy numeric,         -- 9 time-distribution entropy
  chain_depth int,              -- 10 multi-hop position
  self_loop_count int,          -- 11
  max_tx_size numeric,          -- 12
  primary key (wallet_id, computed_at))
-- NB: mixer_exposure + counterparty_risk are NOT features here — they come from the Attribution
-- Overlay (chain.address_tags). peel/structuring/cyclic are the pattern DETECTORS, not features.
-- (See docs/TAKEDOWN-Design.md — features ≠ patterns.)

chain.wallet_risk_scores(
  id uuid pk, wallet_id uuid fk→wallets,
  iso_forest_score numeric,              -- anomaly triage
  typology_flags jsonb,                  -- ELSA-ported deterministic rules that fired
  composite_risk text check (composite_risk in ('low','medium','high')),
  confidence numeric, reasoning text,    -- TRM-style explicit reasoning (Glass Box)
  model_version text, computed_at)

chain.address_tags(                       -- attribution DB (the moat gap — seed early)
  id uuid pk, address text, chain text,
  tag text, category text check (category in
     ('exchange','mixer','scam','gambling','sanctioned','service','unknown')),
  source text,                           -- ofac_sdn | etherscan | arkham | chainabuse | community
  confidence numeric, added_at, unique(address, chain, source))

chain.graph_snapshots(                    -- optional cached per-case subgraph exports
  id uuid pk, case_id uuid, spec jsonb, built_at)
```

---

## fiat — TRACE (BridgeWatch fiat↔crypto)

```sql
fiat.fiat_accounts(
  id uuid pk, account_number text, bank_name text, holder_name text,
  data_mode text,                        -- poc: PaySim/synthetic; live: bank feed
  source text, created_at, unique(account_number, bank_name))

fiat.fiat_transactions(
  id uuid pk, from_account_id uuid, to_account_id uuid, amount numeric,
  ts timestamptz, channel text,          -- transfer | qris | ewallet
  data_mode text, raw jsonb, ingested_at)

-- The bridge: correlate a fiat outflow with a crypto deposit by time-window + amount.
fiat.correlations(
  id uuid pk, case_id uuid,
  fiat_tx_id uuid fk→fiat_transactions, crypto_tx_id uuid fk→chain.transactions,
  time_delta_seconds int, amount_match numeric, confidence numeric,
  method text, created_at)
```

---

## action — UNCOVER

```sql
action.action_documents(
  id uuid pk, case_id uuid fk→cases, agency_id uuid,
  type text check (type in ('account_blocking','str_report','summary')),
  format text,                           -- ppatk_str | iasc | generic
  content_ref text,                      -- object-store key (ReportLab PDF)
  status text check (status in ('draft','issued','acknowledged')),
  generated_by uuid, generated_at, sha256 bytea)   -- doc is evidence → hashed

action.notifications(
  id uuid pk, case_id uuid, target_agency_id uuid, channel text,
  payload jsonb, status text check (status in ('mock','queued','sent','failed')),
  data_mode text,                        -- poc: mock sink (status='mock'); live: real dispatch
  sent_at, created_at)
```

---

## Row-Level Security (RLS) model

Enable RLS on every agency-scoped table. Middleware, after verifying the JWT, sets per-request
Postgres session vars — **no extra query needed for authz**:

```sql
SET LOCAL app.current_agency = '<agency_uuid>';
SET LOCAL app.current_user   = '<user_uuid>';
SET LOCAL app.current_role   = '<role>';
```

Baseline policy (owning-agency OR explicitly shared case):

```sql
ALTER TABLE core.cases ENABLE ROW LEVEL SECURITY;
CREATE POLICY case_access ON core.cases USING (
  agency_id = current_setting('app.current_agency')::uuid
  OR id IN (SELECT case_id FROM core.case_shares
            WHERE agency_id = current_setting('app.current_agency')::uuid)
);
```

- **Agency-owned child tables** (intel `messages`/`entities`, `action.*`, `casedata.*`, `chain.graph_snapshots`)
  resolve their case/agency and apply the same predicate (directly on `agency_id`, or via parent `case_id`).
- **Shared raw-ledger tables are NOT RLS'd** — `chain.transactions`/`wallets`, `fiat.fiat_transactions`/`correlations`
  carry no `agency_id`: they're public-chain / reference facts shared across agencies, not agency-owned
  (deliberate exclusion, migration `20260715_06_rls_and_manifest.py`). Only per-case *snapshots* of them are scoped.
- **Regulators** (PPATK/OJK) may get a broader policy variant (e.g. read across shared cases for their
  supervised entities) — modeled as additional `USING` branches keyed on `app.current_role`, never as
  a blanket bypass.
- **Write policies** (`WITH CHECK`) prevent inserting rows for another agency.
- **The app connects as a non-superuser role** (superusers bypass RLS) — enforced in deployment.

---

## Neo4j graph model (derived projection)

Postgres → Neo4j sync (batch ETL for MVP; CDC later). Rebuildable from Postgres at any time.

**Nodes** (`:Label {key props}`):
- `:Wallet {address, chain, risk, tags[]}`
- `:BankAccount {number, bank, holder}`
- `:Person {name, aliases[]}` · `:Phone {e164}` · `:Url {value}`
- `:Syndicate {id, label}`
- `:Exchange {name}` / `:Service {category}` (from address_tags)
- `:Case {id, title}`

**Relationships** (typed, with properties):
- `(:Wallet)-[:SENT {value, token, ts, tx_hash}]->(:Wallet)`   ← chain.transactions
- `(:BankAccount)-[:TRANSFERRED {amount, ts}]->(:BankAccount)`  ← fiat.fiat_transactions
- `(:BankAccount)-[:CORRELATED {confidence, time_delta}]->(:Wallet)`  ← fiat.correlations (the bridge)
- `(:Person)-[:CONTROLS]->(:Wallet|:BankAccount)` · `(:Entity)-[:MEMBER_OF]->(:Syndicate)`
- `(:Wallet)-[:TAGGED_AS]->(:Service)` · `(any)-[:PART_OF]->(:Case)`

**Why Neo4j:** GDS runs Louvain (rings), betweenness (hubs), and multi-hop/path queries natively for
the interactive investigator graph. NetworkX still handles small per-case subgraph algorithms in-app;
Neo4j holds the persistent cross-case graph.

---

## POC ↔ LIVE data isolation (evidentiary integrity)

- Every data-producing row carries `data_mode ∈ {poc, live}`. API/session context pins the mode;
  queries filter by it. **LIVE evidence views never read POC rows.**
- Production runs **separate DB instances** for real evidence (distinct credentials/hosts) so POC/demo
  data is physically incapable of entering a real case. Neo4j likewise separated per mode.
- Chain-of-custody hashing applies in both modes, but only LIVE rows are treated as legal evidence.

---

## Open schema questions (to resolve during build)

1. **Transaction volume** — if chain.transactions grows huge, add TimescaleDB (Postgres ext) partition
   on `ts`, or revisit Elasticsearch for tx search. Defer until measured.
2. **Entity dedup/identity resolution** — canonical-entity table vs. clustering-on-read for the same
   wallet/account seen across sessions. Lean toward a `canonical_entity_id` link once patterns emerge.
3. **Retention policy** — per-mode + per-agency retention windows (PPATK minimums) as a config, with
   soft-delete + purge jobs.
4. **Neo4j sync cadence** — batch interval for MVP; evaluate Debezium CDC for near-real-time later.
