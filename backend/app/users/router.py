"""USERS router — agency-scoped user access management (UAM).

GET   /api/users            → list this agency's users
POST  /api/users            → provision a user
PATCH /api/users/{id}       → change role and/or active status

**Admin-gated** (`agency-admin`, `platform-admin`). An `agency-admin` is
confined to its own agency; a `platform-admin` may act on another by passing
`agency_id`, which is an explicit, audited privilege rather than an implicit one.

Three rules here exist to prevent an admin from doing damage that cannot be
undone from inside the product:

* **No privilege escalation** — only a `platform-admin` may create or grant
  `platform-admin`. Otherwise any agency-admin could mint themselves the
  cross-agency role, and the agency boundary would be advisory.
* **No self-lockout** — you cannot deactivate or demote yourself. The failure
  mode is silent and total: the admin clicks once and can no longer administer.
* **No last-admin lockout** — the final active admin of an agency cannot be
  removed, or the agency has nobody who can restore access.

Every mutation is audited (`app/core/audit.py`): a role grant or a deactivation
is precisely the kind of change the person making it is best placed to hide.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.core.audit import (
    USER_CREATED,
    USER_DEACTIVATED,
    USER_REACTIVATED,
    USER_ROLE_CHANGED,
    record_action,
)
from app.core.auth import ADMIN_ROLES, PLATFORM_ADMIN, AuthContext, require_role
from app.core.db import get_optional_tenant_session
from app.core.user_repository import (
    UserRepository,
    get_user_admin_repository,
    scope_session_to_agency,
)
from app.users.schemas import CreateUserRequest, UpdateUserRequest, UserAdminOut

router = APIRouter(tags=["users"])

RepoDep = Depends(get_user_admin_repository)
AdminDep = Depends(require_role(ADMIN_ROLES))


def _out(user) -> UserAdminOut:
    return UserAdminOut(
        id=str(user.id), agency_id=str(user.agency_id), email=user.email,
        name=user.name, role=user.role, is_active=user.is_active,
    )


def _conflict(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=409, detail={"code": code, "message": message})


def _forbidden(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=403, detail={"code": code, "message": message})


async def _resolve_agency(
    auth: AuthContext, requested: uuid.UUID | None, session
) -> uuid.UUID:
    """Which agency this request may act on — and re-scope RLS if crossing.

    An agency-admin asking for another agency is refused rather than silently
    served their own: quietly redirecting the request would make the UI show
    one agency while claiming to show another.
    """
    own = auth.agency.id
    if requested is None or requested == own:
        return own
    if auth.role != PLATFORM_ADMIN:
        raise _forbidden(
            "cross_agency_forbidden",
            "Only a platform-admin can administer another agency's users.",
        )
    # Verified platform-admin: re-point RLS at the target agency for this
    # transaction. Without this the policy (own agency OR self) would return an
    # empty list — which reads as "that agency has no users", a lie.
    await scope_session_to_agency(session, requested)
    return requested


def _actor_agency(auth: AuthContext, target: uuid.UUID) -> dict:
    """Note the acting agency when it isn't the target's.

    The entry is chained under the TARGET agency — that agency's admins are the
    people who must be able to see that their access list changed, and RLS
    scopes the write there anyway. When a platform-admin reached in from
    outside, the trail has to say so, or the row reads as if a local admin did it.
    """
    return {} if auth.agency.id == target else {"acting_agency_id": str(auth.agency.id)}


def _guard_role_grant(auth: AuthContext, role: str) -> None:
    if role == PLATFORM_ADMIN and auth.role != PLATFORM_ADMIN:
        raise _forbidden(
            "privilege_escalation",
            "Only a platform-admin can grant the platform-admin role.",
        )


@router.get("/users", response_model=list[UserAdminOut])
async def list_users(
    agency_id: uuid.UUID | None = Query(
        default=None, description="platform-admin only: administer another agency"
    ),
    auth: AuthContext = AdminDep,
    repo: UserRepository = RepoDep,
    session=Depends(get_optional_tenant_session),
) -> list[UserAdminOut]:
    """Users of your agency (or another, for a platform-admin)."""
    target = await _resolve_agency(auth, agency_id, session)
    return [_out(u) for u in await repo.list_users(target)]


@router.post("/users", response_model=UserAdminOut, status_code=201)
async def create_user(
    request: Request,
    body: CreateUserRequest,
    auth: AuthContext = AdminDep,
    repo: UserRepository = RepoDep,
    session=Depends(get_optional_tenant_session),
) -> UserAdminOut:
    """Provision a user. They can then sign in via the configured auth path —
    this does not send an invitation, it authorises an identity."""
    target = await _resolve_agency(auth, body.agency_id, session)
    _guard_role_grant(auth, body.role)

    existing = await repo.find_by_email(body.email)
    if existing is not None:
        raise _conflict("user_exists", f"{body.email} already has an account.")

    user = await repo.create_user(
        agency_id=target, email=body.email, name=body.name, role=body.role
    )
    await record_action(
        session,
        agency_id=str(target),
        action=USER_CREATED,
        actor_user_id=str(auth.user.id),
        actor_name=auth.user.name,
        target_type="user",
        target_id=str(user.id),
        target_label=user.email,
        request=request,
        detail={"role": user.role, "name": user.name, **_actor_agency(auth, target)},
    )
    return _out(user)


@router.patch("/users/{user_id}", response_model=UserAdminOut)
async def update_user(
    request: Request,
    user_id: uuid.UUID,
    body: UpdateUserRequest,
    auth: AuthContext = AdminDep,
    repo: UserRepository = RepoDep,
    session=Depends(get_optional_tenant_session),
) -> UserAdminOut:
    """Change a user's role and/or active status."""
    if body.role is None and body.is_active is None:
        raise HTTPException(
            status_code=422,
            detail={"code": "nothing_to_change", "message": "Send role and/or is_active."},
        )

    user = await repo.get_by_id(user_id)
    if user is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "user_not_found", "message": f"No user with id {user_id}"},
        )

    # Scope check BEFORE any mutation: an agency-admin must not touch another
    # agency's user, and a platform-admin acting cross-agency needs RLS moved.
    await _resolve_agency(auth, user.agency_id, session)

    self_edit = user.id == auth.user.id
    demoting = body.role is not None and body.role != user.role and user.role in ADMIN_ROLES
    deactivating = body.is_active is False and user.is_active

    if self_edit and (deactivating or demoting):
        raise _conflict(
            "self_lockout",
            "You cannot deactivate or demote your own account — ask another admin.",
        )
    if (deactivating or demoting) and user.role in ADMIN_ROLES:
        if await repo.count_active_admins(user.agency_id) <= 1:
            raise _conflict(
                "last_admin",
                "This is the agency's last active admin — promote another first, "
                "or the agency would have nobody who can restore access.",
            )

    updated = user
    if body.role is not None and body.role != user.role:
        _guard_role_grant(auth, body.role)
        before = updated.role
        updated = await repo.set_role(user_id, body.role) or updated
        await record_action(
            session,
            agency_id=str(user.agency_id),
            action=USER_ROLE_CHANGED,
            actor_user_id=str(auth.user.id),
            actor_name=auth.user.name,
            target_type="user",
            target_id=str(user_id),
            target_label=updated.email,
            request=request,
            # before→after: "who has which power now" is only answerable from
            # the log if the log says what it changed FROM.
            detail={"from": before, "to": body.role, **_actor_agency(auth, user.agency_id)},
        )

    if body.is_active is not None and body.is_active != user.is_active:
        updated = await repo.set_active(user_id, body.is_active) or updated
        await record_action(
            session,
            agency_id=str(user.agency_id),
            action=USER_REACTIVATED if body.is_active else USER_DEACTIVATED,
            actor_user_id=str(auth.user.id),
            actor_name=auth.user.name,
            target_type="user",
            target_id=str(user_id),
            target_label=updated.email,
            request=request,
            detail={"role": updated.role, **_actor_agency(auth, user.agency_id)},
        )

    return _out(updated)
