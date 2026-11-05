# Earth Vital Signs Monitor

Global environmental monitoring and predictive analytics dashboard built on NASA (and NASA-partner) observations. It
tracks eight indicators, tests which ones are increasing, and forecasts November 2026 – October 2028 with models that
are chosen per indicator by out-of-sample skill.

* Reference month: **October 2026**. Forecast window: **Nov 2026 – Oct 2028**. Report horizons: +6, +12, +18, +24 months (Apr 2027, Oct 2027, Apr 2028, Oct 2028).
* Results with all numbers: [`docs/RESULTS.md`](docs/RESULTS.md) (regenerated on every pipeline run).

## What is in the box

```
pipeline/          data retrieval, validation, analysis, models, validation, report
  config.py        parameter registry: sources, URLs, resolution, coverage, delays, limitations
  sources.py       fetchers (retry + validation + keep-last-good), parsers, POWER/GISTEMP-map reductions, manifest
  analysis.py      trends (OLS + HAC, Mann-Kendall, Theil-Sen), STL, moving averages, YoY, anomalies, correlations
  models.py        naive, seasonal naive, drift, linear, quadratic, ETS, SARIMA, gradient boosting
  validation.py    rolling-origin CV, metrics, selection, intervals, residual diagnostics
  run.py           orchestration -> data/processed/dashboard.json
  report.py        docs/RESULTS.md
api/main.py        FastAPI backend (serves the pipeline output; hot-reloads it)
web/index.html     dashboard (static page; ECharts; reads the API or bundled JSON)
web/build_site.py  builds ./site for Vercel / GitHub Pages
web/build_artifact.py  single-file bundle (page + data) for hosting without a backend
data/raw/          agency files as retrieved + MANIFEST.json (URL, dates, SHA-256)
data/processed/    dashboard.json (all observations, analysis, forecasts, metrics)
tests/             tests: provenance hashes, parsers, no-leakage CV, metrics, output invariants, API
.github/workflows/ daily data update + tests; GitHub Pages deploy
render.yaml        Render blueprint for the API     vercel.json   static frontend on Vercel
```

## Datasets

| Parameter | Dataset (agency) | Resolution / coverage | Latest at retrieval (5 Nov 2026) |
|---|---|---|---|
| Global mean surface temperature anomaly | NASA GISS **GISTEMP v4** LOTI, `GLB.Ts+dSST.csv` | Monthly, global; base 1951–1980 | Sep 2026 (file published 22 Oct 2026) |
| Atmospheric CO₂ | **NOAA GML Mauna Loa** monthly means (the record shown on NASA's Climate Vital Signs) | Monthly, one station | Sep 2026 (file created 9 Oct 2026) |
| Sea surface temperature | **NOAA NCEI ERSSTv5** global ocean (GISTEMP's ocean input) | Monthly, global ocean; base 1901–2000 | Sep 2026 |
| Global mean sea level | **NASA Sea Level Change Portal** GMSL vital sign (TOPEX/Jason/Sentinel-6 altimetry; = PO.DAAC `NASA_SSH_GMSL_INDICATOR`) | ~7-day, 66°S–66°N; aggregated to months | late Oct 2026 (decimal year 2026.82) |
| Arctic sea ice extent | **NSIDC Sea Ice Index G02135 v4.0** (NASA DAAC) | Monthly, Northern Hemisphere | **Oct 2026** (files dated 2 Nov 2026) |
| Precipitation | **NASA POWER** (MERRA-2) `PRECTOTCORR`, 126-point 20° global sample | Monthly | Sep 2026 |
| Land surface (air) temperature | NASA GISS **GISTEMP v4** station index `GLB.Ts.csv` | Monthly, land stations | Sep 2026 |
| Aerosol optical depth | **NASA POWER** (MERRA-2) `AOD_55`, same sample (available from 2001) | Monthly | Jul 2026 |
| Map layers | GISTEMP gridded anomalies/trends (2° → 10° blocks); POWER point anomalies/trends | | Jul–Sep 2026 quarter |

**Why some series are not NASA-operated:** NASA does not run the long-term in-situ CO₂ record or publish an open global
SST time series; the pipeline uses the NOAA records that NASA itself displays (CO₂) or ingests (ERSSTv5 inside GISTEMP),
and labels them as NOAA throughout.

**October 2026:** only Arctic sea ice and sea level include October 2026. GISTEMP and NCEI publish mid-month, NOAA CO₂
in the first week, and POWER monthly aggregates after month end (MERRA-2 aerosols lag ~3 months). The dashboard shows
each series' real latest month, its delay, and separates observation / publication / retrieval / forecast dates.

### Data provenance for the current snapshot

The build environment used for this release could not reach NASA servers directly (outbound network policy), so the
2026-11-05 snapshot was retrieved through a real web browser from the agency endpoints listed above. Every stored file's
SHA-256 was checked against the hash computed in the browser over the bytes received (the GISTEMP files are byte-identical
copies; the CO₂ file was checked value-for-value against NOAA's live file). Hashes, URLs, publication and retrieval times
are in `data/raw/MANIFEST.json`, and `tests/test_pipeline.py::test_manifest_hashes_match_stored_files` re-checks them.
In normal operation, `python -m pipeline.run --fetch` downloads directly from the agencies (GitHub-hosted runners have
open internet access). The POWER and GISTEMP-map reductions run in Python in production; the snapshot used an equivalent
browser routine (same algorithm, documented in `pipeline/sources.py`).

## Methods

**Trend analysis.** OLS trend with calendar-month terms and Newey–West (12-lag) standard errors, over the full record and
the last 30 years; Mann–Kendall test and Theil–Sen slope on annual means; recent-15-yr vs previous-15-yr rate
(acceleration); robust STL decomposition (period 12) and seasonal strength; 12- and 60-month moving averages; year-over-year
change and record rank; anomalies = STL remainder beyond ±3 robust SD; Pearson correlation of annual means and of
year-to-year differences (the latter removes shared trends — correlation is never presented as causation).

**Models (all evaluated for every parameter).** Persistence, seasonal naive, random walk with drift (baselines); linear and
quadratic regression with month effects (30-year window); damped Holt–Winters ETS; SARIMA (order by AIC from a candidate
set); gradient boosting on lagged differences. Prophet and LSTM were deliberately not used (reasons in
`pipeline/models.py::NOT_USED`: no benefit over validated statistical trend models; far too few independent seasonal
cycles for deep learning).

**Validation.** Rolling-origin, expanding window: 20 origins 6 months apart, each forecasting the full horizon to Oct 2028
(24–27 months). Chronological only. MAE, RMSE, MAPE (strictly positive quantities only), MASE, bias, skill vs the best
naive baseline. The model with the lowest mean RMSE is selected **per parameter**.

**Uncertainty.** 80/95% intervals = selected model's horizon-specific out-of-sample RMSE (made non-decreasing) × Gaussian
quantiles. The 12-month-mean change used for ranking has its own out-of-sample RMSE. Calibration (empirical coverage) and
one-step walk-forward residual tests (Ljung–Box, Shapiro–Wilk, bias t-test) are reported on the dashboard.

**Ranking.** By P(Nov 2027–Oct 2028 mean > latest 12-month mean), then by change ÷ detrended interannual SD; wording
follows IPCC calibrated likelihood language.

### Key limitations
* ENSO and volcanic/aerosol events are not modelled; they dominate two-year temperature and aerosol variability.
* Forecasts are statistical extrapolations, not physical climate projections or official NASA products.
* POWER-based precipitation and AOD are 126-point sample indices, not gridded global means. The latest 12 months are
  unusually wet in that index, so its projected decrease is mean reversion, not a trend.
* Land temperature is station air temperature, not satellite skin LST (MODIS LST requires Earthdata login).
* Interval coverage is checked on the same validation folds that set the widths (shape check, not an independent test).

## Run locally

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m pipeline.run --fetch      # or without --fetch to model the stored, verified raw files
python -m pipeline.report           # docs/RESULTS.md
python -m pytest -q tests
uvicorn api.main:app --reload       # http://localhost:8000  (dashboard at /, API docs at /docs)
```

## API

`/api/health` · `/api/meta` · `/api/parameters` · `/api/parameters/{id}` · `/api/forecast/{id}?model=sarima&horizon=12`
· `/api/compare?ids=co2,gmst&normalize=zscore` · `/api/ranking` · `/api/map/{gistemp_grid|gistemp_zonal|power_points|regions}`
· `/api/insights` · `/api/correlations` · `POST /api/admin/refresh` (header `X-Admin-Token`). Interactive docs at `/docs`.

## Deploy (public)

Deployment needs accounts that only you can create; nothing below requires payment.

**Option A — GitHub only (simplest, free).** Frontend on GitHub Pages, daily data/model refresh by GitHub Actions.
1. Create a new GitHub repository and push this folder (`git init && git add . && git commit -m init && git remote add origin … && git push -u origin main`).
2. Repository → Settings → Pages → Source: **GitHub Actions**.
3. Settings → Actions → General → Workflow permissions: **Read and write**.
4. Actions tab → *Update data and forecasts* → **Run workflow**. When it finishes the dashboard is live at `https://<user>.github.io/<repo>/`. It re-runs daily at 06:17 UTC.

**Option B — Vercel frontend + Render API (as specified).** Do Option A steps 1 and 3 first.
1. Render → New → **Blueprint** → select the repo (uses `render.yaml`). Copy the service URL, e.g. `https://earth-vital-signs-api.onrender.com`; check `/api/health`.
2. GitHub → Settings → Secrets and variables → Actions → **Variables** → `API_BASE` = that URL. Run the workflow once so `site/` is rebuilt pointing at the API.
3. Vercel → Add New Project → import the repo → Framework *Other*, no build command, output directory `site` (already in `vercel.json`) → Deploy.
4. On Render set `CORS_ORIGINS` to your Vercel URL. Every daily data commit redeploys both.
   (Render's free plan sleeps after inactivity; the frontend falls back to its bundled copy of the data while the API wakes.)

**Optional:** add repository secret `EARTHDATA_TOKEN` (from https://urs.earthdata.nasa.gov → Generate Token) to also pull the
PO.DAAC GMSL file.

## Updating data

Automatic: the workflow runs `pipeline.run --fetch`, which only replaces a raw file when the new download validates
(structure, plausible ranges, no fewer records than before), records it in `MANIFEST.json`, re-runs all models, runs the
tests, regenerates `docs/RESULTS.md`, rebuilds `site/` and commits. Manual: run the same commands locally, or call
`POST /api/admin/refresh` on the API. Update frequency follows the sources (monthly for most; weekly for sea level).

### Indicators not included

Vegetation (NDVI) was investigated but is not shown: in November 2026 no NASA NDVI time series could be downloaded
without an Earthdata login (NASA Earth Observations was decommissioned in September 2026; AppEEARS and Giovanni need
authentication). Rather than display an empty section or substitute non-NASA data, the indicator was removed.
