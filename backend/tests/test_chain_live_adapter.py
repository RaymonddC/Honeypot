"""TronscanAdapter (LIVE) — field mapping, optional API key, best-effort Redis.

No network I/O: a fake httpx client stands in for ``adapter._client`` and records
the call it received. Payload shape below is the REAL TRONSCAN
``/api/transfer/trc20`` response (one SUCCESS row + one REVERT row) that exposed
the original from/to/block_timestamp field-name bug.
"""

import httpx
import pytest

from app.chain.adapters import USDT_TRC20, TronscanAdapter
from app.core.config import Settings

PAYLOAD = {
    "data": [
        {
            "amount": "195000000",
            "block_timestamp": 1783965228000,
            "block": 84431722,
            "from": "TNXoiAJ3dct8Fjg4M9fkLFh9S2v9TXc32G",
            "to": "TAaFSxbiB2KsC7b2sXwVb26DVwkSGjGHNH",
            "hash": "25cd00d8e38c5700d362d306c674fcd26274209673aa2ab2ff22d58ef3e13eba",
            "contract_ret": "SUCCESS",
            "decimals": 6,
            "token_name": "TetherToken",
        },
        {
            "amount": "5000000",
            "block_timestamp": 1783965300000,
            "block": 84431799,
            "from": "TReverted1111111111111111111111111",
            "to": "TReverted2222222222222222222222222",
            "hash": "deadbeef",
            "contract_ret": "REVERT",
            "decimals": 6,
        },
    ]
}

ADDRESS = "TNXoiAJ3dct8Fjg4M9fkLFh9S2v9TXc32G"


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._payload


class FakeHttpxClient:
    """Records every .get() call; always answers with the fixed PAYLOAD."""

    def __init__(self, payload: dict = PAYLOAD) -> None:
        self._payload = payload
        self.calls: list[dict] = []

    async def get(self, url, params=None, headers=None):
        self.calls.append({"url": url, "params": params, "headers": headers})
        return FakeResponse(self._payload)


class DeadRedis:
    """Simulates Redis being unreachable — every call raises."""

    async def get(self, key):
        raise ConnectionError("redis down")

    async def set(self, key, value, ex=None):
        raise ConnectionError("redis down")


def _make_adapter(settings: Settings | None = None, redis=None) -> TronscanAdapter:
    adapter = TronscanAdapter(settings or Settings())
    adapter._client = FakeHttpxClient()
    adapter._redis = redis if redis is not None else DeadRedis()
    return adapter


async def test_fetch_transfers_maps_live_tronscan_fields_and_skips_reverts():
    adapter = _make_adapter()

    page = await adapter.fetch_transfers(ADDRESS)

    assert len(page.items) == 1
    transfer = page.items[0]
    assert transfer.from_addr == "TNXoiAJ3dct8Fjg4M9fkLFh9S2v9TXc32G"
    assert transfer.to_addr == "TAaFSxbiB2KsC7b2sXwVb26DVwkSGjGHNH"
    assert transfer.value == 195.0
    assert transfer.ts.year == 2026
    assert transfer.data_mode == "live"
    assert transfer.token_contract == USDT_TRC20


async def test_fetch_transfers_survives_dead_redis():
    adapter = _make_adapter(redis=DeadRedis())

    page = await adapter.fetch_transfers(ADDRESS)

    assert len(page.items) == 1


async def test_fetch_tronscan_sends_api_key_header_when_configured():
    settings = Settings(tronscan_api_key="test-tron-key")
    adapter = _make_adapter(settings=settings)

    await adapter.fetch_transfers(ADDRESS)

    call = adapter._client.calls[0]
    assert call["headers"]["TRON-PRO-API-KEY"] == "test-tron-key"


async def test_fetch_tronscan_omits_api_key_header_when_unset():
    adapter = _make_adapter(settings=Settings(tronscan_api_key=""))

    await adapter.fetch_transfers(ADDRESS)

    call = adapter._client.calls[0]
    assert "TRON-PRO-API-KEY" not in call["headers"]


class _StatusErrorResponse:
    """A response whose raise_for_status() raises like httpx does for a bad status."""

    def __init__(self, status: int) -> None:
        self.status_code = status

    def raise_for_status(self) -> None:
        request = httpx.Request("GET", "https://example.test")
        response = httpx.Response(self.status_code, request=request)
        raise httpx.HTTPStatusError(f"{self.status_code}", request=request, response=response)

    def json(self) -> dict:  # pragma: no cover — never reached (raise_for_status first)
        return {}


class _AllStatusClient:
    """Every provider call fails with the same HTTP status (both TRONSCAN + TronGrid)."""

    def __init__(self, status: int) -> None:
        self._status = status

    async def get(self, url, params=None, headers=None):
        return _StatusErrorResponse(self._status)


def _adapter_with(status: int) -> TronscanAdapter:
    adapter = TronscanAdapter(Settings())
    adapter._client = _AllStatusClient(status)
    adapter._redis = DeadRedis()
    return adapter


async def test_bad_address_400_from_both_providers_degrades_to_empty_not_500():
    """A malformed/unknown address (e.g. a truncated paste) makes both providers
    400 — the adapter must return an empty page so the investigation 404s, not 500."""
    adapter = _adapter_with(400)

    page = await adapter.fetch_transfers("TMuA6YqfCeX8EhbfYEg5y7S4DqzSJireY")  # truncated

    assert page.items == []
    assert page.next_cursor is None


async def test_non_400_upstream_error_still_raises():
    """A real upstream failure (5xx) must NOT be masked as 'no activity' — it
    surfaces as an error rather than silently returning an empty investigation."""
    adapter = _adapter_with(503)

    with pytest.raises(httpx.HTTPStatusError):
        await adapter.fetch_transfers("TNXoiAJ3dct8Fjg4M9fkLFh9S2v9TXc32G")
