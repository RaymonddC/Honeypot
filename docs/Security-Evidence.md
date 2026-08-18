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
