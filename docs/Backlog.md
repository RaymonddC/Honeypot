# ITTU — Backlog

> The single **"what are we aiming for"** board. Keep it current — check items off as they ship.
> This is the short prioritized list; full rationale, effort, and triggers live in
> [`Production-Roadmap.md`](Production-Roadmap.md). Status legend: S/M/L = small/medium/large effort.

_Last updated: 2026-08-16 · branch `feat/c1-notifications-delivery`._

---

## 🩹 Fixed this cycle (worth remembering — both were silent failures)
- [x] **DB migration drift → broke "create case"** (2026-08-15) — the Neon DB was 3 migrations behind, so
      `core.cases` had no `stage` column and every insert 500'd with nothing pointing at the cause. Fixed by
      `alembic upgrade head`; **prevented** by a boot guard that refuses to start when the schema is behind
      (`app/core/migration_guard.py`) plus CI integrity tests (single-head + apply-chain canary).
- [x] **`casedata` grants missing for `ittu_app`** (2026-08-16, `6d93896`) — `create_app_role.sql` granted
      every schema except `casedata`, so under Postgres persistence the analyst-entered bank-account /
      crypto-transfer features hit `InsufficientPrivilege` with no hint. Verified DENIED→ACCESSIBLE on the
      live DB; grants applied and the script fixed for fresh environments.

## ✅ Done — core is feature-complete
All four pillars + honeypot (text **and** live-mic voice), Response dashboard, and the case-centric
hub. Live blockchain tracing (async jobs, hardened, cycle-fix). Auth/RLS + Google OAuth. LLM brain
live in prod. Persistence (Postgres/Neon, dual in-memory/Postgres repositories). **C1 dispatch
delivery** — production-ready notification layer (HMAC-signed webhooks, idempotency keys, durable
retried delivery via the Dramatiq actor, `GET /api/notifications` outbox feed + retry, Dispatch Log
on the Response dashboard). **282 backend tests green**, frontend build green.

## 🟢 Actionable now — buildable today (no external gate)
- [x] **B1 — TTS (ElevenLabs)** · S · **DONE (2026-08-08)** — code path complete end-to-end: the
      `ElevenLabsTTSAdapter` synthesizes real audio, the `/audio/{seq}` endpoint now **serves the bytes**
      (was discarding them), cached to avoid re-paying the provider, and degrades to browser speech if
      synthesis fails. **Only remaining step is operational:** set `ITTU_TTS_PROVIDER=elevenlabs` +
      `ITTU_ELEVENLABS_API_KEY` on Render and flip the Control Panel to hear the natural voice (the
      demo's wow moment). Keyless POC still uses browser TTS.
- [x] **C1 — Notifications** · ~~S~~ M · **DONE (2026-08-08)** — built production-ready, not a demo
      shim: signed + idempotent + retried LIVE delivery (`ITTU_NOTIFICATION_DELIVERY=worker`),
      agency outbox feed, POC mock path unchanged. Flip `ITTU_MODE=live` + set the webhook URL/secret
      to dispatch for real.
- [ ] **A1-prod — Dramatiq executor swap** (investigation jobs) · S–M · *deferred by choice* — async
      already works in-process; build only when there's real concurrency (submit→poll contract is a
      drop-in). *(Note: C1 already stood up the Dramatiq delivery actor + broker for notifications.)*
- [ ] **Go-live hardening** · M · contract tests per LIVE adapter, observability/uptime, a security +
      RLS-isolation review, separate DB per mode. Only when heading to real production.
- [ ] **Audit trail — broaden & surface** · M · *later (parked 2026-08-14, not urgent)* — a user-facing /
      admin audit view over the existing custody hash-chain + `core.audit_log` (who did what, when —
      logins, dispatches, entity reviews, config changes). Foundations already exist (message/doc
      SHA-256 chain, `action_bundle.audit`, `core.audit_log`); this is exposing + extending them.
- [x] **`alembic check` drift reconciliation** · S–M · **DONE (2026-08-16)** — the last leg of the
      migration guards. All four drift items were the same shape (the DB had the object, the ORM model
      never declared it), so they were reconciled model-side with **no schema change and no migration**:
      casedata index/FK declarations, `wallet_risk_scores.wallet_id` nullability, and the `messages`
      unique constraint. `alembic check` now runs in CI (`test_models_match_migrations`, against the
      ephemeral pgserver cluster — no external DB), catching the direction the other guards can't: a
      model edited with no migration written, which is exactly how the `stage` outage was authored.
      **Verified the guard actually fails** by injecting an undeclared column and watching it go red.
      Caveat recorded in the test: autogenerate doesn't diff CHECK constraints, RLS policies, or
      server-side functions, so green means "no detectable table/column/index/constraint drift".
- [ ] **Qwen TTS provider** · S · *researched & skipped 2026-08-16, optional* — only the **hosted
      Qwen-Audio-3.0-TTS-Flash** (DashScope) has Indonesian; the open-source Qwen3-TTS does not. Cheap
      (~$0.013/1K chars) + expressive/voice-cloning, but "free" is a **90-day trial**, not ongoing (Google
      TTS stays free monthly), needs a new **Alibaba DashScope key**, and Alibaba Cloud is a data-governance
      flag for LIVE forensics. Doesn't fill a gap (Google/Gemini/ElevenLabs already wired). Wire as a
      flip-to-LIVE adapter (`ITTU_QWEN_API_KEY`) only if its voices are wanted.
- ❌ **AI Rudder — evaluated & REJECTED (2026-08-16)** — enterprise AI voice-agent platform (BotLab,
      no-code), 500+ clients, strong Indonesia/SEA footprint; built for loan collection, telemarketing,
      KYC. **Rejected on architecture, not price: it owns the conversation**, so ITTU's persona loop,
      entity extraction and SHA-256 hash-chained custody are all bypassed — you get transcripts
      secondhand (no public API/webhook docs; enterprise sales only) and nothing court-usable out the
      other end. That objection does **not** dissolve at scale — 1,000 concurrent calls have the same
      problem as one, so there is no "use it later when we're bigger" path for the honeypot. It could
      only ever fit a *different, non-forensic* workload (e.g. mass victim outreach/warning campaigns,
      which need no evidence chain) — a separate product, not ITTU. Also: no self-serve (can't
      prototype), opaque custom pricing, and a commercial third party processing + storing scam-call
      content is a data-governance flag for law-enforcement evidence. **Keep as market context only**
      (proof Indonesian voice AI works commercially — worth a capstone mention). Stay with Twilio as
      dumb transport + our own STT/TTS/agent loop: the custody chain IS the product.
- [ ] **Voice honeypot — outbound calling MVP** · L · *in progress 2026-08-16* — full architecture in
      [`Voice-Honeypot-Outbound.md`](Voice-Honeypot-Outbound.md): a number pool, a bulk-upload dial
      campaign (Dramatiq-paced, mirrors the C1 notification worker), and a triage queue that attaches
      each connected call's session to a matched case or leaves it for an investigator to assign.
      - [x] **Phase 1 — data model** (`e69f938`) — `honeypot` schema (numbers, dial_campaigns,
            dial_targets) + call columns on `intel.scam_sessions`, RLS on all three (dial_targets policed
            via a join through its campaign).
      - [x] **Phase 2 — case "Calls & conversations" list** (`b82726f`) — see the separate entry below.
      - [x] **Phase 3 — Numbers + Campaigns CRUD + Honeypot Ops UI** (`7e4e9c8`) — `/api/honeypot/*`,
            new `/honeypot-ops` page. Bulk upload reports per-row rejects instead of failing the batch;
            a bare local number (`08…`) is REJECTED, never auto-prefixed to `+62` — guessing a country
            code in a police dialer could call an unrelated real person.
      - [ ] **Phase 4 — POC dial worker + Requeue + one-session-per-attempt call log** — in progress.
      - [ ] **Phase 5 — real Twilio `PstnChannelAdapter` + media bridge** — `Live-Voice-Calls.md`'s
            scope; needs a Twilio account. Self-test/demo numbers only (see Gated below for real targets).
      - [ ] **Phase 6 — triage queue + case-linking** — can follow phase 4.
- [x] **Case detail: "Calls / Conversations" list** · S · **DONE (2026-08-16, `b82726f`)** — session rows
      on the case are now expandable into the existing transcript view, with `started_at` shown and voice
      calls badged. Deliberately no mock fallback on that fetch: a mock transcript rendered under a real
      case would be misleading evidence. Duration/recording/disposition columns arrive with phase 4/5.

## 🔒 Gated — blocked on external approval (start the conversations now, don't build yet)
- [ ] **A2 — Telegram channel** · M · **Polri** authorization
- [ ] **B2 + B3 — STT (Whisper streaming) + Twilio telephony** · L · **Polri** — the
      `PstnChannelAdapter` + media bridge (`Live-Voice-Calls.md`); dialing *real reported scam numbers*
      via the outbound campaign feature (`Voice-Honeypot-Outbound.md`) is the same gate — self-test/demo
      numbers are exempt (you're calling yourself), real targets are not.
- [ ] **A3 — Address tags feed** (OFAC/Arkham/chainabuse) · M · **partner**
- [ ] **C2 — Fiat feed** · L · **PPATK / bank** partnership
- [ ] **F3 — Identity hardening** (Keycloak IdP + delegated admin + cross-agency sharing) · L ·
      real multi-agency deployment

## 📜 Non-code long-pole — legal/institutional (start early, they're the slow ones)
- [ ] Polri law-enforcement authorization (any live suspect engagement)
- [ ] PPATK / bank partnership (live fiat feed)
- [ ] Data-protection & evidence-admissibility compliance
