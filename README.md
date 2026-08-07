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
Module stubs: `GET /api/{infiltrate|trace|takedown|uncover|intel}/ping`.
Migrations: `alembic upgrade head` (no revisions yet in P0).
Worker (optional): `dramatiq app.workers`.

### 3. Frontend

```sh
cd frontend
npm install
npm run dev
```

Open http://localhost:3000 → redirects to `/investigation`; the app shell
(sidebar + topbar + mode badge) renders with placeholder screens.

## MODE toggle (POC ↔ LIVE)

Every external boundary sits behind an adapter; `ITTU_MODE` (global) +
`ITTU_MODULE_MODES` (per-module JSON override, e.g. `{"takedown":"live"}`)
select the implementation at startup. **POC is the safe default** — LIVE
requires explicit config + credentials. See `docs/Adapter-MODE-Framework.md`.
Frontend badge: `NEXT_PUBLIC_ITTU_MODE` (defaults to `poc`).

## Status

P0 ✅ scaffold. Next: **P1 — TAKEDOWN + Investigation screen**
(see `docs/Build-Phases.md`).
