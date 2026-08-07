# ITTU — Persistence + Auth Foundation Plan

> **STATUS (superseded — historical plan): P-1…P-4 are BUILT.** This doc reads as a
> forward plan, but the wiring it describes is done: RLS + the non-owning `ittu_app`
> role (migrations 05/06/08–10), `core.evidence_manifest` + `chain.graph_snapshots`,
> and dual in-memory/Postgres repositories selected by `settings.persistence` for
> INFILTRATE (`app/infiltrate/repository.py`), UNCOVER (`app/uncover/repository.py`),
> AUTH/users (`app/core/user_repository.py`), and case data (`app/casedata`, `app/cases`).
> Google OAuth is live (`app/auth/router.py:post_google_login`). Read below as the
> rationale/design record, not an open to-do list.

## The key insight
**The database layer is ~90% built and completely unused at request time.** We
have: the async engine + `Base`, SQLAlchemy models for all 5 schemas
(`core/intel/chain/fiat/action`), Alembic migrations `01–05`, RLS policies on
`core.*`, and an RLS-aware `get_tenant_session` dependency that sets
`app.current_agency/user/role`. **No route uses any of it** — all state is ~7
module-level dicts. So this is a **wiring job**, not a rebuild.

## What actually needs migrating (the whole target)
| Store | File | → Table |
|---|---|---|
| `_SESSIONS`, `_MESSAGES`, `_ENTITIES`, `_SYNDICATES` | `infiltrate/service.py` | `intel.scam_sessions / messages / entities / syndicates(+members)` |
| `_LIVE_STATES` (ephemeral in-flight) | `infiltrate/service.py` | none — stays in-memory/Redis |
| `_ACTIONS`, `_DOCUMENTS` | `uncover/service.py` | `action.action_documents / notifications` |
| `_USERS` | `core/auth.py` | `core.users` (agencies already seeded) |
| `_CACHE` (fiat↔crypto memo) | `trace/service.py` | derivable — **skip** |

TAKEDOWN / CHAIN / FIAT / INTEL routers are **stateless** (compute over adapters) — nothing to migrate. The demo-seeded `uuid5` user/agency ids **already match** the seeded `core.agencies/users` rows, so existing JWTs line up once Postgres is live.

## Architecture decisions (made as lead)
1. **Repository pattern behind the existing service logic.** Each store becomes a repo module (`infiltrate/repository.py`, `uncover/repository.py`) exposing the *same* read/write surface the service uses today, returning the *same Pydantic models*. Service business logic is untouched — only store access swaps.
2. **Repository = a MODE boundary, like everything else.** An in-memory repo (POC, no DB — keeps the run-lean demo + fast tests) and a Postgres repo (LIVE), selected by a `persistence` setting / DB availability. Consistent with the adapter/MODE framework; lets us migrate module-by-module without breaking the demo.
3. **RLS is the hard isolation backstop.** Extend RLS DDL to the agency-scoped `intel/chain/fiat/action` tables (currently only `core.*`), matching the `core` policy shape. Routes use `get_tenant_session`; the app connects as a **non-superuser role**; app-level filtering is defense-in-depth on top.
4. **Every write stamps `agency_id` (from `AuthContext`) + `data_mode` (from `settings.mode`).** Reads are RLS-filtered by `app.current_agency`. This is what makes it multi-tenant.
5. **Separate Postgres instances per `data_mode` in prod** (poc vs live), per `Data-Model.md` — demo data physically cannot enter a real case. Managed Postgres = **Neon** (free tier) to start.
6. **Auth enforcement turns on with persistence.** The currently-unauthenticated read routes get `get_current_user` so agency scoping actually applies; Google OAuth stub gets fleshed out as its own track.

## Decomposition & build order (delegatable chunks)
Each phase is one delegation; I own schema/contract decisions + review between phases.

- **P-1 · DB foundation & harness** *(migrations + infra)* — Migration `06`: `ENABLE ROW LEVEL SECURITY` + policies on the agency-scoped `intel/chain/fiat/action` tables; add the two doc-specified-but-missing tables (`core.evidence_manifest`, `chain.graph_snapshots`). Create the non-superuser **app role**; make `get_tenant_session` the request path; add the `persistence` toggle + Neon `DATABASE_URL`. A **test Postgres** harness (testcontainers or a dockerized pg — RLS/schemas can't run on sqlite). Deliver: repos can be built against a real, RLS-enforcing DB.
- **P-2 · INFILTRATE persistence** *(biggest store)* — `infiltrate/repository.py` (in-memory + Postgres impls) backing the 4 intel stores; swap `service.py` store access; thread `agency_id` + `data_mode`; port `seed_demo_session` to an idempotent DB seed; keep `_LIVE_STATES` ephemeral. Tests both impls.
- **P-3 · UNCOVER persistence** — `uncover/repository.py` backing `_ACTIONS/_DOCUMENTS` + the custody log → `action.*`. Same pattern.
- **P-4 · AUTH real + isolation** — persist `_USERS` → `core.users` (upsert on login); enforce `get_current_user` on read routes; **prove multi-agency isolation** (agency A cannot read agency B's sessions — an RLS integration test); flesh out Google OAuth (add `google-auth`, real `id_token` verification + provisioning).
- **P-5 · Verify & cutover** — end-to-end: restart-durable state, isolation proven, `data_mode` separation, the full demo running on Postgres. Deploy: provision Neon, run migrations, set `ITTU_DATABASE_URL` + persistence-on + the app role on Render.

## Delegation map
- P-1 → a migrations/DB-infra specialist. P-2/P-3 → persistence specialists (one each). P-4 → an auth specialist. **I own:** the repository interface contract, schema calls, the isolation-test design, and review between every phase.

## Risks / open calls
- **Testing DB + RLS needs a real Postgres** (testcontainers in CI) — sqlite can't do schemas/RLS. Non-trivial CI change.
- **Keep the in-memory fallback?** Yes (decision #2) — preserves the zero-dependency POC demo + fast unit tests; DB repo is the LIVE path. Costs a second impl per store.
- **`_LIVE_STATES`** (in-flight voice/engagement) stays ephemeral — Redis if we need it cross-process.
- **Read-route auth**: adding `get_current_user` to now-open endpoints is a behavior change; the frontend already sends the bearer, so low risk, but verify.

## Recommended first step
Delegate **P-1** (migrations + harness) — it unblocks everything and is self-contained. I'll review the migration + role setup before P-2 starts.
