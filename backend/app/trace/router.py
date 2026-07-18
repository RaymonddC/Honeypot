"""TRACE router — the Bridge View / BridgeWatch API (docs/API-Contract.md).

POST /api/bridge/simulate      → generate the synthetic PT A2Z scenario (POC)
GET  /api/bridge/sankey        → sankey nodes/links (d3-sankey, ids as strings)
GET  /api/bridge/correlations  → fiat↔crypto matches (+uncorrelated deposits)
GET  /api/bridge/mules         → mule clusters (Louvain + DBSCAN behavioral)

All endpoints compute in-memory from the seeded generator + chain fixtures
(POC pattern, mirrors P1). ``seed`` selects a scenario; omit it for the
default deterministic demo (seed 4656 — the case's account count).
"""

from collections import Counter

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.chain.schemas import Transfer
from app.core.adapters import ChainDataAdapter, FiatDataAdapter
from app.fiat.generator import IDR_PER_USDT
from app.fiat.schemas import FiatGenParams
from app.trace.correlation import METHOD, CorrelationOut
from app.trace.mules import MuleClusterOut
from app.trace.sankey import SankeyLink, SankeyNode
from app.trace.service import ChainAdapterDep, FiatAdapterDep, build_bridge

router = APIRouter(tags=["trace"])

DEFAULT_SEED = FiatGenParams().seed


class SimulateRequest(BaseModel):
    case_id: str | None = None
    params: FiatGenParams | None = None


class SimulateSummary(BaseModel):
    accounts: dict[str, int]        # by role + total
    transactions: dict[str, int]    # by kind + total
    crypto_deposits: int
    correlations: int
    mule_clusters: int


class SimulateResponse(BaseModel):
    status: str = "ok"
    data_mode: str
    seed: int
    idr_per_usdt: float = IDR_PER_USDT
    case_framing: dict
    summary: SimulateSummary


class CorrelationsResponse(BaseModel):
    case_id: str | None = None
    data_mode: str
    seed: int
    idr_per_usdt: float = IDR_PER_USDT
    method: str = METHOD
    items: list[CorrelationOut]
    unmatched_deposits: list[Transfer]  # e.g. the TAKEDOWN 86,200 USDT cash-out


class MulesResponse(BaseModel):
    case_id: str | None = None
    data_mode: str
    seed: int
    method: str = "louvain+dbscan"
    items: list[MuleClusterOut]


class SankeyResponse(BaseModel):
    case_id: str | None = None
    data_mode: str
    seed: int
    nodes: list[SankeyNode]
    links: list[SankeyLink]
    meta: dict


SeedQuery = Query(default=DEFAULT_SEED, ge=0, description="Generator seed (scenario id)")
CaseQuery = Query(default=None, alias="case", description="Case id (optional, echoed back)")


@router.post("/bridge/simulate", response_model=SimulateResponse)
async def post_simulate(
    body: SimulateRequest | None = None,
    fiat: FiatDataAdapter = FiatAdapterDep,
    chain: ChainDataAdapter = ChainAdapterDep,
) -> SimulateResponse:
    """Generate (or re-generate) the synthetic PT A2Z scenario and warm the cache."""
    params = (body.params if body else None) or FiatGenParams()
    bridge = await build_bridge(fiat, chain, params)
    ds = bridge.dataset
    roles = Counter(a.role for a in ds.accounts)
    kinds = Counter(t.kind or "unknown" for t in ds.transactions)
    return SimulateResponse(
        data_mode=bridge.data_mode,
        seed=ds.params.seed,
        case_framing=ds.case_framing,
        summary=SimulateSummary(
            accounts={"total": len(ds.accounts), **roles},
            transactions={"total": len(ds.transactions), **kinds},
            crypto_deposits=len(bridge.deposits),
            correlations=len(bridge.correlations),
            mule_clusters=len(bridge.clusters),
        ),
    )


@router.get("/bridge/sankey", response_model=SankeyResponse)
async def get_sankey(
    case: str | None = CaseQuery,
    seed: int = SeedQuery,
    fiat: FiatDataAdapter = FiatAdapterDep,
    chain: ChainDataAdapter = ChainAdapterDep,
) -> SankeyResponse:
    """Aggregated flows: QRIS merchants → mules → exchange → USDT → offshore."""
    bridge = await build_bridge(fiat, chain, FiatGenParams(seed=seed))
    return SankeyResponse(
        case_id=case,
        data_mode=bridge.data_mode,
        seed=seed,
        nodes=bridge.sankey.nodes,
        links=bridge.sankey.links,
        meta=bridge.sankey.meta,
    )


@router.get("/bridge/correlations", response_model=CorrelationsResponse)
async def get_correlations(
    case: str | None = CaseQuery,
    seed: int = SeedQuery,
    min_confidence: float = Query(default=0.0, ge=0.0, le=1.0),
    fiat: FiatDataAdapter = FiatAdapterDep,
    chain: ChainDataAdapter = ChainAdapterDep,
) -> CorrelationsResponse:
    """Confidence-ranked fiat↔crypto on-ramp matches (amount + 30-min window)."""
    bridge = await build_bridge(fiat, chain, FiatGenParams(seed=seed))
    items = [c for c in bridge.correlations if c.confidence >= min_confidence]
    return CorrelationsResponse(
        case_id=case,
        data_mode=bridge.data_mode,
        seed=seed,
        items=items,
        unmatched_deposits=bridge.unmatched,
    )


@router.get("/bridge/mules", response_model=MulesResponse)
async def get_mules(
    case: str | None = CaseQuery,
    seed: int = SeedQuery,
    fiat: FiatDataAdapter = FiatAdapterDep,
    chain: ChainDataAdapter = ChainAdapterDep,
) -> MulesResponse:
    """Mule clusters: Louvain communities + DBSCAN behavioral fingerprints."""
    bridge = await build_bridge(fiat, chain, FiatGenParams(seed=seed))
    return MulesResponse(
        case_id=case,
        data_mode=bridge.data_mode,
        seed=seed,
        items=bridge.clusters,
    )


@router.get("/trace/ping")
async def ping() -> dict[str, str]:
    return {"module": "trace"}
