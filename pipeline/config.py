"""Parameter registry: what each environmental indicator is, where it comes from,
and how it is modelled.

Every number shown on the dashboard traces back to one of the raw files listed
here. Nothing in this module contains observational values.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"
MANIFEST_PATH = RAW_DIR / "MANIFEST.json"

# The analysis is framed around October 2026 as the reference month and the
# two-year window November 2026 - October 2028.
REFERENCE_MONTH = "2026-10"
TARGET_START = "2026-11"
TARGET_END = "2028-10"
# Horizons reported on the dashboard, counted from the reference month.
REPORT_HORIZONS = {6: "2027-04", 12: "2027-10", 18: "2028-04", 24: "2028-10"}


@dataclass
class Source:
    agency: str
    dataset: str
    url: str
    landing_page: str
    citation: str
    temporal_resolution: str
    spatial_coverage: str
    baseline: str
    typical_delay: str
    raw_files: list[str]
    notes: str = ""


@dataclass
class Parameter:
    id: str
    name: str
    short: str
    unit: str
    source: Source
    # "increase" means larger values are the direction of concern (used only
    # for wording; the ranking itself is purely numerical).
    concern_direction: str = "increase"  # "increase", "decrease" or "none"
    fit_start: str | None = None  # first month used for model fitting
    status: str = "ok"
    unavailable_reason: str = ""
    value_decimals: int = 2
    tags: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    description: str = ""


GISTEMP = Source(
    agency="NASA Goddard Institute for Space Studies (GISS)",
    dataset="GISTEMP v4 Land-Ocean Temperature Index (GLB.Ts+dSST)",
    url="https://data.giss.nasa.gov/gistemp/tabledata_v4/GLB.Ts+dSST.csv",
    landing_page="https://data.giss.nasa.gov/gistemp/",
    citation="GISTEMP Team, 2026: GISS Surface Temperature Analysis (GISTEMP), version 4. NASA Goddard Institute for Space Studies. Lenssen et al. (2024), JGR Atmospheres.",
    temporal_resolution="Monthly",
    spatial_coverage="Global (land stations GHCNv4 + ocean ERSSTv5), 2x2 degree grid aggregated to a global mean",
    baseline="1951-1980 mean",
    typical_delay="Published around the 10th-20th of the following month; the October 2026 value was not yet released at retrieval.",
    raw_files=["gistemp/GLB.Ts+dSST.csv"],
)

GISTEMP_LAND = Source(
    agency="NASA Goddard Institute for Space Studies (GISS)",
    dataset="GISTEMP v4 meteorological-station index (GLB.Ts)",
    url="https://data.giss.nasa.gov/gistemp/tabledata_v4/GLB.Ts.csv",
    landing_page="https://data.giss.nasa.gov/gistemp/",
    citation="GISTEMP Team, 2026: GISS Surface Temperature Analysis (GISTEMP), version 4. NASA GISS.",
    temporal_resolution="Monthly",
    spatial_coverage="Global, land meteorological stations only (GHCNv4), extrapolated up to 1200 km",
    baseline="1951-1980 mean",
    typical_delay="Same release cycle as GISTEMP LOTI (mid following month).",
    raw_files=["gistemp/GLB.Ts.csv"],
    notes=(
        "This is near-surface AIR temperature over land from weather stations, not satellite "
        "land-surface SKIN temperature (MODIS LST). MODIS LST requires an Earthdata login and "
        "was not retrievable without credentials; the station index is the closest openly "
        "published NASA land-temperature record."
    ),
)

NOAA_CO2 = Source(
    agency="NOAA Global Monitoring Laboratory (record shown on NASA's Climate Vital Signs)",
    dataset="Mauna Loa Observatory monthly mean CO2 (co2_mm_mlo)",
    url="https://gml.noaa.gov/webdata/ccgg/trends/co2/co2_mm_mlo.csv",
    landing_page="https://gml.noaa.gov/ccgg/trends/",
    citation="Lan, X., Tans, P. and Thoning, K.W.: Trends in globally-averaged CO2 determined from NOAA Global Monitoring Laboratory measurements. NOAA GML.",
    temporal_resolution="Monthly",
    spatial_coverage="Single station (Mauna Loa, Hawaii, 19.5N 155.6W); representative of the well-mixed background atmosphere",
    baseline="Absolute concentration (ppm, dry-air mole fraction)",
    typical_delay="Monthly file regenerated in the first days of the following month (file creation 9 Oct 2026 contained September 2026).",
    raw_files=["noaa_gml/co2_mm_mlo.csv"],
    notes=(
        "NASA does not operate the long-term in-situ CO2 record; NASA's Vital Signs page "
        "displays this NOAA series. Values were cross-checked: all 823 monthly means in the "
        "stored file are identical to NOAA's live file (canonical SHA-256 match)."
    ),
)

NCEI_OCEAN = Source(
    agency="NOAA NCEI (ERSSTv5 - the ocean component used inside NASA GISTEMP)",
    dataset="Climate at a Glance: Global Ocean surface temperature anomalies (ERSSTv5-based)",
    url="https://www.ncei.noaa.gov/access/monitoring/climate-at-a-glance/global/time-series/globe/ocean/tavg/1/0/1950-2026/data.csv",
    landing_page="https://www.ncei.noaa.gov/access/monitoring/climate-at-a-glance/",
    citation="NOAA National Centers for Environmental Information, Climate at a Glance: Global Time Series (2026).",
    temporal_resolution="Monthly",
    spatial_coverage="Global ocean, 2x2 degree ERSSTv5 grid aggregated to a global ocean mean",
    baseline="1901-2000 mean",
    typical_delay="Released around the 12th-15th of the following month.",
    raw_files=["ncei/global_ocean_tavg_1950_2026.csv"],
    notes=(
        "NASA's satellite SST products (e.g. MUR via PO.DAAC) require an Earthdata login. "
        "ERSSTv5 is the sea-surface temperature input that NASA GISTEMP itself uses, so this "
        "series is consistent with the GISTEMP global index."
    ),
)

NASA_GMSL = Source(
    agency="NASA Sea Level Change Portal (JPL/PO.DAAC)",
    dataset="Global Mean Sea Level vital sign (satellite altimetry: TOPEX/Poseidon, Jason-1/2/3, Sentinel-6 Michael Freilich)",
    url="https://sealevel.nasa.gov/vital-signs/global-mean-sea-level/",
    landing_page="https://sealevel.nasa.gov/understanding-sea-level/key-indicators/global-mean-sea-level/",
    citation="NASA Sea Level Change Portal, Global Mean Sea Level; underlying dataset NASA_SSH_GMSL_INDICATOR (PO.DAAC).",
    temporal_resolution="About 7 days (aggregated here to calendar-month means)",
    spatial_coverage="Global ocean between ~66S and 66N (altimeter coverage)",
    baseline="Height relative to the 1993-2008 reference (series starts near 0 in 1993); annual cycle retained",
    typical_delay="Near-real-time; the series extended to decimal year 2026.82 (late October 2026) at retrieval.",
    raw_files=["nasa_sealevel/gmsl_vital_sign.csv"],
    notes=(
        "Extracted from the data array embedded in the NASA vital-sign page. The same series "
        "is distributed as NASA_SSH_GMSL_INDICATOR.txt on PO.DAAC (Earthdata login required); "
        "the pipeline uses that file instead when EARTHDATA_TOKEN is configured."
    ),
)

NSIDC = Source(
    agency="NSIDC (NASA DAAC) - Sea Ice Index, version 4",
    dataset="Sea Ice Index G02135 v4.0 - Northern Hemisphere monthly extent",
    url="https://noaadata.apps.nsidc.org/NOAA/G02135/north/monthly/data/",
    landing_page="https://nsidc.org/data/g02135",
    citation="Fetterer, F., K. Knowles, W. N. Meier, M. Savoie, and A. K. Windnagel. Sea Ice Index, Version 4. NSIDC.",
    temporal_resolution="Monthly (derived from daily passive-microwave data: NASA SMMR, DMSP SSM/I-SSMIS)",
    spatial_coverage="Northern Hemisphere (Arctic), 25 km polar stereographic grid",
    baseline="Absolute extent (million km2); 15% concentration threshold",
    typical_delay="Monthly files refreshed within the first days of the next month (files dated 2 Nov 2026 include October 2026).",
    raw_files=["nsidc/N_monthly_extent_area_v4.0.csv"],
    notes="December 1987 and January 1988 are missing in the source (satellite data gap); they are linearly interpolated for modelling only and flagged as estimated.",
)

POWER = Source(
    agency="NASA Langley Research Center - POWER project (MERRA-2 reanalysis)",
    dataset="POWER Monthly API v2.10, 126-point global grid sample (20 degree spacing, 60S-60N)",
    url="https://power.larc.nasa.gov/api/temporal/monthly/point",
    landing_page="https://power.larc.nasa.gov/",
    citation="NASA Prediction Of Worldwide Energy Resources (POWER) Project, NASA Langley Research Center; data from NASA GMAO MERRA-2.",
    temporal_resolution="Monthly (POWER also serves daily data)",
    spatial_coverage="126 grid points (lat -60..60 by 20, lon -170..170 by 20) combined with cos(latitude) area weights; polar caps not sampled",
    baseline="Absolute values; anomalies computed against 1991-2020 calendar-month climatology",
    typical_delay="Monthly aggregates are published after the month closes; MERRA-2 aerosol fields lag further (AOD available through July 2026 at retrieval).",
    raw_files=["nasa_power/grid20_global_sample_monthly.csv", "nasa_power/grid20_point_stats.csv"],
    notes=(
        "A 126-point sample is an index of large-scale behaviour, not a true global gridded mean. "
        "It is suitable for trend direction and anomaly detection; absolute values should not be "
        "compared with GPCP/IMERG global means."
    ),
)

PARAMETERS: dict[str, Parameter] = {
    p.id: p
    for p in [
        Parameter("gmst", "Global mean surface temperature anomaly", "Global temperature", "°C", GISTEMP,
                  fit_start="1970-01", tags=["temperature"], limitations=['El Niño/La Niña (ENSO) is not modelled explicitly; it shifts global temperature by roughly ±0.1-0.2 °C from year to year, which dominates a two-year outlook.', 'GISTEMP values are revised slightly every month as late station and ship reports arrive.', 'The October 2026 value had not been published at retrieval (GISTEMP releases mid-month).'],
                  description='The global average of near-surface air temperature over land and sea-surface temperature over the ocean, expressed as a departure from the 1951–1980 average. It is the primary indicator of global warming.'),
        Parameter("co2", "Atmospheric CO₂ concentration (Mauna Loa)", "CO₂", "ppm", NOAA_CO2, fit_start="1980-01",
                  tags=["atmosphere"], limitations=['Single-station record; recent months are provisional and can be revised by NOAA by a few tenths of a ppm.', 'The forecast extrapolates the recent growth rate; it assumes no abrupt change in global emissions or land/ocean uptake.'],
                  description='The monthly mean concentration of carbon dioxide in dry air at Mauna Loa Observatory, Hawaii — the longest continuous direct record of atmospheric CO₂. A seasonal cycle driven by Northern Hemisphere plant growth sits on top of a steady rise.'),
        Parameter("sst", "Global sea surface temperature anomaly", "Sea surface temperature", "°C", NCEI_OCEAN,
                  fit_start="1970-01", tags=["ocean", "temperature"], limitations=['ERSSTv5 is a NOAA reconstruction (the ocean input to NASA GISTEMP); NASA satellite SST products need an Earthdata login.', 'ENSO phase changes dominate year-to-year global ocean temperature and are not predicted explicitly.'],
                  description="The average temperature of the ocean's surface layer over the global ocean, as a departure from the 1901–2000 average. The ocean absorbs most of the excess heat in the climate system, and this record also carries the signature of El Niño and La Niña."),
        Parameter("gmsl", "Global mean sea level", "Sea level", "mm", NASA_GMSL, value_decimals=1, tags=["ocean"], limitations=['The most recent calendar month is built from fewer weekly samples than usual (partial month).', 'The annual cycle is retained in the NASA series, so month-to-month changes include seasonal water exchange between land and ocean.'],
                  description='The average height of the global ocean surface measured by satellite radar altimeters since 1993, relative to a reference level near the start of the record. It rises as sea water warms and expands and as glaciers and ice sheets add water; the annual cycle is kept.'),
        Parameter("arctic_ice", "Arctic sea ice extent", "Arctic sea ice", "million km²", NSIDC,
                  concern_direction="decrease", tags=["cryosphere"], limitations=['December 1987 and January 1988 are missing (satellite gap) and interpolated only for model fitting.', 'Summer extent is strongly controlled by weather in a given year, so single-year forecasts carry wide uncertainty even though the long-term decline is clear.'],
                  description='The area of the Arctic Ocean with at least 15% sea-ice cover, observed by passive-microwave satellites since late 1978. Extent peaks in March and reaches its minimum in September; summer ice is a sensitive indicator of Arctic warming.'),
        Parameter("precip", "Precipitation (global grid-sample index)", "Precipitation", "mm/day", POWER, concern_direction="none",
                  value_decimals=3, tags=["hydrology"], limitations=['This is a 126-point sample index (60°S-60°N) from MERRA-2-based POWER data, not a gridded global precipitation product such as GPCP or IMERG.', 'The latest months in POWER can come from a near-real-time stream and may be revised; the last 12 months are unusually wet in this index, so a projected decrease reflects expected return toward normal, not a downward trend.'],
                  description="Bias-corrected total precipitation from NASA's MERRA-2 reanalysis (via POWER), averaged with area weights over a 126-point global sample between 60°S and 60°N. It tracks large-scale changes in the global water cycle."),
        Parameter("land_temp", "Land surface air temperature anomaly", "Land temperature", "°C", GISTEMP_LAND,
                  fit_start="1970-01", tags=["temperature"], limitations=['Near-surface air temperature from land weather stations, not satellite land-surface skin temperature (MODIS LST needs an Earthdata login).'],
                  description='Near-surface air temperature measured at land weather stations worldwide, combined into a global index and expressed as a departure from the 1951–1980 average. Land warms faster than the ocean surface.'),
        Parameter("aod", "Aerosol optical depth at 550 nm (global grid-sample index)", "Aerosol optical depth",
                  "unitless", POWER, value_decimals=3, tags=["atmosphere", "pollution"], limitations=['Aerosol optical depth comes from the MERRA-2 reanalysis (a model constrained by satellite retrievals), sampled at 126 points; it is not a direct observation.', 'Episodic events (wildfire seasons, dust outbreaks, volcanic eruptions) drive much of the variability and cannot be predicted from past values; the historical trend is not statistically significant.', 'Latest available month is July 2026 (MERRA-2 aerosol fields lag the meteorology).'],
                  description='Aerosol optical depth at 550 nm — how strongly airborne particles such as dust, smoke, sea salt and pollution dim sunlight — from MERRA-2 (2001 onward) at the same 126 sample points. Higher values mean hazier air.'),
    ]
}
