# ITTU — Infiltrate, Trace, Takedown & Uncover

AI-powered financial-crime forensics platform for Indonesia. **P0–P5 shipped** — all four
pillars (Infiltrate honeypot incl. live-mic voice, Trace, Takedown, Uncover) + Response
dashboard + a case-centric hub, with auth/RLS, live blockchain tracing (async jobs), and the
LLM brain in prod. Design docs live in [`docs/`](docs/) (start with `docs/README.md`;
current state in `docs/Build-Phases.md` + `docs/Production-Roadmap.md`).

```
backend/    FastAPI modular monolith (Python 3.12) — SQLAlchemy async + Alembic,
            Dramatiq workers, adapter/MODE registry
frontend/   Next.js 16 + TypeScript + Tailwind — ELSA-anchored dark shell, case hub + 4 pillars
docs/       full planning + design set
```

## Run it

### 1. Infra (Postgres + Redis)

```sh
docker compose up -d
```

### 2. Backend

```sh
cd backend
cp .env.example .env
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

Verify: `curl http://localhost:8000/health` → `{"status":"ok","mode":"poc"}`.

**Migrations** — `alembic upgrade head`, run as the OWNING role
(`ITTU_MIGRATION_DATABASE_URL`); the app connects as the non-owning `ittu_app`
role so RLS actually applies (`backend/scripts/create_app_role.sql`, once per
database). Only needed under `ITTU_PERSISTENCE=postgres`; the default `memory`
runs the POC with no database at all. **A schema behind the code is refused at
boot** rather than failing later on the first write — that guard exists because
a 3-migration-behind database once broke case creation with nothing pointing at
the cause.

**Worker** — `dramatiq app.workers` (needs Redis). Off by default, and
**required** for anything queued: LIVE notification dispatch with
`ITTU_NOTIFICATION_DELIVERY=worker`, and outbound dialing with
`ITTU_DIAL_ENQUEUE_ON_START=true`. Without it those jobs queue and are never
executed. See `docs/Deploy.md` §6.

### 3. Frontend

```sh
cd frontend
npm install
npm run dev
```

Open http://localhost:3000 → redirects to `/home`. Screens: the case hub
(`/case`), the four pillars (`/honeypot`, `/bridge`, `/investigation`,
`/actions`), the Response dashboard (`/response`), **Honeypot Ops**
(`/honeypot-ops` — outbound number pool, dial campaigns, call triage), and the
Control Panel (`/settings`).

## MODE toggle (POC ↔ LIVE)

Every external boundary sits behind an adapter; `ITTU_MODE` (global) +
`ITTU_MODULE_MODES` (per-module JSON override, e.g. `{"takedown":"live"}`)
select the implementation at startup. **POC is the safe default** — LIVE
requires explicit config + credentials. See `docs/Adapter-MODE-Framework.md`.
Frontend badge: `NEXT_PUBLIC_ITTU_MODE` (defaults to `poc`).

## Status

**P0–P5 shipped**, 374 backend tests green. Beyond the four pillars: persistence
(Postgres/Neon + RLS), production-ready notification dispatch (signed,
idempotent, retried), real TTS voices (ElevenLabs / Gemini / Google, switchable
per call from the Control Panel), and the **outbound voice honeypot** — number
pool, bulk dial campaigns, a paced/retried dial worker, a per-attempt call log,
and triage that files each call into a case
([`docs/Voice-Honeypot-Outbound.md`](docs/Voice-Honeypot-Outbound.md)).

Dialing is **simulated**: real telephony (Twilio + streaming STT + the media
bridge) is the remaining build, and engaging real reported numbers is gated on
**Polri authorization** — see `docs/Live-Voice-Calls.md` and the Backlog.

Current priorities: [`docs/Backlog.md`](docs/Backlog.md).
