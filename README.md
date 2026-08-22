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
pip install -r requirements-dev.txt && pip install -e . --no-deps
uvicorn app.main:app --reload
```

`requirements-dev.txt` is a **lock** — pinned transitive versions, and what CI
installs, so your machine and CI resolve identically. (They didn't once:
`alembic>=1.13` gave local 1.18.5 and CI 1.19.1, and a migration guard passed
locally while failing CI on version alone.) `pyproject.toml` remains the source
of truth for direct dependencies; after changing one, regenerate:

```sh
cd backend && uv pip compile pyproject.toml --extra dev --universal -o requirements-dev.txt
```

**`--universal` is not optional.** Without it the lock is resolved for whatever
machine ran the command, and environment markers are dropped — a Linux-compiled
lock then pins `pgserver` unconditionally, and installing on Windows dies with
*"No matching distribution found for pgserver"* (it is declared
`platform_system != 'Windows'`, and the worker is Linux/WSL-only anyway).
Universal resolution keeps the markers so one lock serves Windows, Linux and CI.

Verify: `curl http://localhost:8000/health` → `{"status":"ok","mode":"poc"}`.

**When something isn't working, curl `/ready` first** — it probes the actual
dependencies (database reachable, schema at migration head, schema grants
present, RLS genuinely enforcing, Redis reachable) and each check says what to
do about it. `/health` deliberately stays shallow because it is the platform
health check; see `docs/Deploy.md` §7.

**Wallet lookups 404 in local dev?** Check `ITTU_MODULE_MODES`. With
`{"takedown":"live"}` the TAKEDOWN module queries the **real TRONSCAN API**, and
the POC demo addresses (`TXtR9dQ…`, the mule fan-out) are fictional — so every
lookup correctly returns *"No transfers found"*. Nothing is broken; the module is
simply pointed at the real chain. `GET /api/config` reports the effective mode per
module. Set `takedown` back to `poc` to use the offline fixtures.

**Migrations** — `alembic upgrade head`, run as the OWNING role
(`ITTU_MIGRATION_DATABASE_URL`); the app connects as the non-owning `ittu_app`
role so RLS actually applies (`backend/scripts/create_app_role.sql`, once per
database). Only needed under `ITTU_PERSISTENCE=postgres`; the default `memory`
runs the POC with no database at all. **A schema behind the code is refused at
boot** rather than failing later on the first write — that guard exists because
a 3-migration-behind database once broke case creation with nothing pointing at
the cause.

**Worker** — off by default, and **required** for anything queued: LIVE
notification dispatch with `ITTU_NOTIFICATION_DELIVERY=worker`, and outbound
dialing with `ITTU_DIAL_ENQUEUE_ON_START=true`. Without it those jobs queue and
are never executed. Deployment: `docs/Deploy.md` §6.

```sh
cd backend
.venv/bin/dramatiq app.workers          # add --processes 2 --threads 2 to see concurrency
```

Three things that must be true or nothing runs, in the order they bite:

1. **Run it from Linux/WSL, not native Windows.** Dramatiq's worker is
   Unix-oriented (fork/signals). The API is fine on Windows — both reach the
   same Docker Redis and Postgres over `localhost`.
2. **`ITTU_PERSISTENCE=postgres`.** The actor runs in a separate process and
   loads its row by id; the in-memory repositories cannot serve it.
3. **Restart the API after changing either flag** — settings are read at boot,
   so an already-running API keeps the old value and silently never enqueues.

Enqueue failures are logged, not raised (a broker hiccup must not 500 a campaign
start), so when nothing happens check the API log for `dial enqueue failed…`
before suspecting the worker. A healthy-looking worker on an idle queue usually
means the API and worker are pointed at different `ITTU_REDIS_URL`s.

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

**P0–P5 shipped**, 449 backend tests green. Beyond the four pillars: persistence
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
