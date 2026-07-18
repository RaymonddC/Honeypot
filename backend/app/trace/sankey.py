"""Sankey flow builder — aggregate volumes per laundering stage.

docs/TRACE-Design.md §5. Stages:

    0 QRIS shell merchants → 1 mule clusters → 2 exchange bank accounts
      → 3 USDT hot wallet → 4 foreign/offshore (estimated)

Node/link values are IDR (integer rupiah); crypto-side links also carry
``value_usdt``. Links reference nodes by string ``id`` — the frontend maps
ids to indices for d3-sankey (``nodeId`` accessor).
"""

from pydantic import BaseModel

from app.core.config import Mode
from app.fiat.schemas import FiatDataset
from app.trace.correlation import CorrelationOut
from app.trace.mules import MuleClusterOut

STAGES = [
    "QRIS shell merchants",
    "Mule accounts",
    "Exchange IDR accounts",
    "USDT hot wallet",
    "Foreign / offshore",
]


class SankeyNode(BaseModel):
    id: str
    name: str
    stage: int
    stage_name: str
    meta: dict = {}


class SankeyLink(BaseModel):
    source: str
    target: str
    value: float             # IDR
    value_usdt: float | None = None
    kind: str                # sweep | bulk | onramp | offshore


class SankeyOut(BaseModel):
    nodes: list[SankeyNode]
    links: list[SankeyLink]
    meta: dict
    data_mode: Mode = "poc"


def build_sankey(
    dataset: FiatDataset,
    clusters: list[MuleClusterOut],
    correlations: list[CorrelationOut],
) -> SankeyOut:
    by_id = dataset.accounts_by_id()
    cluster_of: dict = {}  # account id -> MuleClusterOut
    for c in clusters:
        for a in c.accounts:
            cluster_of[a.id] = c

    nodes: dict[str, SankeyNode] = {}
    links: dict[tuple[str, str, str], SankeyLink] = {}

    def node(id_: str, name: str, stage: int, **meta) -> SankeyNode:
        if id_ not in nodes:
            nodes[id_] = SankeyNode(
                id=id_, name=name, stage=stage, stage_name=STAGES[stage], meta=meta
            )
        return nodes[id_]

    def add(source: str, target: str, value: float, kind: str,
            value_usdt: float | None = None) -> None:
        key = (source, target, kind)
        if key in links:
            links[key].value += value
            if value_usdt is not None:
                links[key].value_usdt = (links[key].value_usdt or 0.0) + value_usdt
        else:
            links[key] = SankeyLink(
                source=source, target=target, value=value, value_usdt=value_usdt, kind=kind
            )

    # Stage 0 → 1: merchant sweeps into mule clusters.
    for t in dataset.transactions:
        if t.kind != "merchant_sweep":
            continue
        m = by_id[t.from_account_id]
        c = cluster_of.get(t.to_account_id)
        if c is None:
            continue
        mid = f"merchant:{m.id}"
        node(mid, m.holder_name, 0, bank=m.bank_name, account_number=m.account_number)
        cid = f"cluster:{c.cluster_id}"
        node(cid, f"Mule cluster {c.cluster_id} ({c.size} accts)", 1,
             flagged_mules=c.flagged_mules, confidence=c.confidence)
        add(mid, cid, t.amount, "sweep")

    # Stage 1 → 2: collector bulk transfers to exchange bank accounts.
    for t in dataset.transactions:
        if t.kind != "bulk_to_exchange":
            continue
        c = cluster_of.get(t.from_account_id)
        x = by_id[t.to_account_id]
        if c is None:
            continue
        cid = f"cluster:{c.cluster_id}"
        xid = f"exchange:{x.id}"
        node(xid, f"Indodax IDR ·· {x.account_number[-4:]} ({x.bank_name})", 2,
             bank=x.bank_name, account_number=x.account_number)
        add(cid, xid, t.amount, "bulk")

    # Stage 2 → 3: correlated on-ramp conversions into the USDT hot wallet.
    wid = f"wallet:{dataset.hot_wallet}"
    node(wid, f"Indodax USDT hot wallet ({dataset.hot_wallet[:6]}…{dataset.hot_wallet[-4:]})", 3,
         address=dataset.hot_wallet, chain="tron")
    exchange_by_number = {
        a.account_number: a for a in dataset.accounts if a.role == "exchange"
    }
    total_onramp_idr = 0.0
    total_onramp_usdt = 0.0
    for corr in correlations:
        x = exchange_by_number.get(corr.fiat.to_account_number)
        if x is None:
            continue
        add(f"exchange:{x.id}", wid, corr.fiat.amount_idr, "onramp",
            value_usdt=corr.crypto.amount_usdt)
        total_onramp_idr += corr.fiat.amount_idr
        total_onramp_usdt += corr.crypto.amount_usdt

    # Stage 3 → 4: offshore payout (no on-chain outflow in fixtures — estimated).
    if total_onramp_idr:
        fid = "foreign:offshore"
        node(fid, "Offshore payout wallets (est.)", 4, estimated=True)
        add(wid, fid, total_onramp_idr, "offshore", value_usdt=total_onramp_usdt)

    ordered = sorted(nodes.values(), key=lambda n: (n.stage, n.name))
    link_list = [
        SankeyLink(
            source=lk.source, target=lk.target, value=round(lk.value),
            value_usdt=round(lk.value_usdt, 2) if lk.value_usdt is not None else None,
            kind=lk.kind,
        )
        for lk in sorted(links.values(), key=lambda link: (link.source, link.target))
    ]

    stage_totals = {
        STAGES[s]: round(sum(link.value for link in link_list
                             if nodes[link.source].stage == s))
        for s in range(4)
    }
    return SankeyOut(
        nodes=ordered,
        links=link_list,
        meta={
            **dataset.case_framing,
            "idr_per_usdt": dataset.idr_per_usdt,
            "stage_totals_idr": stage_totals,
            "correlated_deposits": len(correlations),
            "onramp_total_idr": round(total_onramp_idr),
            "onramp_total_usdt": round(total_onramp_usdt, 2),
        },
    )
