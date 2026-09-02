"""Settings defaults — the persistence toggle (docs/Persistence-Plan.md P-1).

Default MUST be "memory": the POC runs with no database, unchanged, until a
repository layer (P-2+) actually reads this flag.
"""

from app.core.config import Settings


def test_persistence_defaults_to_memory(monkeypatch):
    """No ITTU_PERSISTENCE set → memory (POC-safe default)."""
    monkeypatch.delenv("ITTU_PERSISTENCE", raising=False)
    settings = Settings(_env_file=None)
    assert settings.persistence == "memory"
    assert settings.persistence_enabled is False


def test_persistence_postgres_opt_in(monkeypatch):
    """Explicit opt-in flips the toggle; nothing else changes behavior in P-1."""
    monkeypatch.setenv("ITTU_PERSISTENCE", "postgres")
    settings = Settings(_env_file=None)
    assert settings.persistence == "postgres"
    assert settings.persistence_enabled is True


def test_mode_resolver_follows_the_current_settings_not_a_captured_one():
    """The resolver must never hold its own ``Settings``.

    It used to. Because ``get_mode_resolver`` is ``@lru_cache``d, a
    ``get_settings.cache_clear()`` — which the pgserver tests do to point alembic
    at an ephemeral cluster — rebuilt the singleton while the resolver kept the
    orphaned one. Every MODE read then answered from an object nothing else could
    reach, and ``/api/config`` reported a mode that could not be changed.

    CI stayed green only by alphabetical luck: the files that clear the cache
    sorted after the files that check MODE. Adding one early-sorting test file
    broke three auth tests, which is how this was found. This test removes the
    luck.
    """
    from app.core.config import get_mode_resolver, get_settings

    resolver = get_mode_resolver()
    original = get_settings()
    prior_mode, prior_overrides = original.mode, dict(original.module_modes)
    try:
        original.mode = "poc"
        original.module_modes = {}
        assert resolver.effective_mode("auth") == "poc"

        # Rebuild the singleton out from under the (cached) resolver.
        get_settings.cache_clear()
        try:
            rebuilt = get_settings()
            assert rebuilt is not original, "cache_clear should have produced a new instance"
            rebuilt.mode = "poc"
            rebuilt.module_modes = {"auth": "live"}

            assert get_mode_resolver() is resolver, (
                "the factory is still cached — that is fine, but it means the "
                "resolver below must be reading settings at use, not at build"
            )
            assert resolver.effective_mode("auth") == "live", (
                "the resolver answered from an orphaned Settings — it is "
                "capturing the instance again"
            )
            assert resolver.effective_mode("trace") == "poc"
        finally:
            get_settings.cache_clear()
    finally:
        s = get_settings()
        s.mode, s.module_modes = prior_mode, prior_overrides


# --------------------------------------------------------------------------- #
# Mixed module modes under Postgres — refused at boot
# --------------------------------------------------------------------------- #


def _coherence_check_with(mode: str, overrides: dict, persistence: str):
    """Run assert_modes_are_coherent against a specific config.

    Mutates the cached singleton and restores it, matching the pattern the
    resolver test above uses — the guard reads get_settings() at call time.
    """
    from app.core.config import assert_modes_are_coherent, get_settings

    s = get_settings()
    prior = (s.mode, s.module_modes, s.persistence)
    s.mode, s.module_modes, s.persistence = mode, overrides, persistence
    try:
        assert_modes_are_coherent()
        return None
    except RuntimeError as exc:
        return str(exc)
    finally:
        s.mode, s.module_modes, s.persistence = prior


def test_mixed_module_modes_are_refused_under_postgres():
    """The boot refusal. `app.data_mode` is ONE value per transaction and a
    request spans modules, so a per-module mode cannot be honestly stamped —
    better to refuse than to write rows tagged with a mode that is not theirs."""
    error = _coherence_check_with("poc", {"uncover": "live"}, "postgres")
    assert error is not None, "a mixed-mode postgres config was allowed to boot"


def test_the_refusal_names_the_offenders_and_both_ways_out():
    """A rule the reader cannot act on is a rule they will work around.

    The person most likely to hit this is a developer whose local .env has both
    ITTU_MODULE_MODES and ITTU_PERSISTENCE=postgres, mid-task, with no idea why
    the app stopped starting. The message has to do the explaining.
    """
    error = _coherence_check_with("poc", {"uncover": "live"}, "postgres")

    assert "uncover" in error and "'live'" in error, "the offending override is not named"
    assert "ITTU_MODE='poc'" in error, "the global mode it conflicts with is not named"
    assert "ITTU_PERSISTENCE=memory" in error, "way out #1 (memory mode) is not offered"
    assert "ITTU_MODULE_MODES" in error, "way out #2 (align the override) is not offered"
    assert "transaction" in error, "the WHY is missing — the reader learns a rule, not a reason"


def test_mixed_module_modes_stay_supported_in_memory_mode():
    """Memory mode has no RLS and no row stamping, so mixed modes remain fully
    usable there — which is where they are actually used (a LIVE takedown
    adapter against replayed INFILTRATE transcripts)."""
    assert _coherence_check_with("poc", {"takedown": "live"}, "memory") is None


def test_an_override_on_a_module_that_persists_nothing_is_allowed():
    """The narrowing that keeps this guard honest.

    The incoherence is about the row STAMP. `takedown` and `trace` have no
    Postgres repository — their data flows through adapters (TRONSCAN, fixtures)
    and is never persisted — so they cannot mis-stamp anything, and refusing
    them buys no safety.

    This matters because `ITTU_MODULE_MODES={"takedown":"live"}` with a POC
    database is the configuration a developer actually uses: real blockchain
    data, replayed everything else. The first version of this guard refused it,
    and a guard that blocks a provably safe setup does not make anyone safer —
    it teaches them to switch guards off.
    """
    assert _coherence_check_with("poc", {"takedown": "live"}, "postgres") is None
    assert _coherence_check_with("poc", {"trace": "live"}, "postgres") is None


def test_a_persisting_module_is_still_refused_even_beside_a_safe_one():
    """The narrowing must not become a loophole: one safe override alongside a
    persisting one must still refuse, naming the persisting one."""
    error = _coherence_check_with("poc", {"takedown": "live", "cases": "live"}, "postgres")
    assert error is not None, "a persisting module's conflict was masked by a safe override"
    assert "cases" in error, f"the refusal must name the module that can actually mis-stamp: {error}"


def test_persisting_modules_matches_the_modules_that_have_a_postgres_repository():
    """Pins the set against the tree, so a module gaining persistence without
    being added here cannot silently fall out of the guard's coverage."""
    from pathlib import Path

    from app.core.config import PERSISTING_MODULES

    app_dir = Path(__file__).resolve().parents[1] / "app"
    found = {
        d.name
        for d in app_dir.iterdir()
        if d.is_dir() and (d / "repository.py").is_file()
        and "class Postgres" in (d / "repository.py").read_text(encoding="utf-8")
    }
    assert found == set(PERSISTING_MODULES), (
        "PERSISTING_MODULES has drifted from the modules that actually own a "
        f"Postgres repository.\n  in the tree: {sorted(found)}\n  in the set:  "
        f"{sorted(PERSISTING_MODULES)}"
    )


def test_agreeing_overrides_are_not_a_conflict():
    """An override that RESTATES the global mode is redundant, not incoherent —
    refusing it would be a papercut with no safety benefit."""
    assert _coherence_check_with("live", {"takedown": "live"}, "postgres") is None
    assert _coherence_check_with("poc", {}, "postgres") is None
