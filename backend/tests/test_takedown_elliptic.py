"""Elliptic Data Set validation harness for the TAKEDOWN Isolation Forest.

Exercises both load paths (synthetic fallback + the real 3-file CSV loader on a
vendored schema sample) and asserts the Isolation Forest actually separates the
illicit cluster. No network, no 200k download.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.takedown import elliptic
from tests.conftest import bearer

SAMPLE_DIR = (
    Path(__file__).resolve().parent.parent
    / "app" / "takedown" / "fixtures" / "elliptic" / "elliptic_sample"
)

client = TestClient(app)
client.headers.update(bearer())


def test_synthetic_sample_has_the_elliptic_schema():
    data = elliptic.synthetic_elliptic(n_licit=500, n_illicit=50, seed=1)
    assert data.source == "synthetic"
    assert data.X.shape[1] == elliptic.N_FEATURES == 166       # 166-feature schema
    assert data.X.shape[0] == data.y.shape[0] == 550
    assert data.n_illicit == 50 and data.n_licit == 500
    assert set(data.y.tolist()) == {0, 1}


def test_isolation_forest_separates_illicit_on_synthetic():
    report = elliptic.validate_isolation_forest(
        elliptic.synthetic_elliptic(seed=1)
    )
    # The IF must rank illicit as anomalous far better than chance.
    assert report.roc_auc >= 0.9
    assert report.precision >= 0.8                             # few false alarms
    assert report.true_positives > 0
    assert report.model_version.startswith("takedown-")
    assert "synthetic" in report.source


def test_real_schema_csv_loader():
    """The real 3-file Elliptic loader path, on the vendored schema sample."""
    assert SAMPLE_DIR.exists(), "vendored elliptic_sample missing"
    data = elliptic.load_elliptic(SAMPLE_DIR)
    assert data.source == "elliptic-csv"
    assert data.X.shape[1] == elliptic.N_FEATURES
    # 'unknown' rows are dropped from the labelled set, but counted in n_total.
    assert data.n_total > data.n_illicit + data.n_licit
    assert data.n_illicit > 0 and data.n_licit > 0

    report = elliptic.validate_isolation_forest(data)
    assert report.source == "elliptic-csv"
    assert report.roc_auc >= 0.9


def test_load_elliptic_defaults_to_synthetic_when_no_real_files(monkeypatch):
    monkeypatch.delenv("ITTU_ELLIPTIC_DIR", raising=False)
    data = elliptic.load_elliptic()   # no real CSVs at FIXTURES_DIR root
    assert data.source == "synthetic"


def test_env_var_selects_real_csv_dir(monkeypatch):
    monkeypatch.setenv("ITTU_ELLIPTIC_DIR", str(SAMPLE_DIR))
    data = elliptic.load_elliptic()
    assert data.source == "elliptic-csv"


def test_run_validation_is_reproducible():
    a = elliptic.run_validation()
    b = elliptic.run_validation()
    assert a.roc_auc == b.roc_auc and a.f1 == b.f1            # deterministic


def test_model_card_endpoint_reports_elliptic_metrics():
    r = client.get("/api/takedown/model-card")
    assert r.status_code == 200, r.text
    card = r.json()
    assert card["unsupervised"] is True
    assert card["n_features"] == 12                            # canonical count
    assert len(card["features"]) == 13                         # volume split total/mean
    assert len(card["typology_detectors"]) == 5
    val = card["elliptic_validation"]
    assert val["roc_auc"] >= 0.9
    assert val["n_illicit"] > 0 and val["n_licit"] > 0
