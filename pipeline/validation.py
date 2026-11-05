"""Out-of-sample validation, model selection and prediction intervals.

* Rolling-origin (expanding window) evaluation: the training set always ends
  before the test window; origins are spaced ``step`` months apart and the most
  recent origin leaves exactly ``horizon`` months for testing. No random splits.
* Metrics per model: MAE, RMSE, MAPE (only for strictly positive physical
  quantities), MASE against the seasonal-naive / naive baseline, bias and skill
  versus the best baseline.
* Selection: lowest mean RMSE over horizons 1..H.
* Intervals: horizon-specific RMSE of the selected model's own out-of-sample
  errors (made non-decreasing with horizon), used as a Gaussian scale for 80%
  and 95% intervals. Empirical coverage of these intervals in the backtest is
  reported so users can see whether they are honest.
* Residual diagnostics: one-step-ahead walk-forward errors over the last 36
  months (model re-fitted each month), Ljung-Box and Shapiro-Wilk tests.
"""
from __future__ import annotations

import copy
import logging

import numpy as np
import pandas as pd
from scipy import stats

from .models import BASELINES, SARIMA

log = logging.getLogger("pipeline.validation")

Z80, Z95 = 1.2816, 1.96


def fill_for_modelling(y: pd.Series) -> tuple[pd.Series, list[str]]:
    filled = y.index[y.isna()].strftime("%Y-%m").tolist()
    return y.interpolate(limit_direction="both"), filled


def _make(proto):
    m = copy.copy(proto)
    return m


def rolling_origin(y: pd.Series, protos: dict, horizon: int, n_origins: int = 20, step: int = 6,
                   min_train: int = 120) -> dict:
    n = len(y)
    last_origin = n - horizon
    origins = [last_origin - step * k for k in range(n_origins)]
    origins = sorted(o for o in origins if o >= min_train)
    out = {name: {"errors": [], "preds": [], "origins": []} for name in protos}
    for o in origins:
        train, test = y.iloc[:o], y.iloc[o:o + horizon].values
        for name, proto in protos.items():
            try:
                m = _make(proto).fit(train)
                p = m.predict(horizon)
                if not np.all(np.isfinite(p)):
                    raise ValueError("non-finite forecast")
            except Exception as exc:  # noqa: BLE001
                log.warning("%s failed at origin %s: %s", name, y.index[o].date(), exc)
                p = np.full(horizon, np.nan)
            out[name]["errors"].append(p - test)
            out[name]["preds"].append(p)
            out[name]["origins"].append(y.index[o].strftime("%Y-%m"))
    for name in out:
        out[name]["errors"] = np.array(out[name]["errors"])
        out[name]["preds"] = np.array(out[name]["preds"])
    out["_origins"] = origins
    return out


def metrics(cv: dict, y: pd.Series, horizon: int, seasonal: bool, positive: bool) -> dict:
    origins = cv["_origins"]
    actual = np.array([y.iloc[o:o + horizon].values for o in origins])
    base_name = "snaive" if seasonal else "naive"
    base_mae = np.nanmean(np.abs(cv[base_name]["errors"]))
    res = {}
    for name, d in cv.items():
        if name.startswith("_"):
            continue
        e = d["errors"]
        ok = np.isfinite(e).all(axis=1)
        if ok.sum() < max(3, len(origins) // 2):
            res[name] = {"failed": True}
            continue
        e = e[ok]
        rmse_h = np.sqrt(np.mean(e ** 2, axis=0))
        r = {
            "mae": float(np.mean(np.abs(e))),
            "rmse": float(np.sqrt(np.mean(e ** 2))),
            "bias": float(np.mean(e)),
            "mase": float(np.mean(np.abs(e)) / base_mae) if base_mae > 0 else None,
            "rmse_by_horizon": [float(x) for x in rmse_h],
            "mae_by_horizon": [float(x) for x in np.mean(np.abs(e), axis=0)],
            "n_origins": int(ok.sum()),
        }
        if positive:
            r["mape"] = float(np.mean(np.abs(e) / np.abs(actual[ok])) * 100)
        # error of the forecast 12-month mean over months 13-24 (or last 12 of the horizon)
        k0 = max(0, horizon - 12)
        r["annual_mean_rmse"] = float(np.sqrt(np.mean(np.mean(e[:, k0:], axis=1) ** 2)))
        res[name] = r
    baselines = [n for n in res if n in BASELINES and not res[n].get("failed")]
    best_base = min(baselines, key=lambda n: res[n]["rmse"])
    for n, r in res.items():
        if not r.get("failed"):
            r["skill_vs_best_baseline"] = float(1 - r["rmse"] / res[best_base]["rmse"])
    return {"by_model": res, "best_baseline": best_base}


def select(met: dict) -> str:
    ok = {n: r for n, r in met["by_model"].items() if not r.get("failed")}
    return min(ok, key=lambda n: (ok[n]["rmse"], n in BASELINES))


def interval_scale(rmse_h: list[float], H: int) -> np.ndarray:
    s = np.maximum.accumulate(np.asarray(rmse_h, dtype=float))
    if len(s) < H:
        s = np.r_[s, np.repeat(s[-1], H - len(s))]
    return s[:H]


def coverage(cv: dict, name: str, y: pd.Series, horizon: int, scale: np.ndarray) -> dict:
    e = cv[name]["errors"]
    e = e[np.isfinite(e).all(axis=1)]
    c80 = float(np.mean(np.abs(e) <= Z80 * scale[None, :horizon]))
    c95 = float(np.mean(np.abs(e) <= Z95 * scale[None, :horizon]))
    return {"empirical_80": c80, "empirical_95": c95,
            "note": "In-sample to the validation folds (the same errors set the interval width), so this checks "
                    "calibration shape rather than giving an independent test."}


def walk_forward_residuals(y: pd.Series, proto, months: int = 36) -> dict:
    errs, dates = [], []
    for o in range(len(y) - months, len(y)):
        try:
            p = _make(proto).fit(y.iloc[:o]).predict(1)[0]
            errs.append(float(p - y.iloc[o]))
            dates.append(y.index[o].strftime("%Y-%m"))
        except Exception:  # noqa: BLE001
            continue
    e = np.array(errs)
    out = {"dates": dates, "errors": [round(x, 5) for x in errs], "n": len(e)}
    if len(e) >= 12:
        from statsmodels.stats.diagnostic import acorr_ljungbox

        lb = acorr_ljungbox(e, lags=[6, 12], return_df=True)
        out["mean_error"] = float(e.mean())
        out["std_error"] = float(e.std(ddof=1))
        out["one_step_mae"] = float(np.abs(e).mean())
        out["ljung_box_p_lag6"] = float(lb["lb_pvalue"].iloc[0])
        out["ljung_box_p_lag12"] = float(lb["lb_pvalue"].iloc[1])
        out["shapiro_p"] = float(stats.shapiro(e).pvalue)
        out["t_test_bias_p"] = float(stats.ttest_1samp(e, 0).pvalue)
        out["interpretation"] = _interpret_resid(out)
    return out


def _interpret_resid(r: dict) -> str:
    parts = []
    parts.append("no significant autocorrelation left in one-step errors (Ljung-Box p > 0.05)"
                 if r["ljung_box_p_lag12"] > 0.05 else
                 "one-step errors remain autocorrelated (Ljung-Box p <= 0.05): the model misses some persistent structure, so intervals may be optimistic")
    parts.append("no significant bias" if r["t_test_bias_p"] > 0.05 else
                 f"systematic bias of {r['mean_error']:+.3g} per month (t-test p <= 0.05)")
    parts.append("errors consistent with normality" if r["shapiro_p"] > 0.05 else "errors are non-normal (heavy tails or skew)")
    return "; ".join(parts) + "."


def build_protos(classes, y: pd.Series, seasonal: bool) -> dict:
    protos = {}
    for cls in classes:
        if cls is SARIMA:
            try:
                protos[cls.name] = SARIMA.select(y, seasonal)
            except Exception as exc:  # noqa: BLE001
                log.warning("SARIMA selection failed: %s", exc)
            continue
        protos[cls.name] = cls(seasonal)
    return protos
