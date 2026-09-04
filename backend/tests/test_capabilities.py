"""The capability registry — the closed set, and the seed that matches it.

These tests exist to keep two things true that nothing else would notice
breaking:

1. every capability the registry advertises is actually ENFORCED somewhere, so
   the admin UI can never offer a switch wired to nothing, and
2. the migration's literal seed still matches ``DEFAULT_ROLE_CAPABILITIES``,
   which are deliberately duplicated (a migration must not import a constant a
   later release will change).
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest

from app.core import roles as roles_module
from app.core.auth import require_capability
from app.core.capabilities import (
    CAPABILITIES,
    CAPABILITY_KEYS,
    DEFAULT_ROLE_CAPABILITIES,
    UNREMOVABLE_CAPABILITIES,
    USERS_ADMIN,
    is_capability,
)
from app.core.config import Settings, get_settings

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _memory_mode(monkeypatch):
    """Resolve from the seeded defaults, not the developer's database."""
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    get_settings.cache_clear()
    monkeypatch.setattr(get_settings(), "persistence", "memory", raising=False)
    roles_module.invalidate()
    yield
    roles_module.invalidate()
    get_settings.cache_clear()


# --------------------------------------------------------------------------- #
# The set is closed, and every member is real
# --------------------------------------------------------------------------- #


def test_a_capability_that_nothing_enforces_would_be_a_lie():
    """Every declared capability must appear in a `require_capability(...)` call.

    This is the property that makes the admin UI honest: an operator toggling
    "Operate the honeypot" must be changing something. A capability nobody
    checks is worse than an absent one — the UI would report a protection that
    does not exist, which is the same defect as a chain that says "verified"
    about something it cannot see.
    """
    app_dir = BACKEND_DIR / "app"
    sources = "\n".join(
        p.read_text(encoding="utf-8") for p in app_dir.rglob("*.py")
        if p.name not in {"capabilities.py", "auth.py"}
    )
    # Two ways a capability is legitimately enforced:
    #   require_capability(X)      — gates a whole endpoint
    #   has_capability(role, X)    — a conditional check inside a handler, used
    #                                where only PART of the behaviour is gated
    #                                (cross-agency administration, for example)
    # Both count. Only counting the first would push authors toward the wrong
    # shape just to satisfy this test.
    guarded = set(re.findall(r"require_capability\(\s*([A-Z_]+)\s*\)", sources))
    guarded |= set(re.findall(r'require_capability\(\s*"([^"]+)"\s*\)', sources))
    guarded |= set(re.findall(r"has_capability\([^,]+,\s*([A-Z_]+)\s*\)", sources))
    guarded |= set(re.findall(r'has_capability\([^,]+,\s*"([^"]+)"\s*\)', sources))

    # Constants resolve to their values.
    from app.core import capabilities as cap_mod

    resolved = {getattr(cap_mod, g, g) for g in guarded}
    unenforced = CAPABILITY_KEYS - resolved

    assert not unenforced, (
        "these capabilities are declared but no endpoint requires them, so the "
        f"admin UI would offer a switch wired to nothing: {sorted(unenforced)}"
    )


def test_a_typo_in_a_guard_is_caught_at_definition_not_at_the_first_request():
    """A guard naming a capability that does not exist can never be satisfied —
    every request 403s and nothing says why. Caught when the module loads."""
    with pytest.raises(ValueError) as exc:
        require_capability("honeypot.oprate")
    assert "honeypot.oprate" in str(exc.value)
    assert "capabilities.py" in str(exc.value), (
        "the error must point at where capabilities are declared"
    )


def test_is_capability_rejects_anything_not_declared():
    assert is_capability(USERS_ADMIN)
    assert not is_capability("users.admin.superuser")
    assert not is_capability("")


def test_every_capability_has_a_description_written_for_the_grantor():
    """These strings are what an administrator reads while deciding whether to
    hand someone a power. A key name is not an explanation."""
    for cap in CAPABILITIES:
        assert cap.label and cap.description, cap.key
        assert len(cap.description) > 40, (
            f"{cap.key}'s description is too thin to decide from: {cap.description!r}"
        )


# --------------------------------------------------------------------------- #
# Defaults and the lockout floor
# --------------------------------------------------------------------------- #


def test_default_roles_only_grant_capabilities_that_exist():
    for role, caps in DEFAULT_ROLE_CAPABILITIES.items():
        unknown = set(caps) - CAPABILITY_KEYS
        assert not unknown, f"{role} is seeded with unknown capabilities: {unknown}"


def test_someone_can_always_administer_users():
    """The floor that stops a configurable permission system locking everyone
    out of itself. If no seeded role holds `users.admin`, a fresh deployment has
    no way to grant it either — there is no path back in."""
    holders = [r for r, c in DEFAULT_ROLE_CAPABILITIES.items() if USERS_ADMIN in c]
    assert holders, "no seeded role can administer users — a fresh install is unadministerable"
    assert USERS_ADMIN in UNREMOVABLE_CAPABILITIES


def test_only_the_platform_role_crosses_agencies():
    """Cross-agency administration is the one capability that breaks tenant
    isolation, so it must not be seeded onto an agency-scoped role."""
    from app.core.capabilities import USERS_ADMIN_CROSS_AGENCY

    holders = {
        r for r, c in DEFAULT_ROLE_CAPABILITIES.items() if USERS_ADMIN_CROSS_AGENCY in c
    }
    assert holders == {"platform-admin"}, (
        f"cross-agency user administration is seeded onto: {sorted(holders)}"
    )


def test_institutional_roles_cannot_operate_the_honeypot():
    """The judgement the default policy encodes, pinned so a careless edit to
    the seed has to argue with it: a bank or exchange compliance officer must
    not run a tool that engages a live suspect."""
    from app.core.capabilities import HONEYPOT_OPERATE

    for role in ("bank-compliance", "exchange-compliance"):
        assert HONEYPOT_OPERATE not in DEFAULT_ROLE_CAPABILITIES[role], (
            f"{role} was granted honeypot operation — that is a law-enforcement act"
        )


# --------------------------------------------------------------------------- #
# Resolution
# --------------------------------------------------------------------------- #


def test_an_unknown_role_holds_nothing():
    """A role can be deleted while someone still holds a token naming it. They
    lose their capabilities — the intended consequence, and not an error here."""
    assert _run(roles_module.capabilities_for("no-such-role")) == frozenset()


def test_resolution_matches_the_seeded_policy_in_memory_mode():
    caps = _run(roles_module.capabilities_for("police-investigator"))
    assert caps == DEFAULT_ROLE_CAPABILITIES["police-investigator"]


def test_an_unreadable_roles_table_grants_nothing(monkeypatch):
    """Fail CLOSED. A database that is down must not fall back to the seeded
    defaults in code — that is how a capability revoked in the database comes
    back to life during an outage.
    """
    monkeypatch.setattr(get_settings(), "persistence", "postgres", raising=False)
    roles_module.invalidate()

    async def _boom():
        return None  # what _load_from_db returns when the read fails

    monkeypatch.setattr(roles_module, "_load_from_db", _boom)

    assert _run(roles_module.all_role_capabilities()) == {}
    assert _run(roles_module.capabilities_for("platform-admin")) == frozenset(), (
        "a failed read fell back to the in-code defaults — a revoked capability "
        "would come back during a database outage"
    )


def test_a_failed_read_is_not_cached(monkeypatch):
    """Otherwise one blip denies every request for the whole TTL."""
    monkeypatch.setattr(get_settings(), "persistence", "postgres", raising=False)
    roles_module.invalidate()

    calls = {"n": 0}

    async def _flaky():
        calls["n"] += 1
        return None if calls["n"] == 1 else {"agency-admin": frozenset({USERS_ADMIN})}

    monkeypatch.setattr(roles_module, "_load_from_db", _flaky)

    assert _run(roles_module.capabilities_for("agency-admin")) == frozenset()
    assert _run(roles_module.capabilities_for("agency-admin")) == frozenset({USERS_ADMIN}), (
        "the failure was cached, so recovery took a full TTL"
    )


# --------------------------------------------------------------------------- #
# The seed migration must not drift from the defaults
# --------------------------------------------------------------------------- #


def test_the_seed_migration_matches_the_default_policy():
    """The migration duplicates these values deliberately — it must describe the
    schema at its point in history, not import a constant a later release will
    change. Duplication is only safe while something checks it."""
    import importlib.util

    # BOTH seed migrations must agree with the policy: 19 (insert-if-absent) and
    # 21 (backfill-if-empty). 19 is a no-op on any database that ran 05, which
    # is every one of them — 21 is the one that actually populates the column,
    # and a drift there is the one that would silently 403 everybody.
    for filename in (
        "20260823_19_seed_roles.py",
        "20260904_21_backfill_role_permissions.py",
    ):
        path = BACKEND_DIR / "migrations" / "versions" / filename
        spec = importlib.util.spec_from_file_location(f"seed_{filename}", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        seeded = {name: frozenset(caps) for name, caps in module.SEED.items()}
        assert seeded == dict(DEFAULT_ROLE_CAPABILITIES), (
            f"{filename} disagrees with DEFAULT_ROLE_CAPABILITIES.\n"
            f"  migration: { {k: sorted(v) for k, v in seeded.items()} }\n"
            f"  defaults:  { {k: sorted(v) for k, v in DEFAULT_ROLE_CAPABILITIES.items()} }"
        )
