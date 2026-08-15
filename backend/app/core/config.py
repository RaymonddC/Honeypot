"""Settings + MODE resolution (see docs/Adapter-MODE-Framework.md).

Env vars use the ``ITTU_`` prefix, e.g.::

    ITTU_MODE=poc
    ITTU_MODULE_MODES={"takedown":"live"}
    ITTU_DATABASE_URL=postgresql+asyncpg://ittu:ittu@localhost:5432/ittu
    ITTU_REDIS_URL=redis://localhost:6379/0
"""

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

Mode = Literal["poc", "live"]

# `auth` is a cross-cutting module: POC = demo login, LIVE = Google OAuth.
MODULES = ("infiltrate", "trace", "takedown", "uncover", "intel", "auth")

# Absolute path to backend/.env (this file is backend/app/core/config.py), so the
# .env is found no matter which directory uvicorn is launched from. A relative
# "./.env" is also checked (harmless if missing) for any other layout.
_BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ITTU_",
        env_file=(str(_BACKEND_DIR / ".env"), ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # POC is the safe default; LIVE requires explicit config + credentials.
    mode: Mode = "poc"
    # Per-module override, e.g. ITTU_MODULE_MODES='{"takedown":"live"}'
    module_modes: dict[str, Mode] = {}

    database_url: str = "postgresql+asyncpg://ittu:ittu@localhost:5432/ittu"
    redis_url: str = "redis://localhost:6379/0"

    # Persistence toggle (docs/Persistence-Plan.md P-1). "memory" is the safe
    # default — the POC runs with NO database, exactly today's behavior. Flipping
    # to "postgres" (ITTU_PERSISTENCE=postgres) is a P-2+ concern: it only takes
    # effect once repositories actually read this flag (not wired here).
    persistence: Literal["memory", "postgres"] = "memory"

    # Owner/migration DB URL — used by the container's entrypoint to run
    # `alembic upgrade head` on deploy. The app's ITTU_DATABASE_URL is the
    # NON-owning ittu_app role (RLS-subject) which can't run DDL, so migrations
    # must connect as the OWNING role via this var. Empty = auto-migration is
    # skipped (the DB is assumed already at head). Same asyncpg URL form as
    # ITTU_DATABASE_URL (postgresql+asyncpg://…?ssl=require).
    migration_database_url: str = ""

    # Blockchain LIVE (takedown module): optional TRONSCAN key for higher rate
    # limits. The public API works keyless; set ITTU_TRONSCAN_API_KEY in prod.
    tronscan_api_key: str = ""

    # Notification LIVE (uncover module): operator-owned webhook URL that
    # receives each dispatch packet as JSON POST. Empty = fail loud (no
    # silent mock fallback — Adapter-MODE principle #3).
    notification_webhook_url: str = ""    # ITTU_NOTIFICATION_WEBHOOK_URL
    # HMAC-SHA256 signing key. When set, every LIVE dispatch carries an
    # `X-ITTU-Signature: t=<ts>,v1=<hex>` header the recipient verifies to
    # prove the packet is genuinely from ITTU (and, via the timestamp, isn't a
    # replay). Empty = unsigned POST (acceptable only on a trusted internal
    # endpoint; set it for any cross-org agency webhook). Booleans-only leaves
    # the API — the key itself never appears in a response or a stored payload.
    notification_webhook_secret: str = ""   # ITTU_NOTIFICATION_WEBHOOK_SECRET
    # LIVE delivery engine: "sync" POSTs inline during the dispatch request
    # (simple, no infra); "worker" persists each notification as `queued` and
    # hands delivery to the `dispatch_notifications` Dramatiq actor (durable,
    # retried, off-request — the production path). "worker" requires
    # ITTU_PERSISTENCE=postgres (the actor reads the row cross-process) and a
    # running `dramatiq app.workers` + Redis; it fails loud otherwise. POC
    # (mock sink) ignores this entirely.
    notification_delivery: Literal["sync", "worker"] = "sync"
    # Worker delivery retry budget + backoff (ms) for the Dramatiq actor.
    notification_max_retries: int = 3
    notification_retry_backoff_ms: int = 30_000
    # Per-webhook HTTP timeout (seconds).
    notification_webhook_timeout_seconds: float = 15.0

    # CORS: origins allowed to call the API. Kept as a STRING (not list[str]) so
    # pydantic-settings never tries to JSON-decode the env var and crash on deploy.
    # ITTU_CORS_ORIGINS accepts any of:
    #   "https://a.vercel.app"                  (single bare origin)
    #   "https://a.com,https://b.com"           (comma-separated)
    #   '["https://a.vercel.app"]'              (JSON list)
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # --- Voice (P4b/#15) — TTS provider behind the TTSAdapter Protocol --------
    # "browser" (default) = POC voice marks: no server audio, the browser's
    # SpeechSynthesis speaks the line. A real provider name (elevenlabs |
    # google | higgsfield) upgrades to natural server-side audio — MODE-
    # independent, so the deployed POC demo can get the real voice with just
    # this env var + the provider's key. Fail-loud if selected without a key.
    tts_provider: str = "browser"
    # Real-voice provider keys (booleans only ever leave the API — never the key).
    elevenlabs_api_key: str = ""          # ITTU_ELEVENLABS_API_KEY
    # Flash = low-latency model (~sub-second, multilingual incl. id-ID) — better
    # for a live call than the slower eleven_multilingual_v2. Voice IDs are
    # per-account; override if the defaults aren't in your ElevenLabs library.
    elevenlabs_model: str = "eleven_flash_v2_5"             # ITTU_ELEVENLABS_MODEL
    # Generic FALLBACK voice IDs — set your real per-account IDs in .env
    # (ITTU_ELEVENLABS_VOICE_PERSONA / _SCAMMER), not here in code.
    elevenlabs_voice_persona: str = "21m00Tcm4TlvDq8ikWAM"  # ITTU_ELEVENLABS_VOICE_PERSONA (fallback: Rachel)
    elevenlabs_voice_scammer: str = "pNInz6obpgDQGcFmaJgB"  # ITTU_ELEVENLABS_VOICE_SCAMMER (fallback: Adam)
    google_tts_api_key: str = ""          # ITTU_GOOGLE_TTS_API_KEY
    # Gemini TTS (Google AI Studio) — generative, natural-language STYLE control
    # (the persona is prompted to sound like a confused, hesitant grandmother,
    # which flat WaveNet voices can't do). Key is an AI Studio key, DISTINCT from
    # the Cloud-TTS key above. Indonesian is auto-detected from the text.
    gemini_api_key: str = ""              # ITTU_GEMINI_API_KEY
    gemini_tts_model: str = "gemini-2.5-flash-preview-tts"  # ITTU_GEMINI_TTS_MODEL

    # --- LLM (live brain, paid + opt-in) --------------------------------------
    # Engaged only when INFILTRATE MODE=live or a session is started with
    # interactive=true AND a key is present. POC stays scripted + keyless.
    llm_model: str = "claude-haiku-4-5"   # ITTU_LLM_MODEL (fast/cheap for voice latency)
    llm_api_key: str = ""                 # ITTU_LLM_API_KEY (fallback: ANTHROPIC_API_KEY)
    # Optional base URL for an OpenAI-compatible gateway (e.g. OpenRouter). Usually
    # unneeded — a model prefixed "openrouter/..." routes automatically — but set
    # ITTU_LLM_API_BASE to force any custom endpoint.
    llm_api_base: str = ""                # ITTU_LLM_API_BASE

    # --- Auth (P5) — we always mint OUR OWN JWT {sub, agency_id, role, exp} ---
    # Dev-only default (≥32 bytes for HS256); override via ITTU_JWT_SECRET in prod.
    jwt_secret: str = "ittu-dev-only-secret-change-me-in-prod-0123"
    jwt_algorithm: str = "HS256"
    jwt_ttl_seconds: int = 8 * 3600
    # LIVE Google OAuth: expected `aud` of the verified id_token.
    google_client_id: str = ""
    # LIVE Google OAuth operator provisioning (no self-service signup): a JSON
    # allowlist mapping real Google emails → an agency (slug) + role. An email
    # can log in via POST /api/auth/google ONLY if it's a seeded user OR listed
    # here. Kept as a STRING (parsed in `oauth_provision_list`) so pydantic never
    # tries to JSON-decode the env var and crash on deploy. Example:
    #   ITTU_OAUTH_PROVISION=[{"email":"you@gmail.com","agency":"bareskrim","role":"police-investigator"}]
    oauth_provision: str = ""

    @property
    def persistence_enabled(self) -> bool:
        """True once persistence is flipped to Postgres (ITTU_PERSISTENCE=postgres)."""
        return self.persistence == "postgres"

    @property
    def effective_llm_api_key(self) -> str:
        """Live-LLM key: ITTU_LLM_API_KEY, falling back to ANTHROPIC_API_KEY."""
        return self.llm_api_key or os.environ.get("ANTHROPIC_API_KEY", "")

    @property
    def oauth_provision_list(self) -> list[dict[str, str]]:
        """Parse ITTU_OAUTH_PROVISION → [{email, agency, role}, ...].

        Malformed JSON / bad entries yield an empty list (fail CLOSED — no email
        gets provisioned rather than silently mis-provisioned). Emails are
        lower-cased for case-insensitive matching.
        """
        raw = self.oauth_provision.strip()
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []
        out: list[dict[str, str]] = []
        for entry in data if isinstance(data, list) else []:
            if not isinstance(entry, dict):
                continue
            email, agency, role = entry.get("email"), entry.get("agency"), entry.get("role")
            if email and agency and role:
                out.append(
                    {"email": str(email).lower(), "agency": str(agency), "role": str(role)}
                )
        return out

    @property
    def cors_origin_list(self) -> list[str]:
        """Parse cors_origins → list, accepting JSON, comma-separated, or a single origin."""
        raw = self.cors_origins.strip()
        if not raw:
            return []
        if raw.startswith("["):
            try:
                return [str(o).strip() for o in json.loads(raw) if str(o).strip()]
            except json.JSONDecodeError:
                pass
        return [o.strip() for o in raw.split(",") if o.strip()]


class ModeResolver:
    """Resolve the effective MODE for a module: override or global default."""

    def __init__(self, settings: "Settings") -> None:
        self._settings = settings

    def effective_mode(self, module: str) -> Mode:
        return self._settings.module_modes.get(module, self._settings.mode)


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_mode_resolver() -> ModeResolver:
    return ModeResolver(get_settings())
