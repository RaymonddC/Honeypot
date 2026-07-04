"""Blockchain boundary adapters — POC (deterministic fixtures) and LIVE (TRONSCAN).

Registered in the core adapter registry under ``("blockchain", "poc"/"live")``.
Both implement the ``ChainDataAdapter`` protocol (app/core/adapters.py) with
identical signatures + Pydantic return models, and stamp ``data_mode``.
"""

import json
from functools import lru_cache
from pathlib import Path

import httpx

from app.core.adapters import register
from app.core.config import Mode, Settings
from app.chain.schemas import AddressTagOut, Transfer, TransferPage, WalletBalance

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# USDT-TRC20 contract on TRON mainnet.
USDT_TRC20 = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"

TRONSCAN_BASE = "https://apilist.tronscanapi.com"
TRONGRID_BASE = "https://api.trongrid.io"
PAGE_SIZE = 50
CACHE_TTL_SECONDS = 3600


@lru_cache
def _load_fixture_transfers() -> tuple[Transfer, ...]:
    raw = json.loads((FIXTURES_DIR / "transfers.json").read_text())
    return tuple(Transfer(**row, data_mode="poc") for row in raw)


@lru_cache
def load_address_tags() -> tuple[AddressTagOut, ...]:
    """Attribution overlay seed (POC snapshot of exchange/scam tags)."""
    raw = json.loads((FIXTURES_DIR / "tags.json").read_text())
    return tuple(AddressTagOut(**row) for row in raw)


def tags_for(address: str) -> list[AddressTagOut]:
    return [t for t in load_address_tags() if t.address == address]


@register("blockchain", "poc")
class CachedTronAdapter:
    """POC: deterministic, offline fixtures (Gary's demo addresses).

    ~20 TRON addresses whose USDT-TRC20 transfers form a coherent peeling
    chain: victims → scam source → 2 relay hops (peeling off small amounts)
    → an Indodax exchange deposit, plus a mule fan-out and a wash cycle.
    """

    data_mode: Mode = "poc"

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings

    async def fetch_transfers(self, address: str, cursor: str | None = None) -> TransferPage:
        items = [
            t for t in _load_fixture_transfers()
            if address in (t.from_addr, t.to_addr)
        ]
        return TransferPage(items=items, next_cursor=None)  # fixtures fit one page

    async def balance(self, address: str) -> WalletBalance:
        received = sum(t.value for t in _load_fixture_transfers() if t.to_addr == address)
        sent = sum(t.value for t in _load_fixture_transfers() if t.from_addr == address)
        return WalletBalance(
            address=address,
            token_balance=max(received - sent, 0.0),
            data_mode=self.data_mode,
        )


@register("blockchain", "live")
class TronscanAdapter:
    """LIVE: TRONSCAN ``/api/transfer/trc20`` primary, TronGrid backup.

    Redis-cached (free tiers throttle at ~5–15 req/s); network calls are
    isolated in ``_fetch_*`` helpers. Not exercised in POC/CI — no live
    network in tests.
    """

    data_mode: Mode = "live"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = httpx.AsyncClient(timeout=15.0)
        self._redis = None  # lazy — created on first use

    async def _cache(self):
        if self._redis is None:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(self._settings.redis_url, decode_responses=True)
        return self._redis

    async def fetch_transfers(self, address: str, cursor: str | None = None) -> TransferPage:
        start = int(cursor or 0)
        cache_key = f"trc20:{address}:{start}"
        cache = await self._cache()
        if cached := await cache.get(cache_key):
            data = json.loads(cached)
        else:
            try:
                data = await self._fetch_tronscan(address, start)
            except httpx.HTTPError:
                data = await self._fetch_trongrid(address)
            await cache.set(cache_key, json.dumps(data), ex=CACHE_TTL_SECONDS)

        items = [Transfer(**row, data_mode="live") for row in data["transfers"]]
        next_cursor = str(start + PAGE_SIZE) if len(items) == PAGE_SIZE else None
        return TransferPage(items=items, next_cursor=next_cursor)

    async def _fetch_tronscan(self, address: str, start: int) -> dict:
        """TRONSCAN /api/transfer/trc20, normalized to Transfer kwargs."""
        resp = await self._client.get(
            f"{TRONSCAN_BASE}/api/transfer/trc20",
            params={
                "address": address,
                "trc20Id": USDT_TRC20,
                "start": start,
                "limit": PAGE_SIZE,
                "direction": 0,  # both
            },
        )
        resp.raise_for_status()
        payload = resp.json()
        return {
            "transfers": [
                {
                    "tx_hash": row["hash"],
                    "from_addr": row["transferFromAddress"],
                    "to_addr": row["transferToAddress"],
                    "value": int(row["amount"]) / 10**6,  # USDT has 6 decimals
                    "token_symbol": "USDT",
                    "token_contract": USDT_TRC20,
                    "ts": row["timestamp"],  # epoch ms — pydantic coerces
                    "block_number": row.get("block"),
                }
                for row in payload.get("data", [])
            ]
        }

    async def _fetch_trongrid(self, address: str) -> dict:
        """TronGrid backup: /v1/accounts/{address}/transactions/trc20."""
        resp = await self._client.get(
            f"{TRONGRID_BASE}/v1/accounts/{address}/transactions/trc20",
            params={"contract_address": USDT_TRC20, "limit": PAGE_SIZE},
        )
        resp.raise_for_status()
        payload = resp.json()
        return {
            "transfers": [
                {
                    "tx_hash": row["transaction_id"],
                    "from_addr": row["from"],
                    "to_addr": row["to"],
                    "value": int(row["value"]) / 10**6,
                    "token_symbol": "USDT",
                    "token_contract": USDT_TRC20,
                    "ts": row["block_timestamp"],
                    "block_number": None,
                }
                for row in payload.get("data", [])
            ]
        }

    async def balance(self, address: str) -> WalletBalance:
        resp = await self._client.get(f"{TRONGRID_BASE}/v1/accounts/{address}")
        resp.raise_for_status()
        data = (resp.json().get("data") or [{}])[0]
        return WalletBalance(
            address=address,
            native_balance=data.get("balance", 0) / 10**6,  # TRX has 6 decimals
            data_mode=self.data_mode,
        )
