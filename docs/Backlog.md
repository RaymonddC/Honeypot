# ITTU — Backlog

> The single **"what are we aiming for"** board. Keep it current — check items off as they ship.
> This is the short prioritized list; full rationale, effort, and triggers live in
> [`Production-Roadmap.md`](Production-Roadmap.md). Status legend: S/M/L = small/medium/large effort.

_Last updated: 2026-07-24 · branch `main`._

---

## ✅ Done — core is feature-complete
All four pillars + honeypot (text **and** live-mic voice), Response dashboard, and the case-centric
hub. Live blockchain tracing (async jobs, hardened, cycle-fix). Auth/RLS + Google OAuth. LLM brain
live in prod. Persistence (Postgres/Neon, dual in-memory/Postgres repositories). **270 backend tests
green**, frontend build green.

## 🟢 Actionable now — buildable today (no external gate)
- [ ] **B1 — TTS (ElevenLabs)** · S · already wired, needs a key + adapter impl. **Biggest visible
      payoff** — natural voice on the honeypot call (the demo's wow moment).
- [ ] **C1 — Notifications** · S · completes the dispatch → notify action loop.
- [ ] **A1-prod — Dramatiq executor swap** · S–M · *deferred by choice* — async already works
      in-process; build only when there's real concurrency (submit→poll contract is a drop-in).
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
