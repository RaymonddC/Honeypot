# ITTU — Build Phases (shippable increments)

> Real build, phased for pacing (user is on Pro with limited usage). **One phase per session**, each
> self-contained + shippable. Resume any time from this doc — no re-derivation needed.
> Design refs: `docs/*` (all module designs + `Frontend-Design.md` + mockup).

## Status (2026-07-05) — branch `build/p0-scaffold`
✅ **P0** scaffold (`9bd3f8d`) · ✅ **P1** TAKEDOWN/Investigation (`ccce5d7`, Cytoscape fix `1f33213`) ·
✅ **P2** TRACE/Bridge (`897d113` + tests `7bc86ab`) · ✅ **P3** UNCOVER Action Panel + Dashboard
(`23fc5cc` + live-align/fixes `6c4eef1`). **70 backend tests green; all 4 screens built + live-verified.**
⬜ **P4** INFILTRATE Honeypot · ⬜ **P5** auth/RLS + integration + LIVE toggles · ⬜ #1 node-styling polish.
Lesson baked in: after each phase, do a frontend↔backend live field-alignment pass (bit us on P1 + P3).

## Execution strategy (usage-conserving)
- **Opus (lead)** = plan, review, integrate, tricky logic. **Fable agents** (`model: fable`) = bulk
  mechanical build (scaffold, boilerplate, port). Background agents keep output out of lead context.
- Per phase: spawn 1–2 Fable build agents (backend / frontend) that coordinate on the API contract;
  lead reviews + wires together; **stop at the phase checkpoint** for the user to test + pace usage.
- Stack (locked): FastAPI modular monolith · Postgres+RLS · Next.js 16 + shadcn (ELSA tokens) · Redis
  · Dramatiq · LiteLLM gateway · NetworkX (Neo4j deferred) · adapter/MODE toggle. Design = the mockup.

## Phases

### P0 — Scaffold  ✅=bootable
Monorepo: `backend/` (FastAPI app-factory + lifespan, pydantic-settings w/ `MODE`, SQLAlchemy async +
Alembic base, adapter registry skeleton, Dramatiq stub, `/health`) · `frontend/` (Next.js 16 + TS +
Tailwind + shadcn init, ELSA design tokens in `globals.css`, app shell + nav from the mockup) ·
`docker-compose.yml` (postgres, redis) · `.env.example` · root README.
**Checkpoint:** `docker compose up` boots Postgres+Redis; backend `/health` OK; frontend shell renders.

### P1 — TAKEDOWN + Investigation screen  (the 60% core)
Backend: chain adapter (POC fixtures from mockup data + TRONSCAN live), `wallets`/`transactions`
models + migration, 12-feature engine, IsolationForest + 5 typology detectors, risk scoring w/
reasoning, NetworkX graph → Cytoscape JSON, endpoints (`/investigate`, `/wallets/{a}/graph`,
`/wallets/{a}/risk`). Frontend: Investigation screen wired to API (port mockup → real Cytoscape.js) +
Glass Box.
**Checkpoint:** enter a TRON address (or POC fixture) → real graph + scores + reasoning.

### P2 — TRACE / Bridge View
Synthetic fiat generator (PT A2Z params), correlation engine (amount + 30-min), mule clustering
(Louvain/DBSCAN), sankey endpoint. Frontend: Bridge View (d3-sankey, split-screen, alert feed).
**Checkpoint:** Sankey renders from generated data; on-ramp correlations listed.

### P3 — UNCOVER + Response Dashboard
ReportLab freeze/LTKM templates, notification mock sink, action endpoints; metrics endpoint. Frontend:
Action Panel (generate + human-gated dispatch) + Response Dashboard (tiles + trend + cases).
**Checkpoint:** one click generates the 3 docs (hashed) + POC mock dispatch; dashboard populated.

### P4 — INFILTRATE / Honeypot (text; voice = P4b)
LiteLLM gateway config (tiered routing), thin agent loop + persona, hybrid entity extraction
(regex+checksum → LLM/JSON), custody hash-chain logging, crime classifier. Frontend: Honeypot console
(transcript + inline extraction + entities + custody). **P4b:** voice channel (STT→loop→TTS, OLAF reuse).
**Checkpoint:** POC replay session extracts validated entities → feeds Investigation.

### P5 — Auth/RLS + integration + LIVE toggles + polish
Google OAuth→JWT, Postgres RLS policies, wire MODE per-module toggles, end-to-end demo narrative
(honeypot→investigation→bridge→action→dashboard), QA/Security pass (RLS isolation, custody).
**Checkpoint:** full demo thread runs in POC; LIVE adapters wired (gated).

## Resume protocol
Each session: read this doc + the relevant module design doc, check `git log` / repo state for the last
completed phase, continue the next. Build-readiness checklist in `docs/README.md` (API keys, goAML
schema, narrative-name reconcile) applies before LIVE.
