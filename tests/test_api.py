import pytest
from fastapi.testclient import TestClient

from api.main import DATA, app

pytestmark = pytest.mark.skipif(not DATA.exists(), reason="run the pipeline first")
client = TestClient(app)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["parameters"] == 8


def test_parameters_list():
    r = client.get("/api/parameters").json()
    ids = {p["id"] for p in r}
    assert {"gmst", "co2", "sst", "gmsl", "arctic_ice", "precip", "land_temp", "aod"} == ids


@pytest.mark.parametrize("h,end", [(6, "2027-04"), (12, "2027-10"), (18, "2028-04"), (24, "2028-10")])
def test_forecast_horizons(h, end):
    r = client.get(f"/api/forecast/co2?horizon={h}").json()
    assert r["dates"][-1] == end and len(r["mean"]) == len(r["dates"])


def test_forecast_other_model_and_errors():
    assert client.get("/api/forecast/gmst?model=naive&horizon=12").json()["model"] == "naive"
    assert client.get("/api/forecast/gmst?model=nope").status_code == 404
    assert client.get("/api/forecast/gmst?horizon=7").status_code == 422
    assert client.get("/api/forecast/ndvi").status_code == 404  # removed: no data available
    assert client.get("/api/parameters/xyz").status_code == 404


def test_compare_and_maps():
    r = client.get("/api/compare?ids=co2,gmst&normalize=zscore").json()
    assert len(r["series"]) == 2
    assert len(client.get("/api/map/gistemp_grid").json()["cells"]) == 648
    assert client.get("/api/map/nope").status_code == 404
    assert client.get("/api/ranking").status_code == 200
    assert client.get("/api/insights").status_code == 200


def test_admin_refresh_requires_token():
    assert client.post("/api/admin/refresh").status_code == 403
