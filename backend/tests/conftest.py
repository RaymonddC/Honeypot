"""Shared fixtures — deterministic POC data, no network, no Postgres."""

from datetime import datetime, timezone

import pytest

from app.chain.adapters import _load_fixture_transfers
from app.chain.schemas import Transfer
from app.core.config import get_settings as _get_settings

# Tests are hermetic + POC: force memory persistence at import — BEFORE any
# module-scoped TestClient builds its lifespan (e.g. test_api.py) — so a
# developer .env with ITTU_PERSISTENCE=postgres never makes the suite reach for
# a (possibly-down) Postgres. The autouse _hermetic_provider_keys fixture below
# re-asserts this per test; the pgserver/auth-live tests opt back into postgres
# themselves.
_get_settings().persistence = "memory"

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
        s.persistence, s.mode, s.module_modes,
    )
    s.llm_api_key = s.elevenlabs_api_key = s.google_tts_api_key = ""
    # POC is the default posture. A developer .env that flips modes/persistence
    # for LIVE testing (ITTU_PERSISTENCE=postgres, ITTU_MODULE_MODES={"auth":
    # "live"}, ITTU_MODE=live, …) must NOT flip every test out of POC — the
    # pgserver/auth-live tests opt into those themselves (see auth_live fixture).
    s.persistence = "memory"
    s.mode = "poc"
    s.module_modes = {}
    yield
    (
        s.llm_api_key, s.elevenlabs_api_key, s.google_tts_api_key,
        s.persistence, s.mode, s.module_modes,
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
