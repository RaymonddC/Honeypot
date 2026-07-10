"""Shared fixtures — deterministic POC data, no network, no Postgres."""

from datetime import datetime, timezone

import pytest

from app.chain.adapters import _load_fixture_transfers
from app.chain.schemas import Transfer

SOURCE = "TXtR9dQpR7mK2vN8fLbY3wZaQ4pJ6"
RELAY1 = "TLa8NqPv5RkXm3WdJc7YtB2sFhE9gUn6Kz"
RELAY2 = "TKe2WmXr9NpQv4LdYc6JtB8sFhA3gUn5Mz"
EXCHANGE = "TBGgUKGDdVWr52tsmSGYcFDkTeDoK5Sw3d"
MULE1 = "TMu01eA9kQvXr4NpLd8YcJt5BsFhG2aWn"[:34]
VICTIM1 = "TN3xKp8VqYmWdR5tJcE2sLbHnG9aQfU4Zw"


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
