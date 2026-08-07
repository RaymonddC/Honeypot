# UNCOVER — Module Design (deep-dive) · "Action Panel"

> Turns a confirmed investigation into legal action in one click: **account/wallet freeze request PDF**,
> **LTKM/STR draft for PPATK goAML**, and **multi-agency alert** — all hashed as evidence. Closes the
> analysis→execution gap the proposal calls out ("berminggu-minggu → satu klik"). Screen 3 of the MVP.
> Grounded in the proposal (ReportLab, PP 43/2015, goAML, POJK 27/2024) + Gary's Action Panel spec +
> Research-RegMarket (goAML has no on-chain capability; UU ITE Pasal 5 electronic evidence).

---

## Design principles
1. **One click → many artifacts.** An investigator confirms a pattern/case; the panel assembles every
   output from case data — no re-typing. The analyst only fills what *must* be human (subject identity).
2. **Compatible with existing workflows.** Output in **PPATK goAML / IASC** formats investigators
   already use — ITTU accelerates their flow, it doesn't replace it. (Adoption lever from the proposal.)
3. **Every document is evidence.** SHA-256 hashed + timestamped + stored immutably + linked to the case
   custody chain; carries the **reasoning/provenance** behind each risk flag (Glass Box) → court-defensible
   under UU ITE Pasal 5.
4. **POC/LIVE by toggle.** POC = documents generate for real but dispatch to a **mock sink** (shown as
   "would send to…"); LIVE = real multi-agency dispatch + goAML submission. Same code path.
5. **Human-gated dispatch.** Generation is automatic; **sending** requires explicit analyst confirmation
   (irreversible, outward-facing action). No auto-fire.

---

## Component architecture

```
  Investigator confirms case/pattern (Screen 1/2)
                     │  case_id + selected entities (wallets, accounts, tx) + findings
                     ▼
        ┌────────────────────────────┐
        │  Action Orchestrator        │  gathers case data, fans out to generators
        └───┬──────────┬──────────┬───┘
            ▼          ▼          ▼
   ┌────────────┐ ┌──────────┐ ┌───────────────┐
   │ Freeze Doc │ │ LTKM/STR │ │ Case Evidence │   Document Generators
   │ (ReportLab)│ │ (goAML   │ │ Pack (graph   │   Jinja2 assemble → ReportLab render
   │            │ │  draft)  │ │ snapshot,     │
   │            │ │          │ │ timeline)     │
   └─────┬──────┘ └────┬─────┘ └──────┬────────┘
         └─────────────┼──────────────┘
                       ▼
        ┌──────────────────────────────┐
        │ Evidence & Custody            │  SHA-256 hash + timestamp + object-store +
        │ (action_documents, manifest)  │  audit_log entry
        └──────────────┬───────────────┘
                       ▼  analyst previews/edits (subject identity), then confirms
        ┌──────────────────────────────┐
        │ Notification Hub              │  POC: mock sink | LIVE: real dispatch
        │ routing: crime/entity→agencies│  status tracking + Dramatiq retries
        └──────────────┬───────────────┘
              ┌────────┼─────────┬──────────┬────────┐
              ▼        ▼         ▼          ▼        ▼
            Bank    Exchange   PPATK       OJK     Polri     (→ Response Dashboard: time-to-freeze)
           (freeze) (freeze)  (goAML STR) (alert) (alert)
```

### 1. Action Orchestrator
- Input: `case_id` + selected entities (wallets/accounts/tx) + confirmed findings (risk scores,
  patterns). Pulls everything from Postgres (`chain.*`, `fiat.*`, `intel.*`, `chain.wallet_risk_scores`).
- Fans out to the document generators, then to custody, then (on confirm) to the Notification Hub.
- Idempotent + transactional: docs are persisted before dispatch; a failed dispatch never loses the docs.

### 2. Document Generators (ReportLab flowables in Python — no Jinja2)
> Server builds real PDFs directly with ReportLab `Paragraph`/`Table` flowables (`app/uncover/documents.py`).
> The frontend *separately* re-renders the same documents as **client-side HTML** for the in-app preview
> (`frontend/lib/actions/letter.ts` freeze/LTKM, `receipt.ts` dispatch) — the downloadable evidence is the
> server PDF (`GET /api/documents/{id}`, custody-hashed).
- **(a) Account/Wallet Freeze Request PDF** — auto-populated: target wallet(s)/account(s), tx hashes,
  risk scores + reasoning, timestamps, case reference, requesting agency, legal basis (UU ITE / POJK
  27/2024–23/2025). Template variants: **bank account freeze** vs **exchange wallet freeze/flag**.
- **(b) LTKM / STR draft (goAML-compatible)** — the Suspicious Transaction Report for PPATK.
  Pre-filled: reporting entity, report type=STR, transaction details (amount/date/from-to
  account+wallet), risk indicators + typology codes, narrative/grounds-for-suspicion. **Subject
  identity is a human-filled placeholder** (analyst completes). Output: **human-readable PDF + a
  goAML-shaped structured draft** (JSON now; goAML **XML** stub mapped to its schema). Full live goAML
  submission is a LIVE/Phase-3 integration (needs PPATK access — proposal months 9–12).
- **(c) Case Evidence Pack** — graph snapshot (Cytoscape export), transaction timeline, flagged
  patterns, risk scores with reasoning, and the **chain-of-custody manifest** (model/prompt versions,
  hashes). The court-ready bundle.
- **Template Engine:** versioned templates (PPATK/IASC/goAML formats) — version recorded per document
  for evidentiary reproducibility.

### 3. Evidence & Custody
- Each document: **SHA-256 hash**, timestamp, stored in object store (`content_ref`), row in
  `action.action_documents` (status `draft`), and an append-only `core.audit_log` entry. Immutable;
  any later edit produces a new versioned document, never an in-place change.

### 4. Notification Hub (multi-agency dispatch — POC/LIVE adapter)
- **Routing table:** `crime_type` + entity types → target agencies + document types. E.g. mule bank
  account → the holding **bank** (freeze request) + **PPATK** (STR); deposit wallet → the **exchange**
  (freeze/flag) + PPATK; plus **OJK/BI/Polri** alerts per case. RBAC-scoped — each agency sees only its
  packet.
- **POC:** mock sink — `notifications.status='mock'`, UI shows "would dispatch to Bank X / Exchange Y /
  PPATK". Fully demo-able, nothing leaves the system.
- **LIVE:** real channels — secure webhook/API, email, **goAML STR submission**, and **IASC** account-
  freeze integration (IASC already operates the freeze mechanism across 79+ member banks). Today's wired
  channel is a signed webhook (`ITTU_NOTIFICATION_WEBHOOK_URL`); no channel configured → fail loud.
- **Delivery (C1, production-ready):** status lifecycle `mock | queued | sending | sent | failed`
  tracked per target (`attempt_count`, `last_error`, `updated_at`) → feeds the Response Dashboard.
  - **Sync path** (default, `ITTU_NOTIFICATION_DELIVERY=sync`): the LIVE sink POSTs inline during the
    dispatch request. Simple, no worker/Redis needed.
  - **Durable worker path** (`=worker`, LIVE + Postgres): dispatch persists each notification as
    `queued` and hands delivery to the **`dispatch_notifications` Dramatiq actor** — retries with
    backoff, off-request, status tracked on the row. Idempotent on `sent` (safe at-least-once).
  - **Authenticity:** every LIVE POST carries an `X-ITTU-Idempotency-Key` (so a retry never
    double-actions a freeze/STR at the recipient) and, when `ITTU_NOTIFICATION_WEBHOOK_SECRET` is set,
    an HMAC-SHA256 `X-ITTU-Signature: t=<ts>,v1=<hex>` the recipient verifies (see Security-Evidence §
    Webhook signing).
- **Outbox feed + retry:** `GET /api/notifications` (RLS-scoped, filters: status/agency_type/case) is
  the agency **Dispatch Log** (on the Response dashboard); `POST /api/notifications/{id}/retry`
  (role-gated) re-dispatches a failed one, reusing the same idempotency key.

### 5. Action Panel UI (frontend — reuse ELSA design system)
- One-click **Generate** → preview all documents inline; **edit** the LTKM subject/narrative fields;
  **Confirm & Dispatch** (explicit, human-gated); live **dispatch-status** panel; **download** PDFs.
  Show the **Glass Box reasoning** behind each risk flag inside the generated report so the analyst
  (and later a judge) sees *why* it was flagged.

---

## Data flow (one action)
Confirm case/pattern → Action Orchestrator gathers case data → Generators build Freeze PDF + LTKM
draft + Evidence Pack (Jinja2→ReportLab) → hash + store + `action_documents(draft)` + audit_log →
analyst previews, fills subject identity, **Confirms** → Notification Hub routes per agency (POC mock /
LIVE dispatch) → status tracked (Dramatiq retries) → `action_documents(issued)` + Response Dashboard
updates time-to-freeze.

---

## Legal & compliance anchors (from research)
- **PP 43/2015 (amended PP 61/2021)** — STR reporting-party format to PPATK.
- **POJK 27/2024 / 23/2025** — AML/CFT/CPF alignment; cited as freeze-request legal basis.
- **UU ITE Pasal 5** — electronic documents are valid evidence → hashing + custody make outputs
  admissible.
- **goAML** — PPATK's reporting platform; it has **no on-chain capability**, so ITTU's crypto-enriched
  STR is genuinely additive. MVP produces a goAML-shaped draft; live XML submission is Phase-3.
- **Execution reality:** ITTU *generates the request*; the actual freeze is executed by the bank/
  exchange (via the **IASC** mechanism) under their authority. The tool compresses the paperwork +
  coordination, not the legal authority.

---

## POC ↔ LIVE summary
| Aspect | POC | LIVE |
|---|---|---|
| Document generation | Real PDFs/drafts, `data_mode=poc` | Real, `data_mode=live` |
| goAML STR | goAML-shaped draft (no submission) | Live goAML XML submission |
| Dispatch | Mock sink ("would send to…") | Real multi-agency + IASC freeze |
| Custody hashing | Applied (not legal evidence) | Applied (legal evidence) |

---

## Reuse & build
| Piece | Source | Action |
|---|---|---|
| Action Panel UI shell, Glass Box reasoning in reports | ELSA design system | **Reuse** |
| PDF generation | ReportLab (proposal/stack) | **Build** templates (freeze / STR / evidence pack) |
| `action_documents`, `notifications` tables | `docs/Data-Model.md` | **Use** |
| goAML XML schema mapping | — | **Build** (draft now, live submission Phase-3) |
| Notification routing + dispatch (Dramatiq) | — | **Build** (mock adapter first) |

---

## Open questions (resolve during build)
1. **goAML XML schema** — obtain PPATK's current goAML schema version to shape the draft correctly.
2. **IASC integration surface** — API vs. manual portal for the LIVE freeze path (affects Phase-3).
3. **Freeze-request legal template** — validate wording with legal/Polri so generated requests are
   actionable, not just informational.
4. **Which agencies per crime type** — finalize the routing table with Gary (regulatory workflow SME).
