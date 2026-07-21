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

    async def _cache_get(self, key: str) -> dict | None:
        """Best-effort read — Redis is an accelerator, never a hard requirement."""
        try:
            if raw := await (await self._cache()).get(key):
                return json.loads(raw)
        except Exception:
            self._redis = None  # drop a broken client; retry lazily next call
        return None

    async def _cache_set(self, key: str, data: dict) -> None:
        try:
            await (await self._cache()).set(key, json.dumps(data), ex=CACHE_TTL_SECONDS)
        except Exception:
            self._redis = None

    def _auth_headers(self) -> dict[str, str]:
        """Optional TRON-PRO-API-KEY → higher TRONSCAN rate limits in prod."""
        key = getattr(self._settings, "tronscan_api_key", "") or ""
        return {"TRON-PRO-API-KEY": key} if key else {}

    async def fetch_transfers(self, address: str, cursor: str | None = None) -> TransferPage:
        start = int(cursor or 0)
        cache_key = f"trc20:{address}:{start}"
        data = await self._cache_get(cache_key)
        if data is None:
            try:
                data = await self._fetch_tronscan(address, start)
            except httpx.HTTPError:
                try:
                    data = await self._fetch_trongrid(address)
                except httpx.HTTPStatusError as exc:
                    # Both providers rejected the lookup. A 400 means the address
                    # is malformed or unknown (e.g. a truncated paste) — degrade to
                    # "no activity" so the investigation comes back empty (→ 404),
                    # never a 500. Other statuses (auth, rate-limit, 5xx) still
                    # surface as real errors rather than a silent empty result.
                    if exc.response.status_code != 400:
                        raise
                    data = {"transfers": []}
            await self._cache_set(cache_key, data)

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
            headers=self._auth_headers(),
        )
        resp.raise_for_status()
        payload = resp.json()
        # Live TRONSCAN row keys: from/to/block_timestamp/hash/amount/decimals/
        # block/contract_ret. Skip reverted transfers (never real value movement).
        return {
            "transfers": [
                {
                    "tx_hash": row["hash"],
                    "from_addr": row["from"],
                    "to_addr": row["to"],
                    "value": int(row["amount"]) / 10 ** int(row.get("decimals", 6)),
                    "token_symbol": "USDT",
                    "token_contract": USDT_TRC20,
                    "ts": row["block_timestamp"],  # epoch ms — pydantic v2 coerces
                    "block_number": row.get("block"),
                }
                for row in payload.get("data", [])
                if row.get("contract_ret", "SUCCESS") == "SUCCESS"
            ]
        }

    async def _fetch_trongrid(self, address: str) -> dict:
        """TronGrid backup: /v1/accounts/{address}/transactions/trc20."""
        # TronGrid is a SEPARATE provider with its own API keys — the TRONSCAN key
        # 401s here — so the fallback stays anonymous (wire ITTU_TRONGRID_API_KEY
        # only if a real TronGrid key is ever added).
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
        resp = await self._client.get(f"{TRONGRID_BASE}/v1/accounts/{address}")  # TronGrid: anonymous
        resp.raise_for_status()
        data = (resp.json().get("data") or [{}])[0]
        return WalletBalance(
            address=address,
            native_balance=data.get("balance", 0) / 10**6,  # TRX has 6 decimals
            data_mode=self.data_mode,
        )
