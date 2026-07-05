"""TRACE bridge service — orchestrates generator → monitor → correlation →
mules → sankey, computed in-memory per seed (POC pattern, mirrors P1).

Crypto side: USDT deposits at the Indodax hot wallet =
- real fixture deposits via the chain adapter (e.g. the TAKEDOWN peeling
  chain's 86,200 USDT cash-out — surfaces as an *uncorrelated* deposit), plus
- the dataset's synthetic on-ramp deposits (amount-conserving counterparts
  of the bulk fiat transfers, so correlation has real ground truth to find).
"""

from dataclasses import dataclass

from fastapi import Depends

# Importing adapter modules registers their POC/LIVE implementations.
from app.chain import adapters as chain_adapters  # noqa: F401
from app.chain.schemas import Transfer
from app.core.adapters import ChainDataAdapter, FiatDataAdapter, get_adapter
from app.fiat import adapters as fiat_adapters  # noqa: F401
from app.fiat.schemas import FiatDataset, FiatGenParams
from app.trace import correlation as corrmod
from app.trace import mules as mulesmod
from app.trace import sankey as sankeymod

MODULE = "trace"


def get_fiat_adapter() -> FiatDataAdapter:
    """FastAPI dependency: fiat adapter under TRACE's effective MODE."""
    return get_adapter("fiat", MODULE)


def get_chain_adapter() -> ChainDataAdapter:
    """FastAPI dependency: blockchain adapter under TRACE's effective MODE."""
    return get_adapter("blockchain", MODULE)


FiatAdapterDep = Depends(get_fiat_adapter)
ChainAdapterDep = Depends(get_chain_adapter)


@dataclass
class BridgeResult:
    dataset: FiatDataset
    deposits: list[Transfer]
    correlations: list[corrmod.CorrelationOut]
    unmatched: list[Transfer]
    clusters: list[mulesmod.MuleClusterOut]
    sankey: sankeymod.SankeyOut

    @property
    def data_mode(self) -> str:
        return self.dataset.data_mode


# In-memory result cache per generator param set (POC — no Postgres at request time).
_CACHE: dict[tuple, BridgeResult] = {}


async def monitor_deposits(
    chain_adapter: ChainDataAdapter, dataset: FiatDataset
) -> list[Transfer]:
    """Crypto Deposit Monitor: all USDT deposits at the exchange hot wallet."""
    page = await chain_adapter.fetch_transfers(dataset.hot_wallet)
    real = [t for t in page.items if t.to_addr == dataset.hot_wallet]
    seen = {t.tx_hash for t in real}
    synthetic = [d for d in dataset.crypto_deposits if d.tx_hash not in seen]
    return sorted(real + synthetic, key=lambda t: t.ts)


async def build_bridge(
    fiat_adapter: FiatDataAdapter,
    chain_adapter: ChainDataAdapter,
    params: FiatGenParams | None = None,
) -> BridgeResult:
    p = params or FiatGenParams()
    key = (p.seed, p.n_merchants, p.n_clusters, p.n_payers)
    if key in _CACHE:
        return _CACHE[key]

    dataset = await fiat_adapter.load_dataset(p)
    deposits = await monitor_deposits(chain_adapter, dataset)
    correlations = corrmod.correlate(dataset.transactions, dataset.accounts, deposits)
    unmatched = corrmod.unmatched_deposits(deposits, correlations)
    clusters = mulesmod.detect_mule_clusters(dataset)
    sankey = sankeymod.build_sankey(dataset, clusters, correlations)

    result = BridgeResult(
        dataset=dataset,
        deposits=deposits,
        correlations=correlations,
        unmatched=unmatched,
        clusters=clusters,
        sankey=sankey,
    )
    _CACHE[key] = result
    return result
