"""ITTU API — app factory + lifespan (P0 scaffold)."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

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
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
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
        return JSONResponse(status_code=exc.status_code, content={"error": detail})

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "mode": settings.mode}

    for router in (
        infiltrate_router,
        trace_router,
        takedown_router,
        uncover_router,
        intel_router,
    ):
        app.include_router(router, prefix="/api")

    return app


app = create_app()
