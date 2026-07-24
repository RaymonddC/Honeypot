"""TAKEDOWN investigation service — adapter → BFS ingest → graph → scores."""

import asyncio
import logging

from fastapi import Depends

# Importing app.chain.adapters registers the POC/LIVE blockchain adapters.
from app.chain import adapters as chain_adapters  # noqa: F401
from app.chain.adapters import tags_for
from app.chain.schemas import Transfer
from app.core.adapters import ChainDataAdapter, get_adapter
from app.takedown import graph as graphmod
from app.takedown.scoring import WalletScore, score_investigation

MODULE = "takedown"


def get_blockchain_adapter() -> ChainDataAdapter:
    """FastAPI dependency: blockchain adapter under TAKEDOWN's effective MODE."""
    return get_adapter("blockchain", MODULE)


_log = logging.getLogger("app.takedown")

# LIVE ingest budget. Free-tier TRON APIs rate-limit hard, and a real wallet's BFS
# fans out unboundedly (every counterparty's full history, ×hops) — which exhausts
# the quota and times out. Bound breadth/pages/total-addresses in LIVE, and fetch
# each hop's frontier CONCURRENTLY (bounded) so tracing stays responsive (~53s→~10s
# on a whale). POC (small deterministic fixtures) is NEVER capped, so the seeded
# demo graph is unchanged.
LIVE_MAX_ADDRESSES_PER_HOP = 8
LIVE_MAX_PAGES_PER_ADDRESS = 1
LIVE_MAX_TOTAL_ADDRESSES = 25
LIVE_CONCURRENCY = 4  # gentle on the free key tier — higher trips 429s


async def _fetch_all_pages(
    adapter: ChainDataAdapter, address: str, live: bool
) -> list[Transfer]:
    """Every transfer page for one address (page-capped in LIVE)."""
    items: list[Transfer] = []
    cursor: str | None = None
    pages = 0
    while True:
        page = await adapter.fetch_transfers(address, cursor=cursor)
        pages += 1
        items.extend(page.items)
        if not page.next_cursor or (live and pages >= LIVE_MAX_PAGES_PER_ADDRESS):
            break
        cursor = page.next_cursor
    return items


def _index_by_address(transfers: list[Transfer]) -> dict[str, list[Transfer]]:
    """Group transfers by each endpoint address (for the manual-transfer merge)."""
    index: dict[str, list[Transfer]] = {}
    for t in transfers:
        index.setdefault(t.from_addr, []).append(t)
        index.setdefault(t.to_addr, []).append(t)
    return index


async def gather_transfers(
    adapter: ChainDataAdapter,
    source: str,
    hops: int = graphmod.MAX_HOPS,
    extra_transfers: list[Transfer] | None = None,
) -> list[Transfer]:
    """Lazy BFS ingest: fetch transfers per address, expanding ≤`hops` from source.

    Each hop's frontier is fetched concurrently (bounded by a semaphore in LIVE).
    In LIVE the traversal is bounded (breadth/pages/total addresses) to stay within
    free-tier rate limits; POC is unbounded. ``asyncio.gather`` preserves input
    order, so the merge is order-identical to a sequential walk — the POC fixture
    graph is byte-for-byte unchanged.

    ``extra_transfers`` are analyst-entered edges (app/casedata) folded into the
    same BFS: any touching a visited address join the graph and expand the
    frontier, so a hand-entered transaction — or a brand-new wallet known only
    from manual data — is investigable exactly like adapter data.
    """
    live = getattr(adapter, "data_mode", "poc") == "live"
    manual_index = _index_by_address(extra_transfers or [])
    sem = asyncio.Semaphore(LIVE_CONCURRENCY)

    async def fetch_one(address: str) -> list[Transfer]:
        if live:
            async with sem:  # cap concurrent upstream calls (rate-limit friendly)
                return await _fetch_all_pages(adapter, address, live)
        return await _fetch_all_pages(adapter, address, live)

    seen_tx: set[tuple[str, str, str]] = set()
    transfers: list[Transfer] = []
    visited: set[str] = set()
    frontier = {source}
    fetched = 0
    capped = False

    for hop in range(min(hops, graphmod.MAX_HOPS) + 1):
        addresses = sorted(frontier - visited)
        if live and len(addresses) > LIVE_MAX_ADDRESSES_PER_HOP:
            addresses, capped = addresses[:LIVE_MAX_ADDRESSES_PER_HOP], True
        if live and fetched + len(addresses) > LIVE_MAX_TOTAL_ADDRESSES:
            addresses, capped = addresses[: LIVE_MAX_TOTAL_ADDRESSES - fetched], True
        if not addresses:
            break
        visited.update(addresses)
        fetched += len(addresses)

        # Fetch this hop's whole frontier at once; results keep `addresses` order.
        # The source (hop 0) propagates errors — if we can't even fetch the root,
        # surface it (→ 502/503). A downstream counterparty that errors (e.g. a
        # transient 429) is skipped so one bad node never kills the whole trace.
        per_address = await asyncio.gather(
            *(fetch_one(a) for a in addresses), return_exceptions=hop > 0
        )

        next_frontier: set[str] = set()
        failed = 0
        for items in per_address:
            if isinstance(items, BaseException):
                failed += 1
                continue
            for t in items:
                key = (t.tx_hash, t.from_addr, t.to_addr)
                if key not in seen_tx:
                    seen_tx.add(key)
                    transfers.append(t)
                next_frontier.update((t.from_addr, t.to_addr))
        # Manual (analyst-entered) transfers touching this hop's addresses —
        # offline, never rate-capped, folded in like fixture/live edges.
        for address in addresses:
            for t in manual_index.get(address, []):
                key = (t.tx_hash, t.from_addr, t.to_addr)
                if key not in seen_tx:
                    seen_tx.add(key)
                    transfers.append(t)
                next_frontier.update((t.from_addr, t.to_addr))
        if failed:
            capped = True
            _log.info(
                "LIVE BFS for %s: %d/%d addresses failed at hop %d (skipped) — partial graph.",
                source, failed, len(addresses), hop,
            )
        frontier = next_frontier - visited
        if not frontier or (live and fetched >= LIVE_MAX_TOTAL_ADDRESSES):
            break

    if capped:
        _log.info(
            "LIVE BFS for %s hit an ingest cap (%d addresses, %d transfers) — graph "
            "is a bounded sample, not full history.",
            source, fetched, len(transfers),
        )
    return transfers


class Investigation:
    """One scored investigation rooted at `source`."""

    def __init__(self, source: str, transfers: list[Transfer]) -> None:
        self.source = source
        self.transfers = transfers
        self.data_mode = transfers[0].data_mode if transfers else "poc"
        self.graph = graphmod.build_digraph(transfers)
        self.depths = graphmod.hop_depths(self.graph, source)
        self.scores: dict[str, WalletScore] = score_investigation(source, transfers)

    def cytoscape(self, hops: int = graphmod.MAX_HOPS) -> dict:
        sub = graphmod.bfs_subgraph(self.graph, self.source, hops)
        tags = {a: tags_for(a) for a in sub.nodes}
        return graphmod.to_cytoscape(
            sub, self.source, depths=self.depths, scores=self.scores, tags=tags
        )


async def investigate(
    address: str,
    adapter: ChainDataAdapter,
    hops: int = graphmod.MAX_HOPS,
    extra_transfers: list[Transfer] | None = None,
) -> Investigation | None:
    """Run the full pipeline; None if the address has no transfers.

    ``extra_transfers`` are analyst-entered edges (app/casedata) merged into the
    BFS — so an address known only from manually-added data is still investigable.
    """
    transfers = await gather_transfers(adapter, address, hops, extra_transfers=extra_transfers)
    if not transfers:
        return None
    return Investigation(address, transfers)


AdapterDep = Depends(get_blockchain_adapter)
