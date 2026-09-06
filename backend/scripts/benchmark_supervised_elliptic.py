"""Supervised RandomForest benchmark on the Elliptic dataset.

A *ceiling benchmark* that sits NEXT TO the unsupervised Isolation Forest number
in app/takedown/elliptic.py — it shows the Elliptic feature space is learnable
WHEN labels exist. It is NOT ITTU's production metric: production TAKEDOWN is
unsupervised (no labelled Indonesian crypto data), leaning on deterministic
typology detectors + honeypot-confirmed labels, with Isolation Forest as a
supporting input.

Standard Elliptic evaluation: temporal split (train time-step <=34, test >=35),
labelled rows only, illicit (class 1) as the positive class. Held-out — no leak.

Run:
    export ITTU_ELLIPTIC_DIR=/path/to/elliptic_bitcoin_dataset
    python scripts/benchmark_supervised_elliptic.py

Last measured (full dataset): ROC-AUC 0.9321 · precision 0.9818 · recall 0.6962
· F1 0.8147 (illicit, test set). See GET /api/takedown/model-card.
"""

import os

import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    classification_report,
    precision_recall_fscore_support,
    roc_auc_score,
)


def main() -> None:
    d = os.environ.get("ITTU_ELLIPTIC_DIR")
    if not d:
        raise SystemExit(
            "Set ITTU_ELLIPTIC_DIR to the folder with elliptic_txs_features.csv + "
            "elliptic_txs_classes.csv (Kaggle ellipticco/elliptic-data-set)."
        )

    feat = pd.read_csv(os.path.join(d, "elliptic_txs_features.csv"), header=None)
    cls = pd.read_csv(os.path.join(d, "elliptic_txs_classes.csv"))

    # features: col0 = txId, col1 = time_step, col2.. = 165 features
    feat = feat.rename(columns={0: "txId", 1: "time_step"})
    df = feat.merge(cls, left_on="txId", right_on=cls.columns[0])

    # keep labelled only; class "1"=illicit, "2"=licit (drop "unknown")
    df = df[df["class"].astype(str).isin(["1", "2"])].copy()
    df["y"] = (df["class"].astype(str) == "1").astype(int)  # 1 = illicit

    feature_cols = [c for c in feat.columns if c not in ("txId", "time_step")]
    train = df[df["time_step"] <= 34]
    test = df[df["time_step"] >= 35]

    clf = RandomForestClassifier(
        n_estimators=100, random_state=42, n_jobs=-1,
        class_weight="balanced_subsample",
    )
    clf.fit(train[feature_cols].values, train["y"].values)

    yte = test["y"].values
    proba = clf.predict_proba(test[feature_cols].values)[:, 1]
    pred = clf.predict(test[feature_cols].values)
    roc = roc_auc_score(yte, proba)
    p, r, f1, _ = precision_recall_fscore_support(
        yte, pred, average="binary", pos_label=1, zero_division=0
    )

    print("=== Supervised RandomForest — Elliptic (temporal split) ===")
    print(f"  train rows        {len(train):,}  (illicit={int(train['y'].sum()):,})")
    print(f"  test rows         {len(test):,}  (illicit={int(yte.sum()):,})")
    print(f"  features          {len(feature_cols)}")
    print("  split             time_step <=34 train | >=35 test")
    print(f"  ROC-AUC           {roc:.4f}")
    print(f"  precision(illicit){p:.4f}")
    print(f"  recall(illicit)   {r:.4f}")
    print(f"  F1(illicit)       {f1:.4f}")
    print("=" * 58)
    print(classification_report(yte, pred, target_names=["licit", "illicit"], digits=4))


if __name__ == "__main__":
    main()
