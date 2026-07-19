"""ITTU API — app factory + lifespan (P0 scaffold)."""

import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.exceptions import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.auth.router import router as auth_router
from app.core.config import get_settings
from app.core.db import engine
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
    from app.infiltrate.service import seed_demo_session

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
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": detail},
            headers=exc.headers,  # e.g. WWW-Authenticate: Bearer on 401s
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
        return JSONResponse(status_code=http_status, content={"error": {"code": code, "message": message}})

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "mode": settings.mode}

    for router in (
        auth_router,
        infiltrate_router,
        trace_router,
        takedown_router,
        uncover_router,
        intel_router,
    ):
        app.include_router(router, prefix="/api")

    return app


app = create_app()
