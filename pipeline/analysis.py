"""Descriptive and inferential trend analysis for one monthly series."""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats


def seasonal_strength(y: pd.Series) -> float:
    """Hyndman's seasonal strength F_s = max(0, 1 - Var(R)/Var(S+R)) from STL."""
    from statsmodels.tsa.seasonal import STL

    w = y.dropna().iloc[-360:]
    if len(w) < 48:
        return 0.0
    r = STL(w, period=12, robust=True).fit()
    return float(max(0.0, 1 - np.var(r.resid) / np.var(r.seasonal + r.resid)))


def ols_trend(y: pd.Series, start: str | None = None) -> dict:
    """Linear trend per decade with Newey-West (HAC, 12-month) standard errors.
    Seasonal cycles are removed with calendar-month dummies."""
    import statsmodels.api as sm

    w = y.loc[start:] if start else y
    w = w.dropna()
    t = np.array([(d.year - w.index[0].year) * 12 + (d.month - w.index[0].month) for d in w.index]) / 120.0
    dummies = pd.get_dummies(w.index.month, drop_first=True).astype(float).values
    X = sm.add_constant(np.column_stack([t, dummies]))
    fit = sm.OLS(w.values, X).fit(cov_type="HAC", cov_kwds={"maxlags": 12})
    slope, se = float(fit.params[1]), float(fit.bse[1])
    return {"period": f"{w.index[0]:%Y-%m} to {w.index[-1]:%Y-%m}", "per_decade": slope, "per_year": slope / 10,
            "se_per_decade": se, "ci95_per_decade": [slope - 1.96 * se, slope + 1.96 * se],
            "p_value": float(fit.pvalues[1]), "r2": float(fit.rsquared)}


def mann_kendall_sen(y: pd.Series, start: str | None = None) -> dict:
    """Mann-Kendall (via Kendall's tau on annual means) and Theil-Sen slope.
    Annual means remove seasonality and most serial correlation."""
    w = (y.loc[start:] if start else y).dropna()
    ann = w.groupby(w.index.year).agg(["mean", "count"])
    ann = ann[ann["count"] == 12]["mean"]
    if len(ann) < 8:
        return {}
    tau, p = stats.kendalltau(ann.index.values, ann.values)
    sen = stats.theilslopes(ann.values, ann.index.values)
    return {"years": f"{ann.index[0]}-{ann.index[-1]}", "kendall_tau": float(tau), "p_value": float(p),
            "sen_slope_per_year": float(sen.slope), "sen_ci95_per_year": [float(sen.low_slope), float(sen.high_slope)]}


def acceleration(y: pd.Series, years: int = 30) -> dict:
    """Compare the trend in the most recent 15 years with the 15 years before it."""
    w = y.dropna().iloc[-12 * years:]
    half = len(w) // 2
    a, b = ols_trend(w.iloc[:half]), ols_trend(w.iloc[half:])
    return {"earlier": a, "recent": b, "ratio": b["per_decade"] / a["per_decade"] if a["per_decade"] else None}


def stl_components(y: pd.Series, years: int = 30) -> dict | None:
    from statsmodels.tsa.seasonal import STL

    w = y.dropna().iloc[-12 * years:]
    if len(w) < 48:
        return None
    r = STL(w, period=12, robust=True).fit()
    resid = r.resid
    mad = np.median(np.abs(resid - np.median(resid))) * 1.4826
    z = (resid - np.median(resid)) / mad if mad > 0 else resid * 0
    return {"dates": w.index.strftime("%Y-%m").tolist(), "trend": np.round(r.trend.values, 5).tolist(),
            "seasonal": np.round(r.seasonal.values, 5).tolist(), "resid": np.round(resid.values, 5).tolist(),
            "robust_z": np.round(np.asarray(z), 3).tolist()}


def anomalies(y: pd.Series, comp: dict | None, years: int = 10, threshold: float = 3.0) -> list[dict]:
    """Months whose STL remainder is > threshold robust standard deviations."""
    if comp is None:
        return []
    out = []
    cutoff = (y.index[-1] - pd.DateOffset(years=years)).strftime("%Y-%m")
    for d, z, v in zip(comp["dates"], comp["robust_z"], comp["resid"]):
        if d >= cutoff and abs(z) >= threshold:
            out.append({"date": d, "robust_z": z, "remainder": v, "observed": float(y.loc[d + "-01"])})
    return out


def moving_averages(y: pd.Series) -> dict:
    ma12 = y.rolling(12, min_periods=12).mean()
    ma60 = y.rolling(60, min_periods=60, center=True).mean()
    return {"ma12": [None if np.isnan(v) else round(float(v), 5) for v in ma12.values],
            "ma60_centered": [None if np.isnan(v) else round(float(v), 5) for v in ma60.values]}


def year_over_year(y: pd.Series) -> dict:
    s = y.dropna()
    last = s.index[-1]
    same = last - pd.DateOffset(years=1)
    l12, p12 = s.iloc[-12:], s.iloc[-24:-12]
    return {
        "latest_month": last.strftime("%Y-%m"), "latest": float(s.iloc[-1]),
        "same_month_prior_year": float(s.loc[same]) if same in s.index else None,
        "change_vs_same_month": float(s.iloc[-1] - s.loc[same]) if same in s.index else None,
        "last12_mean": float(l12.mean()), "prior12_mean": float(p12.mean()),
        "last12_period": f"{l12.index[0]:%Y-%m} to {l12.index[-1]:%Y-%m}",
        "change_12m_mean": float(l12.mean() - p12.mean()),
        "record_rank_of_latest_month": int((s[s.index.month == last.month] > s.iloc[-1]).sum() + 1),
        "years_with_this_month": int((s.index.month == last.month).sum()),
    }


def baseline_stats(y: pd.Series, start="1991-01", end="2020-12") -> dict:
    w = y.loc[start:end].dropna()
    if len(w) < 120:
        w = y.dropna().iloc[:120]
    start, end = f"{w.index[0]:%Y-%m}", f"{w.index[-1]:%Y-%m}"
    ann = w.groupby(w.index.year).mean()
    resid = ann.values - np.polyval(np.polyfit(ann.index.values, ann.values, 1), ann.index.values)
    return {"period": f"{start} to {end}", "mean": float(w.mean()), "std_monthly": float(w.std()),
            "std_annual_mean": float(ann.std()),
            "interannual_sd_detrended": float(np.std(resid, ddof=2))}


def classify(trend: dict, mk: dict, seasonal_f: float) -> str:
    sig = trend["p_value"] < 0.05 and (not mk or mk.get("p_value", 1) < 0.05)
    direction = "increasing" if trend["per_decade"] > 0 else "decreasing"
    label = direction if sig else "no statistically significant trend"
    if seasonal_f > 0.6:
        label += " (strong seasonal cycle)"
    elif seasonal_f > 0.3:
        label += " (moderate seasonal cycle)"
    return label


def correlations(series: dict[str, pd.Series], start: int = 1993, end: int = 2025) -> dict:
    """Pearson correlation of annual means (levels) and of year-to-year changes.
    Level correlations between co-trending series are inflated by the shared
    trend; the first-difference correlations are the more informative ones."""
    ann = pd.DataFrame({k: s.groupby(s.index.year).mean() for k, s in series.items()}).loc[start:end].dropna(axis=1)
    lv = ann.corr()
    df = ann.diff().dropna().corr()
    keys = list(ann.columns)
    pairs = []
    n = len(ann)
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            r_l, r_d = float(lv.loc[a, b]), float(df.loc[a, b])
            t = r_d * np.sqrt((n - 3) / max(1e-9, 1 - r_d ** 2))
            p_d = float(2 * stats.t.sf(abs(t), n - 3))
            pairs.append({"a": a, "b": b, "r_levels": r_l, "r_differences": r_d, "p_differences": p_d})
    return {"years": f"{start}-{end}", "n_years": n, "keys": keys,
            "levels": np.round(lv.values, 3).tolist(), "differences": np.round(df.values, 3).tolist(),
            "pairs": pairs,
            "caveat": "Correlation is not causation. Annual-mean levels share long-term trends, which inflates level "
                      "correlations; correlations of year-to-year changes remove the shared trend but are noisier."}
