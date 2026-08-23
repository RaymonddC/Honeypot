# ITTU — Security & Evidence Spec (consolidated)

> Cross-cutting security, tenancy, and court-grade evidence contract. Consolidates the RLS model,
> chain-of-custody, explainability, and legal anchors referenced across every module doc.

## 1. Identity & access
- **Login:** Google OAuth → verify `id_token` → mint **our JWT** with `{sub, agency_id, role, exp}`
  (reuse ELSA's OAuth→JWT login UX; do NOT use Firebase Auth). Sessions revocable.
- **RBAC roles:** `regulator-analyst`, `police-investigator`, `bank-compliance`,
  `exchange-compliance`, `agency-admin`, `platform-admin`. Enforced via FastAPI dependencies.
- **Target IdP / provisioning / delegated-admin model** (Keycloak broker, role-mapping table,
  cross-agency case-sharing): see [Identity-Access-Architecture.md](Identity-Access-Architecture.md).
  Nothing there changes this RBAC + RLS core — only where identity and role assignment originate.

## 2. Multi-agency isolation — Postgres RLS (the hard backstop)
- RLS enabled on **every** agency-scoped table (day one). Middleware sets `app.current_agency` /
  `app.current_user` / `app.current_role` per request (no extra authz query).
- Baseline policy: **owning agency OR explicitly shared** via `core.case_shares` (never implicit).
  Regulators get broader `USING` branches keyed on role — never a blanket bypass.
- **App connects as a non-superuser role** (superusers bypass RLS) — enforced in deployment.
- App-level tenant filtering is defense-in-depth *on top of* RLS, never instead of it.

## 3. Chain of custody (tamper-evident evidence)
- **Hash chain:** `intel.messages` and `core.audit_log` carry `sha256` + `prev_sha256` → a tamper of any
  link breaks the chain. `action.action_documents` carries `sha256` only — each generated document is
  **independently** hashed as evidence (not chained doc-to-doc). Append-only; edits create new versions.
- **What chain verification proves, and what it does not.** A passing verification proves no entry was
  **altered or removed**: every hash still links to its predecessor, so any edit or deletion breaks
  every hash after it. It does **not** prove that every action was recorded in the first place. An
  entry that failed to be written leaves nothing behind — the entries either side of it link to each
  other normally, so there is no gap for verification to find. That is a property of every append-only
  hash chain, not a weakness specific to this one, and no in-database mechanism can close it: the
  largest cause of a failed write is the database being unavailable, which is precisely when a
  database-side marker cannot be written either. Write failures are therefore counted
  (`ittu_audit_entries_dropped_total`, by reason) and alerted on as an incident — see `Deploy.md` §8
  and the won't-do reasoning in `Backlog.md`. This distinction is stated in the API
  (`GET /api/audit`) and on the `/audit` screen too, because "✓ Chain verified" invites the stronger
  reading and an auditor is entitled to know which claim they are being handed.
- **What a verified chain proves — and what it does not.** `chain_ok: true` means no entry was
  **altered or removed**: every hash still links to its predecessor. It does **not** mean every
  action reached the log. An entry that failed to be written leaves nothing behind — the entries
  around it link normally, so verification has no gap to find. This is a property of any append-only
  hash chain, not a defect in this one, and it is why write failures are counted and alerted on
  separately (`ittu_audit_entries_dropped_total`, `Deploy.md` §8) instead of being inferred from the
  chain. Recorded here because "verified" invites the stronger reading, and anyone relying on this
  trail as evidence is entitled to know which of the two claims they are being handed.
- **One chain per agency, not one per artifact (2026-08-23).** An evidence bundle's custody view
  (`ActionBundle.audit`) is a filtered, agency-scoped slice of `core.audit_log`, not a chain of its
  own. It used to come from a second, per-process, **in-memory** chain in `app/uncover/custody.py`,
  which recorded strictly less than the core trail already did and was empty after every restart —
  and because the Action Panel derived the displayed **evidence hash** from that chain's head, the
  same bundle showed one evidence hash before a restart and another after. The evidence hash is now
  a deterministic digest of the bundle's document hashes: it moves if and only if the documents do.
  One consequence to read correctly: a bundle's entries carry their `seq` in the **agency's** chain,
  so they are deliberately non-contiguous — the numbers in between are that agency's other actions,
  not missing entries.
- **Preserved originals** stored separately from enriched/derived data.
- **`core.evidence_manifest`** per session/case records model + prompt + pipeline versions →
  reproducible & explainable in court.
- **Per-entity provenance:** every `intel.entities` row logs message → method → confidence →
  review_status. Un-validated LLM entities are never treated as actionable.
- **Voice:** call audio + STT transcript + diarization hashed alongside text.
- **Outbound dispatch authenticity (C1):** every LIVE agency notification is signed so the *recipient*
  can prove it genuinely came from ITTU and wasn't replayed or forged — the dispatch itself is
  evidence. When `ITTU_NOTIFICATION_WEBHOOK_SECRET` is set, each webhook POST carries
  `X-ITTU-Signature: t=<unix_ts>,v1=<hex>` where `hex = HMAC_SHA256(secret, f"{t}.{raw_body}")`, plus
  `X-ITTU-Timestamp`. **Recipient verification:** recompute `v1` over `"{t}.{body}"` with the shared
  secret (constant-time compare) and reject if `t` is outside a small window (replay guard). An
  `X-ITTU-Idempotency-Key` (also on the packet's stored row) makes at-least-once redelivery safe — the
  recipient dedupes so a retry never double-actions a freeze/STR. Delivery state
  (`status/attempt_count/last_error`) is tracked per notification for an audit trail.

## 4. Explainability contract (evidentiary credibility > raw accuracy)
- Every risk score / flag / correlation carries **confidence + explicit reasoning + evidence**
  (which txs/features/patterns). Surfaced in the **Glass Box** UI (ELSA reuse) and embedded in
  generated documents so an analyst — and a judge — sees *why*.
- Isolation Forest is presented as **triage**, paired with deterministic typology rules for the
  court-explainable signal.

## 5. Honeypot-specific controls (dual-use engine)
- Strictly **reactive & victim-framed** (prompt + tool-gating): never initiate/solicit fraud, access
  scammer systems, or redistribute seized data → clear of entrapment + UU ITE Arts. 30/32/33/36.
- Access control + audit + abuse monitoring + **kill switch** on the agent itself.
- **Human-in-the-loop** at high-value/bot-probe turns.

## 6. POC/LIVE evidentiary integrity

> ⚠ **NOT BUILT — as of 2026-08-23 this section describes the TARGET, not the system.**
> Verified: `data_mode` is stamped on 24 of 32 tables and constrained by a CHECK, but it is
> **never read as a filter** — 0 of 201 references appear in a WHERE clause, and no RLS policy
> mentions it. There is ONE database, and a LIVE query returns POC rows. `core.audit_log` has
> no `data_mode` column at all. What genuinely protects against demo data being mistaken for
> evidence today is narrower and output-level: generated PDFs carry a "POC DEMONSTRATION
> OUTPUT — not a legal instrument" banner, the dialer refuses to place a `live` call it cannot
> really make, and responses carry an `X-Data-Mode` header the UI badges. Tracked in
> `docs/Backlog.md`.

- `data_mode` on every produced row; **LIVE evidence views never read POC rows.**
- Production runs **separate DB instances** per mode (distinct creds) — demo data physically cannot
  enter a real case. Custody hashing applies in both modes; only LIVE is legal evidence.

## 7. Data protection & deployment security
- **PDP Law (UU 27/2022)** + **PP 71/2019** → local/on-prem hosting likely mandatory for PPATK/OJK/
  Polri. Keep everything **container-portable** (K3s/MicroK8s) so on-prem is a config choice.
- Encryption at-rest (sensitive investigation data) + in-transit (TLS). Secrets via env/Docker secrets
  (MVP) → Vault/SM (LIVE). Retention per PPATK minimums (configurable, soft-delete + purge).

## 8. Legal anchors (verified — Research-RegMarket)
- **UU ITE Pasal 5** (as amended UU 19/2016, UU 1/2024) — electronic docs are valid evidence.
- **PP 43/2015 (amended PP 61/2021)** — STR reporting-party format to PPATK.
- **POJK 27/2024 / 23/2025** — AML/CFT/CPF alignment.
- Honeypot call-recording defensible under Polri supervision (reactive/victim-framed).

---

## 9. RLS isolation review (2026-08-18)

Run against the **live schema**, not by reading code — which is what found the leak.
Method and result recorded here because "we reviewed it" is worth nothing without saying
what was checked and what it missed.

### What was checked

| Check | Result |
|---|---|
| Every table with `agency_id` has RLS **and** a policy | ✅ clean (32 tables) |
| Tables with RLS **disabled** that still carry a tenant-linking column | ⚠️ **2 found** |
| Cross-tenant read test (seed as agency B, read as agency A) | ⚠️ **1 leak confirmed** |
| Endpoint auth coverage (behavioural: call without a token) | ✅ all sensitive routes 401/403 |
| Queries run as the **owning** role, where RLS does not filter | ✅ by-id only; the one search filters explicitly |

### The leak (fixed, migration `20260818_16`)

Table-level coverage looked clean — and that is exactly why the gap survived. **Join tables
have no `agency_id` of their own**, so they pass a "does every agency table have a policy"
check while being unprotected. Confirmed empirically:

```
agency A reading agency B's data:
  intel.syndicates        : 0  blocked
  intel.entities          : 0  blocked
  intel.syndicate_members : 1  LEAK
```

An agency was denied another's syndicate **and** its entity, yet could read the row *linking
them* — leaking the shape of another agency's investigation graph (which opaque ids cluster,
link type, confidence, how many links exist). The ids are unreadable alone; the structure is
still intelligence. A structural scan found a second table of the same shape:
`fiat.correlations` (`case_id` → agency-scoped `core.cases`), empty today — fixed before it
fills.

Both now use the join-through-parent policy the codebase **already** used for
`honeypot.dial_targets` / `dial_attempts`, so this was an inconsistency, not a missing
concept. Verified in both directions, because an over-broad RLS policy fails silently as
"no data": other agencies blocked, own rows still visible, migration round-trips.
Regression tests in `tests/test_rls_isolation.py`.

### Deliberate exceptions (not findings)

- **`GET /api/config`, `GET /api/bridge/sankey`** are intentionally unauthenticated — the
  first exposes only mode flags and presence booleans (never key values), the second is
  demo data. Recorded so a future reviewer doesn't "fix" them by accident.
- **`chain.*` / `fiat.fiat_*` have no RLS**: public blockchain/fiat reference data, not
  tenant data. `fiat.correlations` was the exception because it is *derived per case*.
- **Background workers connect as the owning role**, so RLS does **not** filter their
  queries — a system actor is handed a row id and must read it to learn the owner, which
  RLS cannot resolve. Actor code therefore scopes by `agency_id` explicitly; see
  `honeypot_ops.dialer.resolve_case_id`, which has a test asserting it never crosses
  agencies.

### Related fixes earlier in the same cycle

- `casedata` was missing from `scripts/create_app_role.sql`, so under Postgres persistence
  the app hit `InsufficientPrivilege` on analyst-entered data with no hint (`6d93896`).
- `core.audit_log` is append-only at the DB level: separate INSERT and SELECT policies, no
  UPDATE or DELETE policy at all.
