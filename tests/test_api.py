"""
test_api.py: API / CONTRACT TESTS
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A "contract" is the promise the API makes to its consumers (the dashboard,
Metabase, anyone): which URLs exist, what parameters they accept, what JSON
shape comes back, and which bad requests are rejected. These tests lock that
promise, so a refactor can't silently break a consumer.

They use FastAPI's TestClient (see conftest.py) against the loaded database,
so they assert on *shape and rules*, never on exact row counts.

Run only these:  pytest -m api
"""

import pytest

pytestmark = pytest.mark.api


# ── Response shape ─────────────────────────────────────────────

def test_overview_shape(client):
    body = client.get("/api/overview").json()
    for key in ("facility_count", "sensor_count", "reading_count", "anomaly_count",
                "latest_reading_at", "avg_power_output_mw", "anomaly_rate_pct"):
        assert key in body
    assert body["anomaly_count"] <= body["reading_count"]
    assert 0 <= body["anomaly_rate_pct"] <= 100


def test_anomalies_shape_and_ordering(client):
    body = client.get("/api/anomalies", params={"limit": 25}).json()
    assert body["count"] == len(body["anomalies"]) <= 25
    assert body["z_threshold"] == 3.0
    scores = [a["z_score"] for a in body["anomalies"]]
    assert scores == sorted(scores, reverse=True), "must be sorted by z_score DESC"
    assert all(s > 3.0 for s in scores), "every row must exceed the threshold"


def test_ranking_is_complete_and_ranked(client):
    body = client.get("/api/facilities/ranking").json()
    assert body["count"] == len(body["facilities"]) > 0
    ranks = [f["overall_rank"] for f in body["facilities"]]
    assert ranks == sorted(ranks) and ranks[0] == 1


def test_output_trend_shape(client):
    body = client.get("/api/output-trend", params={"hours": 6}).json()
    assert body["hours"] == 6
    assert isinstance(body["points"], list)


def test_detection_quality_shape(client):
    body = client.get("/api/detection-quality").json()
    assert body["sensors"] and "total" in body
    assert {"precision_pct", "recall_pct"} <= set(body["total"])


# ── Parameters do what they say ────────────────────────────────

def test_higher_threshold_returns_fewer_anomalies(client):
    loose = client.get("/api/anomalies", params={"z_threshold": 2, "limit": 1000}).json()
    strict = client.get("/api/anomalies", params={"z_threshold": 5, "limit": 1000}).json()
    assert strict["count"] <= loose["count"]


@pytest.mark.parametrize("ftype", ["wind", "solar", "substation"])
def test_facility_type_filter(client, ftype):
    body = client.get("/api/anomalies", params={"facility_type": ftype, "limit": 50}).json()
    assert all(a["facility_type"] == ftype for a in body["anomalies"])


# ── Input validation: bad requests are rejected with 422 ───────

@pytest.mark.parametrize("path, params", [
    ("/api/anomalies", {"z_threshold": 0.5}),    # below ge=1.0
    ("/api/anomalies", {"z_threshold": 11}),     # above le=10.0
    ("/api/anomalies", {"limit": 0}),
    ("/api/anomalies", {"limit": 1001}),
    ("/api/anomalies", {"z_threshold": "abc"}),  # wrong type
    ("/api/output-trend", {"hours": 0}),
    ("/api/output-trend", {"hours": 169}),
    ("/api/detection-quality", {"z_threshold": 0}),
])
def test_invalid_parameters_are_rejected(client, path, params):
    assert client.get(path, params=params).status_code == 422


# ── HTTP behaviour & security basics ───────────────────────────

def test_unknown_route_is_404(client):
    assert client.get("/api/does-not-exist").status_code == 404


def test_read_only_api_rejects_post(client):
    assert client.post("/api/anomalies").status_code == 405


def test_cors_header_present_for_dashboard(client):
    response = client.get("/health", headers={"Origin": "https://example.org"})
    assert "access-control-allow-origin" in response.headers


def test_sql_injection_in_filter_is_inert(client, db):
    """
    facility_type is user input that ends up next to SQL. It is validated against an
    allow-list (wind/solar/substation) and passed as a bound parameter, so the
    payload is rejected with 422 and the table survives.
    """
    payload = "wind'; DROP TABLE readings; --"
    response = client.get("/api/anomalies", params={"facility_type": payload})
    assert response.status_code == 422
    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM readings")
        assert cur.fetchone()[0] > 0
