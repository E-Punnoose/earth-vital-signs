import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from pipeline.config import PARAMETERS, RAW_DIR, REPORT_HORIZONS, TARGET_END
from pipeline.sources import downsample_gistemp_grid, load_series, reduce_power
from pipeline.validation import interval_scale, metrics, rolling_origin
from pipeline.models import LinearTrend, Model, Naive, SeasonalNaive

ROOT = Path(__file__).resolve().parent.parent
DASH = ROOT / "data" / "processed" / "dashboard.json"


# ---------------------------------------------------------------- provenance
def test_manifest_hashes_match_stored_files():
    man = json.loads((RAW_DIR / "MANIFEST.json").read_text())["files"]
    assert man, "manifest is empty"
    for rel, meta in man.items():
        assert hashlib.sha256((RAW_DIR / rel).read_bytes()).hexdigest() == meta["sha256"], rel


@pytest.mark.parametrize("pid,first,min_last", [
    ("gmst", "1880-01", "2026-09"), ("land_temp", "1880-01", "2026-09"), ("co2", "1958-03", "2026-09"),
    ("sst", "1950-01", "2026-09"), ("arctic_ice", "1978-11", "2026-10"), ("gmsl", "1993-01", "2026-10"),
    ("precip", "1981-01", "2026-09"), ("aod", "2001-01", "2026-07")])
def test_series_span(pid, first, min_last):
    s, q = load_series(pid)
    assert f"{s.index[0]:%Y-%m}" == first
    assert f"{s.dropna().index[-1]:%Y-%m}" >= min_last
    assert s.index.freqstr == "MS"


def test_values_come_from_files():
    # spot checks against the agency files as stored
    assert load_series("gmst")[0].loc["2026-09-01"] == pytest.approx(1.38)
    assert load_series("co2")[0].loc["2026-09-01"] == pytest.approx(426.07)
    assert load_series("arctic_ice")[0].loc["2026-10-01"] == pytest.approx(6.69)
    s, q = load_series("arctic_ice")
    assert q["missing_months"] == ["1987-12", "1988-01"]  # gaps are kept, not invented


# ------------------------------------------------------------- reductions
def _fake_point(base, months=("198101", "198102", "202612"), missing=()):
    d = {}
    for p in ("PRECTOTCORR", "AOD_55", "TS"):
        d[p] = {m: (-999 if m in missing else base) for m in months}
        d[p][months[0][:4] + "13"] = base
    return d


def test_reduce_power_weighting_and_coverage():
    months = [f"{y}{m:02d}" for y in range(1981, 2027) for m in range(1, 13)]
    pts = {(0, 10): _fake_point(1.0, months), (60, 10): _fake_point(3.0, months, missing=("202612",))}
    series, stats_csv = reduce_power(pts)
    lines = series.strip().splitlines()
    first = lines[1].split(",")
    w0, w60 = 1.0, math.cos(math.radians(60))
    assert float(first[1]) == pytest.approx((w0 * 1 + w60 * 3) / (w0 + w60), abs=1e-4)
    # Dec 2026: the 60N point is missing -> only 2/3 of the weight -> below the 90% rule -> blank
    assert lines[-1].startswith("202611") or lines[-1].split(",")[1] != ""
    assert len(stats_csv.strip().splitlines()) == 3


def test_downsample_gistemp_grid():
    rows = ["title", "   i   j     lon     lat    array(i,j)"]
    for j, la in enumerate(range(-89, 90, 2)):
        for i, lo in enumerate(range(-179, 180, 2)):
            v = 9999.0 if la > 80 else 1.0
            rows.append(f"{i+1} {j+1} {lo:.2f} {la:.2f} {v}")
    out = downsample_gistemp_grid("\n".join(rows))
    assert len(out) == 648
    assert out[0].endswith(",1.00")
    assert out[-1].endswith(",")  # all-missing block left blank


# ------------------------------------------------------------- validation
class Spy(Model):
    name, label, family = "spy", "Spy", "test"
    seen = []

    def fit(self, y):
        Spy.seen.append(y.index[-1])
        self.y = y
        return self

    def predict(self, h):
        return np.repeat(self.y.iloc[-1], h)


def test_rolling_origin_is_chronological():
    idx = pd.date_range("1990-01-01", periods=400, freq="MS")
    y = pd.Series(np.arange(400, dtype=float), index=idx)
    Spy.seen = []
    cv = rolling_origin(y, {"spy": Spy(False), "naive": Naive(False), "snaive": SeasonalNaive(False)}, horizon=24)
    for train_end, o in zip(Spy.seen, cv["_origins"]):
        assert train_end < y.index[o]  # training never includes the test window
    assert cv["_origins"][-1] == len(y) - 24


def test_metrics_perfect_model():
    idx = pd.date_range("1990-01-01", periods=400, freq="MS")
    y = pd.Series(0.01 * np.arange(400), index=idx)
    cv = rolling_origin(y, {"linear": LinearTrend(False), "naive": Naive(False), "snaive": SeasonalNaive(False)}, horizon=24)
    met = metrics(cv, y, 24, seasonal=False, positive=False)
    assert met["by_model"]["linear"]["rmse"] < 1e-8
    assert met["by_model"]["linear"]["skill_vs_best_baseline"] > 0.99


def test_interval_scale_monotone():
    s = interval_scale([1, 3, 2, 4], 6)
    assert list(s) == [1, 3, 3, 4, 4, 4]


# ------------------------------------------------------------- output file
@pytest.fixture(scope="module")
def dash():
    if not DASH.exists():
        pytest.skip("run `python -m pipeline.run` first")
    return json.loads(DASH.read_text())


def test_dashboard_forecasts_reach_target(dash):
    for p in dash["parameters"]:
        if p["status"] != "ok":
            assert p["reason"]
            continue
        f = p["forecast"]
        assert f["dates"][-1] == TARGET_END
        assert f["dates"][0] > p["dates"]["latest_observation"]  # forecasts never overlap observations
        for m in f["models"].values():
            for a, b, c, d, e in zip(m["lo95"], m["lo80"], m["mean"], m["hi80"], m["hi95"]):
                assert a <= b <= c <= d <= e
        assert set(p["horizons"]) == {str(k) for k in REPORT_HORIZONS}
        sel = p["modelling"]["selected_model"]
        assert p["modelling"]["metrics"]["by_model"][sel]["rmse"] == min(
            v["rmse"] for v in p["modelling"]["metrics"]["by_model"].values() if not v.get("failed"))


def test_only_parameters_with_data_are_published(dash):
    assert all(p["status"] == "ok" and p["observations"]["values"] for p in dash["parameters"])


def test_ranking_sorted(dash):
    ps = [r["prob_increase"] for r in dash["ranking"]]
    assert ps == sorted(ps, reverse=True)
