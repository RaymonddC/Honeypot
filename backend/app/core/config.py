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

    # --- Outbound dialing (docs/Voice-Honeypot-Outbound.md §4) ----------------
    # Retry budget + backoff (ms) for the `dial_target` Dramatiq actor, mirroring
    # the notification worker's shape. A dial that fails to connect (busy /
    # carrier reject) is retried up to this many times before the target settles
    # as `failed`; the operator can still Requeue it afterwards.
    dial_max_retries: int = 3
    dial_retry_backoff_ms: int = 30_000
    # Whether starting a campaign actually enqueues the dial actor. Off by
    # default so `POST /campaigns/{id}/start` stays a pure status transition
    # unless an operator opts in — enqueueing needs a running `dramatiq
    # app.workers` + Redis, and in LIVE it would place real calls (Polri-gated,
    # design spec §0). POC enqueue is safe: the actor simulates, never dials.
    dial_enqueue_on_start: bool = False   # ITTU_DIAL_ENQUEUE_ON_START
    # Twilio (phase 5 groundwork, app/infiltrate/telephony.py). Empty = no real
    # telephony: the dialer simulates in POC and fails loud in LIVE. The number
    # dialled FROM is not here — it comes from the honeypot number pool, because
    # caller-ID rotation is an operational decision, not static config.
    twilio_account_sid: str = ""          # ITTU_TWILIO_ACCOUNT_SID
    twilio_auth_token: str = ""           # ITTU_TWILIO_AUTH_TOKEN (also signs webhooks)
    # Public origin Twilio reaches us on, e.g. https://ittu-api.onrender.com.
    # REQUIRED for webhook signature checks behind a proxy: Twilio signs the
    # exact public URL it called, but Render/Vercel terminate TLS and hand the
    # app an internal http:// host, so a URL rebuilt from the request would not
    # match and every genuine webhook would be rejected as forged.
    public_base_url: str = ""             # ITTU_PUBLIC_BASE_URL

    # Shared secret carried in the media-stream URL. Twilio cannot present our
    # JWT on a WebSocket, and it does NOT sign stream frames the way it signs
    # webhooks — the answer TwiML is the only place we control, so the token
    # goes in the URL we put there.
    #
    # EMPTY DISABLES THE STREAM ENDPOINT ENTIRELY. Without a token anyone who
    # learns the URL could open a socket and drive a persona, which is both an
    # LLM bill and a fabricated "call" in an evidentiary record — so an
    # unconfigured deployment refuses rather than accepting all comers.
    telephony_stream_token: str = ""      # ITTU_TELEPHONY_STREAM_TOKEN


    # CORS: origins allowed to call the API. Kept as a STRING (not list[str]) so
    # pydantic-settings never tries to JSON-decode the env var and crash on deploy.
    # ITTU_CORS_ORIGINS accepts any of:
    #   "https://a.vercel.app"                  (single bare origin)
    #   "https://a.com,https://b.com"           (comma-separated)
    #   '["https://a.vercel.app"]'              (JSON list)
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # --- Metrics (GET /metrics, Prometheus text) -----------------------------
    # Bearer token a scraper must present. EMPTY (the default) DISABLES the
    # endpoint entirely — it 404s, so an unconfigured deployment does not
    # advertise that it has metrics at all. Unlike /health and /ready, this one
    # is not safe to leave open: it enumerates every route template and the
    # request volume against each, which is reconnaissance for a
    # law-enforcement tool even though no ids are ever labelled. Prometheus,
    # Grafana Agent and Better Stack all support bearer tokens in scrape config.
    # See docs/Deploy.md §8.
    metrics_token: str = ""

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
    # Per-role Google Cloud TTS voice (id-ID WaveNet/Standard, e.g.
    # id-ID-Wavenet-A). Overridable per-request from the Control Panel.
    google_tts_voice_persona: str = "id-ID-Wavenet-A"  # ITTU_GOOGLE_TTS_VOICE_PERSONA (female)
    google_tts_voice_scammer: str = "id-ID-Wavenet-B"  # ITTU_GOOGLE_TTS_VOICE_SCAMMER (male)
    # Gemini TTS (Google AI Studio) — generative, natural-language STYLE control
    # (the persona is prompted to sound like a confused, hesitant grandmother,
    # which flat WaveNet voices can't do). Key is an AI Studio key, DISTINCT from
    # the Cloud-TTS key above. Indonesian is auto-detected from the text.
    gemini_api_key: str = ""              # ITTU_GEMINI_API_KEY
    gemini_tts_model: str = "gemini-2.5-flash-preview-tts"  # ITTU_GEMINI_TTS_MODEL
    # Per-role prebuilt Gemini voice (one of the ~30 named voices, e.g. Sulafat,
    # Charon, Kore). Overridable per-request from the Control Panel; the style
    # directive in the adapter does most of the emotional work regardless.
    gemini_voice_persona: str = "Sulafat"   # ITTU_GEMINI_VOICE_PERSONA (warm)
    gemini_voice_scammer: str = "Charon"    # ITTU_GEMINI_VOICE_SCAMMER (firmer)

    # --- LLM (live brain, paid + opt-in) --------------------------------------
    # Engaged only when INFILTRATE MODE=live or a session is started with
    # interactive=true AND a key is present. POC stays scripted + keyless.
    llm_model: str = "claude-haiku-4-5"   # ITTU_LLM_MODEL (fast/cheap for voice latency)
    llm_api_key: str = ""                 # ITTU_LLM_API_KEY (fallback: ANTHROPIC_API_KEY)
    # Optional base URL for an OpenAI-compatible gateway (e.g. OpenRouter). Usually
    # unneeded — a model prefixed "openrouter/..." routes automatically — but set
    # ITTU_LLM_API_BASE to force any custom endpoint.
    llm_api_base: str = ""                # ITTU_LLM_API_BASE

    # --- Crypto surface (product decision, 2026-09-05) --------------------------
    # Whether the crypto-facing product is exposed at all: TAKEDOWN in full
    # (wallet graph, risk scoring, investigations) and the crypto half of TRACE.
    #
    # OFF by default, deliberately. This hides a CAPABILITY, not a permission —
    # a role holding every capability still gets 404 from these routes while it
    # is off, because the honest answer is "this product does not offer that
    # here" rather than "you may not". 404 also avoids advertising that a crypto
    # feature exists but is withheld.
    #
    # ⚠️ Turning this off has a STRATEGY consequence recorded in
    # docs/Ecosystem-Strategy.md §5.1: crypto checking was the lower-risk way to
    # launch the public layer, because a wallet address is not a person and
    # publishing a score for one accuses nobody. With it hidden, the public
    # layer falls back to named bank accounts, which is the higher-exposure
    # path under UU ITE 27A / UU PDP. Hiding crypto is a decision about the
    # product, not a way to reduce legal risk.
    #
    # Nothing here stops the honeypot EXTRACTING wallet addresses — that
    # intelligence keeps accruing, so switching this on later has data behind it
    # rather than starting cold.
    crypto_enabled: bool = False          # ITTU_CRYPTO_ENABLED

    # --- Auth (P5) — we always mint OUR OWN JWT {sub, agency_id, role, exp} ---
    # Dev-only default (≥32 bytes for HS256); override via ITTU_JWT_SECRET in prod.
    jwt_secret: str = "ittu-dev-only-secret-change-me-in-prod-0123"
    jwt_algorithm: str = "HS256"
    # 1h, not a working day. Request auth never reads the database, so an
    # already-issued token is the ONLY thing between "deactivated" and
    # "actually cut off" — this TTL *is* that revocation window. Shortening
    # it further costs real re-logins: there is no refresh flow, so every
    # expiry bounces the operator to /login (which tells them why).
    jwt_ttl_seconds: int = 3600
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
    def conflicting_module_modes(self) -> dict[str, Mode]:
        """Overrides that disagree with the global mode ON A MODULE THAT PERSISTS.

        Empty = coherent. Only meaningful under Postgres — see
        ``assert_modes_are_coherent``.

        **Why this is narrowed to persisting modules.** The incoherence is about
        the row STAMP: ``app.data_mode`` is one value per transaction, so a
        module whose mode differs from the global one would write rows tagged
        with a mode that is not theirs. A module that writes no rows cannot do
        that. ``takedown`` and ``trace`` have no Postgres repository at all —
        their data flows through adapters (TRONSCAN, fixtures) and is never
        persisted — so ``ITTU_MODULE_MODES={"takedown":"live"}`` is provably
        incapable of mis-stamping anything.

        The first version of this guard refused every override and would have
        blocked exactly that configuration, which is the one a developer
        actually uses (a LIVE blockchain adapter against a POC database). A
        guard that refuses a provably safe setup does not make anyone safer; it
        teaches them to switch guards off.
        """
        return {
            m: v
            for m, v in self.module_modes.items()
            if v != self.mode and m in PERSISTING_MODULES
        }

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
    """Resolve the effective MODE for a module: override or global default.

    **Reads the settings singleton at USE, never captures it.** It used to take
    a ``Settings`` in ``__init__`` and hold it, which was a quiet defect: this
    class is handed out by an ``@lru_cache``d factory, so ``get_settings.
    cache_clear()`` — done by the pgserver tests to point alembic at an
    ephemeral cluster — rebuilt the singleton while this resolver kept the
    orphaned one. ``/api/config`` and ``_auth_mode()`` then reported a MODE
    nobody could change, and the only reason CI stayed green was that the test
    files doing the clearing happened to sort alphabetically after the ones
    checking MODE. Stateless now, so the cache on the factory is harmless.
    """

    def effective_mode(self, module: str) -> Mode:
        settings = get_settings()
        return settings.module_modes.get(module, settings.mode)


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_mode_resolver() -> ModeResolver:
    return ModeResolver()


# Modules that own a Postgres repository and therefore write mode-stamped rows.
# Verified against the tree: takedown and trace have no repository.py Postgres
# class and no session writes — they read through adapters and persist nothing.
# If a module here ever gains or loses persistence, this set must follow it, or
# the coherence guard silently stops covering it.
PERSISTING_MODULES = frozenset(
    {"infiltrate", "uncover", "cases", "casedata", "honeypot_ops"}
)


def assert_modes_are_coherent() -> None:
    """Refuse to run Postgres with per-module modes that disagree with the global.

    **Why this is a hard error and not a warning.** Under Postgres, mode is
    enforced by RLS: ``_tenant_scoped_session`` sets ``app.data_mode`` and the
    policies compare each row's ``data_mode`` against it (migration 20260823_18).
    That variable is ``SET LOCAL`` — ONE value for the whole transaction — and
    ``_tenant_scoped_session`` opens one transaction per REQUEST. A request is
    not module-scoped: UNCOVER reads chain data in the same transaction it
    writes a bundle. So when modules disagree there is no value for
    ``app.data_mode`` that is honest for the whole request, and every choice
    silently mis-stamps or hides someone's rows.

    Memory mode has no RLS and no row stamping, so mixed module modes stay fully
    supported there — which is where they are actually used (a LIVE takedown
    adapter against replayed INFILTRATE transcripts).

    Raises ``RuntimeError`` naming both offending values and both ways out; a
    rule the reader cannot act on is a rule they will work around.
    """
    settings = get_settings()
    if settings.persistence != "postgres":
        return
    conflicts = settings.conflicting_module_modes
    if not conflicts:
        return

    listed = ", ".join(f"{module}={mode!r}" for module, mode in sorted(conflicts.items()))
    raise RuntimeError(
        f"INCOHERENT MODE CONFIG: ITTU_MODE={settings.mode!r} but ITTU_MODULE_MODES "
        f"overrides {listed}, and ITTU_PERSISTENCE=postgres.\n"
        "\n"
        "Why this cannot work: under Postgres, POC/LIVE isolation is enforced by "
        "row-level security. The database is told the request's mode ONCE per "
        "transaction (app.data_mode), and one request spans several modules — so a "
        "per-module mode cannot be honestly represented in the row stamp. Rather "
        "than write rows tagged with a mode that is not theirs, this refuses to start.\n"
        "\n"
        "Two ways out:\n"
        f"  1. Set ITTU_PERSISTENCE=memory — mixed module modes are fully supported "
        f"there ({listed} keeps working).\n"
        f"  2. Align the override(s) with the global mode, or drop them from "
        f"ITTU_MODULE_MODES so everything runs as ITTU_MODE={settings.mode!r}.\n"
        "\n"
        "See docs/Adapter-MODE-Framework.md '`data_mode` enforcement'."
    )
