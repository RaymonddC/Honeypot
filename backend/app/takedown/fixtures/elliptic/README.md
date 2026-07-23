# Elliptic Data Set — validation input for the TAKEDOWN Isolation Forest

The anomaly-detection validation harness (`app/takedown/elliptic.py`,
`scripts/validate_elliptic.py`) scores our production Isolation Forest against
the **Elliptic Data Set** — 203,769 Bitcoin transactions, 166 features each,
~46k labelled licit/illicit (Weber et al., 2019).

The full ~200k-row CSVs are **not committed** (size + dataset licence). Two ways
to run the harness:

### 1. Out-of-the-box (synthetic fallback)
With no real files present, the harness generates a **schema-accurate synthetic
sample** (identical 166-feature shape, a separable illicit cluster) so the
pipeline runs and is unit-tested end-to-end:

```sh
python -m app.takedown.elliptic
# or
python scripts/validate_elliptic.py
```

### 2. Full dataset (real accuracy numbers)
Download the three canonical files from Kaggle
(`ellipticco/elliptic-data-set`) and point the harness at them:

```
elliptic_txs_features.csv     # no header: txId, time_step, f1..f165
elliptic_txs_classes.csv      # header:    txId,class   (1=illicit, 2=licit, unknown)
elliptic_txs_edgelist.csv     # header:    txId1,txId2  (not needed for IF validation)
```

```sh
export ITTU_ELLIPTIC_DIR=/path/to/elliptic
python scripts/validate_elliptic.py        # same code path, full 203k rows
```

The `elliptic_sample/` folder holds a tiny **real-schema** 3-file sample
(synthetically generated, a few hundred rows) used only to exercise the CSV
loader in tests — it is *not* the real dataset.
