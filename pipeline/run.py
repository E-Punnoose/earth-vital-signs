"""Pipeline entry point.

    python -m pipeline.run            # use stored raw files (offline / CI fallback)
    python -m pipeline.run --fetch    # refresh raw files from the agencies first

Writes data/processed/dashboard.json, which both the FastAPI backend and the
static dashboard read.
"""
from __future__ import annotations

import argparse
import copy
import json
import logging
import math
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from scipy import stats

from . import analysis as A
from .config import PARAMETERS, PROCESSED_DIR, RAW_DIR, REFERENCE_MONTH, REPORT_HORIZONS, TARGET_END, TARGET_START
from .models import BASELINES, MODEL_CLASSES, NOT_USED
from .sources import fetch_all, load_manifest, load_series
from .validation import (Z80, Z95, build_protos, coverage, fill_for_modelling, interval_scale, metrics,
                         rolling_origin, select, walk_forward_residuals)

log = logging.getLogger("pipeline")
PIPELINE_VERSION = "1.0.0"
POSITIVE_QUANTITIES = {"co2", "arctic_ice", "precip", "aod"}
# Anomaly series already have the mean seasonal cycle removed; describing them as "seasonal" would mislead.
ANOMALY_SERIES = {"gmst", "sst", "land_temp"}


def _r(x, d=5):
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return None
    return round(float(x), d)


def months_between(a: pd.Timestamp, b: str) -> int:
    bt = pd.Timestamp(b + "-01")
    return (bt.year - a.year) * 12 + (bt.month - a.month)


def likelihood_label(p: float) -> str:
    if p >= 0.99:
        return "Virtually certain to increase"
    if p >= 0.90:
        return "Very likely to increase"
    if p >= 0.66:
        return "Likely to increase"
    if p > 0.33:
        return "About as likely as not"
    if p > 0.10:
        return "Likely to decrease"
    if p > 0.01:
        return "Very likely to decrease"
    return "Virtually certain to decrease"


def process_parameter(pid: str) -> dict:
    t0 = time.time()
    P = PARAMETERS[pid]
    y, quality = load_series(pid)
    obs = y.dropna()
    last = obs.index[-1]
    fit_y = y.loc[P.fit_start:] if P.fit_start else y
    fit_y, filled = fill_for_modelling(fit_y.loc[: last])
    quality["filled_for_modelling"] = filled

    # ---------------- descriptive analysis ----------------
    fs = A.seasonal_strength(obs)
    seasonal = fs > 0.3
    trend_full = A.ols_trend(obs)
    trend_30 = A.ols_trend(obs.iloc[-360:])
    mk_full = A.mann_kendall_sen(obs)
    mk_30 = A.mann_kendall_sen(obs.iloc[-360:])
    comp = A.stl_components(obs)
    an = {
        "seasonal_strength": fs,
        "seasonal": seasonal,
        "classification": A.classify(trend_30, mk_30, 0.0 if pid in ANOMALY_SERIES else fs),
        "trend_full_record": trend_full,
        "trend_last_30y": trend_30,
        "mann_kendall_full": mk_full,
        "mann_kendall_last_30y": mk_30,
        "acceleration": A.acceleration(obs),
        "year_over_year": A.year_over_year(obs),
        "baseline_1991_2020": A.baseline_stats(obs),
        "moving_averages": A.moving_averages(y),
        "stl": comp,
        "anomalies_last_10y": A.anomalies(obs, comp),
    }

    # ---------------- modelling ----------------
    H = months_between(last, TARGET_END)
    protos = build_protos(MODEL_CLASSES, fit_y, seasonal)
    cv = rolling_origin(fit_y, protos, horizon=H, n_origins=20, step=6)
    met = metrics(cv, fit_y, H, seasonal, pid in POSITIVE_QUANTITIES)
    best = select(met)
    fdates = pd.date_range(last + pd.offsets.MonthBegin(1), periods=H, freq="MS")

    forecasts, backtests = {}, {}
    actual_bt = fit_y.iloc[-H:]
    for name, proto in protos.items():
        mres = met["by_model"].get(name, {})
        if mres.get("failed"):
            continue
        try:
            m = copy.copy(proto).fit(fit_y)
            mean = m.predict(H)
        except Exception as exc:  # noqa: BLE001
            log.warning("%s/%s final fit failed: %s", pid, name, exc)
            continue
        sc = interval_scale(mres["rmse_by_horizon"], H)
        forecasts[name] = {
            "mean": [_r(v) for v in mean],
            "lo80": [_r(v) for v in mean - Z80 * sc], "hi80": [_r(v) for v in mean + Z80 * sc],
            "lo95": [_r(v) for v in mean - Z95 * sc], "hi95": [_r(v) for v in mean + Z95 * sc],
        }
        bt = cv[name]["preds"][-1]
        backtests[name] = {"origin": cv[name]["origins"][-1], "predicted": [_r(v) for v in bt]}

    sel = forecasts[best]
    sc_best = interval_scale(met["by_model"][best]["rmse_by_horizon"], H)
    cov = coverage(cv, best, fit_y, H, sc_best)
    resid = walk_forward_residuals(fit_y, protos[best], months=36)

    # horizon table (calendar months counted from the October 2026 reference)
    horizons = {}
    for k, ym in REPORT_HORIZONS.items():
        i = list(fdates.strftime("%Y-%m")).index(ym)
        horizons[str(k)] = {"date": ym, "steps_ahead_of_last_obs": i + 1, "mean": sel["mean"][i],
                            "lo80": sel["lo80"][i], "hi80": sel["hi80"][i], "lo95": sel["lo95"][i], "hi95": sel["hi95"][i]}

    # ---------------- ranking metrics ----------------
    last12 = obs.iloc[-12:]
    tgt_last12 = [i for i, d in enumerate(fdates.strftime("%Y-%m")) if "2027-11" <= d <= TARGET_END]
    f_mean_final_year = float(np.mean([sel["mean"][i] for i in tgt_last12]))
    delta = f_mean_final_year - float(last12.mean())
    sigma = met["by_model"][best]["annual_mean_rmse"]
    p_inc = float(stats.norm.cdf(delta / sigma)) if sigma > 0 else float(delta > 0)
    ivar = an["baseline_1991_2020"]["interannual_sd_detrended"]
    rank = {
        "last12_obs_mean": float(last12.mean()),
        "last12_obs_period": f"{last12.index[0]:%Y-%m} to {last12.index[-1]:%Y-%m}",
        "forecast_mean_nov2027_oct2028": f_mean_final_year,
        "projected_change": delta,
        "projected_change_sigma": sigma,
        "projected_change_ci95": [delta - 1.96 * sigma, delta + 1.96 * sigma],
        "prob_increase": p_inc,
        "likelihood": likelihood_label(p_inc),
        "standardized_change": delta / ivar if ivar > 0 else None,
        "percent_change": 100 * delta / float(last12.mean()) if pid in POSITIVE_QUANTITIES else None,
        "trend_implied_2y_change": 2 * trend_30["per_year"],
    }

    # ---------------- assemble ----------------
    src = P.source
    man = load_manifest()["files"]
    files = {f: man.get(f, {}) for f in src.raw_files}
    out = {
        "id": pid, "name": P.name, "short": P.short, "unit": P.unit, "status": "ok",
        "concern_direction": P.concern_direction, "decimals": P.value_decimals, "tags": P.tags,
        "limitations": P.limitations, "description": P.description,
        "source": {**src.__dict__, "files": files},
        "dates": {
            "first_observation": f"{obs.index[0]:%Y-%m}",
            "latest_observation": f"{last:%Y-%m}",
            "reference_month": REFERENCE_MONTH,
            "reference_month_available": f"{last:%Y-%m}" >= REFERENCE_MONTH,
            "months_behind_reference": max(0, months_between(last, REFERENCE_MONTH)),
            "dataset_published": next((v.get("source_published") for v in files.values() if v.get("source_published")), None),
            "retrieved_utc": max((v.get("retrieved_utc", "") for v in files.values()), default=None),
            "forecast_issued": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "forecast_start": f"{fdates[0]:%Y-%m}", "forecast_end": f"{fdates[-1]:%Y-%m}",
        },
        "quality": quality,
        "latest": {"date": f"{last:%Y-%m}", "value": float(obs.iloc[-1])},
        "observations": {"dates": y.index.strftime("%Y-%m").tolist(), "values": [_r(v) for v in y.values]},
        "analysis": an,
        "modelling": {
            "fit_start": f"{fit_y.index[0]:%Y-%m}", "horizon_months": H, "seasonal_models": seasonal,
            "validation": {"scheme": "rolling-origin, expanding window", "n_origins": len(cv["_origins"]),
                           "origin_spacing_months": 6, "origins": [f"{fit_y.index[o]:%Y-%m}" for o in cv["_origins"]],
                           "horizon_months": H},
            "metrics": met, "selected_model": best, "selected_is_baseline": best in BASELINES,
            "models": {n: {"label": p.label, "family": p.family, "description": p.description,
                           **({"spec": p.spec, "selection": getattr(p, "selection", None)} if n == "sarima" else {})}
                       for n, p in protos.items()},
            "not_used": NOT_USED,
            "interval_method": "Gaussian intervals scaled by the selected model's horizon-specific out-of-sample RMSE (made non-decreasing with horizon).",
            "interval_coverage_check": cov,
            "residuals": resid,
        },
        "forecast": {"dates": fdates.strftime("%Y-%m").tolist(), "selected": best, "models": forecasts},
        "backtest": {"dates": actual_bt.index.strftime("%Y-%m").tolist(), "actual": [_r(v) for v in actual_bt.values],
                     "models": backtests},
        "horizons": horizons,
        "ranking": rank,
        "runtime_s": round(time.time() - t0, 1),
    }
    log.info("%s done in %.1fs - selected %s", pid, out["runtime_s"], best)
    return out


def unavailable(pid: str) -> dict:
    P = PARAMETERS[pid]
    return {"id": pid, "name": P.name, "short": P.short, "unit": P.unit, "status": "unavailable",
            "reason": P.unavailable_reason, "source": P.source.__dict__, "tags": P.tags}


# -------------------------------------------------------------------------
# Regional / map products and insights
# -------------------------------------------------------------------------
def map_products() -> dict:
    g = pd.read_csv(RAW_DIR / "gistemp/map_10deg.csv")
    z = pd.read_csv(RAW_DIR / "gistemp/zonal_2deg.csv")
    p = pd.read_csv(RAW_DIR / "nasa_power/grid20_point_stats.csv")
    acol, tcol = g.columns[2], g.columns[3]
    zc = z.columns
    w = np.cos(np.radians(z["lat"]))

    def band(lo, hi, col):
        m = (z["lat"] >= lo) & (z["lat"] <= hi) & z[col].notna()
        return float(np.average(z.loc[m, col], weights=w[m]))

    regions = {
        "arctic_64_90N": {"change_1981_2025": band(64, 90, zc[2]), "latest_quarter_anom": band(64, 90, zc[1])},
        "nh_midlat_24_64N": {"change_1981_2025": band(24, 64, zc[2]), "latest_quarter_anom": band(24, 64, zc[1])},
        "tropics_24S_24N": {"change_1981_2025": band(-24, 24, zc[2]), "latest_quarter_anom": band(-24, 24, zc[1])},
        "sh_midlat_64_24S": {"change_1981_2025": band(-64, -24, zc[2]), "latest_quarter_anom": band(-64, -24, zc[1])},
        "antarctic_90_64S": {"change_1981_2025": band(-90, -64, zc[2]), "latest_quarter_anom": band(-90, -64, zc[1])},
        "global": {"change_1981_2025": band(-90, 90, zc[2]), "latest_quarter_anom": band(-90, 90, zc[1])},
    }
    return {
        "gistemp_grid": {"columns": ["lat", "lon", "anom", "change"], "anom_label": acol, "change_label": tcol,
                         "cells": [[int(a), int(b), _r(c, 2), _r(d, 2)] for a, b, c, d in g.itertuples(index=False, name=None)],
                         "cell_size_deg": 10, "source": "NASA GISTEMP v4 (GHCNv4 + ERSSTv5, 1200 km smoothing), 2x2 degree grid averaged to 10x10 degree blocks (cos-latitude weighted; blocks with fewer than 13 valid 2-degree cells left blank)."},
        "gistemp_zonal": {"lat": z["lat"].tolist(), "anom": [_r(v, 3) for v in z[zc[1]]], "change": [_r(v, 3) for v in z[zc[2]]],
                          "anom_label": zc[1], "change_label": zc[2]},
        "regions": regions,
        "power_points": {"columns": list(p.columns), "rows": [[_r(v, 4) if isinstance(v, float) else v for v in row]
                                                               for row in p.itertuples(index=False, name=None)],
                         "source": "NASA POWER monthly point API (MERRA-2), 126 grid points."},
    }


def make_insights(params: list[dict], maps: dict, corr: dict) -> list[dict]:
    ok = [p for p in params if p["status"] == "ok"]
    by = {p["id"]: p for p in ok}
    ins = []
    def nm(p):
        s = p["short"]
        proper = s.split()[0] in {"Arctic", "Antarctic"}
        return s[0].lower() + s[1:] if len(s) > 1 and s[0].isupper() and s[1].islower() and not proper else s

    def pc(x):
        return f"{x*100:.1f}%" if x >= 0.995 or x <= 0.005 else f"{x*100:.0f}%"

    def listing(ps, with_p=True):
        items = [f"{nm(p)} ({pc(p['ranking']['prob_increase'])})" if with_p else nm(p) for p in ps]
        return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]

    P = lambda p: p["ranking"]["prob_increase"]
    vc = sorted([p for p in ok if P(p) >= 0.9], key=lambda p: -P(p))
    lk = sorted([p for p in ok if 0.66 <= P(p) < 0.9], key=lambda p: -P(p))
    un = [p for p in ok if 0.33 < P(p) < 0.66]
    dec = [p for p in ok if P(p) <= 0.33]
    if vc:
        ins.append({"kind": "increasing", "title": "Very likely to be higher by 2028",
                    "text": "The validated forecasts give at least a 90% chance that the November 2027 – October 2028 average will exceed "
                            f"the latest 12 months for {listing(vc)}."})
    if lk:
        ins.append({"kind": "likely", "title": "Likely, but not certain, to be higher",
                    "text": f"{listing(lk)[0].upper() + listing(lk)[1:]}: more likely than not to rise, with probabilities between 66% and 90%. "
                            "Year-to-year variability is large enough that a lower two-year average remains possible."})
    if dec:
        parts = []
        for p in dec:
            trend_sig = not p["analysis"]["classification"].startswith("no statistically")
            why = ("consistent with its significant long-term downward trend" if trend_sig and p["analysis"]["trend_last_30y"]["per_decade"] < 0
                   else "an expected return toward normal after an unusually high recent 12 months, not a long-term decline "
                        "(its 30-year trend is not statistically significant)")
            parts.append(f"{nm(p)} ({pc(P(p))} chance of an increase) is projected lower: {why}")
        ins.append({"kind": "decreasing", "title": "Projected to be lower", "text": "; ".join(parts)[0].upper() + "; ".join(parts)[1:] + "."})
    if un:
        ins.append({"kind": "uncertain", "title": "No clear direction over two years",
                    "text": f"For {listing(un)}, the projected change is small compared with year-to-year variability and forecast error. "
                            "Their long-term records still show: " + "; ".join(f"{nm(p)} {p['analysis']['classification'].split(' (')[0]}" for p in un)
                            + ". A clear long-term trend can coexist with an uncertain two-year outlook."})
    if "co2" in by:
        c = by["co2"]
        ins.append({"kind": "detail", "title": "CO₂ growth is the most predictable signal",
                    "text": f"Mauna Loa CO₂ averaged {c['ranking']['last12_obs_mean']:.1f} ppm over {c['ranking']['last12_obs_period']}. "
                            f"The selected model ({c['modelling']['models'][c['modelling']['selected_model']]['label']}) projects "
                            f"{c['ranking']['forecast_mean_nov2027_oct2028']:.1f} ppm for Nov 2027-Oct 2028 "
                            f"(95% interval {c['ranking']['projected_change_ci95'][0]:+.1f} to {c['ranking']['projected_change_ci95'][1]:+.1f} ppm change). "
                            f"The 30-year trend is {c['analysis']['trend_last_30y']['per_decade']:.1f} ppm per decade and the recent 15-year rate is "
                            f"{c['analysis']['acceleration']['recent']['per_decade']:.1f} ppm per decade versus {c['analysis']['acceleration']['earlier']['per_decade']:.1f} before."})
    if "gmsl" in by:
        s = by["gmsl"]
        a = s["analysis"]["acceleration"]
        ins.append({"kind": "detail", "title": "Sea-level rise has accelerated",
                    "text": f"Satellite altimetry shows global mean sea level rising {a['recent']['per_decade']/10:.1f} mm/yr over {a['recent']['period']} "
                            f"compared with {a['earlier']['per_decade']/10:.1f} mm/yr over {a['earlier']['period']}. "
                            f"The projected change in the annual mean to Nov 2027-Oct 2028 is {s['ranking']['projected_change']:+.1f} mm "
                            f"(95% interval {s['ranking']['projected_change_ci95'][0]:+.1f} to {s['ranking']['projected_change_ci95'][1]:+.1f})."})
    if "gmst" in by:
        g = by["gmst"]
        yy = g["analysis"]["year_over_year"]
        ins.append({"kind": "detail", "title": "Global temperature: high level, but year-to-year swings dominate a 2-year outlook",
                    "text": f"GISTEMP's latest monthly anomaly is {g['latest']['value']:+.2f} °C ({g['latest']['date']}, vs 1951-1980), ranked "
                            f"#{yy['record_rank_of_latest_month']} of {yy['years_with_this_month']} for that calendar month. The 30-year trend is "
                            f"{g['analysis']['trend_last_30y']['per_decade']:+.2f} °C/decade, but over two years ENSO-driven variability "
                            f"(not modelled explicitly) is comparable in size, which is why the interval is wide."})
    if "arctic_ice" in by:
        a = by["arctic_ice"]
        sep = pd.Series(a["observations"]["values"], index=pd.to_datetime([d + "-01" for d in a["observations"]["dates"]]))
        sep = sep[sep.index.month == 9].dropna()
        lowest = sep.nsmallest(3)
        ins.append({"kind": "detail", "title": "Arctic sea ice continues its long decline, with large variability",
                    "text": f"The 30-year trend in monthly extent is {a['analysis']['trend_last_30y']['per_decade']:+.2f} million km² per decade. "
                            f"September 2026 extent was {float(sep.iloc[-1]):.2f} million km²; the three lowest Septembers on record are "
                            + ", ".join(f"{d.year} ({v:.2f})" for d, v in lowest.items()) + "."})
    r = maps["regions"]
    ins.append({"kind": "regional", "title": "Where warming is strongest",
                "text": f"In GISTEMP's 1981-2025 change map the Arctic (64-90°N) warmed {r['arctic_64_90N']['change_1981_2025']:.2f} °C versus "
                        f"{r['global']['change_1981_2025']:.2f} °C for the globe (about {r['arctic_64_90N']['change_1981_2025']/r['global']['change_1981_2025']:.1f}×). "
                        f"Northern mid-latitudes (24-64°N) warmed {r['nh_midlat_24_64N']['change_1981_2025']:.2f} °C, the tropics "
                        f"{r['tropics_24S_24N']['change_1981_2025']:.2f} °C and the Southern Ocean belt (64-24°S) only "
                        f"{r['sh_midlat_64_24S']['change_1981_2025']:.2f} °C."})
    sig = [x for x in corr["pairs"] if x["p_differences"] < 0.05]
    if sig:
        top = sorted(sig, key=lambda x: -abs(x["r_differences"]))[:3]
        ins.append({"kind": "correlation", "title": "Co-variability (not causation)",
                    "text": "After removing shared trends (year-to-year differences, " + corr["years"] + "), the strongest statistically significant "
                            "associations are: " + "; ".join(f"{by[x['a']]['short']} & {by[x['b']]['short']} r = {x['r_differences']:+.2f}" for x in top)
                            + ". These reflect shared physical drivers (e.g. ENSO) or measurement overlap and do not by themselves establish cause."})
    ins.append({"kind": "uncertainty", "title": "What the uncertainty bands mean",
                "text": "Intervals come from each model's own errors when it was repeatedly re-trained on past data and asked to forecast the "
                        "following months (20 rolling origins). They capture typical forecast error, not structural surprises such as a major "
                        "volcanic eruption, a step change in emissions, or an instrument change."})
    ins.append({"kind": "why", "title": "Why these trends matter",
                "text": "Rising CO₂ is the dominant driver of the long-term warming seen in the temperature records (an attribution established "
                        "by physical climate science, not by the correlations computed here). Warmer oceans and melting land ice raise sea level, "
                        "which compounds coastal flooding; Arctic sea-ice loss reduces surface reflectivity and amplifies regional warming."})
    import re as _re
    mon = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    nice = lambda m: f"{mon[int(m.group(2)) - 1]} {m.group(1)}"
    for i in ins:  # readable month names in generated prose ("2025-10 to 2026-09" -> "Oct 2025 – Sep 2026")
        txt = _re.sub(r"(?<!\d)(\d{4})-(\d{2})(?!\d)", nice, i["text"])
        i["text"] = _re.sub(r"([A-Z][a-z]{2} \d{4}) to ([A-Z][a-z]{2} \d{4})", r"\1 – \2", txt)
    return ins


def run(fetch: bool = False, workers: int = 4) -> dict:
    t0 = time.time()
    fetch_status = fetch_all() if fetch else {}
    ids = [p for p in PARAMETERS if PARAMETERS[p].status == "ok"]
    with ProcessPoolExecutor(max_workers=workers) as ex:
        results = dict(zip(ids, ex.map(process_parameter, ids)))
    params = [results.get(pid) or unavailable(pid) for pid in PARAMETERS]
    ok = [p for p in params if p["status"] == "ok"]
    ranking = sorted(ok, key=lambda p: (-p["ranking"]["prob_increase"], -(p["ranking"]["standardized_change"] or 0)))
    corr_series = {pid: load_series(pid)[0].dropna() for pid in ["gmst", "co2", "sst", "gmsl", "arctic_ice", "precip", "land_temp"]}
    corr = A.correlations(corr_series)
    maps = map_products()
    out = {
        "meta": {
            "title": "Global Environmental Monitoring and Predictive Analytics Dashboard",
            "pipeline_version": PIPELINE_VERSION,
            "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "reference_month": REFERENCE_MONTH, "target_window": [TARGET_START, TARGET_END],
            "report_horizons": REPORT_HORIZONS,
            "fetch_status": fetch_status,
            "manifest": load_manifest(),
            "runtime_s": round(time.time() - t0, 1),
        },
        "parameters": params,
        "ranking": [{"id": p["id"], "short": p["short"], "unit": p["unit"], **p["ranking"],
                     "selected_model": p["modelling"]["selected_model"]} for p in ranking],
        "correlations": corr,
        "maps": maps,
    }
    out["insights"] = make_insights(params, maps, corr)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    path = PROCESSED_DIR / "dashboard.json"
    path.write_text(json.dumps(out, separators=(",", ":"), allow_nan=False))
    log.info("wrote %s (%.0f kB) in %.1fs", path, path.stat().st_size / 1024, time.time() - t0)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true", help="refresh raw files from the agencies first")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    run(fetch=a.fetch, workers=a.workers)
    return 0


if __name__ == "__main__":
    sys.exit(main())
