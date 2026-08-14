# ITTU — Backlog

> The single **"what are we aiming for"** board. Keep it current — check items off as they ship.
> This is the short prioritized list; full rationale, effort, and triggers live in
> [`Production-Roadmap.md`](Production-Roadmap.md). Status legend: S/M/L = small/medium/large effort.

_Last updated: 2026-08-08 · branch `main`._

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

## 🔒 Gated — blocked on external approval (start the conversations now, don't build yet)
- [ ] **A2 — Telegram channel** · M · **Polri** authorization
- [ ] **B2 + B3 — STT (Whisper streaming) + Twilio telephony** · L · **Polri**
- [ ] **A3 — Address tags feed** (OFAC/Arkham/chainabuse) · M · **partner**
- [ ] **C2 — Fiat feed** · L · **PPATK / bank** partnership
- [ ] **F3 — Identity hardening** (Keycloak IdP + delegated admin + cross-agency sharing) · L ·
      real multi-agency deployment

## 📜 Non-code long-pole — legal/institutional (start early, they're the slow ones)
- [ ] Polri law-enforcement authorization (any live suspect engagement)
- [ ] PPATK / bank partnership (live fiat feed)
- [ ] Data-protection & evidence-admissibility compliance
