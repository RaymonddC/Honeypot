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

Every mutation is audited (`app/core/audit.py`) — and so is every REFUSAL of
one. A role grant or a deactivation is precisely the kind of change the person
making it is best placed to hide; an agency-admin *probing* for the
platform-admin role is the same signal one step earlier, and used to leave no
trace at all. Denials keep the domain action name and carry
`detail["_outcome"] = "denied"` plus the guard's code, so "everything Budi did"
stays a single query over `actor_user_id`.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.core.audit import (
    ACCESS_FORBIDDEN,
    USER_CREATED,
    USER_DEACTIVATED,
    USER_REACTIVATED,
    USER_ROLE_CHANGED,
    record_action,
    record_denial,
)
from app.core.auth import (
    ADMIN_ROLES,
    PLATFORM_ADMIN,
    AuthContext,
    require_capability,
)
from app.core.capabilities import USERS_ADMIN, USERS_ADMIN_CROSS_AGENCY
from app.core.roles import has_capability
from app.core.db import get_optional_tenant_session
from app.core.user_repository import (
    UserRepository,
    get_user_admin_repository,
    scope_session_to_agency,
)
from app.users.schemas import CreateUserRequest, UpdateUserRequest, UserAdminOut

router = APIRouter(tags=["users"])

RepoDep = Depends(get_user_admin_repository)
# Capability, not a role list: which roles may administer users is DATA now
# (core.roles), so an agency can define its own without a redeploy.
AdminDep = Depends(require_capability(USERS_ADMIN))


def _out(user) -> UserAdminOut:
    return UserAdminOut(
        id=str(user.id), agency_id=str(user.agency_id), email=user.email,
        name=user.name, role=user.role, is_active=user.is_active,
    )


def _conflict(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=409, detail={"code": code, "message": message})


async def _deny(
    auth: AuthContext,
    *,
    status: int,
    code: str,
    message: str,
    action: str,
    request,
    target_id: str | None = None,
    target_label: str | None = None,
    detail: dict | None = None,
) -> HTTPException:
    """Audit the refusal, then hand back the exception for the caller to raise.

    Returns rather than raises so call sites read ``raise await _deny(...)`` —
    the ``raise`` stays visible at the guard, which is where a reader looks to
    see what the guard does.

    Chained under the ACTOR's agency and takes no session — both are
    ``record_denial``'s doing, and its docstring says why (the request's
    transaction is about to roll back underneath us).
    """
    await record_denial(
        agency_id=str(auth.agency.id),
        action=action,
        denial_code=code,
        actor_user_id=str(auth.user.id),
        actor_name=auth.user.name,
        actor_role=auth.role,
        target_type="user",
        target_id=target_id,
        target_label=target_label,
        request=request,
        detail=detail,
    )
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _intended_action(body: UpdateUserRequest) -> str:
    """Which domain action a PATCH was reaching for, so a denial can be recorded
    under that name rather than a generic one (see the module docstring).

    A role change outranks an activity flag when both are sent: it is the more
    consequential of the two, and it is the one the guards are protecting.
    """
    if body.role is not None:
        return USER_ROLE_CHANGED
    return USER_REACTIVATED if body.is_active else USER_DEACTIVATED


async def _resolve_agency(
    auth: AuthContext, requested: uuid.UUID | None, session, *, action: str, request
) -> uuid.UUID:
    """Which agency this request may act on — and re-scope RLS if crossing.

    An agency-admin asking for another agency is refused rather than silently
    served their own: quietly redirecting the request would make the UI show
    one agency while claiming to show another.
    """
    own = auth.agency.id
    if requested is None or requested == own:
        return own
    if not await has_capability(auth.role, USERS_ADMIN_CROSS_AGENCY):
        raise await _deny(
            auth,
            status=403,
            code="cross_agency_forbidden",
            message=(
                "Administering another agency's users needs the "
                "'users.admin.cross_agency' capability."
            ),
            action=action,
            request=request,
            # The agency they reached for. Naming it leaks nothing: the caller
            # supplied the id, and the entry lands in their OWN agency's chain.
            detail={"target_agency_id": str(requested)},
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


async def _guard_role_grant(
    auth: AuthContext, role: str, *, action: str, request,
    target_id: str | None = None, target_label: str | None = None,
) -> None:
    if role == PLATFORM_ADMIN and auth.role != PLATFORM_ADMIN:
        raise await _deny(
            auth,
            status=403,
            code="privilege_escalation",
            message="Only a platform-admin can grant the platform-admin role.",
            action=action,
            request=request,
            target_id=target_id,
            target_label=target_label,
            detail={"attempted_role": role},
        )


@router.get("/users", response_model=list[UserAdminOut])
async def list_users(
    request: Request,
    agency_id: uuid.UUID | None = Query(
        default=None, description="platform-admin only: administer another agency"
    ),
    auth: AuthContext = AdminDep,
    repo: UserRepository = RepoDep,
    session=Depends(get_optional_tenant_session),
) -> list[UserAdminOut]:
    """Users of your agency (or another, for a platform-admin)."""
    # A refused listing has no domain action to name (nothing was being
    # changed), so it records as ACCESS_FORBIDDEN — same as any other
    # role-gated door someone tried and found locked.
    target = await _resolve_agency(
        auth, agency_id, session, action=ACCESS_FORBIDDEN, request=request
    )
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
    target = await _resolve_agency(
        auth, body.agency_id, session, action=USER_CREATED, request=request
    )
    await _guard_role_grant(
        auth, body.role, action=USER_CREATED, request=request, target_label=body.email
    )

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
        # Audited, and this one is a judgement call. Under RLS a user that
        # exists in ANOTHER agency is invisible to this session, so a 404 here
        # may really be a cross-agency denial wearing a disguise — and a run of
        # them is id enumeration, which is exactly what the trail should catch.
        # It leaks nothing: the entry lands in the ACTOR's own agency chain and
        # names only the id the actor themselves supplied. We deliberately do
        # NOT look the row up out-of-band to enrich it — no email, no name, no
        # owning agency — because that, not the record itself, is what would
        # turn the log into an oracle for other agencies' user lists.
        raise await _deny(
            auth,
            status=404,
            code="user_not_found",
            message=f"No user with id {user_id}",
            action=_intended_action(body),
            request=request,
            target_id=str(user_id),
        )

    # Scope check BEFORE any mutation: an agency-admin must not touch another
    # agency's user, and a platform-admin acting cross-agency needs RLS moved.
    await _resolve_agency(
        auth, user.agency_id, session, action=_intended_action(body), request=request
    )

    self_edit = user.id == auth.user.id
    demoting = body.role is not None and body.role != user.role and user.role in ADMIN_ROLES
    deactivating = body.is_active is False and user.is_active

    if self_edit and (deactivating or demoting):
        raise await _deny(
            auth,
            status=409,
            code="self_lockout",
            message="You cannot deactivate or demote your own account — ask another admin.",
            action=_intended_action(body),
            request=request,
            target_id=str(user_id),
            target_label=user.email,
        )
    if (deactivating or demoting) and user.role in ADMIN_ROLES:
        if await repo.count_active_admins(user.agency_id) <= 1:
            raise await _deny(
                auth,
                status=409,
                code="last_admin",
                message=(
                    "This is the agency's last active admin — promote another first, "
                    "or the agency would have nobody who can restore access."
                ),
                action=_intended_action(body),
                request=request,
                target_id=str(user_id),
                target_label=user.email,
            )

    updated = user
    if body.role is not None and body.role != user.role:
        await _guard_role_grant(
            auth, body.role, action=USER_ROLE_CHANGED, request=request,
            target_id=str(user_id), target_label=user.email,
        )
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
