"""Role administration — define roles and what each one may do.

    GET    /api/roles           → every role, its capabilities, and how many
                                  people hold it
    GET    /api/capabilities    → the closed set the UI may offer
    POST   /api/roles           → create
    PATCH  /api/roles/{name}    → change capabilities
    DELETE /api/roles/{name}    → remove

**Gated on ``roles.admin``, which is seeded to ``platform-admin`` alone**, for a
reason worth stating: ``core.roles`` has no ``agency_id``. A role is global, so
an agency administrator editing one would change what OTHER agencies' users can
do — a tenant-isolation break wearing the clothes of a settings page.

Four guards, each because the failure is unrecoverable from inside the product:

* a role may not be given a capability this build does not enforce — the UI
  would then advertise a protection that does not exist;
* an edit may not leave ZERO roles holding ``users.admin`` or ``roles.admin``
  (``UNREMOVABLE_CAPABILITIES``) — there would be no way back in;
* a role may not be deleted while people still hold it, because those accounts
  would silently lose every capability; and
* the built-in roles may not be renamed out from under the seeds and the OAuth
  provisioning allowlist, which reference them by name.

Every mutation is audited with the before-and-after capability sets, because
"who widened this role, and when" is exactly the question asked after an
incident.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.core.audit import record_action, record_denial
from app.core.auth import AuthContext, get_current_user, require_capability
from app.core.capabilities import (
    CAPABILITIES,
    DEFAULT_ROLE_CAPABILITIES,
    ROLES_ADMIN,
    UNREMOVABLE_CAPABILITIES,
    is_capability,
)
from app.core.db import get_optional_tenant_session
from app.roles.repository import RoleRecord, get_role_repository
from app.users.schemas import RoleName

router = APIRouter(tags=["roles"])

RoleAdminDep = Depends(require_capability(ROLES_ADMIN))

ROLE_CREATED = "role.created"
ROLE_UPDATED = "role.updated"
ROLE_DELETED = "role.deleted"

#: Names the rest of the system references literally — the seed migration, the
#: ITTU_OAUTH_PROVISION allowlist, and the demo login. Renaming or deleting one
#: breaks those silently, so they are protected from deletion.
BUILTIN_ROLES = frozenset(DEFAULT_ROLE_CAPABILITIES)


class RoleOut(BaseModel):
    name: str
    capabilities: list[str]
    user_count: int
    builtin: bool


class CapabilityOut(BaseModel):
    key: str
    label: str
    description: str


class CreateRoleRequest(BaseModel):
    name: RoleName
    capabilities: list[str] = Field(default_factory=list)


class UpdateRoleRequest(BaseModel):
    capabilities: list[str]


def _forbid(code: str, message: str, status: int = 409) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


async def _audit_denial(auth, request, action: str, code: str, target: str, **detail):
    await record_denial(
        agency_id=str(auth.agency.id),
        action=action,
        denial_code=code,
        actor_user_id=str(auth.user.id),
        actor_name=auth.user.name,
        actor_role=auth.role,
        target_type="role",
        target_id=target,
        target_label=target,
        request=request,
        detail=detail,
    )


def _validate_capabilities(caps: list[str]) -> frozenset[str]:
    unknown = sorted({c for c in caps if not is_capability(c)})
    if unknown:
        raise _forbid(
            "unknown_capability",
            f"This build does not enforce: {', '.join(unknown)}. Granting a "
            "capability nothing checks would show a protection that does not "
            "exist.",
            status=422,
        )
    return frozenset(caps)


async def _would_orphan(repo, *, name: str, new_caps: frozenset[str] | None) -> list[str]:
    """Which unremovable capabilities this change would leave with no holder.

    Computed over the RESULTING policy, not the current one, so it catches the
    edit before it is applied — the point of the guard is that there is no way
    back once nobody can administer anything.

    Returns all of them, not the first: stripping a role often orphans several
    at once, and naming one at a time would send an operator round the loop
    fixing them individually.
    """
    roles = {r.name: set(r.capabilities) for r in await repo.list_roles()}
    if new_caps is None:
        roles.pop(name, None)
    else:
        roles[name] = set(new_caps)
    return [
        cap
        for cap in sorted(UNREMOVABLE_CAPABILITIES)
        if not any(cap in caps for caps in roles.values())
    ]


async def _user_counts(session) -> dict[str, int]:
    """How many accounts hold each role. Zero for every role in memory mode —
    there is no user table to count, and the delete guard degrades to allowing
    a delete that Postgres would refuse. Stated rather than hidden."""
    from app.core.config import get_settings

    if session is None or get_settings().persistence != "postgres":
        return {}
    from sqlalchemy import func, select

    from app.core.models import User

    rows = await session.execute(select(User.role, func.count()).group_by(User.role))
    return {role: n for role, n in rows.all()}


@router.get("/capabilities", response_model=list[CapabilityOut])
async def list_capabilities(_auth: AuthContext = Depends(get_current_user)):
    """The closed set the UI may offer. Readable by any authenticated user: it
    is a description of the product, not of anyone's access."""
    return [CapabilityOut(key=c.key, label=c.label, description=c.description) for c in CAPABILITIES]


@router.get("/roles", response_model=list[RoleOut])
async def list_roles(
    _auth: AuthContext = RoleAdminDep,
    session=Depends(get_optional_tenant_session),
):
    repo = get_role_repository(session)
    counts = await _user_counts(session)
    return [
        RoleOut(
            name=r.name,
            capabilities=sorted(r.capabilities),
            user_count=counts.get(r.name, 0),
            builtin=r.name in BUILTIN_ROLES,
        )
        for r in await repo.list_roles()
    ]


@router.post("/roles", response_model=RoleOut, status_code=201)
async def create_role(
    body: CreateRoleRequest,
    request: Request,
    auth: AuthContext = RoleAdminDep,
    session=Depends(get_optional_tenant_session),
):
    repo = get_role_repository(session)
    if await repo.get(body.name) is not None:
        await _audit_denial(auth, request, ROLE_CREATED, "role_exists", body.name)
        raise _forbid("role_exists", f"A role named {body.name!r} already exists.")

    caps = _validate_capabilities(body.capabilities)
    await repo.create(RoleRecord(name=body.name, capabilities=caps))
    await record_action(
        session,
        agency_id=str(auth.agency.id),
        action=ROLE_CREATED,
        actor_user_id=str(auth.user.id),
        actor_name=auth.user.name,
        request=request,
        target_type="role",
        target_label=body.name,
        detail={"role": body.name, "capabilities": sorted(caps)},
    )
    return RoleOut(name=body.name, capabilities=sorted(caps), user_count=0, builtin=False)


@router.patch("/roles/{name}", response_model=RoleOut)
async def update_role(
    name: str,
    body: UpdateRoleRequest,
    request: Request,
    auth: AuthContext = RoleAdminDep,
    session=Depends(get_optional_tenant_session),
):
    repo = get_role_repository(session)
    current = await repo.get(name)
    if current is None:
        raise _forbid("role_not_found", f"No role named {name!r}.", status=404)

    caps = _validate_capabilities(body.capabilities)
    orphaned = await _would_orphan(repo, name=name, new_caps=caps)
    if orphaned:
        await _audit_denial(
            auth, request, ROLE_UPDATED, "last_holder", name, capabilities=orphaned
        )
        raise _forbid(
            "last_holder",
            f"This would leave no role with: {', '.join(orphaned)}. Nobody could "
            "grant them again — there would be no way back in. Give them to "
            "another role first.",
        )

    await repo.set_capabilities(name, caps)
    await record_action(
        session,
        agency_id=str(auth.agency.id),
        action=ROLE_UPDATED,
        actor_user_id=str(auth.user.id),
        actor_name=auth.user.name,
        request=request,
        target_type="role",
        target_label=name,
        # Before AND after: "who widened this role" is the question asked after
        # an incident, and it is unanswerable from the new value alone.
        detail={
            "role": name,
            "was": sorted(current.capabilities),
            "now": sorted(caps),
            "added": sorted(caps - current.capabilities),
            "removed": sorted(current.capabilities - caps),
        },
    )
    counts = await _user_counts(session)
    return RoleOut(
        name=name,
        capabilities=sorted(caps),
        user_count=counts.get(name, 0),
        builtin=name in BUILTIN_ROLES,
    )


@router.delete("/roles/{name}", status_code=204)
async def delete_role(
    name: str,
    request: Request,
    auth: AuthContext = RoleAdminDep,
    session=Depends(get_optional_tenant_session),
):
    repo = get_role_repository(session)
    current = await repo.get(name)
    if current is None:
        raise _forbid("role_not_found", f"No role named {name!r}.", status=404)

    if name in BUILTIN_ROLES:
        await _audit_denial(auth, request, ROLE_DELETED, "builtin_role", name)
        raise _forbid(
            "builtin_role",
            f"{name!r} is referenced by name in the seed migration, the OAuth "
            "provisioning allowlist and the demo login. Deleting it would break "
            "those silently. Remove its capabilities instead.",
        )

    counts = await _user_counts(session)
    holders = counts.get(name, 0)
    if holders:
        await _audit_denial(auth, request, ROLE_DELETED, "role_in_use", name, users=holders)
        raise _forbid(
            "role_in_use",
            f"{holders} account(s) still have this role. They would keep a role "
            "name that grants nothing, and lose every capability at once. Move "
            "them to another role first.",
        )

    orphaned = await _would_orphan(repo, name=name, new_caps=None)
    if orphaned:
        await _audit_denial(
            auth, request, ROLE_DELETED, "last_holder", name, capabilities=orphaned
        )
        raise _forbid(
            "last_holder",
            f"This is the only role with: {', '.join(orphaned)}. Deleting it "
            "would leave nobody able to grant them again.",
        )

    await repo.delete(name)
    await record_action(
        session,
        agency_id=str(auth.agency.id),
        action=ROLE_DELETED,
        actor_user_id=str(auth.user.id),
        actor_name=auth.user.name,
        request=request,
        target_type="role",
        target_label=name,
        detail={"role": name, "capabilities": sorted(current.capabilities)},
    )
