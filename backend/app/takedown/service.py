"""TAKEDOWN investigation service — adapter → BFS ingest → graph → scores."""

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
# the quota and times out. Bound breadth/pages/total-calls in LIVE so tracing stays
# responsive within budget. POC (small deterministic fixtures) is NEVER capped, so
# the seeded demo graph is unchanged.
LIVE_MAX_ADDRESSES_PER_HOP = 12
LIVE_MAX_PAGES_PER_ADDRESS = 2
LIVE_MAX_TOTAL_FETCHES = 60


async def gather_transfers(
    adapter: ChainDataAdapter, source: str, hops: int = graphmod.MAX_HOPS
) -> list[Transfer]:
    """Lazy BFS ingest: fetch transfers per address, expanding ≤`hops` from source.

    In LIVE mode the traversal is bounded (breadth/pages/total fetches) to stay
    within free-tier rate limits; POC is unbounded (small, deterministic fixtures).
    """
    live = getattr(adapter, "data_mode", "poc") == "live"
    seen_tx: set[tuple[str, str, str]] = set()
    transfers: list[Transfer] = []
    visited: set[str] = set()
    frontier = {source}
    fetches = 0
    capped = False

    for _ in range(min(hops, graphmod.MAX_HOPS) + 1):
        next_frontier: set[str] = set()
        addresses = sorted(frontier - visited)
        if live and len(addresses) > LIVE_MAX_ADDRESSES_PER_HOP:
            addresses = addresses[:LIVE_MAX_ADDRESSES_PER_HOP]
            capped = True
        for address in addresses:
            if live and fetches >= LIVE_MAX_TOTAL_FETCHES:
                capped = True
                break
            visited.add(address)
            cursor: str | None = None
            pages = 0
            while True:
                page = await adapter.fetch_transfers(address, cursor=cursor)
                fetches += 1
                pages += 1
                for t in page.items:
                    key = (t.tx_hash, t.from_addr, t.to_addr)
                    if key not in seen_tx:
                        seen_tx.add(key)
                        transfers.append(t)
                    next_frontier.update((t.from_addr, t.to_addr))
                if not page.next_cursor:
                    break
                if live and (pages >= LIVE_MAX_PAGES_PER_ADDRESS or fetches >= LIVE_MAX_TOTAL_FETCHES):
                    capped = True
                    break
                cursor = page.next_cursor
        frontier = next_frontier - visited
        if not frontier or (live and fetches >= LIVE_MAX_TOTAL_FETCHES):
            break

    if capped:
        _log.info(
            "LIVE BFS for %s hit an ingest cap (%d fetches, %d transfers) — graph is "
            "a bounded sample, not full history.",
            source, fetches, len(transfers),
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
    address: str, adapter: ChainDataAdapter, hops: int = graphmod.MAX_HOPS
) -> Investigation | None:
    """Run the full pipeline; None if the address has no transfers."""
    transfers = await gather_transfers(adapter, address, hops)
    if not transfers:
        return None
    return Investigation(address, transfers)


AdapterDep = Depends(get_blockchain_adapter)
