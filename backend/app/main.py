"""ITTU API — app factory + lifespan (P0 scaffold)."""

import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: settings are resolved, the adapter registry is populated by
    # module imports, and the async DB engine is ready (pool connects lazily).
    # Later phases: warm caches, verify LIVE credentials, contract checks.
    # Seed one POC honeypot replay so the Honeypot console shows the live
    # demo narrative on first load (no manual POST needed). POC-only, idempotent.
    from app.core.migration_guard import assert_schema_at_head
    from app.infiltrate.service import seed_demo_session

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
                    {"name": c.name, "ok": c.ok, "detail": c.detail, "critical": c.critical}
                    for c in result.checks
                ],
            },
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
    ):
        app.include_router(router, prefix="/api")

    return app


app = create_app()
