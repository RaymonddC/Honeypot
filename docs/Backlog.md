# ITTU — Backlog

> The single **"what are we aiming for"** board. Keep it current — check items off as they ship.
> This is the short prioritized list; full rationale, effort, and triggers live in
> [`Production-Roadmap.md`](Production-Roadmap.md). Status legend: S/M/L = small/medium/large effort.

_Last updated: 2026-08-16 · branch `feat/c1-notifications-delivery`._

---

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
- [ ] **`alembic check` drift reconciliation** · S–M · *parked 2026-08-15* — enable the model↔migration
      autogenerate check as a CI guard. Blocked by pre-existing drift it surfaces: casedata index/FK
      naming, `wallet_risk_scores.wallet_id` nullability, a `messages` unique constraint. Runtime drift
      guard (fail-loud at boot) + single-head/apply-to-head CI tests already shipped; this is the last leg.
- [ ] **Qwen TTS provider** · S · *researched & skipped 2026-08-16, optional* — only the **hosted
      Qwen-Audio-3.0-TTS-Flash** (DashScope) has Indonesian; the open-source Qwen3-TTS does not. Cheap
      (~$0.013/1K chars) + expressive/voice-cloning, but "free" is a **90-day trial**, not ongoing (Google
      TTS stays free monthly), needs a new **Alibaba DashScope key**, and Alibaba Cloud is a data-governance
      flag for LIVE forensics. Doesn't fill a gap (Google/Gemini/ElevenLabs already wired). Wire as a
      flip-to-LIVE adapter (`ITTU_QWEN_API_KEY`) only if its voices are wanted.
- [ ] **Voice honeypot — outbound calling MVP** · L · *designed 2026-08-16, buildable in phases* — full
      architecture in [`Voice-Honeypot-Outbound.md`](Voice-Honeypot-Outbound.md): a number pool, a
      bulk-upload dial campaign (Dramatiq-paced, mirrors the C1 notification worker), and a triage queue
      that attaches each connected call's session to a matched case or leaves it for an investigator to
      assign. **Phases 1–4 + 6 (data model, case "calls" list, Numbers/Campaigns CRUD + UI, POC-simulated
      dialing worker, triage/case-linking) need no Twilio account and no legal gate — buildable now.**
      Phase 5 (the real `PstnChannelAdapter` + media bridge) is `Live-Voice-Calls.md`'s scope and is where
      a Twilio account + the self-test-only line applies (see the Gated section below for dialing *real*
      reported numbers).
- [ ] **Case detail: "Calls / Conversations" list** · S · *quick win, part of the above* — the case rollup
      already returns `sessions` (`cases/router.py`); today only counts are shown. Render the list
      (number, date, duration, disposition, entity count) → expand into the existing transcript view.
      Useful standalone even before the campaign feature ships.

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
