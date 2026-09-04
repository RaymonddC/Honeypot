"""AUTH router — login (POC demo / LIVE Google), identity, effective config.

POST /api/auth/login   {agency_id|agency_type, role?} → JWT       (POC demo login)
POST /api/auth/google  {id_token}                     → JWT       (LIVE Google OAuth)
GET  /api/auth/me                                     → {user, agency, role}
GET  /api/config                                      → effective MODE per module
                                                        + registered adapters

Demo (mock) login is POC-only. Google login works in **either** mode once
``ITTU_GOOGLE_CLIENT_ID`` is set (the id_token audience is always verified): in
POC a verified account that isn't seeded/allowlisted gets a default demo
identity; in LIVE it's provisioned-only (fail closed). ``effective_mode("auth")``
is the same MODE machinery as every other boundary.
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.adapters import BOUNDARY_MODULE, registered
from app.core.audit import AUTH_LOGIN, record_action
from app.core.auth import (
    DEFAULT_ROLE_BY_AGENCY_TYPE,
    ROLES,
    CurrentUser,
    SeedAgency,
    SeedUser,
    _user_id,
    find_agency,
    find_agency_by_type,
    mint_token,
)
from app.core.config import MODULES, get_mode_resolver, get_settings
from app.core.db import get_optional_session
from app.core.user_repository import UserRepository, get_user_repository, resolve_demo_user
from app.users.schemas import RoleName

router = APIRouter(tags=["auth"])


# --- Schemas -------------------------------------------------------------------


class AgencyOut(BaseModel):
    id: str
    slug: str
    name: str
    type: str


class UserOut(BaseModel):
    id: str
    email: str
    name: str
    role: str
    agency_id: str


class LoginRequest(BaseModel):
    """POC demo login — pick a seeded agency (by uuid or slug) and a role."""

    agency_id: str | None = None  # uuid or slug (bareskrim|ppatk|ojk|bank-bca|indodax)
    agency_type: Literal["regulator", "police", "bank", "exchange"] | None = None
    # A constrained string, not a Literal of the six built-ins. Roles are DATA
    # (core.roles) and can be created in the admin UI — pinning the list here
    # would let an operator create a role that nobody can then sign in with,
    # rejected by a schema before any of our own checks ran. Existence is
    # checked against the roles table below, where the refusal can name the
    # role and say what to do.
    role: RoleName | None = None


class GoogleLoginRequest(BaseModel):
    id_token: str


class TokenResponse(BaseModel):
    token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user: UserOut
    agency: AgencyOut
    role: str


class MeResponse(BaseModel):
    user: UserOut
    agency: AgencyOut
    role: str


class AdapterInfo(BaseModel):
    boundary: str
    module: str  # whose MODE governs this boundary
    mode: str  # the mode this impl is registered under
    impl: str  # class name
    active: bool  # impl selected under the current effective MODE


class ConfigResponse(BaseModel):
    mode: str  # global default MODE
    modules: dict[str, str]  # effective MODE per module (override or global)
    adapters: list[AdapterInfo]
    # --- Voice (#15) — read-only, no secrets: presence booleans only ---------
    tts_provider: str = "browser"  # effective ITTU_TTS_PROVIDER
    tts_providers: list[str] = []  # known live providers (voice.LIVE_TTS_PROVIDERS)
    live_keys: dict[str, bool] = {}  # provider slug -> is a LIVE key configured
    voice_defaults: dict[str, str] = {}  # caller number / greeting (POC fixture)
    # --- Outbound dialing — whether starting a campaign actually calls anything.
    # Both preconditions must hold, and BOTH fail silently otherwise: the flag is
    # read at boot, and enqueue errors are logged rather than raised so a broker
    # hiccup can't 500 a campaign start. Without this the Honeypot Ops page could
    # not tell an operator whether Start would do anything (see
    # docs/Voice-Honeypot-Outbound.md). Flags only — no URLs, no credentials.
    dialing: dict[str, bool | str] = {}


# --- Helpers ---------------------------------------------------------------------


def _auth_mode() -> str:
    return get_mode_resolver().effective_mode("auth")


def _reject_if_deactivated(user: SeedUser) -> None:
    """A deactivated account must not be able to obtain a NEW token.

    This is the mandatory half of revocation: request auth is pure JWT and does
    not read the database, so blocking issuance here is what actually bounds a
    deactivated user's access (to the remaining TTL of any token they already
    hold). See ``get_current_user``'s docstring for that residual window.
    """
    if not user.is_active:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "account_deactivated",
                "message": "This account has been deactivated. Contact your agency admin.",
            },
        )


async def _record_login(session, user: SeedUser, agency: SeedAgency, *, method: str) -> None:
    """Audit a successful login.

    Uses the UNSCOPED session (the same one the login boundary already uses):
    authentication by definition happens before a tenant context exists, so the
    RLS-scoped dependency isn't available yet — the agency is written explicitly
    from the resolved identity instead.

    Only successes are recorded here. Failed attempts are a different signal
    (brute-force detection) and belong in security logging, not in an agency's
    evidentiary chain, where they'd be noise a court has to wade through.
    """
    await record_action(
        session,
        agency_id=str(agency.id),
        action=AUTH_LOGIN,
        actor_user_id=str(user.id),
        actor_name=user.name,
        target_type="user",
        # No target_label: for a login the target IS the actor, and repeating it
        # renders as "Budi Santoso signed in Budi Santoso".
        target_id=str(user.id),
        detail={"method": method, "role": user.role, "email": user.email},
    )


def _token_response(user: SeedUser, agency: SeedAgency) -> TokenResponse:
    token, ttl = mint_token(user)
    return TokenResponse(
        token=token,
        expires_in=ttl,
        user=UserOut(
            id=str(user.id),
            email=user.email,
            name=user.name,
            role=user.role,
            agency_id=str(user.agency_id),
        ),
        agency=AgencyOut(
            id=str(agency.id), slug=agency.slug, name=agency.name, type=agency.type
        ),
        role=user.role,
    )


async def _role_exists(name: str) -> bool:
    """Whether a role is defined. Reads the roles table rather than the frozen
    ROLES tuple, so a role created in the admin UI is immediately usable for
    provisioning — otherwise the product would offer a button that makes
    something it then refuses to accept."""
    from app.core.roles import all_role_capabilities

    return name in await all_role_capabilities()


async def _provisioned_from_allowlist(email: str, settings) -> SeedUser | None:
    """Resolve an operator-allowlisted email → an unpersisted ``SeedUser``, or
    ``None`` if it isn't listed. Raises 500 (fail loud) on a malformed allowlist
    entry — a typo in agency/role must not silently degrade to "not provisioned".
    """
    spec = next(
        (e for e in settings.oauth_provision_list if e["email"] == email.lower()), None
    )
    if spec is None:
        return None
    agency = find_agency(spec["agency"])
    if agency is None:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "provision_agency_unknown",
                "message": f"ITTU_OAUTH_PROVISION lists unknown agency {spec['agency']!r}",
            },
        )
    if not await _role_exists(spec["role"]):
        raise HTTPException(
            status_code=500,
            detail={
                "code": "provision_role_unknown",
                "message": f"ITTU_OAUTH_PROVISION lists role {spec['role']!r}, which does not exist "
                "in core.roles. Create it in Roles administration, or correct "
                "the allowlist.",
            },
        )
    return SeedUser(
        id=_user_id(email), agency_id=agency.id, email=email, name=email, role=spec["role"]
    )


# --- Endpoints --------------------------------------------------------------------


@router.post("/auth/login", response_model=TokenResponse)
async def post_login(
    body: LoginRequest | None = None,
    repo: UserRepository = Depends(get_user_repository),
    session=Depends(get_optional_session),
) -> TokenResponse:
    """POC demo login: seeded agency (+role) → our JWT. No external dependency.

    Disabled when the auth module runs LIVE — Google OAuth is the LIVE path.
    User lookup/mint goes through ``UserRepository`` (P-4b) — memory or
    Postgres, selected by ``settings.persistence``; the endpoint itself
    doesn't know or care which.
    """
    if _auth_mode() != "poc":
        raise HTTPException(
            status_code=403,
            detail={
                "code": "demo_login_disabled",
                "message": "Demo login is POC-only; use POST /api/auth/google in LIVE",
            },
        )

    body = body or LoginRequest()
    if body.agency_id is not None:
        agency = find_agency(body.agency_id)
        if agency is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "agency_not_found",
                    "message": f"No seeded agency {body.agency_id!r}",
                },
            )
    elif body.agency_type is not None:
        agency = find_agency_by_type(body.agency_type)
        if agency is None:  # pragma: no cover — Literal already constrains the type
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "agency_not_found",
                    "message": f"No seeded agency of type {body.agency_type!r}",
                },
            )
    else:
        agency = find_agency("bareskrim")

    role = body.role or DEFAULT_ROLE_BY_AGENCY_TYPE[agency.type]
    # `role` is a constrained STRING, not a Literal — roles are data and a role
    # created in the admin UI must be usable here. Existence is therefore checked
    # against the roles table rather than a frozen tuple. Without this, any
    # well-formed name minted a session for a role that grants nothing: the
    # holder would fail closed on every guard, then quietly reach everything not
    # yet guarded, as a member of whichever agency they named.
    if not await _role_exists(role):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "role_not_found",
                "message": (
                    f"No role named {role!r}. Roles are managed in Roles "
                    "administration (GET /api/roles)."
                ),
            },
        )
    user = await resolve_demo_user(repo, agency, role)
    _reject_if_deactivated(user)
    await _record_login(session, user, agency, method="demo")
    return _token_response(user, agency)


@router.post("/auth/google", response_model=TokenResponse)
async def post_google_login(
    body: GoogleLoginRequest,
    repo: UserRepository = Depends(get_user_repository),
    session=Depends(get_optional_session),
) -> TokenResponse:
    """Google login: verify a Google OAuth ``id_token`` → mint our JWT.

    Available in **either** MODE once ``ITTU_GOOGLE_CLIENT_ID`` is set (the
    id_token audience is always verified). Provisioning differs by mode: in
    **POC** a verified account that isn't seeded/allowlisted gets a default demo
    identity (Bareskrim / police-investigator) — no more open than mock login,
    and on fake POC data; in **LIVE** it fails closed (provisioned-only). An
    ``ITTU_OAUTH_PROVISION`` allowlist entry is honored in both modes. 501 when
    google-auth isn't installed (stub). Lookup/refresh goes through
    ``UserRepository`` (P-4b) — same memory/Postgres toggle as the demo path.
    """
    settings = get_settings()
    if not settings.google_client_id:
        # Never verify a token without our expected audience: passing
        # audience=None makes google-auth SKIP the aud check, so an id_token
        # minted for ANY other OAuth client would verify. Fail loud (403) —
        # Google login simply isn't configured (applies to POC and LIVE alike).
        raise HTTPException(
            status_code=403,
            detail={
                "code": "google_login_unavailable",
                "message": "Google login is not configured — set ITTU_GOOGLE_CLIENT_ID "
                "(the id_token audience cannot be verified without it). "
                "Works in POC and LIVE once configured.",
            },
        )

    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token as google_id_token
    except ImportError:
        raise HTTPException(
            status_code=501,
            detail={
                "code": "google_auth_unavailable",
                "message": "google-auth is not installed; Google login is stubbed",
            },
        )

    try:
        info = google_id_token.verify_oauth2_token(
            body.id_token, google_requests.Request(), settings.google_client_id
        )
    except ValueError:
        raise HTTPException(
            status_code=401,
            detail={"code": "invalid_google_token", "message": "id_token verification failed"},
        )

    email = info.get("email", "")
    user = await repo.find_by_email(email)
    if user is None:
        # Operator-allowlisted email (ITTU_OAUTH_PROVISION) → that agency/role;
        # honored in both modes. First login materializes the row below.
        user = await _provisioned_from_allowlist(email, settings)
    if user is None:
        if _auth_mode() == "poc":
            # POC demo: any Google-verified account gets a default demo identity
            # (fake data, memory-mode — safe, no more open than mock login).
            agency = find_agency("bareskrim")
            user = SeedUser(
                id=_user_id(email),
                agency_id=agency.id,
                email=email,
                name=info.get("name") or email,
                role=DEFAULT_ROLE_BY_AGENCY_TYPE[agency.type],
            )
        else:
            # LIVE stays strict — provisioned users only, fail closed.
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "user_not_provisioned",
                    "message": f"{email} is not provisioned for any agency",
                },
            )
    # Refresh name from Google profile; keep provisioned agency + role. This
    # upsert also creates the row on an allowlisted user's first login.
    user = await repo.upsert(
        SeedUser(
            id=_user_id(user.email),
            agency_id=user.agency_id,
            email=user.email,
            name=info.get("name") or user.name,
            role=user.role,
        )
    )
    _reject_if_deactivated(user)
    agency = find_agency(str(user.agency_id))
    await _record_login(session, user, agency, method="google")
    return _token_response(user, agency)


@router.get("/auth/me", response_model=MeResponse)
async def get_me(auth: CurrentUser) -> MeResponse:
    """The verified identity behind the Bearer token."""
    return MeResponse(
        user=UserOut(
            id=str(auth.user.id),
            email=auth.user.email,
            name=auth.user.name,
            role=auth.role,
            agency_id=str(auth.agency.id),
        ),
        agency=AgencyOut(
            id=str(auth.agency.id),
            slug=auth.agency.slug,
            name=auth.agency.name,
            type=auth.agency.type,
        ),
        role=auth.role,
    )


@router.get("/config", response_model=ConfigResponse)
async def get_config() -> ConfigResponse:
    """Effective MODE per module + which adapter impls are registered/active.

    Open (no auth): the frontend mode badge must render pre-login. Exposes no
    secrets — only mode flags and adapter class names.
    """
    settings = get_settings()
    resolver = get_mode_resolver()
    modules = {module: resolver.effective_mode(module) for module in MODULES}

    adapters = []
    for (boundary, mode), impl in sorted(registered().items()):
        module = BOUNDARY_MODULE.get(boundary, "unknown")
        effective = resolver.effective_mode(module)
        adapters.append(
            AdapterInfo(
                boundary=boundary,
                module=module,
                mode=mode,
                impl=impl,
                active=mode == effective,
            )
        )

    # Voice (#15): NEVER return the key values — only whether one is set.
    from app.infiltrate.voice import LIVE_TTS_PROVIDERS, VOICE_CALLER_NUMBER, VOICE_GREETING

    live_keys = {
        "elevenlabs": bool(settings.elevenlabs_api_key),
        "google": bool(settings.google_tts_api_key),
        "llm": bool(settings.effective_llm_api_key),
    }

    return ConfigResponse(
        mode=settings.mode,
        modules=modules,
        adapters=adapters,
        tts_provider=settings.tts_provider,
        tts_providers=sorted(LIVE_TTS_PROVIDERS),
        live_keys=live_keys,
        voice_defaults={"caller_number": VOICE_CALLER_NUMBER, "greeting": VOICE_GREETING},
        dialing={
            "enqueue_on_start": settings.dial_enqueue_on_start,
            "persistence": settings.persistence,
            # Both must hold or Start is a pure status flip (router._enqueue_campaign).
            "enabled": settings.dial_enqueue_on_start and settings.persistence == "postgres",
        },
    )


# Re-export for tests / discoverability.
__all__ = ["router", "ROLES"]
