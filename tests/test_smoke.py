"""
test_smoke.py: SMOKE TESTS
~~~~~~~~~~~~~~~~~~~~~~~~~~
Goal: answer one question quickly, "is the system alive at all?". If any of
these fail there is no point running the slower suites.

Smoke tests are shallow and wide: touch every critical piece (DB, API,
dashboard files) but verify only that it exists and responds, not that its
numbers are right (that is the job of the API / integration / regression tests).

Run only these:  pytest -m smoke
"""

import json
import os

import pytest

pytestmark = pytest.mark.smoke

CORE_TABLES = ("facilities", "sensors", "readings")
DASHBOARD_DATA = (
    "api_snapshot.json",
    "fingrid_2023_daily.json",
    "fingrid_recent_daily.json",
    "wind_validation_2023.json",
    "detection_thresholds.json",
    "facility_ranking.json",
    "anomaly_examples.json",
    "zero_dropout_rules.json",
    "sql_sources.json",
    "engineering.json",
)


def test_database_is_reachable(db):
    with db.cursor() as cur:
        cur.execute("SELECT 1")
        assert cur.fetchone()[0] == 1


@pytest.mark.parametrize("table", CORE_TABLES)
def test_core_table_has_rows(db, table):
    with db.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {table}")  # table comes from a constant
        assert cur.fetchone()[0] > 0, f"{table} is empty: was the pipeline run?"


def test_api_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_api_main_endpoint_responds(client):
    assert client.get("/api/overview").status_code == 200


def test_openapi_schema_is_served(client):
    """Swagger UI depends on this; also proves every route registered cleanly."""
    response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    for route in ("/health", "/api/overview", "/api/anomalies",
                  "/api/detection-quality", "/api/facilities/ranking"):
        assert route in paths


def test_dashboard_page_exists(project_root):
    index = os.path.join(project_root, "docs", "index.html")
    assert os.path.getsize(index) > 1000


@pytest.mark.parametrize("name", DASHBOARD_DATA)
def test_dashboard_data_is_valid_json(project_root, name):
    path = os.path.join(project_root, "docs", "data", name)
    with open(path, encoding="utf-8") as fh:
        assert json.load(fh), f"{name} parsed but is empty"
