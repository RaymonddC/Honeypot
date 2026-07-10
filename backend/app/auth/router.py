"""AUTH router — login (POC demo / LIVE Google), identity, effective config.

POST /api/auth/login   {agency_id|agency_type, role?} → JWT       (POC demo login)
POST /api/auth/google  {id_token}                     → JWT       (LIVE Google OAuth)
GET  /api/auth/me                                     → {user, agency, role}
GET  /api/config                                      → effective MODE per module
                                                        + registered adapters

Which login path is enabled is decided by ``effective_mode("auth")`` — the same
MODE machinery as every other boundary. POC is the safe default; the Google
path fails closed when the module is POC (never a silent fallthrough).
"""

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.adapters import BOUNDARY_MODULE, registered
from app.core.auth import (
    DEFAULT_ROLE_BY_AGENCY_TYPE,
    ROLES,
    CurrentUser,
    SeedAgency,
    SeedUser,
    _user_id,
    find_agency,
    find_agency_by_type,
    find_user_by_email,
    mint_token,
    register_user,
    upsert_demo_user,
)
from app.core.config import MODULES, get_mode_resolver, get_settings

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
    role: Literal[
        "regulator-analyst",
        "police-investigator",
        "bank-compliance",
        "exchange-compliance",
        "agency-admin",
        "platform-admin",
    ] | None = None


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


# --- Helpers ---------------------------------------------------------------------


def _auth_mode() -> str:
    return get_mode_resolver().effective_mode("auth")


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


# --- Endpoints --------------------------------------------------------------------


@router.post("/auth/login", response_model=TokenResponse)
async def post_login(body: LoginRequest | None = None) -> TokenResponse:
    """POC demo login: seeded agency (+role) → our JWT. No external dependency.

    Disabled when the auth module runs LIVE — Google OAuth is the LIVE path.
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
    user = upsert_demo_user(agency, role)
    return _token_response(user, agency)


@router.post("/auth/google", response_model=TokenResponse)
async def post_google_login(body: GoogleLoginRequest) -> TokenResponse:
    """LIVE login: verify a Google OAuth ``id_token`` → mint our JWT.

    Fails closed in POC (403); 501 when google-auth isn't installed (stub).
    Users must be provisioned (seeded/registered) — no self-service signup.
    """
    if _auth_mode() != "live":
        raise HTTPException(
            status_code=403,
            detail={
                "code": "google_login_disabled",
                "message": "Google OAuth is the LIVE path; set module mode auth=live",
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
                "message": "google-auth is not installed; LIVE Google login is stubbed",
            },
        )

    settings = get_settings()
    try:
        info = google_id_token.verify_oauth2_token(
            body.id_token, google_requests.Request(), settings.google_client_id or None
        )
    except ValueError:
        raise HTTPException(
            status_code=401,
            detail={"code": "invalid_google_token", "message": "id_token verification failed"},
        )

    email = info.get("email", "")
    user = find_user_by_email(email)
    if user is None:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "user_not_provisioned",
                "message": f"{email} is not provisioned for any agency",
            },
        )
    # Refresh name from Google profile; keep provisioned agency + role.
    user = register_user(
        SeedUser(
            id=_user_id(user.email),
            agency_id=user.agency_id,
            email=user.email,
            name=info.get("name") or user.name,
            role=user.role,
        )
    )
    agency = find_agency(str(user.agency_id))
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

    return ConfigResponse(mode=settings.mode, modules=modules, adapters=adapters)


# Re-export for tests / discoverability.
__all__ = ["router", "ROLES"]
