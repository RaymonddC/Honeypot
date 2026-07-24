"""TAKEDOWN router — the Investigation Screen API (docs/API-Contract.md).

POST /api/investigate                      → 202 {job_id}  (async — runs in the background)
GET  /api/investigate/jobs/{job_id}        → {status, result?|error?}
GET  /api/wallets/{address}/graph?hops=3   → {nodes, edges}
GET  /api/wallets/{address}/risk           → risk score (+reasoning, patterns)
GET  /api/takedown/model-card              → model metadata + Elliptic validation

Investigations run as an in-process async job (app/takedown/jobs.py) so the client
never holds a long connection — a trace can't time out the request, even in POC.
Analyst-entered transfers (app/casedata) are merged into every trace.
"""

from functools import lru_cache

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.casedata.repository import CaseDataRepository, get_casedata_repository
from app.core.adapters import ChainDataAdapter
from app.takedown.elliptic import EllipticValidationReport, run_validation
from app.takedown.features import FEATURE_ORDER
from app.takedown.graph import MAX_HOPS
from app.takedown.jobs import JobError, JobStore, get_job_store
from app.takedown.scoring import MODEL_VERSION, WalletScore
from app.chain.schemas import Transfer
from app.takedown.service import AdapterDep, investigate

router = APIRouter(tags=["takedown"])

CaseDataDep = Depends(get_casedata_repository)


async def _manual_transfers(repo: CaseDataRepository) -> list[Transfer]:
    """Analyst-entered crypto edges (app/casedata) as chain Transfers."""
    return [t.as_transfer() for t in await repo.list_crypto_transfers()]

# The 5 deterministic typology detectors (app/takedown/scoring.py).
TYPOLOGY_DETECTORS = [
    "peeling_chain", "rapid_relay", "circular", "structuring", "fan_out",
]


class ModelCard(BaseModel):
    """TAKEDOWN anomaly-model card: what it is + how it validates."""

    model_version: str
    detector: str
    unsupervised: bool
    n_features: int
    features: list[str]
    typology_detectors: list[str]
    elliptic_validation: EllipticValidationReport


@lru_cache(maxsize=1)
def _model_card() -> ModelCard:
    """Built once per process — the Elliptic validation fit is cached."""
    return ModelCard(
        model_version=MODEL_VERSION,
        detector="IsolationForest + 5 deterministic typology detectors",
        unsupervised=True,
        n_features=12,  # canonical feature count (volume counts once; see features.py)
        features=list(FEATURE_ORDER),
        typology_detectors=list(TYPOLOGY_DETECTORS),
        elliptic_validation=run_validation(),
    )


class InvestigateRequest(BaseModel):
    address: str = Field(min_length=4)
    chain: str = "tron"
    # BFS depth. Lower = smaller/faster graph. LIVE clients pass hops=1 for a
    # responsive trace of a busy wallet (a whale at hops=3 fans out to hundreds
    # of nodes and can outrun the browser's fetch timeout). Clamped to ≤MAX_HOPS.
    hops: int = Field(default=MAX_HOPS, ge=1, le=MAX_HOPS)


class GraphOut(BaseModel):
    nodes: list[dict]
    edges: list[dict]


class InvestigateResponse(BaseModel):
    address: str
    chain: str = "tron"
    data_mode: str
    graph: GraphOut
    scores: dict[str, WalletScore]


class JobSubmitResponse(BaseModel):
    job_id: str
    status: str = "pending"


class JobStatusResponse(BaseModel):
    job_id: str
    status: str  # pending | running | done | error
    result: InvestigateResponse | None = None  # present when status == "done"
    error: dict[str, str] | None = None  # {code, message} when status == "error"


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


async def _run_investigation(
    address: str, chain: str, hops: int, adapter: ChainDataAdapter,
    extra_transfers: list[Transfer] | None = None,
) -> InvestigateResponse:
    """The actual work, run inside a job. Provider failures become JobErrors with
    the same {code} the synchronous handler used to surface as 502/503 — the job
    runs off the request, so the app-level httpx handler can't catch them here.

    ``extra_transfers`` (analyst-entered, app/casedata) are resolved in the
    request handler and merged into the trace here."""
    try:
        inv = await investigate(address, adapter, hops=hops, extra_transfers=extra_transfers)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 429:
            raise JobError(
                "provider_rate_limited",
                "The blockchain data provider is rate-limiting requests. Retry "
                "shortly, or set ITTU_TRONSCAN_API_KEY for higher limits.",
            )
        raise JobError("provider_unavailable", "The blockchain data provider is unavailable.")
    except httpx.HTTPError:
        raise JobError("provider_unavailable", "The blockchain data provider is unavailable.")

    # No transfers → done with an empty graph (client renders the honest "no data"
    # state); it's a valid outcome, not an error.
    if inv is None:
        return InvestigateResponse(
            address=address, chain=chain, data_mode="live",
            graph=GraphOut(nodes=[], edges=[]), scores={},
        )
    cyto = inv.cytoscape(hops=hops)
    return InvestigateResponse(
        address=address, chain=chain, data_mode=inv.data_mode,
        graph=GraphOut(**cyto), scores=inv.scores,
    )


@router.post("/investigate", status_code=202, response_model=JobSubmitResponse)
async def post_investigate(
    body: InvestigateRequest,
    adapter: ChainDataAdapter = AdapterDep,
    store: JobStore = Depends(get_job_store),
    casedata: CaseDataRepository = CaseDataDep,
) -> JobSubmitResponse:
    """Submit an investigation (BFS ≤`hops` + score) and return a job id at once.

    Async by design — the trace runs in the background so the request never blocks
    and can't time out. Poll GET /api/investigate/jobs/{job_id} for the result.
    Analyst-entered transfers (app/casedata) are resolved now (request scope, where
    the repo/RLS session is available) and merged into the background trace.
    """
    address, chain, hops = body.address, body.chain, body.hops
    extra = await _manual_transfers(casedata)
    job_id = store.submit(lambda: _run_investigation(address, chain, hops, adapter, extra))
    return JobSubmitResponse(job_id=job_id)


@router.get("/investigate/jobs/{job_id}", response_model=JobStatusResponse)
async def get_investigate_job(
    job_id: str, store: JobStore = Depends(get_job_store)
) -> JobStatusResponse:
    """Poll an investigation job: pending/running, or done+result, or error+{code}."""
    job = store.get(job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "job_not_found", "message": f"No investigation job {job_id}"},
        )
    return JobStatusResponse(
        job_id=job.id,
        status=job.status,
        result=job.result if job.status == "done" else None,
        error=job.error,
    )


@router.get("/wallets/{address}/graph", response_model=WalletGraphResponse)
async def get_wallet_graph(
    address: str,
    hops: int = Query(default=MAX_HOPS, ge=1, le=MAX_HOPS),
    adapter: ChainDataAdapter = AdapterDep,
    casedata: CaseDataRepository = CaseDataDep,
) -> WalletGraphResponse:
    """Cytoscape elements for the wallet's neighbourhood (lazy BFS ≤3 hops)."""
    inv = await investigate(
        address, adapter, hops=hops, extra_transfers=await _manual_transfers(casedata)
    )
    if inv is None:
        raise _not_found(address)
    cyto = inv.cytoscape(hops=hops)
    return WalletGraphResponse(
        address=address, hops=hops, data_mode=inv.data_mode, **cyto
    )


@router.get("/wallets/{address}/risk", response_model=WalletRiskResponse)
async def get_wallet_risk(
    address: str,
    adapter: ChainDataAdapter = AdapterDep,
    casedata: CaseDataRepository = CaseDataDep,
) -> WalletRiskResponse:
    """Risk score + 12 features + fired patterns + Glass Box reasoning."""
    inv = await investigate(address, adapter, extra_transfers=await _manual_transfers(casedata))
    if inv is None or address not in inv.scores:
        raise _not_found(address)
    score = inv.scores[address]
    return WalletRiskResponse(data_mode=inv.data_mode, **score.model_dump())


@router.get("/takedown/model-card", response_model=ModelCard)
async def get_model_card() -> ModelCard:
    """Model card for the wallet risk engine: the Isolation Forest config, its 12
    features + 5 typology detectors, and its accuracy validated against the
    Elliptic Data Set (ROC-AUC / precision / recall / F1). Substantiates the
    proposal's 'anomaly model development has begun on Elliptic' claim with a
    live, reproducible number."""
    return _model_card()


@router.get("/takedown/ping")
async def ping() -> dict[str, str]:
    return {"module": "takedown"}
