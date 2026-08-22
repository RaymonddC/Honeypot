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
2. **`ITTU_CORS_ORIGINS` is already baked into `render.yaml`** (`["https://honeypot-brown.vercel.app"]`)
   — only override it in the Render dashboard if your Vercel origin differs.
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
`ITTU_MODULE_MODES` (e.g. `{"takedown":"live"}`).
`ITTU_METRICS_TOKEN` (enables `GET /metrics`; unset = 404, see §8). Postgres/Redis URLs only matter once
RLS/persistence goes LIVE (add `ITTU_DATABASE_URL` = a Neon connection string then).

## 4. Postgres + RLS: the non-superuser app role (required once persistence goes LIVE)

Row-Level Security (migrations `20260708_05`, `20260715_06`) restricts every agency-scoped
table to `agency_id = app.current_agency()`. **RLS is bypassed by table owners and
superusers** — so the app must connect as a role that did *not* create the tables.

1. Run migrations as your normal owning/admin role (`alembic upgrade head`) — this creates
   the schemas, tables, and RLS policies.
2. Create the app role and grant it table access (not ownership):
   ```
   psql "$MIGRATION_DATABASE_URL" -v app_role_password='<a-strong-password>' \
        -f backend/scripts/create_app_role.sql
   ```
   This creates `ittu_app` (LOGIN only) with `USAGE` on the 5 schemas (`core`, `intel`,
   `chain`, `fiat`, `action`) and `SELECT/INSERT/UPDATE/DELETE` on their tables — enough to
   read/write rows, but RLS still filters *which* rows within those grants.
3. Point the app at `ittu_app`, **not** the owning role:
   ```
   ITTU_DATABASE_URL=postgresql+asyncpg://ittu_app:<password>@<host>/<db>
   ```

**⚠️ Neon caveat:** the connection string Neon's dashboard gives you by default uses the role
that *owns* every table (whichever role ran the migrations) — that role **bypasses RLS
entirely**. If `ITTU_DATABASE_URL` uses it, every RLS policy silently becomes a no-op: the
app sees *all* agencies' rows regardless of `app.current_agency`, with no error to signal it.
You must run `create_app_role.sql` against the Neon database and set `ITTU_DATABASE_URL` to
`ittu_app`'s connection string (same host/db, different role+password) — never the
Neon-provided owner role. There is no way to verify this from the app process alone; the
isolation test in `backend/tests/test_rls_isolation.py` is the way to prove it end-to-end
against a real Postgres before trusting a deployment.

## 5. Automated deploys (no manual redeploy, no manual migrations)

**Auto-migrate on deploy.** The container entrypoint (`backend/scripts/start.sh`, wired as the
Dockerfile `CMD`) runs `alembic upgrade head` *before* uvicorn — but **only** when
`ITTU_PERSISTENCE=postgres` **and** `ITTU_MIGRATION_DATABASE_URL` is set. Migrations run as the
**owning** role (via `ITTU_MIGRATION_DATABASE_URL`), since the app's `ITTU_DATABASE_URL`
(`ittu_app`) can't run DDL. `alembic upgrade` is idempotent, so it's a fast no-op once at head;
a failed migration aborts startup on purpose (never serve code against an un-migrated schema).
So a schema change ships by just deploying the new code — no separate migrate step.

Set on Render (in addition to §4's vars):
```
ITTU_PERSISTENCE=postgres
ITTU_MIGRATION_DATABASE_URL=postgresql+asyncpg://<owner>@<host>/<db>?ssl=require   # owner role
```
Under `ITTU_PERSISTENCE=memory` (POC) the entrypoint skips migrations entirely — no DB needed.

**Reliable auto-deploy.** Render's native auto-deploy webhook is frequently missed (hence the
Manual Deploys). `.github/workflows/render-deploy.yml` triggers a deploy on every push to `main`
via the service's **Deploy Hook** instead. One-time setup:
1. Render → `ittu-api` → Settings → **Deploy Hook** → copy the URL.
2. GitHub → repo Settings → Secrets and variables → Actions → new secret
   `RENDER_DEPLOY_HOOK_URL` = that URL.
3. (Optional) turn OFF Render's native Auto-Deploy so this workflow is the single trigger
   (avoids double builds).

**Note:** asyncpg speaks `?ssl=require`, not libpq's `?sslmode=require` — a raw Neon URL must be
converted (scheme → `postgresql+asyncpg://`, `sslmode`→`ssl`).

## 6. Background worker (Dramatiq) — required for queued work

The API only *enqueues*; a separate process executes. **Without the worker service, queued
jobs are never run** — they accumulate in Redis silently, with no error anywhere:

| Feature | Needs the worker? |
|---|---|
| C1 notification dispatch, `ITTU_NOTIFICATION_DELIVERY=sync` (**default**) | ❌ POSTs inline during the request |
| C1 notification dispatch, `ITTU_NOTIFICATION_DELIVERY=worker` | ✅ **yes** — flipping this on without a worker stops deliveries |
| Outbound dialing, `ITTU_DIAL_ENQUEUE_ON_START=true` | ✅ **yes** |

`render.yaml` now defines `ittu-worker` alongside `ittu-api`: the **same image**, with the
command overridden to `dramatiq app.workers` instead of `scripts/start.sh`.

**Three things that must be right:**

1. **Redis** — provision one (Render Key Value, or Upstash) and set `ITTU_REDIS_URL` on
   **both** the API and the worker to the **same instance**. Different instances = the API
   enqueues into one queue while the worker watches another, and nothing ever runs. The
   default `redis://localhost:6379/0` only works locally (docker compose).
2. **Only the web service migrates.** `scripts/start.sh` runs `alembic upgrade head`; the
   worker deliberately bypasses it via `dockerCommand`. Two containers migrating on the same
   deploy can race the schema.
3. **Paid plan.** Render doesn't offer background workers on free, and a worker that sleeps
   isn't a worker. The web service should also leave free, or it cold-starts on every hit.

The worker also needs `ITTU_PERSISTENCE=postgres` plus **both** DB URLs. It connects as the
**owning** role by design — a system actor is handed a row id and must read it to learn which
agency owns it, which RLS cannot resolve (see `worker_session` in `app/core/db.py`). Because
RLS is therefore *not* filtering the actor's queries, actor code scopes by `agency_id`
explicitly.

**Verify it's actually working** (not just running): start a campaign or dispatch, then check
the worker's Render logs for the job. A silent queue with a healthy-looking worker usually
means mismatched `ITTU_REDIS_URL`s.

## 7. Health vs readiness — where to look when something is wrong

Two endpoints, deliberately different, both unauthenticated (a probe cannot present a token)
and neither containing secrets or connection strings:

| Endpoint | Purpose | Depth |
|---|---|---|
| `GET /health` | **Liveness** — the platform health check (`healthCheckPath` in `render.yaml`) | Shallow on purpose |
| `GET /ready` | **Readiness + diagnostics** — actually probes dependencies | Deep |

`/health` must stay shallow. If it consulted Postgres, a transient database blip would fail
the health check and Render would take the whole service down — turning a degraded page into
an outage. It answers "is the process alive", nothing more.

`/ready` is the one to curl when something isn't working:

```sh
curl -s https://<your-render-url>/ready | jq
```

It returns **503** when a critical check fails (so it can back a readiness probe) and **200**
otherwise — with the **same body either way**, so a human reads *why* rather than guessing
from a status code. Each check exists because that exact failure cost real debugging time and
its symptom pointed somewhere unhelpful:

- **`database`** — reachable, and which role is connected.
- **`rls_enforcing`** — *non-critical warning*: connecting as the **owning** role silently
  bypasses every RLS policy, so agency isolation looks fine in testing and leaks in
  production. Single-role local setups are legitimate; production is not.
- **`schema_at_head`** — the migration drift that once broke case creation with nothing
  naming the cause. The detail tells you to run `alembic upgrade head`.
- **`schema_grants`** — the app connects as non-owning `ittu_app`; a schema missing from
  `scripts/create_app_role.sql` (as `casedata` was) fails with `InsufficientPrivilege` and no
  hint about grants. Names the schema and points at the script.
- **`redis`** — **critical only when something actually queues**
  (`ITTU_NOTIFICATION_DELIVERY=worker` or `ITTU_DIAL_ENQUEUE_ON_START=true`). Marking it
  always-critical would leave every POC deployment permanently "not ready", which trains
  people to ignore the endpoint.

## 8. Metrics and alerting — "was it broken at 3am", and "did we lose a record"

`/ready` answers *is it broken right now*. It cannot answer *was it broken overnight* or *is
latency creeping*, and it cannot tell you that an audit entry was silently lost. That needs a
time series, which needs something to scrape.

### `GET /metrics`

Prometheus text exposition (`text/plain; version=0.0.4`), vendor-neutral — Grafana Cloud,
Grafana Alloy/Agent, Better Stack and Render-side scrapers all read it unchanged.

**It is authenticated, unlike `/health` and `/ready`.** Those carry booleans a platform probe
needs and cannot present a token for. `/metrics` lists every route template and how often each
was called: an API map plus operational tempo. No agency, user or case is ever labelled, so it
cannot answer "what did agency X do" — but "what does this system expose, and when is it busy"
is still reconnaissance worth withholding from anonymous callers on a law-enforcement tool.
Scrapers support bearer tokens; probes do not, and that is exactly where the line is drawn.

```sh
ITTU_METRICS_TOKEN=<a long random string>   # generate with: openssl rand -hex 32
```

**With no token set the endpoint returns 404, not 403** — an unconfigured deployment should be
indistinguishable from one that has no metrics at all. The startup log says
`ITTU metrics: /metrics DISABLED (no ITTU_METRICS_TOKEN set)`, so a failing scrape is
diagnosable from the logs without anything being revealed to an anonymous caller.

Prometheus scrape config:

```yaml
scrape_configs:
  - job_name: ittu-api
    scheme: https
    metrics_path: /metrics
    authorization:
      type: Bearer
      credentials_file: /etc/prometheus/ittu-metrics-token   # never inline the token
    static_configs:
      - targets: ["<your-render-host>"]
```

### What is exposed

| Metric | Type | Labels | What it answers |
|---|---|---|---|
| `ittu_http_requests_total` | counter | `method`, `route`, `status` | Request rate, and error rate via `status` |
| `ittu_http_request_duration_seconds` | histogram | `method`, `route` | Latency distribution / quantiles |
| `ittu_audit_entries_dropped_total` | counter | `reason` | **An audit entry was permanently lost** |
| `ittu_audit_entries_written_total` | counter | `outcome` | The denominator for the above |
| `ittu_audit_denials_suppressed_total` | counter | — | Denials not recorded because the per-actor rate cap was hit |

### ⚠ No identifiers are ever labelled, and this is deliberate

`route` is always the **route template** (`/api/cases/{case_id}`), never the requested URL.
This app's URLs carry case ids, wallet addresses and user ids. Labelling by raw path would copy
tenant identifiers and blockchain addresses into a metrics store that is typically third-party,
less protected than the database, and entirely **outside the RLS boundary** the rest of this
system is careful about — and it would blow up cardinality until the store fell over. Requests
that match no route collapse to a single `<unmatched>` series rather than minting one series per
junk URL.

There are **no `agency_id`, `user_id` or `case_id` labels anywhere**. Per-tenant metrics ("which
agency is busiest") would be genuinely useful and are a **product decision, not a config change**
— it means exporting the tenant dimension into a system with a different protection model, and
it should be decided explicitly rather than added because a dashboard looked sparse.

### ⚠ Counters are per process

They live in memory, so they describe the worker that answered the scrape. The API runs a
**single** uvicorn worker today (`backend/scripts/start.sh` passes no `--workers`), which makes
them complete and correct. If workers are ever added, a scrape lands on whichever one answers
and the numbers become per-worker and jumpy — at that point you need per-worker scrape targets
or a multiprocess collector. Restarts reset the counters, which is normal: `rate()` and
`increase()` handle counter resets.

### Alerting

Alerting is configured in your monitoring vendor, not in this repo — no SDK is embedded here on
purpose.

**Page a human** (something is broken and will not fix itself):

- **`/ready` returns 503 for more than ~2 consecutive checks.** One 503 during a deploy is
  normal. Sustained means a *critical* check is failing — read the body, it names which:
  - **`database`** — Postgres unreachable. Nothing works. Page.
  - **`schema_at_head`** — the schema is behind the code. Writes will 500 with nothing naming
    the cause (this exact failure once broke case creation). Page; fix with `alembic upgrade head`.
  - **`schema_grants`** — the `ittu_app` role is missing a schema grant; whole features fail with
    `InsufficientPrivilege`. Page; fix with `scripts/create_app_role.sql`.
  - **`redis`** — critical *only* when something actually queues
    (`ITTU_NOTIFICATION_DELIVERY=worker` or `ITTU_DIAL_ENQUEUE_ON_START=true`). Dispatch silently
    stops. Page in those configurations.
- **`increase(ittu_audit_entries_dropped_total[1h]) > 0`.** An evidentiary record was lost.
  This is the alert the whole audit investment exists to justify: `verify_chain` detects a
  *forked* or *edited* chain but **cannot** detect an entry that was never written — no gap
  appears in the hash links, so the trail verifies clean while a record is missing. This counter
  is the only signal that it happened. Treat any non-zero value as an incident, and read `reason`:
  - `seq_contention` — sustained concurrent writes to one agency's chain exhausted the retry
    budget (see `app/core/audit.py`).
  - `chain_head_uncommitted` — a denial could not be appended because the enclosing transaction
    held the chain position. Expected to be zero; a non-zero value means a code path is writing a
    success entry and then a denial in one transaction.
  - `error` / `no_agency` — an unexpected failure, or an action with no tenant to attribute it to.

**Warn only** (worth looking at, not worth waking anyone):

- **`rls_enforcing` false** — the app is connected as an owning role, so RLS is silently bypassed
  and agency isolation is not actually enforced. Legitimate in a single-role local setup, **never**
  in production. Non-critical in `/ready` (it would otherwise mark every POC deployment permanently
  unready, which trains people to ignore the endpoint) — so it needs its own alert to be seen at all.
- **5xx rate**: `sum(rate(ittu_http_requests_total{status=~"5.."}[5m]))` above your baseline.
- **Latency**: `histogram_quantile(0.95, sum by (le, route) (rate(ittu_http_request_duration_seconds_bucket[5m])))`
  creeping on a route that used to be fast.
- **`ittu_audit_denials_suppressed_total` rising** — someone is generating refusals fast enough to
  hit the rate cap. Expected under abuse and *not* a failure (the cap is deliberate), but a sustained
  climb is worth a look at who.

## Notes
- **CORS:** the backend now reads allowed origins from `ITTU_CORS_ORIGINS` — set it to the
  Vercel domain or the browser will block API calls.
- **RLS/persistence:** LIVE auth-isolation needs a real Postgres (Neon free tier); the POC
  demo does not. See the migration `20260708_05` + `db.py` docstrings for the runtime check,
  and §4 above for the app-role setup RLS actually depends on.
- **Persistence toggle:** `ITTU_PERSISTENCE` (`memory`/`postgres`, default `memory`) gates
  whether any repository reads/writes Postgres at all — `memory` keeps today's in-memory POC
  behavior unchanged even once `ITTU_DATABASE_URL` is set. See `app/core/config.py`.
- **Data sovereignty:** regulator/on-prem deployments use K3s with the same OCI images — not
  the free cloud tiers above (those are for the hackathon demo).
