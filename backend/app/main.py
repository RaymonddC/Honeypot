"""ITTU API — app factory + lifespan (P0 scaffold)."""

import logging
import secrets
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.auth.router import router as auth_router
from app.cases.router import router as cases_router
from app.casedata.router import router as casedata_router
from app.core.config import get_settings
from app.core.db import engine
from app.core.requests import (
    REQUEST_ID_HEADER,
    RequestContextMiddleware,
    current_request_id,
)
from app.honeypot_ops.router import router as honeypot_ops_router
from app.infiltrate.router import router as infiltrate_router
from app.intel.router import router as intel_router
from app.takedown.router import router as takedown_router
from app.trace.router import router as trace_router
from app.uncover.router import router as uncover_router
from app.users.router import router as users_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: settings are resolved, the adapter registry is populated by
    # module imports, and the async DB engine is ready (pool connects lazily).
    # Later phases: warm caches, verify LIVE credentials, contract checks.
    # Seed one POC honeypot replay so the Honeypot console shows the live
    # demo narrative on first load (no manual POST needed). POC-only, idempotent.
    from app.core.config import assert_modes_are_coherent
    from app.core.migration_guard import assert_schema_at_head
    from app.infiltrate.service import seed_demo_session

    # Refuse to start with per-module modes that disagree with the global mode
    # under Postgres: `app.data_mode` is one value per transaction and a request
    # spans modules, so there is no honest per-module row stamp. Checked BEFORE
    # the schema guard because it needs no database — a misconfiguration should
    # not first present as a connection error.
    assert_modes_are_coherent()

    # Fail loud at boot if the Postgres schema is behind the code's migration
    # head — a drifted schema 500s on the first write (e.g. the missing
    # core.cases.stage column that broke "create case"). No-op in memory mode.
    await assert_schema_at_head()

    # Print the live-LLM state on startup so it's obvious whether the interactive
    # persona will improvise (real key loaded) or fall back to the scripted stall.
    s = get_settings()
    logging.getLogger("uvicorn.error").warning(
        "ITTU live LLM: %s | model=%s | base=%s",
        "LIVE (real improv)" if s.effective_llm_api_key else "SCRIPTED fallback (no key loaded)",
        s.llm_model,
        s.llm_api_base or "(provider default)",
    )
    if s.mode == "live" and s.persistence == "postgres":
        # A LIVE deployment reads ONLY live-stamped rows (migration 20260823_18),
        # and every row written before mode isolation existed is 'poc' by column
        # default. So the first LIVE boot against an existing database shows an
        # EMPTY case list — correct, and alarming enough that someone will file
        # it as an outage and "fix" it by loosening the policy. Say so out loud,
        # once, so the blank screen arrives with its explanation attached.
        logging.getLogger("uvicorn.error").warning(
            "ITTU mode: LIVE + postgres — RLS returns ONLY data_mode='live' rows. "
            "Pre-existing POC data is intentionally invisible, not lost (it is still "
            "in the tables, readable in POC mode). See docs/Deploy.md §4a."
        )
    if not s.metrics_token:
        # /metrics 404s without a token, which is indistinguishable from "this
        # build has no metrics". Say so once at boot so a failing scrape is
        # diagnosable without exposing anything to an anonymous caller.
        logging.getLogger("uvicorn.error").warning(
            "ITTU metrics: /metrics DISABLED (no ITTU_METRICS_TOKEN set) — it will 404"
        )
    await seed_demo_session()
    yield
    # Shutdown
    await engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="ITTU",
        description="Infiltrate, Trace, Takedown & Uncover — AI financial-crime forensics.",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Added AFTER CORS so it wraps it: a request rejected by CORS should still
    # get an id and a log line, otherwise the one failure users report most
    # ("it just doesn't work from the browser") is the one with no trace.
    app.add_middleware(RequestContextMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(HTTPException)
    async def error_envelope(request, exc: HTTPException):
        # API contract error shape: {"error": {"code", "message", "detail?"}}
        detail = exc.detail if isinstance(exc.detail, dict) else {
            "code": "http_error", "message": str(exc.detail),
        }
        # Echo the request id INTO the body, not just the header: a user
        # reporting a failure copies what they can see, and "it failed" plus an
        # id is the difference between reproducing and guessing.
        request_id = current_request_id()
        if request_id:
            detail = {**detail, "request_id": request_id}
        headers = dict(exc.headers or {})
        if request_id:
            headers[REQUEST_ID_HEADER] = request_id
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": detail},
            headers=headers or None,  # e.g. WWW-Authenticate: Bearer on 401s
        )

    @app.exception_handler(httpx.HTTPError)
    async def upstream_provider_error(request, exc: httpx.HTTPError):
        # Any upstream data-provider failure (TRONSCAN/TronGrid, etc.) → clean
        # envelope, never a 500 stack trace. A 429 is a transient rate-limit
        # (retryable); anything else is treated as a provider outage.
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 429:
            code, message, http_status = (
                "provider_rate_limited",
                "The blockchain data provider is rate-limiting requests (free-tier "
                "limit). Retry shortly, or set ITTU_TRONSCAN_API_KEY for higher limits.",
                503,
            )
        else:
            code, message, http_status = (
                "provider_unavailable",
                "The upstream blockchain data provider is currently unavailable.",
                502,
            )
        body = {"code": code, "message": message}
        if current_request_id():
            body["request_id"] = current_request_id()
        return JSONResponse(status_code=http_status, content={"error": body})

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Liveness. Deliberately SHALLOW — this is the platform health check, and
        a transient database blip must not take the service down. Use /ready to
        find out whether dependencies are actually working."""
        return {"status": "ok", "mode": settings.mode}

    @app.get("/ready")
    async def ready() -> JSONResponse:
        """Readiness + diagnostics: database reachable, schema at migration head,
        schema grants present, RLS actually enforcing, Redis reachable.

        Each check is here because that failure cost real debugging time and its
        symptom pointed somewhere unhelpful (see app/core/health.py). Returns 503
        when a critical check fails so it can back a readiness probe; the body is
        the same either way so a human can read WHY. Contains no secrets and no
        connection strings — it is unauthenticated by design, like /health."""
        from app.core.health import readiness

        result = await readiness()
        return JSONResponse(
            status_code=200 if result.ready else 503,
            content={
                "ready": result.ready,
                "mode": result.mode,
                "persistence": result.persistence,
                "checks": [
                    # `status` is the one to read: "pass" | "fail" | "unknown".
                    # `ok` is null when a check could not determine an answer —
                    # NOT the same as passing, and reporting it as true is how
                    # this endpoint once said a service was fine while it had no
                    # idea whether its schema matched its code.
                    {
                        "name": c.name,
                        "status": c.status,
                        "ok": c.ok,
                        "detail": c.detail,
                        "critical": c.critical,
                    }
                    for c in result.checks
                ],
            },
        )

    @app.get("/metrics", include_in_schema=False)
    async def metrics_endpoint(request: Request) -> Response:
        """Prometheus text exposition: request rate/latency/errors, and — the
        reason this exists — the count of audit entries that could NOT be written.

        ``verify_chain`` detects a forked or edited chain but CANNOT detect an
        entry that was never written: no gap appears in the prev-links, so the
        log verifies clean while a record is missing. ``ittu_audit_entries_
        dropped_total`` is the only thing that makes that visible to alerting.

        **Authenticated, unlike /health and /ready.** Those carry booleans a
        probe needs and cannot supply a token for. This one lists every route
        template and how often each was called — an API map plus operational
        tempo. No agency, user or case is ever labelled (see app/core/metrics.py),
        so it cannot answer "what did agency X do", but "when is this system
        busy, and what does it expose" is still reconnaissance worth withholding
        from anonymous callers. Scrapers support bearer tokens; probes do not,
        which is exactly the line drawn here.

        With no ``ITTU_METRICS_TOKEN`` set the endpoint 404s rather than 403s:
        an unconfigured deployment should look like one that has no metrics at
        all. The startup log says so, so an operator debugging a failing scrape
        is not left guessing.
        """
        from app.core import metrics as metrics_module

        expected = get_settings().metrics_token
        presented = (request.headers.get("authorization") or "").removeprefix("Bearer ").strip()
        # compare_digest, not ==, so response timing does not leak the prefix.
        if not expected or not secrets.compare_digest(presented, expected):
            raise HTTPException(status_code=404, detail={"code": "not_found"})
        return Response(
            content=metrics_module.render(),
            # The version parameter is part of the contract: scrapers content-negotiate on it.
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    for router in (
        auth_router,
        infiltrate_router,
        trace_router,
        takedown_router,
        uncover_router,
        intel_router,
        casedata_router,
        cases_router,
        honeypot_ops_router,
        users_router,
    ):
        app.include_router(router, prefix="/api")

    return app


app = create_app()
