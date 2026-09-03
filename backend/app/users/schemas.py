"""UAM request/response shapes. Nothing secret ever leaves here — no tokens,
no oauth_sub, no password material (there is none: auth is OAuth/JWT)."""

import uuid

from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, field_validator

from app.core.auth import ROLES

# A plain constrained string, NOT a Literal of the six built-in names.
#
# Roles are DATA now (core.roles), so a `Literal` here would make a role created
# in the admin UI unassignable: POST /users would reject it as invalid before
# any of our own checks ran, and the error would blame the caller for using a
# role the product just told them to create. Existence is checked against the
# roles table in `app/users/router.py`, where a refusal can say which role is
# unknown and is audited like every other denial.
#
# The shape rule stays, because a role name reaches SQL, the JWT, and the audit
# trail: lowercase letters, digits and hyphens.
RoleName = Annotated[str, StringConstraints(
    min_length=2, max_length=64, pattern=r"^[a-z][a-z0-9-]*$"
)]


class UserAdminOut(BaseModel):
    id: str
    agency_id: str
    email: str
    name: str
    role: str
    is_active: bool


class CreateUserRequest(BaseModel):
    # Deliberately NOT pydantic's EmailStr: that pulls in the optional
    # `email-validator` dependency, and adding one to the locked requirements
    # for a single field is not a trade worth making. A shape check is enough —
    # the address is an identifier here, never something we send mail to.
    email: str = Field(min_length=3, max_length=254)
    name: str = Field(min_length=1, max_length=200)
    role: RoleName
    # platform-admin only; agency-admin is confined to its own agency.
    agency_id: uuid.UUID | None = None

    @field_validator("email")
    @classmethod
    def _looks_like_an_email(cls, v: str) -> str:
        v = v.strip().lower()
        local, _, domain = v.partition("@")
        if not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
            raise ValueError("must be an email address, e.g. name@agency.go.id")
        return v


class UpdateUserRequest(BaseModel):
    """Both fields optional — send the one you're changing."""

    role: RoleName | None = None
    is_active: bool | None = None


__all__ = ["ROLES", "CreateUserRequest", "RoleName", "UpdateUserRequest", "UserAdminOut"]
