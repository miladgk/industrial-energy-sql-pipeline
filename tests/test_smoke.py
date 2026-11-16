"""
test_smoke.py: SMOKE TESTS
~~~~~~~~~~~~~~~~~~~~~~~~~~
Fast "is anything alive at all?" checks, run first in CI: the database answers,
the warehouse holds data, the API starts and registers its routes, and the
dashboard page and its data files exist.

Run only these:  pytest -m smoke
"""

import json
import os

import pytest

pytestmark = pytest.mark.smoke

DASHBOARD_DATA = (
    "fingrid_recent_daily.json",
    "forecast_scorecard.json",
    "co2_forecast.json",
    "grid_events.json",
    "temperature.json",
    "sql_sources.json",
    "engineering.json",
)
API_ROUTES = ("/health", "/api/datasets", "/api/latest", "/api/forecast-scorecard",
              "/api/forecast-error-by-hour", "/api/co2-forecast", "/api/grid-events", "/api/temperature-sensitivity")


def test_database_is_reachable(db):
    with db.cursor() as cur:
        cur.execute("SELECT 1")
        assert cur.fetchone()[0] == 1


def test_warehouse_has_data(db):
    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*), COUNT(DISTINCT dataset_id) FROM fingrid_observation")
        rows, datasets = cur.fetchone()
    db.rollback()
    assert rows > 0 and datasets > 0, "fingrid_observation is empty: restore the snapshot or run src/sync_fingrid.py"


def test_api_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi_schema_is_served(client):
    """Swagger UI depends on this; it also proves every route registered."""
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert set(API_ROUTES) <= set(response.json()["paths"])


def test_dashboard_page_exists(project_root):
    assert os.path.getsize(os.path.join(project_root, "docs", "index.html")) > 1000


@pytest.mark.parametrize("name", DASHBOARD_DATA)
def test_dashboard_data_is_valid_json(project_root, name):
    with open(os.path.join(project_root, "docs", "data", name), encoding="utf-8") as fh:
        assert json.load(fh), f"{name} parsed but is empty"
