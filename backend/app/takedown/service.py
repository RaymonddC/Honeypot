"""TAKEDOWN investigation service — adapter → BFS ingest → graph → scores."""

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


async def gather_transfers(
    adapter: ChainDataAdapter, source: str, hops: int = graphmod.MAX_HOPS
) -> list[Transfer]:
    """Lazy BFS ingest: fetch transfers per address, expanding ≤`hops` from source."""
    seen_tx: set[tuple[str, str, str]] = set()
    transfers: list[Transfer] = []
    visited: set[str] = set()
    frontier = {source}

    for _ in range(min(hops, graphmod.MAX_HOPS) + 1):
        next_frontier: set[str] = set()
        for address in sorted(frontier - visited):
            visited.add(address)
            cursor: str | None = None
            while True:
                page = await adapter.fetch_transfers(address, cursor=cursor)
                for t in page.items:
                    key = (t.tx_hash, t.from_addr, t.to_addr)
                    if key not in seen_tx:
                        seen_tx.add(key)
                        transfers.append(t)
                    next_frontier.update((t.from_addr, t.to_addr))
                if not page.next_cursor:
                    break
                cursor = page.next_cursor
        frontier = next_frontier - visited
        if not frontier:
            break
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
