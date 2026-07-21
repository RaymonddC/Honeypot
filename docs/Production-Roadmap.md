# ITTU — Production / Go-Live Roadmap

The map from the shipped POC to a real, multi-tenant production deployment.

**Core principle (from `Adapter-MODE-Framework.md`):** going live never rewrites the
pipeline. Every boundary is a `Protocol` with a POC and a LIVE class; you implement
the LIVE adapter (same Pydantic contract, enforced by contract tests) and flip the
MODE. So this roadmap is mostly "fill in the LIVE adapters + turn on persistence."

---

## 1. Status snapshot (per boundary)

| Boundary | Module | LIVE adapter | Status | To do |
|---|---|---|---|---|
| **LLM brain** | infiltrate | `LiteLLMGateway` | ✅ **LIVE in prod** | — (9Router/Claude, done) |
| **Blockchain** | takedown | `TronscanAdapter` | ✅ **live-validated + hardened** | flip `takedown=live`; set `ITTU_TRONSCAN_API_KEY` for limits |
| **Notifications** | uncover | `LiveNotificationSink` | 🟠 stub, easy | wire email/SMS/webhook |
| **TTS (voice)** | infiltrate | `ElevenLabs/GoogleTTSAdapter` | 🟢 **wired, needs key** | add key, verify audio |
| **STT (voice)** | infiltrate | `WhisperSTTAdapter` | 🔴 stub | streaming transcription |
| **Text channel** | infiltrate | `TelegramChannelAdapter` | 🔴 stub | bot + webhook + mapping |
| **Voice channel** | infiltrate | `PstnChannelAdapter` | 🔴 stub | Twilio + media bridge |
| **Address tags** | takedown | tag feed | 🔴 stub | OFAC/Arkham/chainabuse feed |
| **Fiat feed** | trace | `BankFeedAdapter` | 🔴 institutional | bank / PPATK partnership |
| **Persistence** | all | Postgres | 🔴 in-memory | wire stores → `intel.*` tables |
| **Auth** | auth | Google OAuth + RLS | 🟢 **OAuth hardened, RLS live** | Keycloak IdP + delegated-admin roster → F3 |

Legend: ✅ live · 🟢 built/near · 🟠 easy stub · 🔴 to build/gated.

---

## 2. Foundation — do this FIRST (everything depends on it)

The POC is entirely in-memory with a demo login. Nothing else is "production" until
this is real. These two are the difference between a *demo* and a *product*.

### F1 — Persistence (Postgres, Neon free tier)
- **Now:** in-memory dicts (`_SESSIONS`, `_MESSAGES`, `_ENTITIES`, chain stores…) reset on every restart.
- **Target:** the `intel.*` tables (already the documented persistence target; Alembic migrations + `Data-Model.md` exist).
- **Work:** repository layer behind each in-memory store → async SQLAlchemy against Neon; keep the same return models. Wire `ITTU_DATABASE_URL`.
- **Effort:** M–L (the schema is designed; it's the wiring + read/write paths + tests).
- **Unblocks:** multi-user, restart-durable state, real evidence storage, RLS.

### F2 — Auth (Google OAuth → JWT) + RLS
- **Now:** demo login mints a JWT; RLS policies are written but not enforced (no real Postgres at request time).
- **Target:** real Google OAuth (`ITTU_GOOGLE_CLIENT_ID`), verified id_token → our JWT `{sub, agency_id, role}`; Postgres **RLS** isolates rows per `agency_id` + `data_mode`.
- **Work:** OAuth callback, verify `aud`, session issuance; turn on RLS policies once F1 lands; contract-test the isolation (Bareskrim can't read PPATK's rows).
- **Effort:** M. **Depends on F1.**
- **Status:** ✅ Persistence + RLS live on Neon; Google OAuth hardened (audience verification, `ITTU_OAUTH_PROVISION` operator allowlist). The IdP/admin *evolution* beyond this is **F3**.

### F3 — Identity & access hardening (IdP + delegated admin) · 🔴 planned
The real multi-agency model. Full design: [`Identity-Access-Architecture.md`](Identity-Access-Architecture.md).
- **Already done (F2):** RBAC roles + `require_role`; Postgres RLS isolation (tested); Google OAuth with audience verification + operator-allowlist provisioning.
- **Planned (real deployment — not needed for the POC/demo):**
  - **Keycloak as identity broker** behind a pluggable IdP boundary — Google kept *behind* it; agency AD/Entra federated later; self-hosted (Keycloak/Zitadel) for data sovereignty. MODE-selected: cloud verifies Google, on-prem verifies Keycloak.
  - **Admin-managed roster** — `core.users` gains `status` (invited/active/disabled); provisioning becomes a pre-created row, demoting `ITTU_OAUTH_PROVISION` to bootstrap-only.
  - **Role-mapping table** — upstream group → default ITTU role, low-privilege default + per-user override, authored in ITTU.
  - **Delegated administration** — platform-admin → agency-admin (agency-scoped via RLS) → employees; agencies self-manage their people.
  - **Consented cross-agency case-sharing** — the owning agency shares a specific case with a specific user, time-boxed + audited; an ACL layer *over* RLS, never a hole in it.
- **Effort:** L. **Depends on F1/F2.** Real-deployment increment.

---

## 3. Track A — Live data feeds

### A1 — Blockchain (TRONSCAN) · ✅ validated + hardened
`TronscanAdapter` hits `apilist.tronscanapi.com` (httpx), TronGrid as anonymous fallback.
- **Work:** register/verify an API key + rate-limit budget; add TronGrid/Bitquery as a fallback provider (`BLOCKCHAIN_PROVIDER`); Redis cache; **validate** the full pipeline (features → 5 typology detectors → graph → risk) against *real* TRON wallets, not fixtures. Confirm `data_mode="live"` tagging.
- **Gate:** flip `ITTU_MODULE_MODES={"takedown":"live"}`.
- **Effort:** S–M. Highest-ROI first data feed.
- **Status:** ✅ **Validated end-to-end against a real TRON wallet** (keyless public API): 95 live USDT transfers fetched + mapped (`data_mode=live`), full pipeline ran — Isolation Forest anomaly scores, `circular`/`structuring` typology detectors fired with Glass Box reasoning, graph 39 nodes/95 edges. Ready to enable via the mode flip.
- **Hardening (done):** bad/unknown address → clean 404 (not 500); upstream errors → clean 502/503 envelope (429 = retryable, hints the key) via an app-level `httpx.HTTPError` handler; **bounded + concurrent + resilient BFS** — per-hop breadth (12), pages/addr (2), total addresses (60), fetched in parallel (semaphore 3), with downstream-node failures skipped (logged partial graph) while a root-fetch error still surfaces. Whale `hops=3` trace **~53s → ~16s**. `ITTU_TRONSCAN_API_KEY` (free, TRONSCAN-only — TronGrid uses a separate key) authenticates the primary and lifts the free-tier 429s; POC path is unbounded + byte-identical.
- **Demo nuance:** enabling `takedown=live` makes the Investigation screen query *real* chains — the seeded honeypot fixture wallet (`TXtR9dQpR7mK2vN8fLbY3wZaQ4pJ6`) won't resolve on-chain, so the scripted honeypot→investigation demo narrative needs POC fixtures. Keep `takedown=poc` for the seeded story; use `live` to investigate real wallets/cases (both coexist via MODE).

### A2 — Text channel (Telegram) · 🔴 build
`TelegramChannelAdapter` is a `NotImplementedError` stub.
- **Work:** a Telegram bot (BotFather token), inbound webhook → map updates to `ChannelMessage`, persona reply via `send()`; per-conversation session state. Same agent loop, extraction, custody underneath.
- **Gate:** legal — engaging real scammers needs authorization (see §6).
- **Effort:** M. WhatsApp Business API is the same shape, later.

### A3 — Address tags · 🔴 build
- **Work:** replace the seed snapshot with live OFAC/Arkham/chainabuse lookups behind `TagSource`, cached.
- **Effort:** S–M (mostly API integration + caching).

---

## 4. Track B — Live voice stack
(Full design in `Live-Voice-Calls.md`.)

### B1 — TTS (ElevenLabs) · 🟢 wired, needs key
- **Work:** set `ITTU_ELEVENLABS_API_KEY` + `ITTU_TTS_PROVIDER=elevenlabs`; verify `/audio/{seq}` streams real Bahasa audio; flip the control panel's voice provider. Browser-independent natural voice.
- **Effort:** S. Biggest perceived-quality jump for the least work.

### B2 — STT (Whisper streaming) · 🔴 build
- **Work:** streaming transcription of real caller audio behind `STTAdapter` (Whisper / Deepgram / Google). Only needed once real audio is inbound (B3).
- **Effort:** M.

### B3 — Telephony (Twilio PSTN + media bridge) · 🔴 build, gated
- **Work:** `PstnChannelAdapter` on Twilio Voice + Media Streams; a FastAPI WebSocket **media bridge** wiring caller audio → STT → agent → TTS → caller, with barge-in and a <~1s latency budget.
- **Gate:** **Polri authorization** for live scammer calls (see §6). A Twilio-call-to-your-own-phone demo needs no gate.
- **Effort:** L.

---

## 5. Track C — Fiat + notifications

### C1 — Notifications · 🟠 easy
- **Work:** `LiveNotificationSink` → real email (SES/Resend) / SMS / webhook for dispatched freeze orders + LTKM filings. Currently a mock sink.
- **Effort:** S.

### C2 — Fiat feed · 🔴 institutional
- **Work:** `BankFeedAdapter` → a real bank / **PPATK** transaction feed to correlate against on-chain flows.
- **Gate:** partnership + data-sharing agreement. Parked until there's an institutional sponsor.
- **Effort:** L + non-technical.

---

## 6. Cross-cutting go-live requirements
- **Contract tests** — every LIVE adapter must return byte-compatible Pydantic models vs its POC twin (the framework's parity guarantee).
- **Secrets** — all keys via env / a secret manager, never in code (already the pattern).
- **Resilience** — LIVE adapters own rate-limiting, retries, Redis caching; graceful degradation (the `/turn` never-500 pattern generalizes).
- **`data_mode` isolation** — LIVE evidence views never read POC rows; **separate DB instances per mode** in prod (`Data-Model.md`).
- **Observability** — structured logging, error tracking, uptime monitoring (UptimeRobot / cron ping).
- **Security & evidence** — a security review + RLS-isolation verification before handling real case data (`Security-Evidence.md`).
- **Data sovereignty** — regulator/on-prem deployments run the same OCI images on **K3s**, not the free cloud tiers.

## 7. Legal / institutional gates (non-code, start early — they're the long pole)
1. **Polri / law-enforcement authorization** — required for any live engagement of real suspects (Telegram A2, telephony B3, production scammer engagement). Lawful recording, engagement, evidence chain, seeded honeypot numbers.
2. **PPATK / bank partnership** — for the live fiat feed (C2).
3. **Data-protection compliance** — PII handling, retention, the custody chain as admissible evidence.

---

## 8. Recommended sequence

| # | Item | Why here | Effort | Gate |
|---|---|---|---|---|
| 1 | **F1 Persistence** | nothing is "production" without it | M–L | — |
| 2 | **F2 Auth + RLS** | multi-agency isolation on real data | M | needs F1 |
| 3 | **A1 Blockchain live** | mostly built, real intel, high ROI | S–M | — |
| 4 | **C1 Notifications** | quick, completes the action loop | S | — |
| 5 | **B1 ElevenLabs TTS** | quick, big quality jump | S | — |
| 6 | **A2 Telegram channel** | real inbound infiltration | M | Polri |
| 7 | **B2+B3 STT + Twilio** | real phone calls | L | Polri |
| 8 | **A3 tags / C2 fiat** | enrichment / institutional | M–L | partner |
| — | **F3 Identity & access hardening** | Keycloak IdP + delegated admin + cross-agency sharing | L | real multi-agency deployment |

**Parallelize:** the legal/institutional gates (§7) are the slow ones — start those
conversations *now*, in parallel with the foundation work (1–5), which needs no
external approval.

---

## 9. What's already done (so the remaining picture is honest)
- ✅ **LLM brain** — live in prod (9Router → Claude Haiku, real Bahasa improv).
- ✅ **The entire pipeline** — agent loop, extraction, custody hash-chain, classifier, syndicate clustering, 12-feature engine, 5 typology detectors, graph, Sankey correlation, action docs — all built and tested; provider-agnostic.
- ✅ **The whole frontend** — every screen, wired, with offline/mock fallback.
- 🟢 **Blockchain LIVE + TTS LIVE** — code exists; needs keys + validation, not writing.

The POC already *is* the production architecture running on POC adapters. Going live
is filling adapters + turning on the database — not a rebuild.
