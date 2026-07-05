"""Mule network detection — Louvain communities + DBSCAN behavioral clustering.

docs/TRACE-Design.md §4: NetworkX community detection (Louvain) on the fiat
transfer graph surfaces mule *clusters*; DBSCAN (scikit-learn) on per-account
behavioral features surfaces the many-in / brief-hold / few-out fingerprint.

Detection uses transaction behavior only — generator ground truth (`role`,
`cluster`) is carried through for demo tooltips/tests but never consulted
by the algorithms.
"""

import uuid
from datetime import datetime

import networkx as nx
import numpy as np
from pydantic import BaseModel
from sklearn.cluster import DBSCAN
from sklearn.preprocessing import StandardScaler

from app.core.config import Mode
from app.fiat.schemas import FiatAccountOut, FiatDataset, FiatTransactionOut

# Behavioral fingerprint thresholds (many-in / brief-hold / few-out).
MIN_INFLOWS = 2                     # ≥2 distinct aggregation inflows
MAX_HOLD_MINUTES = 24 * 60          # aggregation accounts move funds within a day
MIN_FORWARD_RATIO = 0.6             # most of what's received is passed on
                                    # (< 1.0: the newest inflows are still in transit)
MAX_QRIS_IN_RATIO = 0.5             # mules are fed by transfers, not QRIS micro-deposits

DBSCAN_EPS = 1.2
DBSCAN_MIN_SAMPLES = 3


class AccountProfile(BaseModel):
    id: uuid.UUID
    account_number: str
    bank_name: str
    holder_name: str
    role: str                        # generator ground truth (POC legibility)
    in_count: int
    out_count: int
    total_in_idr: float
    total_out_idr: float
    qris_in_ratio: float
    forward_ratio: float
    median_hold_minutes: float | None
    behavioral_flag: bool            # matches the mule fingerprint
    dbscan_cluster: int              # −1 = outlier


class MuleClusterOut(BaseModel):
    cluster_id: str
    size: int
    flagged_mules: int
    confidence: float                # share of members matching the fingerprint
    total_in_idr: float
    exchange_outflow_idr: float
    exchange_accounts: list[str]     # bank accounts this cluster bulk-transfers to
    accounts: list[AccountProfile]
    data_mode: Mode = "poc"


def _profiles(
    accounts: list[FiatAccountOut], transactions: list[FiatTransactionOut]
) -> dict[uuid.UUID, dict]:
    """Raw behavioral features per account, from transactions only."""
    feats: dict[uuid.UUID, dict] = {
        a.id: {
            "in": [], "out": [], "qris_in": 0,
        }
        for a in accounts
    }
    for t in transactions:
        feats[t.to_account_id]["in"].append(t)
        feats[t.from_account_id]["out"].append(t)
        if t.channel == "qris":
            feats[t.to_account_id]["qris_in"] += 1

    out: dict[uuid.UUID, dict] = {}
    for a in accounts:
        f = feats[a.id]
        ins, outs = f["in"], f["out"]
        total_in = sum(t.amount for t in ins)
        total_out = sum(t.amount for t in outs)
        holds: list[float] = []
        for o in outs:
            prior = [i.ts for i in ins if i.ts <= o.ts]
            if prior:
                holds.append((o.ts - max(prior)).total_seconds() / 60)
        holds.sort()
        median_hold = holds[len(holds) // 2] if holds else None
        out[a.id] = {
            "in_count": len(ins),
            "out_count": len(outs),
            "total_in_idr": total_in,
            "total_out_idr": total_out,
            "qris_in_ratio": f["qris_in"] / len(ins) if ins else 0.0,
            "forward_ratio": (total_out / total_in) if total_in else 0.0,
            "median_hold_minutes": median_hold,
        }
    return out


def _is_mule_like(p: dict) -> bool:
    return (
        p["in_count"] >= MIN_INFLOWS
        and 1 <= p["out_count"] <= p["in_count"]
        and p["qris_in_ratio"] <= MAX_QRIS_IN_RATIO
        and p["forward_ratio"] >= MIN_FORWARD_RATIO
        and p["median_hold_minutes"] is not None
        and p["median_hold_minutes"] <= MAX_HOLD_MINUTES
    )


def _dbscan_labels(
    ordered_ids: list[uuid.UUID], profiles: dict[uuid.UUID, dict]
) -> dict[uuid.UUID, int]:
    """DBSCAN over standardized behavioral features (deterministic)."""
    if not ordered_ids:
        return {}
    rows = []
    for aid in ordered_ids:
        p = profiles[aid]
        rows.append([
            p["in_count"],
            p["out_count"],
            np.log1p(p["total_in_idr"]),
            p["qris_in_ratio"],
            min(p["forward_ratio"], 2.0),
            np.log1p(p["median_hold_minutes"] if p["median_hold_minutes"] is not None
                     else 7 * 24 * 60),
        ])
    X = StandardScaler().fit_transform(np.asarray(rows, dtype=float))
    labels = DBSCAN(eps=DBSCAN_EPS, min_samples=DBSCAN_MIN_SAMPLES).fit_predict(X)
    return dict(zip(ordered_ids, (int(x) for x in labels)))


def detect_mule_clusters(dataset: FiatDataset) -> list[MuleClusterOut]:
    """Louvain communities on the aggregation graph + per-account fingerprints."""
    accounts = dataset.accounts
    by_id = dataset.accounts_by_id()
    profiles = _profiles(accounts, dataset.transactions)

    # Aggregation graph: only accounts that both receive and forward transfers
    # (drops payers, exchange accounts, retail one-shots) — behavior, not roles.
    active = [
        a for a in accounts
        if profiles[a.id]["in_count"] >= 1 and profiles[a.id]["out_count"] >= 1
    ]
    active_ids = {a.id for a in active}

    g = nx.Graph()
    g.add_nodes_from(a.id for a in active)
    for t in dataset.transactions:
        if t.channel == "qris":
            continue
        if t.from_account_id in active_ids and t.to_account_id in active_ids:
            w = g.get_edge_data(t.from_account_id, t.to_account_id, {}).get("weight", 0.0)
            g.add_edge(t.from_account_id, t.to_account_id, weight=w + t.amount)

    communities = nx.community.louvain_communities(g, weight="weight", seed=dataset.params.seed)
    communities = [c for c in communities if len(c) >= 3]
    # Stable ordering: largest volume first.
    communities.sort(
        key=lambda c: -sum(profiles[a]["total_in_idr"] for a in c)
    )

    dbscan = _dbscan_labels([a.id for a in active], profiles)
    exchange_by_id = {a.id: a for a in accounts if a.role == "exchange"}

    clusters: list[MuleClusterOut] = []
    for i, members in enumerate(communities):
        member_accounts = sorted((by_id[m] for m in members), key=lambda a: str(a.id))
        rows: list[AccountProfile] = []
        flagged = 0
        exchange_outflow = 0.0
        exchange_accts: set[str] = set()
        for a in member_accounts:
            p = profiles[a.id]
            flag = _is_mule_like(p)
            flagged += flag
            rows.append(AccountProfile(
                id=a.id,
                account_number=a.account_number,
                bank_name=a.bank_name,
                holder_name=a.holder_name,
                role=a.role,
                in_count=p["in_count"],
                out_count=p["out_count"],
                total_in_idr=round(p["total_in_idr"]),
                total_out_idr=round(p["total_out_idr"]),
                qris_in_ratio=round(p["qris_in_ratio"], 3),
                forward_ratio=round(p["forward_ratio"], 3),
                median_hold_minutes=(
                    round(p["median_hold_minutes"], 1)
                    if p["median_hold_minutes"] is not None else None
                ),
                behavioral_flag=flag,
                dbscan_cluster=dbscan.get(a.id, -1),
            ))
        for t in dataset.transactions:
            if t.from_account_id in members and t.to_account_id in exchange_by_id:
                exchange_outflow += t.amount
                x = exchange_by_id[t.to_account_id]
                exchange_accts.add(f"{x.bank_name} ·· {x.account_number[-4:]}")

        rows.sort(key=lambda r: (-r.total_in_idr, r.account_number))
        clusters.append(MuleClusterOut(
            cluster_id=f"MC{i + 1}",
            size=len(rows),
            flagged_mules=flagged,
            confidence=round(flagged / len(rows), 3),
            total_in_idr=round(sum(r.total_in_idr for r in rows)),
            exchange_outflow_idr=round(exchange_outflow),
            exchange_accounts=sorted(exchange_accts),
            accounts=rows,
        ))
    return clusters
