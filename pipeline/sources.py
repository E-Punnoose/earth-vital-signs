"""Retrieval and parsing of the source datasets.

Design rules
------------
* Each fetcher downloads from the original agency URL, validates the payload
  (structure, plausible ranges, no regression in record length) and only then
  replaces the stored raw file. If anything fails, the previous verified file is
  kept, so the dashboard keeps working during agency outages.
* Every write is recorded in data/raw/MANIFEST.json with the source URL, the
  retrieval time, the SHA-256 of the stored file and the last observation date.
* Parsers turn the raw files into monthly pandas Series indexed by month-start
  timestamps. No values are invented: gaps stay NaN unless a model explicitly
  needs a complete series, in which case the filled months are flagged.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .config import MANIFEST_PATH, RAW_DIR

log = logging.getLogger("pipeline.sources")

USER_AGENT = "nasa-env-dashboard/1.0 (+https://github.com/; research dashboard)"


# --------------------------------------------------------------------------
# HTTP helpers
# --------------------------------------------------------------------------
def http_get(url: str, *, method: str = "GET", data: dict | None = None, headers: dict | None = None,
             retries: int = 4, timeout: float = 60.0) -> bytes:
    """GET/POST with exponential back-off. Raises after the last attempt."""
    import requests  # imported lazily so offline runs need no network stack

    h = {"User-Agent": USER_AGENT}
    h.update(headers or {})
    last: Exception | None = None
    for attempt in range(retries):
        try:
            resp = requests.request(method, url, data=data, headers=h, timeout=timeout)
            if resp.status_code == 429 or resp.status_code >= 500:
                raise RuntimeError(f"HTTP {resp.status_code}")
            resp.raise_for_status()
            return resp.content
        except Exception as exc:  # noqa: BLE001 - we log and retry everything
            last = exc
            wait = 2 ** attempt
            log.warning("fetch %s failed (%s); retry %d/%d in %ss", url, exc, attempt + 1, retries, wait)
            time.sleep(wait)
    raise RuntimeError(f"giving up on {url}: {last}")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text())
    return {"files": {}}


def save_manifest(m: dict) -> None:
    MANIFEST_PATH.write_text(json.dumps(m, indent=2, sort_keys=True))


def record(rel: str, *, url: str, method: str, last_obs: str, published: str | None = None,
           retrieved: str | None = None, note: str = "") -> None:
    m = load_manifest()
    path = RAW_DIR / rel
    m["files"][rel] = {
        "url": url,
        "retrieval_method": method,
        "retrieved_utc": retrieved or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_published": published,
        "last_observation": last_obs,
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "note": note,
    }
    save_manifest(m)


def _safe_replace(rel: str, content: bytes, validator) -> bool:
    """Validate new content, then atomically replace the stored raw file."""
    path = RAW_DIR / rel
    try:
        validator(content, path)
    except Exception as exc:  # noqa: BLE001
        log.error("validation failed for %s: %s - keeping previous verified copy", rel, exc)
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(content)
    tmp.replace(path)
    return True


def _not_shorter(new_rows: int, path: Path, count) -> None:
    if path.exists():
        old = count(path.read_bytes())
        if new_rows < old:
            raise ValueError(f"new file has {new_rows} records, stored copy has {old}")


# --------------------------------------------------------------------------
# Parsers (raw file -> monthly Series)
# --------------------------------------------------------------------------
def _month_index(years, months) -> pd.DatetimeIndex:
    return pd.to_datetime({"year": years, "month": months, "day": 1})


def parse_gistemp_table(path: Path) -> pd.Series:
    lines = path.read_text().splitlines()
    hdr = next(i for i, l in enumerate(lines) if l.startswith("Year,"))
    df = pd.read_csv(path, skiprows=hdr, na_values=["***", "****"])
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    long = df.melt(id_vars="Year", value_vars=months, var_name="m", value_name="v")
    long["month"] = long["m"].map({m: i + 1 for i, m in enumerate(months)})
    long.index = _month_index(long["Year"], long["month"])
    s = long["v"].astype(float).sort_index()
    return s.loc[: s.last_valid_index()]


def parse_co2(path: Path) -> pd.Series:
    df = pd.read_csv(path)
    idx = pd.to_datetime(df["yyyy-mm"] + "-01")
    s = pd.Series(df["average_ppm"].values, index=idx, dtype=float)
    return s.where(s > 0)


def parse_ncei(path: Path) -> pd.Series:
    df = pd.read_csv(path, header=None, names=["ym", "v"], dtype={"ym": str})
    idx = pd.to_datetime(df["ym"], format="%Y%m")
    return pd.Series(df["v"].astype(float).values, index=idx)


def parse_nsidc(path: Path) -> pd.Series:
    df = pd.read_csv(path, header=None, names=["ym", "extent", "area"])
    idx = pd.to_datetime(df["ym"] + "-01")
    s = pd.Series(df["extent"].astype(float).values, index=idx)
    return s.where(s > 0)


def decimal_year_to_datetime(x: float) -> pd.Timestamp:
    year = int(math.floor(x))
    start = pd.Timestamp(year=year, month=1, day=1)
    end = pd.Timestamp(year=year + 1, month=1, day=1)
    return start + (end - start) * (x - year)


def parse_gmsl(path: Path) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Returns (monthly mean, samples per month, native-resolution series)."""
    df = pd.read_csv(path, header=None, names=["t", "v"])
    native = pd.Series(df["v"].astype(float).values, index=[decimal_year_to_datetime(t) for t in df["t"]])
    grp = native.groupby(native.index.to_period("M"))
    monthly = grp.mean()
    counts = grp.count()
    monthly.index = monthly.index.to_timestamp()
    counts.index = counts.index.to_timestamp()
    return monthly, counts, native


def parse_power_series(path: Path, column: str) -> pd.Series:
    df = pd.read_csv(path, dtype={"yyyymm": str})
    idx = pd.to_datetime(df["yyyymm"], format="%Y%m")
    s = pd.Series(df[column].astype(float).values, index=idx)
    return s.loc[s.first_valid_index(): s.last_valid_index()]


def load_series(pid: str) -> tuple[pd.Series, dict]:
    """Load the observed monthly series for a parameter, plus quality info."""
    q: dict = {"filled_months": [], "partial_months": []}
    if pid == "gmst":
        s = parse_gistemp_table(RAW_DIR / "gistemp/GLB.Ts+dSST.csv")
    elif pid == "land_temp":
        s = parse_gistemp_table(RAW_DIR / "gistemp/GLB.Ts.csv")
    elif pid == "co2":
        s = parse_co2(RAW_DIR / "noaa_gml/co2_mm_mlo.csv")
    elif pid == "sst":
        s = parse_ncei(RAW_DIR / "ncei/global_ocean_tavg_1950_2026.csv")
    elif pid == "arctic_ice":
        s = parse_nsidc(RAW_DIR / "nsidc/N_monthly_extent_area_v4.0.csv")
    elif pid == "gmsl":
        s, counts, _ = parse_gmsl(RAW_DIR / "nasa_sealevel/gmsl_vital_sign.csv")
        last = s.index[-1]
        q["samples_in_last_month"] = int(counts.iloc[-1])
        q["samples_per_month_median"] = float(counts.median())
        if counts.iloc[-1] < counts.median():
            q["partial_months"].append(last.strftime("%Y-%m"))
    elif pid == "precip":
        s = parse_power_series(RAW_DIR / "nasa_power/grid20_global_sample_monthly.csv", "PRECTOTCORR")
    elif pid == "aod":
        s = parse_power_series(RAW_DIR / "nasa_power/grid20_global_sample_monthly.csv", "AOD_55")
    else:
        raise KeyError(pid)
    s = s.asfreq("MS")
    q["missing_months"] = [d.strftime("%Y-%m") for d in s.index[s.isna()]]
    return s, q


# --------------------------------------------------------------------------
# POWER grid-sample reduction (identical to the routine used for the
# 2026-11-05 snapshot, see README "Data provenance")
# --------------------------------------------------------------------------
POWER_LATS = [-60, -40, -20, 0, 20, 40, 60]
POWER_LONS = list(range(-170, 171, 20))
POWER_PARAMS = ["PRECTOTCORR", "AOD_55", "TS"]


def _r4(x: float) -> float:
    return math.floor(x * 10000 + 0.5) / 10000  # JS Math.round semantics


def _fmt(x: float) -> str:
    v = _r4(x)
    s = repr(v)
    return s[:-2] if s.endswith(".0") else s


def reduce_power(points: dict[tuple[int, int], dict]) -> tuple[str, str]:
    """points[(lat, lon)] = POWER 'parameter' dict -> (series_csv, stats_csv)."""
    keys = sorted(points)
    months = sorted(k for k in points[keys[0]]["TS"] if not k.endswith("13"))
    total_w = sum(math.cos(math.radians(la)) for la, _ in keys)
    lines = ["yyyymm," + ",".join(POWER_PARAMS)]
    for m in months:
        row, any_ok = [m], False
        for p in POWER_PARAMS:
            sw = sv = 0.0
            for la, lo in keys:
                v = points[(la, lo)][p].get(m)
                if v is not None and v != -999:
                    w = math.cos(math.radians(la))
                    sw += w
                    sv += w * v
            ok = sw / total_w >= 0.9
            row.append(_fmt(sv / sw) if ok else "")
            any_ok |= ok
        if any_ok:
            lines.append(",".join(row))
    series_csv = "\n".join(lines) + "\n"

    def stat(obj):
        vals = [(m, obj[m]) for m in months if obj.get(m) is not None and obj[m] != -999]
        base = [v for m, v in vals if "199101" <= m <= "202012"]
        last12 = vals[-12:]
        bm = sum(base) / len(base)
        clim: dict[str, list[float]] = {}
        for m, v in vals:
            if "199101" <= m <= "202012":
                clim.setdefault(m[4:], []).append(v)
        cm = {k: sum(v) / len(v) for k, v in clim.items()}
        anom = sum(v - cm[m[4:]] for m, v in last12) / len(last12)
        yrs: dict[int, list[float]] = {}
        for m, v in vals:
            y = int(m[:4])
            if y <= 2025:
                yrs.setdefault(y, []).append(v)
        ys = [y for y in yrs if len(yrs[y]) == 12]
        ym = [sum(yrs[y]) / 12 for y in ys]
        mx, my = sum(ys) / len(ys), sum(ym) / len(ym)
        sxy = sum((y - mx) * (v - my) for y, v in zip(ys, ym))
        sxx = sum((y - mx) ** 2 for y in ys)
        return [_fmt(bm), _fmt(anom), _fmt(10 * sxy / sxx), last12[0][0], last12[-1][0]]

    cols = []
    for p in POWER_PARAMS:
        cols += [f"{p}_base9120", f"{p}_anom_last12", f"{p}_trend_per_decade", f"{p}_last12_start", f"{p}_last12_end"]
    out = ["lat,lon," + ",".join(cols)]
    for la, lo in keys:
        out.append(f"{la},{lo}," + ",".join(str(x) for p in POWER_PARAMS for x in stat(points[(la, lo)][p])))
    return series_csv, "\n".join(out) + "\n"


# --------------------------------------------------------------------------
# GISTEMP gridded map reduction (2x2 degree -> 10x10 degree, cos-lat weighted)
# --------------------------------------------------------------------------
def downsample_gistemp_grid(txt: str) -> list[str]:
    rows = []
    for line in txt.splitlines()[2:]:
        parts = line.split()
        if len(parts) == 5:
            rows.append((float(parts[2]), float(parts[3]), float(parts[4])))
    blocks: dict[tuple[int, int], list[float]] = {}
    for lo, la, v in rows:
        if v >= 9999:
            continue
        bi, bj = int(math.floor((la + 90) / 10)), int(math.floor((lo + 180) / 10))
        w = math.cos(math.radians(la))
        b = blocks.setdefault((bi, bj), [0.0, 0.0, 0])
        b[0] += w * v
        b[1] += w
        b[2] += 1
    out = []
    for bi in range(18):
        for bj in range(36):
            b = blocks.get((bi, bj))
            val = f"{math.floor(100 * b[0] / b[1] + 0.5) / 100:.2f}" if b and b[2] >= 13 else ""
            out.append(f"{-85 + 10 * bi},{-175 + 10 * bj},{val}")
    return out


# --------------------------------------------------------------------------
# Fetchers (production). Each returns True if the stored file was refreshed.
# --------------------------------------------------------------------------
def _count_lines(b: bytes) -> int:
    return len([l for l in b.decode("utf-8", "replace").splitlines() if l.strip()])


def fetch_gistemp() -> dict[str, bool]:
    res = {}
    for rel, url in [
        ("gistemp/GLB.Ts+dSST.csv", "https://data.giss.nasa.gov/gistemp/tabledata_v4/GLB.Ts+dSST.csv"),
        ("gistemp/GLB.Ts.csv", "https://data.giss.nasa.gov/gistemp/tabledata_v4/GLB.Ts.csv"),
    ]:
        try:
            content = http_get(url)

            def validate(b: bytes, path: Path) -> None:
                txt = b.decode()
                if "Year,Jan,Feb" not in txt:
                    raise ValueError("unexpected GISTEMP header")
                tmp = path.with_suffix(".check")
                tmp.write_bytes(b)
                s = parse_gistemp_table(tmp)
                tmp.unlink()
                if not (-3 < s.min() and s.max() < 5):
                    raise ValueError("anomaly out of plausible range")
                _not_shorter(len(s.dropna()), path, lambda old: len(parse_gistemp_table(path).dropna()))

            ok = _safe_replace(rel, content, validate)
            if ok:
                s = parse_gistemp_table(RAW_DIR / rel)
                record(rel, url=url, method="direct HTTPS", last_obs=s.last_valid_index().strftime("%Y-%m"))
            res[rel] = ok
        except Exception as exc:  # noqa: BLE001
            log.error("GISTEMP fetch failed: %s", exc)
            res[rel] = False
    return res


def fetch_co2() -> dict[str, bool]:
    rel = "noaa_gml/co2_mm_mlo.csv"
    url = "https://gml.noaa.gov/webdata/ccgg/trends/co2/co2_mm_mlo.csv"
    try:
        raw = http_get(url).decode()
        created = re.search(r"# File Creation:\s*(.+)", raw)
        rows = [l.split(",") for l in raw.splitlines() if l and l[0].isdigit()]
        out = "yyyy-mm,average_ppm,deseasonalized_ppm,ndays\n" + "".join(
            f"{r[0]}-{int(r[1]):02d},{float(r[3]):.2f},{float(r[4]):.2f},{int(r[5])}\n" for r in rows)

        def validate(b: bytes, path: Path) -> None:
            vals = [float(l.split(",")[1]) for l in b.decode().splitlines()[1:]]
            if not (300 < max(vals) < 500):
                raise ValueError("CO2 out of range")
            _not_shorter(len(vals), path, lambda old: _count_lines(old) - 1)

        ok = _safe_replace(rel, out.encode(), validate)
        if ok:
            record(rel, url=url, method="direct HTTPS", last_obs=out.splitlines()[-1].split(",")[0],
                   published=created.group(1).strip() if created else None)
        return {rel: ok}
    except Exception as exc:  # noqa: BLE001
        log.error("CO2 fetch failed: %s", exc)
        return {rel: False}


def fetch_ncei_ocean() -> dict[str, bool]:
    rel = "ncei/global_ocean_tavg_1950_2026.csv"
    url = ("https://www.ncei.noaa.gov/access/monitoring/climate-at-a-glance/global/time-series/"
           f"globe/ocean/tavg/1/0/1950-{datetime.now(timezone.utc).year}/data.csv")
    try:
        raw = http_get(url).decode()
        rows = [l for l in raw.splitlines() if re.match(r"^\d{6},", l)]
        out = "\n".join(rows) + "\n"

        def validate(b: bytes, path: Path) -> None:
            if len(rows) < 900:
                raise ValueError("too few rows")
            _not_shorter(len(rows), path, _count_lines)

        ok = _safe_replace(rel, out.encode(), validate)
        if ok:
            record(rel, url=url, method="direct HTTPS", last_obs=rows[-1][:4] + "-" + rows[-1][4:6])
        return {rel: ok}
    except Exception as exc:  # noqa: BLE001
        log.error("NCEI fetch failed: %s", exc)
        return {rel: False}


def fetch_nsidc() -> dict[str, bool]:
    rel = "nsidc/N_monthly_extent_area_v4.0.csv"
    base = "https://noaadata.apps.nsidc.org/NOAA/G02135/north/monthly/data/"
    try:
        rows = []
        for m in range(1, 13):
            txt = http_get(f"{base}N_{m:02d}_extent_v4.0.csv").decode()
            for l in txt.strip().splitlines()[1:]:
                c = [x.strip() for x in l.split(",")]
                rows.append((f"{c[0]}-{int(c[1]):02d}", c[4], c[5]))
        rows.sort()
        out = "".join(f"{a},{b},{c}\n" for a, b, c in rows)

        def validate(b: bytes, path: Path) -> None:
            ext = [float(l.split(",")[1]) for l in b.decode().splitlines() if float(l.split(",")[1]) > 0]
            if not (2 < min(ext) and max(ext) < 18):
                raise ValueError("extent out of range")
            _not_shorter(len(rows), path, _count_lines)

        ok = _safe_replace(rel, out.encode(), validate)
        if ok:
            record(rel, url=base, method="direct HTTPS (12 monthly files merged)", last_obs=rows[-1][0])
        return {rel: ok}
    except Exception as exc:  # noqa: BLE001
        log.error("NSIDC fetch failed: %s", exc)
        return {rel: False}


def fetch_gmsl() -> dict[str, bool]:
    rel = "nasa_sealevel/gmsl_vital_sign.csv"
    token = os.environ.get("EARTHDATA_TOKEN")
    try:
        if token:
            url = ("https://archive.podaac.earthdata.nasa.gov/podaac-ops-cumulus-protected/"
                   "NASA_SSH_GMSL_INDICATOR/NASA_SSH_GMSL_INDICATOR.txt")
            log.info("EARTHDATA_TOKEN present - PO.DAAC file will be stored alongside the vital-sign series")
            b = http_get(url, headers={"Authorization": f"Bearer {token}"})
            (RAW_DIR / "nasa_sealevel/NASA_SSH_GMSL_INDICATOR.txt").write_bytes(b)
            record("nasa_sealevel/NASA_SSH_GMSL_INDICATOR.txt", url=url, method="PO.DAAC (Earthdata token)",
                   last_obs="see file")
        page_url = "https://sealevel.nasa.gov/vital-signs/global-mean-sea-level/"
        html = http_get(page_url).decode("utf-8", "replace")
        xs = json.loads(re.search(r"var chart_x\s*=\s*(\[[^\]]*\])", html).group(1))
        ys = json.loads(re.search(r"var chart_y\s*=\s*(\[[^\]]*\])", html).group(1))
        out = "".join(f"{x},{y}\n" for x, y in zip(xs, ys))

        def validate(b: bytes, path: Path) -> None:
            if len(xs) != len(ys) or len(xs) < 1500:
                raise ValueError("unexpected GMSL array length")
            if xs[0] > 1994 or max(ys) > 400:
                raise ValueError("implausible GMSL values")
            _not_shorter(len(xs), path, _count_lines)

        ok = _safe_replace(rel, out.encode(), validate)
        if ok:
            record(rel, url=page_url, method="vital-sign page embedded data (chart_x/chart_y)", last_obs=str(xs[-1]))
        return {rel: ok}
    except Exception as exc:  # noqa: BLE001
        log.error("GMSL fetch failed: %s", exc)
        return {rel: False}


def fetch_power() -> dict[str, bool]:
    rels = ["nasa_power/grid20_global_sample_monthly.csv", "nasa_power/grid20_point_stats.csv"]
    end_year = datetime.now(timezone.utc).year
    points = {}
    try:
        for la in POWER_LATS:
            for lo in POWER_LONS:
                url = ("https://power.larc.nasa.gov/api/temporal/monthly/point?parameters=PRECTOTCORR,AOD_55,TS"
                       f"&community=AG&longitude={lo}&latitude={la}&start=1981&end={end_year}&format=JSON")
                j = json.loads(http_get(url))
                points[(la, lo)] = j["properties"]["parameter"]
        series_csv, stats_csv = reduce_power(points)

        def validate(b: bytes, path: Path) -> None:
            if _count_lines(b) < 500:
                raise ValueError("too few months")

        ok1 = _safe_replace(rels[0], series_csv.encode(), validate)
        ok2 = _safe_replace(rels[1], stats_csv.encode(), lambda b, p: None)
        for rel, ok in zip(rels, (ok1, ok2)):
            if ok:
                record(rel, url="https://power.larc.nasa.gov/api/temporal/monthly/point", method="POWER API x126 points",
                       last_obs=series_csv.strip().splitlines()[-1].split(",")[0])
        return dict(zip(rels, (ok1, ok2)))
    except Exception as exc:  # noqa: BLE001
        log.error("POWER fetch failed: %s", exc)
        return {r: False for r in rels}


def fetch_gistemp_maps() -> dict[str, bool]:
    """Latest complete calendar quarter anomaly + 1981-(last full year) change map."""
    rel_grid, rel_zonal = "gistemp/map_10deg.csv", "gistemp/zonal_2deg.csv"
    try:
        s = parse_gistemp_table(RAW_DIR / "gistemp/GLB.Ts+dSST.csv")
        last = s.last_valid_index()
        q_start = {3: 1, 6: 4, 9: 7, 12: 10}.get(last.month)
        if q_start is None:  # last complete quarter
            q_end = (last.month - 1) // 3 * 3
            q_start = q_end - 2 if q_end else 10
            qyear = last.year if q_end else last.year - 1
        else:
            qyear = last.year
        base = {"sat": "4", "sst": "7", "airs": "0", "base1": "1951", "base2": "1980", "radius": "1200", "pol": "reg"}

        def run(params):
            html = http_get("https://data.giss.nasa.gov/cgi-bin/gistemp/amaps.cgi", method="POST",
                            data={**base, **params}).decode()
            links = re.findall(r'(?:href|src)="([^"]+)"', html)
            g = http_get("https://data.giss.nasa.gov" + next(l for l in links if l.endswith("amaps.txt"))).decode()
            z = http_get("https://data.giss.nasa.gov" + next(l for l in links if l.endswith("amaps_zonal.txt"))).decode()
            return g, z

        g1, z1 = run({"type": "anoms", "mean_gen": f"{q_start:02d}03", "year1": str(qyear), "year2": str(qyear)})
        g2, z2 = run({"type": "trends", "mean_gen": "0112", "year1": "1981", "year2": str(last.year - 1)})
        d1, d2 = downsample_gistemp_grid(g1), downsample_gistemp_grid(g2)
        label = f"{['Jan','Apr','Jul','Oct'][(q_start-1)//3]}-{['Mar','Jun','Sep','Dec'][(q_start-1)//3]}{qyear}"
        grid = f"lat,lon,anom_{label}_vs_1951_1980,trend_1981_{last.year-1}_degC_total_change\n" + "".join(
            f"{a},{b.split(',')[2]}\n" for a, b in zip(d1, d2))

        def zon(t):
            out = []
            for l in t.splitlines():
                p = l.split()
                if len(p) == 2:
                    try:
                        la, v = float(p[0]), float(p[1])
                    except ValueError:
                        continue
                    out.append((f"{la:.0f}", "" if v >= 9999 else f"{v:.3f}"))
            return out

        zz1, zz2 = zon(z1), zon(z2)
        zonal = "lat,anom_latest_quarter,change_1981_last_full_year\n" + "".join(
            f"{a[0]},{a[1]},{b[1]}\n" for a, b in zip(zz1, zz2))
        ok1 = _safe_replace(rel_grid, grid.encode(), lambda b, p: None if _count_lines(b) == 649 else (_ for _ in ()).throw(ValueError("grid size")))
        ok2 = _safe_replace(rel_zonal, zonal.encode(), lambda b, p: None)
        for rel, ok in ((rel_grid, ok1), (rel_zonal, ok2)):
            if ok:
                record(rel, url="https://data.giss.nasa.gov/gistemp/maps/", method="amaps.cgi + 10x10 cos-lat block mean",
                       last_obs=f"{qyear} {label}")
        return {rel_grid: ok1, rel_zonal: ok2}
    except Exception as exc:  # noqa: BLE001
        log.error("GISTEMP map fetch failed: %s", exc)
        return {rel_grid: False, rel_zonal: False}


FETCHERS = [fetch_gistemp, fetch_co2, fetch_ncei_ocean, fetch_nsidc, fetch_gmsl, fetch_power, fetch_gistemp_maps]


def fetch_all() -> dict[str, bool]:
    status: dict[str, bool] = {}
    for f in FETCHERS:
        status.update(f())
    return status
