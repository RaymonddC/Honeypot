# ITTU — Deploy guide (free tier)

The POC runs **in-memory** (no Postgres/Redis needed at request time), so the demo
deploys as two independent apps — and the frontend even runs **standalone** (mock/
offline mode) if no backend is up.

```
 Frontend (Next.js)  ──►  Vercel        (free)
 Backend  (FastAPI)  ──►  Fly.io/Render  (free, optional — POC works without it)
 DB/Redis            ──►  none needed for POC (add Neon + Upstash when P5 RLS goes live)
```

## 1. Frontend → Vercel

1. Push the branch to GitHub (already done: `build/p0-scaffold` → merged to `main`).
2. Vercel → **New Project** → import the repo.
3. **Root Directory: `frontend`**  ← the important monorepo setting (Framework auto-detects Next.js).
4. **Environment Variables:**
   | Name | Value |
   |---|---|
   | `NEXT_PUBLIC_API_URL` | your backend URL (e.g. `https://ittu-api.fly.dev`) — or leave as-is for **offline/mock demo** |
   | `NEXT_PUBLIC_ITTU_MODE` | `poc` |
5. **Deploy.** `frontend/vercel.json` sets the framework + security headers.

**Standalone demo:** if `NEXT_PUBLIC_API_URL` points at a backend that isn't up, every
screen renders on demo data with an `● offline` badge, and login offers
"Continue offline — demo session". So you can ship the Vercel URL *today* with no backend.

## 2. Backend → Fly.io (optional, for LIVE data)

`backend/Dockerfile` already exists.
```bash
cd backend
fly launch            # detects the Dockerfile; pick a name e.g. ittu-api
fly secrets set ITTU_CORS_ORIGINS='["https://<your-app>.vercel.app"]'   # allow the frontend
fly secrets set ITTU_JWT_SECRET='<a long random string>'
fly deploy
```
Then set the frontend's `NEXT_PUBLIC_API_URL` to the Fly URL and redeploy Vercel.
(Render works the same way: New Web Service → repo → root `backend` → Docker.)

## 3. Environment variables (reference)

**Frontend:** `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_ITTU_MODE`.
**Backend (`ITTU_` prefix):** `ITTU_CORS_ORIGINS` (JSON list — add the Vercel domain),
`ITTU_JWT_SECRET` (change from the dev default), `ITTU_MODE` (`poc`/`live`),
`ITTU_MODULE_MODES` (e.g. `{"takedown":"live"}`). Postgres/Redis URLs only matter once
RLS/persistence goes LIVE (add `ITTU_DATABASE_URL` = a Neon connection string then).

## Notes
- **CORS:** the backend now reads allowed origins from `ITTU_CORS_ORIGINS` — set it to the
  Vercel domain or the browser will block API calls.
- **RLS/persistence:** LIVE auth-isolation needs a real Postgres (Neon free tier); the POC
  demo does not. See the migration `20260708_05` + `db.py` docstrings for the runtime check.
- **Data sovereignty:** regulator/on-prem deployments use K3s with the same OCI images — not
  the free cloud tiers above (those are for the hackathon demo).
