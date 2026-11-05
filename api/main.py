"""FastAPI backend for the environmental dashboard.

Serves the pipeline output (data/processed/dashboard.json). The file is
re-read automatically when it changes on disk, so a scheduled pipeline run
updates the API without a restart. If the file is missing or corrupt the last
good copy kept in memory continues to be served.

Endpoints
---------
GET  /api/health                      liveness + data age
GET  /api/meta                        run metadata, provenance manifest
GET  /api/parameters                  list with latest value, trend, ranking
GET  /api/parameters/{id}             full detail (observations, analysis, models, forecasts)
GET  /api/forecast/{id}?model=&horizon=  forecast for one model, truncated to 6/12/18/24 months
GET  /api/compare?ids=a,b&normalize=  aligned observed + forecast series for several parameters
GET  /api/ranking                     parameters ranked by probability of increase
GET  /api/map/{layer}                 gistemp_grid | gistemp_zonal | power_points | regions
GET  /api/insights                    generated, data-driven statements
POST /api/admin/refresh               run the pipeline (requires ADMIN_TOKEN header)
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("DASHBOARD_JSON", ROOT / "data" / "processed" / "dashboard.json"))
WEB = ROOT / "web"
log = logging.getLogger("api")

app = FastAPI(title="NASA Environmental Monitoring API", version="1.0.0",
              description="Observations, trend analysis and validated two-year forecasts built from NASA (and partner) datasets.")
app.add_middleware(GZipMiddleware, minimum_size=1000)
origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"], allow_headers=["*"])

_state = {"data": None, "mtime": None, "error": None}
_lock = threading.Lock()


def data() -> dict:
    with _lock:
        try:
            mtime = DATA.stat().st_mtime
            if _state["data"] is None or mtime != _state["mtime"]:
                _state["data"] = json.loads(DATA.read_text())
                _state["mtime"] = mtime
                _state["error"] = None
        except Exception as exc:  # noqa: BLE001
            _state["error"] = str(exc)
            log.error("could not load %s: %s", DATA, exc)
        if _state["data"] is None:
            raise HTTPException(503, "dashboard data not available yet; run `python -m pipeline.run`")
        return _state["data"]


def param(pid: str) -> dict:
    for p in data()["parameters"]:
        if p["id"] == pid:
            return p
    raise HTTPException(404, f"unknown parameter '{pid}'")


@app.get("/api/health")
def health():
    d = data()
    gen = datetime.fromisoformat(d["meta"]["generated_utc"])
    return {"status": "ok" if not _state["error"] else "degraded", "generated_utc": d["meta"]["generated_utc"],
            "data_age_hours": round((datetime.now(timezone.utc) - gen).total_seconds() / 3600, 1),
            "last_load_error": _state["error"], "parameters": len(d["parameters"])}


@app.get("/api/meta")
def meta():
    return data()["meta"]


@app.get("/api/parameters")
def parameters():
    out = []
    for p in data()["parameters"]:
        row = {k: p.get(k) for k in ("id", "name", "short", "unit", "status", "tags")}
        if p["status"] == "ok":
            row.update(latest=p["latest"], dates=p["dates"], classification=p["analysis"]["classification"],
                       trend_last_30y=p["analysis"]["trend_last_30y"], selected_model=p["modelling"]["selected_model"],
                       ranking=p["ranking"], source=p["source"]["dataset"])
        else:
            row["reason"] = p.get("reason")
        out.append(row)
    return out


@app.get("/api/parameters/{pid}")
def parameter(pid: str):
    return param(pid)


@app.get("/api/forecast/{pid}")
def forecast(pid: str, model: str | None = None, horizon: int = Query(24, description="6, 12, 18 or 24 months after Oct 2026")):
    p = param(pid)
    if p["status"] != "ok":
        raise HTTPException(409, p.get("reason", "parameter unavailable"))
    if horizon not in (6, 12, 18, 24):
        raise HTTPException(422, "horizon must be 6, 12, 18 or 24")
    f = p["forecast"]
    model = model or f["selected"]
    if model not in f["models"]:
        raise HTTPException(404, f"model '{model}' not available; options: {sorted(f['models'])}")
    end = data()["meta"]["report_horizons"][str(horizon)]
    n = f["dates"].index(end) + 1
    m = f["models"][model]
    met = p["modelling"]["metrics"]["by_model"][model]
    return {"id": pid, "unit": p["unit"], "model": model, "model_label": p["modelling"]["models"][model]["label"],
            "selected_model": f["selected"], "horizon_months": horizon, "end": end,
            "dates": f["dates"][:n], **{k: v[:n] for k, v in m.items()},
            "validation": {k: met.get(k) for k in ("mae", "rmse", "mape", "mase", "bias", "skill_vs_best_baseline", "n_origins")},
            "latest_observation": p["latest"]}


@app.get("/api/compare")
def compare(ids: str, normalize: str = Query("none", pattern="^(none|zscore|baseline)$"), start: str = "1993-01"):
    """normalize=zscore: (x - mean_1993_2020)/sd ; baseline: x - mean_1991_2020."""
    out = []
    for pid in [i.strip() for i in ids.split(",") if i.strip()]:
        p = param(pid)
        if p["status"] != "ok":
            continue
        ob, f = p["observations"], p["forecast"]
        base = p["analysis"]["baseline_1991_2020"]
        mu, sd = base["mean"], base["std_monthly"] or 1
        tr = (lambda v: None if v is None else (v - mu) / sd) if normalize == "zscore" else \
             (lambda v: None if v is None else v - mu) if normalize == "baseline" else (lambda v: v)
        i0 = next((i for i, d in enumerate(ob["dates"]) if d >= start), 0)
        sel = f["models"][f["selected"]]
        out.append({"id": pid, "short": p["short"], "unit": p["unit"],
                    "observed": {"dates": ob["dates"][i0:], "values": [tr(v) for v in ob["values"][i0:]]},
                    "forecast": {"dates": f["dates"], "mean": [tr(v) for v in sel["mean"]],
                                 "lo95": [tr(v) for v in sel["lo95"]], "hi95": [tr(v) for v in sel["hi95"]]}})
    if not out:
        raise HTTPException(404, "no available parameters in 'ids'")
    return {"normalize": normalize, "series": out}


@app.get("/api/ranking")
def ranking():
    return data()["ranking"]


@app.get("/api/map/{layer}")
def map_layer(layer: str):
    maps = data()["maps"]
    if layer not in maps:
        raise HTTPException(404, f"layer must be one of {sorted(maps)}")
    return maps[layer]


@app.get("/api/insights")
def insights():
    return data()["insights"]


@app.get("/api/correlations")
def correlations():
    return data()["correlations"]


@app.post("/api/admin/refresh")
def refresh(x_admin_token: str | None = Header(None)):
    token = os.environ.get("ADMIN_TOKEN")
    if not token or x_admin_token != token:
        raise HTTPException(403, "forbidden")

    def job():
        from pipeline.run import run
        run(fetch=True, workers=2)

    threading.Thread(target=job, daemon=True).start()
    return {"status": "started"}


# Serve the static dashboard from the same service (optional; Vercel can host it instead).
@app.get("/")
def index():
    idx = WEB / "index.html"
    if idx.exists():
        return FileResponse(idx)
    return {"service": "NASA Environmental Monitoring API", "docs": "/docs"}


@app.get("/data/dashboard.json")
def raw_json():
    data()
    return FileResponse(DATA, media_type="application/json")
