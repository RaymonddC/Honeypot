# ITTU — Response Dashboard (Screen 4)

> The metrics view that narrates ITTU's core promise: **response time from days → minutes.** Backed by
> real `cases` / `action_documents` / `notifications` data — no vanity numbers. Screen 4 of the MVP.

## Metrics

| Metric | Definition | Source |
|---|---|---|
| **Cases in progress** | count of cases `status ∈ {open, active}` | `core.cases` |
| **Avg time-to-freeze** | mean(`action_documents.issued_at` − `cases.created_at`) for freeze docs that reached `acknowledged` | `core.cases`, `action.action_documents`, `action.notifications` |
| **Funds at risk** | Σ exposure of flagged wallets/accounts in open cases | `chain.wallet_risk_scores`, `fiat.correlations`, `chain.wallets` |
| **Funds frozen** | Σ amounts on acknowledged freeze requests | `action.action_documents` (freeze) + `notifications` ack |
| **Recovery rate** | funds frozen ÷ funds at risk (case-weighted); benchmark vs. IASC 4.76% baseline | derived |
| **Sessions / entities (honeypot)** | active sessions, entities extracted (confirmed) | POC: `BASELINE_HONEYPOT` constant (`app/uncover/metrics.py`) — deterministic stand-in until INFILTRATE persistence lands; not yet from `intel.scam_sessions`/`entities` |
| **Wallets scored** | count risk-scored this period | `chain.wallet_risk_scores` |

## Behavior
- **Range filter** (`?range=7d|30d|all`), **agency-scoped** by RLS (each agency sees its own; regulators
  see shared cases).
- **"Days → minutes" hero:** show current avg time-to-freeze vs. the >12h baseline the proposal cites.
- Light polling / refresh; all values computed from real rows (POC data flows through the same
  pipeline so the demo dashboard is populated by the demo run itself).

## Build
- One `GET /metrics/response` endpoint (aggregation queries) + a dashboard page (Next.js + shadcn cards
  + recharts/simple SVG, ELSA design system). No new storage — pure read-model over existing tables.
