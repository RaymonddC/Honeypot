"""Shared fixtures — deterministic POC data, no network, no Postgres."""

from datetime import datetime, timezone

import pytest

from app.chain.adapters import _load_fixture_transfers
from app.chain.schemas import Transfer
from app.core.config import Settings, get_settings as _get_settings

# Tests are hermetic: NEVER read the developer's backend/.env. Every Settings()
# construction — including fresh instances built inside individual tests (e.g.
# `Settings(tts_provider="elevenlabs")`) — must rely only on explicit init
# kwargs + os.environ, so real credentials, custom voice IDs, or a LIVE mode in
# a dev .env can't break the keyless / fail-loud / default-voice assertions.
# Disabling the env_file source is broader (and more robust) than the per-test
# key-clearing fixture below, which only sanitizes the cached singleton.
Settings.model_config["env_file"] = None

# Force memory persistence at import — BEFORE any module-scoped TestClient
# builds its lifespan (e.g. test_api.py) — so a developer .env with
# ITTU_PERSISTENCE=postgres never makes the suite reach for a (possibly-down)
# Postgres. The autouse _hermetic_provider_keys fixture below re-asserts this
# per test; the pgserver/auth-live tests opt back into postgres themselves.
_get_settings.cache_clear()  # rebuild the singleton now that .env is disabled
_get_settings().persistence = "memory"

# The crypto surface (TAKEDOWN, and the crypto half of TRACE) ships DISABLED —
# a product decision, not a code one (docs/Ecosystem-Strategy.md). The suite
# tests the feature, so it opts in: without this, every crypto test 404s with
# `feature_disabled` and reads as broken rather than switched off.
#
# `test_crypto_flag.py` sets it explicitly in both directions, so the switch
# itself is still covered rather than assumed.
_get_settings().crypto_enabled = True

SOURCE = "TXtR9dQpR7mK2vN8fLbY3wZaQ4pJ6"
RELAY1 = "TLa8NqPv5RkXm3WdJc7YtB2sFhE9gUn6Kz"
RELAY2 = "TKe2WmXr9NpQv4LdYc6JtB8sFhA3gUn5Mz"
EXCHANGE = "TBGgUKGDdVWr52tsmSGYcFDkTeDoK5Sw3d"
MULE1 = "TMu01eA9kQvXr4NpLd8YcJt5BsFhG2aWn"[:34]
VICTIM1 = "TN3xKp8VqYmWdR5tJcE2sLbHnG9aQfU4Zw"


@pytest.fixture(autouse=True)
def _hermetic_provider_keys(monkeypatch):
    """Keep tests independent of the developer's real backend/.env credentials.

    The settings now load backend/.env by absolute path (so uvicorn finds it from
    any cwd), which means a real ITTU_LLM_API_KEY / TTS key would leak into the
    suite and break the keyless/fail-loud assertions. Clear those live keys before
    every test; tests exercising the live path set their own key.
    """
    from app.core.config import get_settings

    for var in (
        "ANTHROPIC_API_KEY", "ITTU_LLM_API_KEY",
        "ITTU_ELEVENLABS_API_KEY", "ITTU_GOOGLE_TTS_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    s = get_settings()
    saved = (
        s.llm_api_key, s.elevenlabs_api_key, s.google_tts_api_key,
        s.persistence, s.mode, s.module_modes, s.crypto_enabled,
    )
    s.llm_api_key = s.elevenlabs_api_key = s.google_tts_api_key = ""
    # POC is the default posture. A developer .env that flips modes/persistence
    # for LIVE testing (ITTU_PERSISTENCE=postgres, ITTU_MODULE_MODES={"auth":
    # "live"}, ITTU_MODE=live, …) must NOT flip every test out of POC — the
    # pgserver/auth-live tests opt into those themselves (see auth_live fixture).
    s.persistence = "memory"
    s.mode = "poc"
    s.module_modes = {}
    # Re-asserted PER TEST, not just at import: any test that calls
    # get_settings.cache_clear() rebuilds the singleton from env, where the
    # crypto flag defaults OFF — every later crypto test would then 404 and read
    # as broken rather than switched off. Same reason persistence is re-asserted
    # here rather than trusted from module scope.
    s.crypto_enabled = True
    yield
    (
        s.llm_api_key, s.elevenlabs_api_key, s.google_tts_api_key,
        s.persistence, s.mode, s.module_modes, s.crypto_enabled,
    ) = saved


@pytest.fixture(scope="session")
def fixture_transfers() -> list[Transfer]:
    return list(_load_fixture_transfers())


def bearer(role: str = "police-investigator", agency: str = "bareskrim") -> dict[str, str]:
    """Authorization header for a demo user (P5 auth) — no HTTP round-trip."""
    from app.core.auth import find_agency, mint_token, upsert_demo_user

    user = upsert_demo_user(find_agency(agency), role)
    token, _ = mint_token(user)
    return {"Authorization": f"Bearer {token}"}


def make_transfer(frm: str, to: str, value: float, ts: str, i: int = 0) -> Transfer:
    """Hand-rolled transfer for detector unit tests."""
    return Transfer(
        tx_hash=f"deadbeef{i:056d}",
        from_addr=frm,
        to_addr=to,
        value=value,
        ts=datetime.fromisoformat(ts).replace(tzinfo=timezone.utc),
    )


# --------------------------------------------------------------------------- #
# pgserver seeding — psql that actually fails when the SQL fails
# --------------------------------------------------------------------------- #


class PsqlSeedError(RuntimeError):
    """A statement in a pgserver seed script failed. Raised at the point of
    failure so a broken fixture reports itself, instead of the test failing
    later on an assertion about data that was never inserted."""


def psql_strict(cluster, sql: str, *, label: str = "") -> str:
    """Run ``sql`` on a pgserver cluster and RAISE if any statement fails.

    **Why this exists.** ``pgserver``'s own ``PostgresServer.psql()`` is
    ``subprocess.check_output(...)`` — so it does check the exit status, and the
    exit status is genuinely 0. The problem is upstream of that: **psql's
    default is to keep going after a SQL error and still exit 0.** The error
    text goes to stderr, which nothing captures, so the call returns cleanly
    with empty stdout and the fixture looks like it worked.

    Measured, not assumed (see this helper's tests):

    - a NOT NULL violation via plain ``psql()`` returns normally, stdout ``''``;
    - **a failing statement does NOT abort the rest of the script**, so a seed
      whose first INSERT fails still runs the second and leaves the database
      half-populated — which is why the eventual failure looks like a data
      mismatch rather than a setup error.

    That cost two debugging rounds in one task (a missing ``public_id``, then a
    missing ``bundle_id``), and every pgserver test file seeds this way — the
    files that prove RLS isolation, chain integrity, and mode isolation. A
    harness that hides setup failures is a bad foundation for tests relied on to
    prove security properties.

    The fix is ``ON_ERROR_STOP``, which makes psql abort at the first error and
    exit non-zero — so the exit status becomes meaningful and ``check_output``
    raises. Deliberately NOT stderr-sniffing: matching on the text ``ERROR``
    would be locale-dependent and would trip over legitimate NOTICE output and
    over rows that merely contain the word.

    Raises rather than ``pytest.fail``: inside a fixture this surfaces as a
    pytest ERROR ("setup broke, the test never ran") rather than a FAILURE
    ("the assertion was wrong"), which is the distinction worth having. It also
    behaves the same at module, fixture, and test-body level.
    """
    import subprocess

    # `\set ON_ERROR_STOP on` is a psql meta-command and works over stdin, so
    # this needs no change to how pgserver invokes the binary.
    payload = "\\set ON_ERROR_STOP on\n" + sql
    try:
        return cluster.psql(payload)
    except subprocess.CalledProcessError as exc:
        # psql exits 3 on a SQL error under ON_ERROR_STOP. pgserver's psql()
        # does not pipe stderr, so Postgres's own message goes to the parent's
        # stderr — pytest shows it under "Captured stderr", directly above this
        # exception. Point at it rather than pretending we have it here.
        raise PsqlSeedError(
            f"psql seeding failed{f' ({label})' if label else ''} — exit code "
            f"{exc.returncode}. Postgres's error is in pytest's Captured stderr "
            f"for this test, immediately above.\n"
            f"--- SQL ---\n{sql.strip()}\n-----------"
        ) from exc
