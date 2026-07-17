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
