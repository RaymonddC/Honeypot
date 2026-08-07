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
