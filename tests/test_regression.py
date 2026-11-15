"""
test_regression.py: REGRESSION TESTS (golden dataset)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Regression = "did my change break something that used to work?". The recipe:

  1. Build a tiny dataset by hand whose correct answers we can work out on paper.
  2. Run the real API (and therefore the real SQL) on it.
  3. Compare against the answers that are written down below ("golden values").

If someone edits the SQL in api.py and the numbers change, this fails and shows
exactly which number moved, before the change reaches the dashboard.

The golden data lives in its own throw-away schema (`golden_regression`) and the
API is pointed at it, so it never touches or depends on your real data.

The dataset (all readings every 5 minutes in March 2024):

  Golden Wind   (wind, 100 MW)  sensor 1  power_output
      20 clean readings alternating 10 / 12   -> mean 11, sample stddev 1.0260
       1 injected spike  = 100                -> z = 86.7  (flagged)
       1 injected drop   = 0                  -> z = 10.7  (flagged)
                           sensor 3  temperature
      19 clean readings = 10 and 1 clean outlier = 30
                                              -> mean 11, stddev 4.4721, z(30) = 4.25
                                                 flagged but NOT injected = false positive
       1 injected value  = 10.5 (z = 0.11)    -> real fault the detector misses
  Golden Solar  (solar, 20 MW)   sensor 2  power_output
      20 clean readings all = 10              -> stddev 0 (edge case: z must be 0, no crash)

Run only these:  pytest -m regression
"""

import psycopg2.extras
import pytest

import api
from db_connection import get_connection

pytestmark = pytest.mark.regression

SCHEMA = "golden_regression"


def _build_golden_schema():
    conn = get_connection()
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
        cur.execute(f"CREATE SCHEMA {SCHEMA}")
        cur.execute(f"SET search_path TO {SCHEMA}")
        cur.execute("""
            CREATE TABLE facilities (
                facility_id SERIAL PRIMARY KEY, facility_name VARCHAR(100) NOT NULL,
                facility_type VARCHAR(50) NOT NULL, country VARCHAR(50) NOT NULL,
                capacity_mw NUMERIC(8,2) NOT NULL, commissioned_year SMALLINT NOT NULL);
            CREATE TABLE sensors (
                sensor_id SERIAL PRIMARY KEY, facility_id INT NOT NULL REFERENCES facilities,
                sensor_type VARCHAR(50) NOT NULL, unit VARCHAR(20) NOT NULL);
            CREATE TABLE readings (
                reading_id BIGSERIAL PRIMARY KEY, sensor_id INT NOT NULL REFERENCES sensors,
                recorded_at TIMESTAMPTZ NOT NULL, value NUMERIC(10,4),
                is_anomaly BOOLEAN DEFAULT FALSE);
        """)
        cur.execute("""
            INSERT INTO facilities (facility_name, facility_type, country, capacity_mw, commissioned_year)
            VALUES ('Golden Wind', 'wind', 'Finland', 100, 2015),
                   ('Golden Solar', 'solar', 'Sweden', 20, 2020)""")
        cur.execute("""
            INSERT INTO sensors (facility_id, sensor_type, unit)
            VALUES (1, 'power_output', 'MW'), (2, 'power_output', 'MW'), (1, 'temperature', 'C')""")

        series = {                     # sensor_id -> [(value, is_anomaly), ...]
            1: [(10 if i % 2 == 0 else 12, False) for i in range(20)] + [(100, True), (0, True)],
            2: [(10, False)] * 20,
            3: [(10, False)] * 19 + [(30, False), (10.5, True)],
        }
        for sensor, values in series.items():
            for i, (v, flag) in enumerate(values):
                cur.execute(
                    "INSERT INTO readings (sensor_id, recorded_at, value, is_anomaly) "
                    "VALUES (%s, %s::timestamptz + %s * INTERVAL '1 minute', %s, %s)",
                    (sensor, "2024-03-01 00:00+00", 5 * i, v, flag))
    conn.close()


def _drop_golden_schema():
    conn = get_connection()
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
    conn.close()


@pytest.fixture(scope="module")
def golden_client():
    """A TestClient whose API reads from the golden schema instead of public."""
    from fastapi.testclient import TestClient

    _build_golden_schema()

    def golden_connection():
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {SCHEMA}")  # no public: can't leak real data
        conn.commit()
        return conn

    patch = pytest.MonkeyPatch()
    patch.setattr(api, "get_connection", golden_connection)
    try:
        yield TestClient(api.app)
    finally:
        patch.undo()
        _drop_golden_schema()


def test_golden_overview(golden_client):
    body = golden_client.get("/api/overview").json()
    assert body["facility_count"] == 2
    assert body["sensor_count"] == 3
    assert body["reading_count"] == 63
    assert body["anomaly_count"] == 3
    assert body["anomaly_rate_pct"] == 4.76
    assert body["avg_power_output_mw"] == pytest.approx(10.5)  # (20*11 + 20*10) / 40


def test_golden_anomalies(golden_client):
    body = golden_client.get("/api/anomalies").json()
    assert body["count"] == 3
    # Ordered by z-score: spike (100), dropout (0), clean outlier (30)
    values = [a["value"] for a in body["anomalies"]]
    assert values == [100.0, 0.0, 30.0]
    z = [a["z_score"] for a in body["anomalies"]]
    assert z == pytest.approx([86.74, 10.72, 4.249], abs=0.01)
    assert [a["sensor_type"] for a in body["anomalies"]] == ["power_output", "power_output", "temperature"]


def test_golden_zero_stddev_sensor_never_flagged(golden_client):
    """Golden Solar has stddev 0; the CASE in the SQL must give z = 0, not divide by zero."""
    body = golden_client.get("/api/anomalies", params={"z_threshold": 1}).json()
    assert all(a["facility_name"] != "Golden Solar" for a in body["anomalies"])


def test_golden_anomalies_threshold_boundary(golden_client):
    # z(30) = 4.249 sits between 4 and 5, so raising the threshold must drop exactly that row.
    assert golden_client.get("/api/anomalies", params={"z_threshold": 4}).json()["count"] == 3
    assert golden_client.get("/api/anomalies", params={"z_threshold": 5}).json()["count"] == 2


def test_golden_ranking(golden_client):
    facilities = golden_client.get("/api/facilities/ranking").json()["facilities"]
    assert [(f["facility_name"], f["overall_rank"], f["avg_efficiency_pct"]) for f in facilities] == [
        ("Golden Solar", 1, 50.0),   # 10 MW average / 20 MW capacity
        ("Golden Wind", 2, 11.0),    # 11 MW average / 100 MW capacity
    ]


def test_golden_detection_quality(golden_client):
    body = golden_client.get("/api/detection-quality").json()
    by_type = {row["sensor_type"]: row for row in body["sensors"]}

    power = by_type["power_output"]
    assert (power["readings"], power["injected"], power["flagged"], power["true_positives"]) == (42, 2, 2, 2)
    assert (power["spikes"], power["spikes_flagged"], power["drops"], power["drops_flagged"]) == (1, 1, 1, 1)
    assert (power["precision_pct"], power["recall_pct"]) == (100.0, 100.0)

    temp = by_type["temperature"]   # one false positive and one missed fault
    assert (temp["readings"], temp["injected"], temp["flagged"], temp["true_positives"]) == (21, 1, 1, 0)
    assert (temp["precision_pct"], temp["recall_pct"]) == (0.0, 0.0)

    total = body["total"]
    assert (total["readings"], total["injected"], total["flagged"], total["true_positives"]) == (63, 3, 3, 2)
    assert (total["precision_pct"], total["recall_pct"]) == (66.7, 66.7)
