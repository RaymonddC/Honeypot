"""TAKEDOWN router — the Investigation Screen API (docs/API-Contract.md).

POST /api/investigate                      → {graph, scores}
GET  /api/wallets/{address}/graph?hops=3   → {nodes, edges}
GET  /api/wallets/{address}/risk           → risk score (+reasoning, patterns)
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.adapters import ChainDataAdapter
from app.takedown.graph import MAX_HOPS
from app.takedown.scoring import WalletScore
from app.takedown.service import AdapterDep, investigate

router = APIRouter(tags=["takedown"])


class InvestigateRequest(BaseModel):
    address: str = Field(min_length=4)
    chain: str = "tron"


class GraphOut(BaseModel):
    nodes: list[dict]
    edges: list[dict]


class InvestigateResponse(BaseModel):
    address: str
    chain: str = "tron"
    data_mode: str
    graph: GraphOut
    scores: dict[str, WalletScore]


class WalletGraphResponse(BaseModel):
    address: str
    chain: str = "tron"
    hops: int
    data_mode: str
    nodes: list[dict]
    edges: list[dict]


class WalletRiskResponse(WalletScore):
    data_mode: str


def _not_found(address: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={
            "code": "wallet_not_found",
            "message": f"No transfers found for address {address}",
        },
    )


@router.post("/investigate", response_model=InvestigateResponse)
async def post_investigate(
    body: InvestigateRequest, adapter: ChainDataAdapter = AdapterDep
) -> InvestigateResponse:
    """Ingest (BFS ≤3 hops) + score a wallet, return graph + per-wallet scores."""
    inv = await investigate(body.address, adapter)
    if inv is None:
        raise _not_found(body.address)
    cyto = inv.cytoscape()
    return InvestigateResponse(
        address=body.address,
        chain=body.chain,
        data_mode=inv.data_mode,
        graph=GraphOut(**cyto),
        scores=inv.scores,
    )


@router.get("/wallets/{address}/graph", response_model=WalletGraphResponse)
async def get_wallet_graph(
    address: str,
    hops: int = Query(default=MAX_HOPS, ge=1, le=MAX_HOPS),
    adapter: ChainDataAdapter = AdapterDep,
) -> WalletGraphResponse:
    """Cytoscape elements for the wallet's neighbourhood (lazy BFS ≤3 hops)."""
    inv = await investigate(address, adapter, hops=hops)
    if inv is None:
        raise _not_found(address)
    cyto = inv.cytoscape(hops=hops)
    return WalletGraphResponse(
        address=address, hops=hops, data_mode=inv.data_mode, **cyto
    )


@router.get("/wallets/{address}/risk", response_model=WalletRiskResponse)
async def get_wallet_risk(
    address: str, adapter: ChainDataAdapter = AdapterDep
) -> WalletRiskResponse:
    """Risk score + 12 features + fired patterns + Glass Box reasoning."""
    inv = await investigate(address, adapter)
    if inv is None or address not in inv.scores:
        raise _not_found(address)
    score = inv.scores[address]
    return WalletRiskResponse(data_mode=inv.data_mode, **score.model_dump())


@router.get("/takedown/ping")
async def ping() -> dict[str, str]:
    return {"module": "takedown"}
