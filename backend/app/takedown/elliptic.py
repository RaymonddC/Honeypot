"""Elliptic Dataset validation harness for the TAKEDOWN Isolation Forest.

The proposal commits to *validating anomaly-detection accuracy* against the
**Elliptic Data Set** — 203,769 Bitcoin transactions, 166 features each, a
subset labelled licit/illicit (Weber et al. 2019; Kaggle
``ellipticco/elliptic-data-set``). This module is that harness: it loads the
canonical 3-file Elliptic layout, fits the *same* unsupervised Isolation Forest
configuration TAKEDOWN uses in production (``app/takedown/scoring.py``:
``contamination``, ``-decision_function`` = anomaly), and scores it against the
ground-truth illicit labels (ROC-AUC, precision/recall/F1, confusion counts).

The real 200k CSVs are **not vendored** (size + licence — see
``fixtures/elliptic/README.md`` for the one-line Kaggle fetch). When they are
absent, ``load_elliptic`` falls back to a schema-accurate **synthetic** sample
(same 166-feature shape, an illicit cluster the detector can separate) so the
harness — and its tests — run out-of-the-box and prove the pipeline end-to-end.
Drop the real files into ``ITTU_ELLIPTIC_DIR`` and the identical code path
produces the full-dataset numbers.

Run it:  ``python -m app.takedown.elliptic``  (or ``scripts/validate_elliptic.py``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from pydantic import BaseModel
from sklearn.ensemble import IsolationForest
from sklearn.metrics import (
    confusion_matrix,
    precision_recall_fscore_support,
    roc_auc_score,
)

# Canonical Elliptic layout (Kaggle ellipticco/elliptic-data-set).
FEATURES_CSV = "elliptic_txs_features.csv"   # no header: txId, time_step, f1..f165
CLASSES_CSV = "elliptic_txs_classes.csv"     # header: txId,class  (1=illicit,2=licit,unknown)
N_FEATURES = 166                             # incl. time step as feature 0 (per the paper)

# Class encoding in the raw file → our binary illicit label.
_ILLICIT_RAW = "1"   # Elliptic: class "1" = illicit
_LICIT_RAW = "2"     # Elliptic: class "2" = licit
# "unknown" / "3" rows are unlabelled → excluded from supervised scoring.

DEFAULT_CONTAMINATION = 0.05   # matches app/takedown/scoring.py iso_forest_scores
FIXTURES_DIR = Path(__file__).parent / "fixtures" / "elliptic"


@dataclass
class EllipticData:
    """Labelled feature matrix ready for validation.

    ``X`` is (n, N_FEATURES); ``y`` is 1 = illicit, 0 = licit (labelled rows
    only — unknown rows are dropped for supervised scoring). ``source`` records
    whether these are the real CSVs or the synthetic fallback.
    """

    X: np.ndarray
    y: np.ndarray
    source: str            # "elliptic-csv" | "synthetic"
    n_total: int           # rows before dropping unknown (real dataset size)
    n_illicit: int
    n_licit: int


class EllipticValidationReport(BaseModel):
    """Validation metrics for one Isolation Forest run over Elliptic labels."""

    source: str
    model_version: str
    contamination: float
    n_total: int
    n_labelled: int
    n_illicit: int
    n_licit: int
    roc_auc: float                 # anomaly score vs illicit label
    precision: float               # at the contamination threshold
    recall: float
    f1: float
    true_positives: int
    false_positives: int
    true_negatives: int
    false_negatives: int
    note: str = ""


# --------------------------------------------------------------------------- #
# Loading — real CSVs, else schema-accurate synthetic fallback
# --------------------------------------------------------------------------- #


def _resolve_data_dir(data_dir: str | os.PathLike | None) -> Path | None:
    """Real-data dir from arg → ``ITTU_ELLIPTIC_DIR`` env → vendored fixtures."""
    for cand in (data_dir, os.environ.get("ITTU_ELLIPTIC_DIR"), FIXTURES_DIR):
        if not cand:
            continue
        p = Path(cand)
        if (p / FEATURES_CSV).exists() and (p / CLASSES_CSV).exists():
            return p
    return None


def load_elliptic(data_dir: str | os.PathLike | None = None) -> EllipticData:
    """Load labelled Elliptic rows, or the synthetic fallback if CSVs are absent.

    Real path expects the two canonical CSVs (features + classes) in ``data_dir``
    (or ``ITTU_ELLIPTIC_DIR``, or the vendored fixtures sample). Only rows with a
    licit/illicit label are returned (``unknown`` dropped).
    """
    resolved = _resolve_data_dir(data_dir)
    if resolved is None:
        return synthetic_elliptic()
    return _load_csv(resolved)


def _load_csv(data_dir: Path) -> EllipticData:
    """Parse the real 3-file Elliptic layout with pandas (no header on features)."""
    import pandas as pd

    feats = pd.read_csv(data_dir / FEATURES_CSV, header=None)
    classes = pd.read_csv(data_dir / CLASSES_CSV)  # columns: txId,class

    # Column 0 is txId; the remaining columns are the 166 features (feature 0 =
    # time step). Join labels on txId, keep row order stable.
    feats = feats.rename(columns={0: "txId"})
    classes = classes.rename(columns={classes.columns[0]: "txId",
                                      classes.columns[1]: "class"})
    merged = feats.merge(classes, on="txId", how="left")

    raw_class = merged["class"].astype(str)
    labelled = raw_class.isin([_ILLICIT_RAW, _LICIT_RAW])
    n_total = len(merged)

    feat_cols = [c for c in feats.columns if c != "txId"]
    X = merged.loc[labelled, feat_cols].to_numpy(dtype=float)
    y = (raw_class[labelled] == _ILLICIT_RAW).to_numpy(dtype=int)

    return EllipticData(
        X=X, y=y, source="elliptic-csv", n_total=n_total,
        n_illicit=int(y.sum()), n_licit=int((y == 0).sum()),
    )


def synthetic_elliptic(
    n_licit: int = 4000, n_illicit: int = 400, seed: int = 42
) -> EllipticData:
    """Schema-accurate synthetic Elliptic sample (166 features).

    Licit rows ~ N(0, 1); illicit rows are a shifted/heavier cluster on a subset
    of features (the anomaly signal an Isolation Forest is meant to catch). This
    is a *stand-in for the real 200k CSVs* so the harness and tests run without
    the download — not a claim of real-data accuracy. Deterministic under ``seed``.
    """
    rng = np.random.default_rng(seed)
    licit = rng.normal(0.0, 1.0, size=(n_licit, N_FEATURES))
    # Illicit: shift + inflate variance on ~20 features so they sit in the tails.
    illicit = rng.normal(0.0, 1.0, size=(n_illicit, N_FEATURES))
    anomalous_cols = rng.choice(N_FEATURES, size=20, replace=False)
    illicit[:, anomalous_cols] += rng.normal(3.2, 1.0, size=(n_illicit, 20))
    illicit[:, anomalous_cols] *= 1.8

    X = np.vstack([licit, illicit])
    y = np.concatenate([np.zeros(n_licit, dtype=int), np.ones(n_illicit, dtype=int)])
    # Shuffle so class order carries no information.
    order = rng.permutation(len(y))
    return EllipticData(
        X=X[order], y=y[order], source="synthetic",
        n_total=len(y), n_illicit=int(n_illicit), n_licit=int(n_licit),
    )


# --------------------------------------------------------------------------- #
# Validation — the SAME Isolation Forest config TAKEDOWN scores wallets with
# --------------------------------------------------------------------------- #


def validate_isolation_forest(
    data: EllipticData, contamination: float = DEFAULT_CONTAMINATION, seed: int = 42
) -> EllipticValidationReport:
    """Fit an Isolation Forest and score its anomaly output against illicit labels.

    Mirrors ``scoring.iso_forest_scores``: unsupervised fit, ``-decision_function``
    as the anomaly score (higher = more anomalous). ROC-AUC uses the continuous
    anomaly score; precision/recall/F1 use the model's hard ``predict`` (-1 =
    outlier) at ``contamination``.
    """
    from app.takedown.scoring import MODEL_VERSION

    model = IsolationForest(contamination=contamination, random_state=seed)
    model.fit(data.X)

    anomaly_score = -model.decision_function(data.X)   # higher = more anomalous
    pred_illicit = (model.predict(data.X) == -1).astype(int)  # -1 = outlier

    roc = float(roc_auc_score(data.y, anomaly_score)) if data.n_illicit and data.n_licit else 0.0
    precision, recall, f1, _ = precision_recall_fscore_support(
        data.y, pred_illicit, average="binary", zero_division=0
    )
    tn, fp, fn, tp = confusion_matrix(data.y, pred_illicit, labels=[0, 1]).ravel()

    note = (
        "Synthetic schema-accurate sample (real CSVs absent - see "
        "fixtures/elliptic/README.md to run the full 203k-tx dataset)."
        if data.source == "synthetic"
        else "Real Elliptic Data Set."
    )
    return EllipticValidationReport(
        source=data.source,
        model_version=MODEL_VERSION,
        contamination=contamination,
        n_total=data.n_total,
        n_labelled=int(len(data.y)),
        n_illicit=data.n_illicit,
        n_licit=data.n_licit,
        roc_auc=round(roc, 4),
        precision=round(float(precision), 4),
        recall=round(float(recall), 4),
        f1=round(float(f1), 4),
        true_positives=int(tp),
        false_positives=int(fp),
        true_negatives=int(tn),
        false_negatives=int(fn),
        note=note,
    )


def run_validation(
    data_dir: str | os.PathLike | None = None,
    contamination: float = DEFAULT_CONTAMINATION,
) -> EllipticValidationReport:
    """Load (real or synthetic) → validate. The one call the CLI + endpoint use."""
    return validate_isolation_forest(load_elliptic(data_dir), contamination=contamination)


def _format_report(r: EllipticValidationReport) -> str:
    # ASCII-only (Windows cp1252 consoles choke on box-drawing chars).
    return "\n".join([
        "=== Elliptic Isolation-Forest validation ===",
        f"  source            {r.source}   ({r.note})",
        f"  model_version     {r.model_version}",
        f"  contamination     {r.contamination}",
        f"  rows (total)      {r.n_total:,}   labelled={r.n_labelled:,} "
        f"(illicit={r.n_illicit:,} licit={r.n_licit:,})",
        f"  ROC-AUC           {r.roc_auc:.4f}",
        f"  precision         {r.precision:.4f}",
        f"  recall            {r.recall:.4f}",
        f"  F1                {r.f1:.4f}",
        f"  confusion         TP={r.true_positives} FP={r.false_positives} "
        f"TN={r.true_negatives} FN={r.false_negatives}",
        "=" * 44,
    ])


if __name__ == "__main__":  # pragma: no cover - manual/CLI entrypoint
    print(_format_report(run_validation()))
