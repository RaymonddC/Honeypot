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
