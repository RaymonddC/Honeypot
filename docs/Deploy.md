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

## 2. Backend → Render (recommended — always-on container)

⚠️ Don't put this backend on Vercel: it's **stateful in-memory** (POC), and Vercel's
stateless serverless functions break the multi-step flows (Action Panel generate→
dispatch→document, and the honeypot lifespan seed). Render runs a real container, so
in-memory state + FastAPI lifespan behave exactly like local.

**One-time via the Blueprint (`render.yaml` at repo root):**
1. Render → **New → Blueprint** → connect this repo → **Apply**. It reads `render.yaml`
   (Docker web service, region Singapore, health check `/health`, `autoDeploy: true`).
2. After the first deploy, set the env var **`ITTU_CORS_ORIGINS`** to your Vercel origin,
   e.g. `["https://honeypot-brown.vercel.app"]` (Render dashboard → the service → Environment).
   `ITTU_JWT_SECRET` is auto-generated; `ITTU_MODE=poc` is preset.
3. Copy the service URL (e.g. `https://ittu-api.onrender.com`) → set it as
   **`NEXT_PUBLIC_API_URL`** in Vercel → redeploy the frontend.

**Auto-deploy:** `autoDeploy: true` means Render rebuilds on every push to the connected
branch — no GitHub Action needed. The Dockerfile binds `$PORT` (Render-injected), falls
back to 8000 locally.

> Free tier sleeps after ~15 min idle → the first request cold-starts (~30–60s) and
> re-runs the lifespan seed. Hit it once to warm it right before a live demo.

*(Alternative: Fly.io — `cd backend && fly launch && fly deploy`; set the same env via
`fly secrets set ITTU_CORS_ORIGINS=... ITTU_JWT_SECRET=...`.)*

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
