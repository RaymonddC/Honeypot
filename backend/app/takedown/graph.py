"""TAKEDOWN graph builder — NetworkX DiGraph → Cytoscape elements JSON.

Per-investigation subgraphs are small (thousands of nodes max) so in-memory
NetworkX is plenty; hop depth is capped at 3 (lazy BFS expansion on demand).
Neo4j deferred (docs/TAKEDOWN-Design.md).
"""

import networkx as nx

from app.chain.schemas import Transfer

MAX_HOPS = 3


def build_digraph(transfers: list[Transfer]) -> nx.MultiDiGraph:
    """nodes = wallets, edges = transfers (value, ts, tx_hash)."""
    g = nx.MultiDiGraph()
    for t in transfers:
        g.add_edge(
            t.from_addr,
            t.to_addr,
            key=t.tx_hash,
            value=t.value,
            token=t.token_symbol,
            ts=t.ts,
            tx_hash=t.tx_hash,
        )
    return g


def hop_depths(g: nx.MultiDiGraph, source: str, max_hops: int = MAX_HOPS) -> dict[str, int]:
    """Undirected BFS hop distance from the investigated source, capped."""
    if source not in g:
        return {source: 0}
    return {
        node: depth
        for node, depth in nx.single_source_shortest_path_length(
            g.to_undirected(as_view=True), source, cutoff=max_hops
        ).items()
    }


def bfs_subgraph(g: nx.MultiDiGraph, source: str, hops: int = MAX_HOPS) -> nx.MultiDiGraph:
    """Lazy multi-hop expansion: only nodes within `hops` of the source."""
    depths = hop_depths(g, source, min(hops, MAX_HOPS))
    return g.subgraph(depths.keys())


def to_cytoscape(
    g: nx.MultiDiGraph,
    source: str,
    depths: dict[str, int] | None = None,
    scores: dict | None = None,
    tags: dict[str, list] | None = None,
) -> dict:
    """Cytoscape.js elements: {nodes: [{data}], edges: [{data}]}.

    Node data carries risk (drives green→yellow→red coloring), hop depth and
    attribution tags; edge data carries value/token/ts/tx_hash (edge sizing +
    direction arrows).
    """
    depths = depths or {}
    scores = scores or {}
    tags = tags or {}

    nodes = []
    for node in g.nodes:
        score = scores.get(node)
        nodes.append(
            {
                "data": {
                    "id": node,
                    "label": f"{node[:6]}…{node[-4:]}",
                    "is_source": node == source,
                    "hop": depths.get(node),
                    "risk": score.composite_risk if score else "low",
                    "risk_score": score.iso_forest_score if score else 0.0,
                    "tags": [t.tag for t in tags.get(node, [])],
                    "categories": [t.category for t in tags.get(node, [])],
                }
            }
        )

    edges = [
        {
            "data": {
                "id": f"{data['tx_hash'][:12]}-{i}",
                "source": u,
                "target": v,
                "value": data["value"],
                "token": data["token"],
                "ts": data["ts"].isoformat(),
                "tx_hash": data["tx_hash"],
            }
        }
        for i, (u, v, data) in enumerate(g.edges(data=True))
    ]
    return {"nodes": nodes, "edges": edges}
