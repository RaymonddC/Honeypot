"""JWT auth + RBAC dependencies (P5) — docs/Security-Evidence.md §1.

Both login paths mint **our own JWT** with claims ``{sub, agency_id, role, exp}``
(pyjwt, HS256). Which path is enabled is a MODE decision (``effective_mode("auth")``):

- **POC**  → demo login (seeded agencies + users, zero external dependency),
- **LIVE** → Google OAuth ``id_token`` verification (see app/auth/router.py).

Downstream code only ever sees the JWT — it never cares which path minted it.

RBAC: ``get_current_user`` (401 without/with a bad token) and ``require_role([...])``
(403 outside the allow-list) are plain FastAPI dependencies. Postgres RLS is the
hard backstop *under* these checks (app/core/models.py + migration 20260708_05).
"""

import time
import uuid
from dataclasses import dataclass
from typing import Annotated, Sequence

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.capabilities import is_capability
from app.core.config import get_settings

# --- RBAC roles (docs/Data-Model.md) ----------------------------------------

ROLES = (
    "regulator-analyst",
    "police-investigator",
    "bank-compliance",
    "exchange-compliance",
    "agency-admin",
    "platform-admin",
)

# Human-gated, irreversible outward actions (UNCOVER dispatch).
DISPATCH_ROLES = (
    "regulator-analyst",
    "police-investigator",
    "agency-admin",
    "platform-admin",
)

# Roles that may administer users. `platform-admin` additionally crosses agency
# boundaries; `agency-admin` is confined to its own (enforced in app/users).
ADMIN_ROLES = ("agency-admin", "platform-admin")
PLATFORM_ADMIN = "platform-admin"

DEFAULT_ROLE_BY_AGENCY_TYPE = {
    "police": "police-investigator",
    "regulator": "regulator-analyst",
    "bank": "bank-compliance",
    "exchange": "exchange-compliance",
    "other": "agency-admin",
}

# --- Seeded agencies + demo users (POC; deterministic ids) -------------------


def _agency_id(slug: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"ittu:agency:{slug}")


def _user_id(email: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"ittu:user:{email}")


@dataclass(frozen=True)
class SeedAgency:
    id: uuid.UUID
    slug: str
    name: str
    type: str  # regulator|police|bank|exchange|other


@dataclass(frozen=True)
class SeedUser:
    id: uuid.UUID
    agency_id: uuid.UUID
    email: str
    name: str
    role: str
    # Deactivated accounts cannot log in and are rejected on any request whose
    # identity resolves through the in-process store. Defaults True so every
    # existing construction site keeps working unchanged.
    is_active: bool = True


SEED_AGENCIES: tuple[SeedAgency, ...] = (
    SeedAgency(_agency_id("bareskrim"), "bareskrim", "Bareskrim Polri", "police"),
    SeedAgency(_agency_id("ppatk"), "ppatk", "PPATK", "regulator"),
    SeedAgency(_agency_id("ojk"), "ojk", "OJK", "regulator"),
    SeedAgency(_agency_id("bank-bca"), "bank-bca", "Bank BCA", "bank"),
    SeedAgency(_agency_id("indodax"), "indodax", "Indodax", "exchange"),
)

_AGENCIES_BY_ID = {str(a.id): a for a in SEED_AGENCIES}
_AGENCIES_BY_SLUG = {a.slug: a for a in SEED_AGENCIES}


def _seed_user(agency_slug: str, email: str, name: str, role: str) -> SeedUser:
    return SeedUser(_user_id(email), _agency_id(agency_slug), email, name, role)


SEED_USERS: tuple[SeedUser, ...] = (
    _seed_user("bareskrim", "budi@bareskrim.polri.go.id", "Budi Santoso", "police-investigator"),
    _seed_user("ppatk", "sari@ppatk.go.id", "Sari Wulandari", "regulator-analyst"),
    _seed_user("ojk", "dewi@ojk.go.id", "Dewi Lestari", "regulator-analyst"),
    _seed_user("bank-bca", "andi@bca.co.id", "Andi Wijaya", "bank-compliance"),
    _seed_user("indodax", "rina@indodax.com", "Rina Hartono", "exchange-compliance"),
    _seed_user("ppatk", "admin@ittu.id", "ITTU Platform Admin", "platform-admin"),
)

# Runtime user store: seeds + users minted on the fly (demo role-combos, LIVE Google).
_USERS: dict[str, SeedUser] = {str(u.id): u for u in SEED_USERS}


def find_agency(ref: str | None) -> SeedAgency | None:
    """Resolve an agency by uuid OR slug (demo-login convenience)."""
    if ref is None:
        return None
    return _AGENCIES_BY_ID.get(ref) or _AGENCIES_BY_SLUG.get(ref.lower())


def find_agency_by_type(agency_type: str) -> SeedAgency | None:
    return next((a for a in SEED_AGENCIES if a.type == agency_type), None)


def get_user(user_id: str) -> SeedUser | None:
    return _USERS.get(user_id)


def find_user_by_email(email: str) -> SeedUser | None:
    return next((u for u in _USERS.values() if u.email == email), None)


def upsert_demo_user(agency: SeedAgency, role: str) -> SeedUser:
    """Find-or-mint the demo user for (agency, role) — deterministic id."""
    existing = next(
        (u for u in _USERS.values() if u.agency_id == agency.id and u.role == role), None
    )
    if existing is not None:
        return existing
    email = f"{role}@{agency.slug}.demo.ittu.id"
    user = SeedUser(_user_id(email), agency.id, email, f"{agency.name} {role}", role)
    _USERS[str(user.id)] = user
    return user


def register_user(user: SeedUser) -> SeedUser:
    """Register an externally-authenticated user (LIVE Google path)."""
    _USERS[str(user.id)] = user
    return user


# --- JWT mint / verify --------------------------------------------------------


def mint_token(user: SeedUser, *, ttl_seconds: int | None = None) -> tuple[str, int]:
    """Mint our JWT. Claims: sub, agency_id, role, exp (+iat, email, name)."""
    settings = get_settings()
    ttl = settings.jwt_ttl_seconds if ttl_seconds is None else ttl_seconds
    now = int(time.time())
    claims = {
        "sub": str(user.id),
        "agency_id": str(user.agency_id),
        "role": user.role,
        "email": user.email,
        "name": user.name,
        "iat": now,
        "exp": now + ttl,
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm), ttl


def decode_token(token: str) -> dict:
    """Decode + verify our JWT. Raises jwt.InvalidTokenError subclasses."""
    settings = get_settings()
    return jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
        options={"require": ["sub", "agency_id", "role", "exp"]},
    )


# --- FastAPI dependencies ------------------------------------------------------


@dataclass(frozen=True)
class AuthContext:
    """The verified request identity: who, which agency, acting as which role."""

    user: SeedUser
    agency: SeedAgency
    role: str


_bearer = HTTPBearer(auto_error=False)


def _unauthorized(code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=401,
        detail={"code": code, "message": message},
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> AuthContext:
    """Verify the Bearer JWT → AuthContext. 401 on missing/expired/invalid.

    **Deactivation and its residual window — read before trusting "revoke".**
    Request auth is pure JWT: it does NOT query the database. So when a user is
    deactivated:

    * they can no longer LOG IN (both login paths reject them — that check is
      the mandatory one, see ``app/auth/router.py``), and
    * a request is rejected here only when ``get_user`` finds them in the
      in-process store — which is the POC/memory case, and any process that has
      already seen them.

    Under Postgres persistence an ALREADY-ISSUED token therefore keeps working
    until it expires (``ITTU_JWT_TTL_SECONDS``, default 1h), because nothing on
    the request path reads ``core.users``. Immediate revocation would need a
    per-request lookup (or a short TTL plus refresh); today the TTL *is* the
    mitigation. Stated plainly because "deactivate" must not be read as
    "instantly cut off" when it is not.
    """
    if credentials is None:
        raise _unauthorized("missing_token", "Authorization: Bearer <jwt> required")
    try:
        claims = decode_token(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise _unauthorized("token_expired", "Token has expired — log in again")
    except jwt.InvalidTokenError:
        raise _unauthorized("invalid_token", "Token is invalid")

    agency = _AGENCIES_BY_ID.get(claims["agency_id"])
    if agency is None:
        raise _unauthorized("unknown_agency", "Token references an unknown agency")

    role = claims["role"]
    known = get_user(claims["sub"])
    if known is not None and not known.is_active:
        # Only reachable when the identity resolves in-process; see the
        # residual-window note above for the Postgres case.
        raise _unauthorized(
            "account_deactivated", "This account has been deactivated"
        )
    user = known or SeedUser(
        id=uuid.UUID(claims["sub"]),
        agency_id=agency.id,
        email=claims.get("email", ""),
        name=claims.get("name", ""),
        role=role,
    )
    return AuthContext(user=user, agency=agency, role=role)


CurrentUser = Annotated[AuthContext, Depends(get_current_user)]


async def get_optional_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> AuthContext | None:
    """Soft variant of ``get_current_user``: no ``Authorization`` header → ``None``
    (not a 401). A *present but invalid/expired* token still raises — only "no
    attempt made" is soft.

    Exists for dependencies that must stay usable on today's unauthenticated
    read routes (docs/Persistence-Plan.md P-2b scope guard — adding hard auth
    to those routes is P-4) while still being able to tell a caller "here's the
    verified identity, if any" without forcing a 401 on every request.
    """
    if credentials is None:
        return None
    return await get_current_user(credentials)


async def require_crypto_enabled() -> None:
    """404 unless the crypto surface is switched on (``ITTU_CRYPTO_ENABLED``).

    **A feature gate, not a permission gate**, and the distinction is the whole
    point. ``require_capability`` answers "may THIS CALLER do it" and returns
    403; this answers "does this product offer it here at all" and returns 404.
    A role holding every capability still gets 404 while the flag is off.

    404 rather than 403 for a second reason: 403 advertises that a crypto
    feature exists and is being withheld, which invites the question we are
    choosing not to answer yet. A disabled feature should look absent.

    Not audited as a denial either — nobody was refused. Recording these as
    ``access.forbidden`` would fill the trail with entries about a product
    decision and bury the refusals that describe someone's behaviour.
    """
    if not get_settings().crypto_enabled:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "feature_disabled",
                "message": (
                    "Crypto tracing is not enabled in this deployment. "
                    "Set ITTU_CRYPTO_ENABLED=true to turn it on."
                ),
                "feature": "crypto",
            },
        )


def require_capability(capability: str):
    """Dependency factory: 403 unless the caller's ROLE holds ``capability``.

    The capability-based twin of ``require_role``, and the one to prefer.
    ``require_role`` hardcodes WHICH roles may act, so every new role means
    editing and redeploying every guard; this names WHAT is being done and lets
    the role↔capability mapping live in ``core.roles`` as data
    (``app/core/capabilities.py`` explains the split).

    Refusals are audited identically — ``access.forbidden``, outcome ``denied``,
    recorded here because the handler never runs and this is the only place that
    knows the refusal happened. ``detail.requires`` names the CAPABILITY rather
    than a role list, which is also what the reader needs: "this account's role
    lacks honeypot.operate" is actionable, "requires one of [4 role names]" is
    something they then have to decode.

    Fails closed by construction: an unreadable ``core.roles`` yields no
    capabilities for anyone (see ``app/core/roles.py``), so protected endpoints
    refuse rather than admit during a database outage.
    """
    if not is_capability(capability):
        # A typo here would create a guard nothing can ever satisfy — every
        # request 403s and the cause is invisible. Caught at import, not at the
        # first unlucky request.
        raise ValueError(
            f"unknown capability {capability!r} — it must be declared in "
            "app/core/capabilities.py, which is the closed set of things this "
            "system actually enforces"
        )

    async def dependency(auth: CurrentUser, request: Request) -> AuthContext:
        from app.core.roles import has_capability

        if not await has_capability(auth.role, capability):
            from app.core.audit import ACCESS_FORBIDDEN, record_denial

            await record_denial(
                agency_id=str(auth.agency.id),
                action=ACCESS_FORBIDDEN,
                denial_code="missing_capability",
                actor_user_id=str(auth.user.id),
                actor_name=auth.user.name,
                actor_role=auth.role,
                target_type="endpoint",
                target_label=f"{request.method} {request.url.path}",
                request=request,
                detail={
                    "method": request.method,
                    "path": request.url.path,
                    "requires": capability,
                },
            )
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "missing_capability",
                    "message": (
                        f"Your role ({auth.role}) does not have the "
                        f"'{capability}' capability."
                    ),
                    "capability": capability,
                },
            )
        return auth

    return dependency


def require_role(roles: Sequence[str]):
    """Dependency factory: 403 unless the JWT role is in the allow-list.

    A refusal is AUDITED (``access.forbidden``, outcome ``denied``). The actor
    is authenticated and known, and "an authenticated user repeatedly reaching
    for something their role forbids" is the single most security-relevant thing
    an audit trail can surface — it used to leave no trace whatsoever. Recording
    happens here rather than at each call site because this is the one place
    that knows the refusal happened at all: the handler never runs.

    The audit write must not change the outcome — ``record_denial`` never
    raises, so the caller still gets a clean 403 even if the log is down.
    """
    allowed = frozenset(roles)

    async def dependency(auth: CurrentUser, request: Request) -> AuthContext:
        if auth.role not in allowed:
            # Imported here, not at module scope: app.core.audit reaches
            # app.core.db, which imports this module.
            from app.core.audit import ACCESS_FORBIDDEN, record_denial

            await record_denial(
                agency_id=str(auth.agency.id),
                action=ACCESS_FORBIDDEN,
                denial_code="forbidden",
                actor_user_id=str(auth.user.id),
                actor_name=auth.user.name,
                actor_role=auth.role,
                target_type="endpoint",
                target_label=f"{request.method} {request.url.path}",
                request=request,
                # Path only, never the query string — same rule as the request
                # log (app/core/requests.py): that is where a token or a phone
                # number ends up tomorrow.
                detail={
                    "method": request.method,
                    "path": request.url.path,
                    "requires": sorted(allowed),
                },
            )
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "forbidden",
                    "message": f"Requires one of: {', '.join(sorted(allowed))}",
                },
            )
        return auth

    return dependency
