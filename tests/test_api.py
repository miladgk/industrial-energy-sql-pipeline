"""
test_api.py: API CONTRACT TESTS
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The FastAPI service through its full HTTP stack (TestClient): response shapes,
input validation, and that every number equals what the database or the
underlying .sql file returns on its own. The database is the restored
warehouse snapshot (real Fingrid data), so the tests ask it what to expect
instead of hard-coding values that change daily.

Run only these:  pytest -m api
"""

import os

import pytest

pytestmark = pytest.mark.api

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _one(db, sql, params=None):
    with db.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    db.rollback()
    return row


@pytest.fixture(scope="module")
def known_day(db):
    """The newest Finnish day whose CO2 forecast has every hour (inputs are complete)."""
    row = _one(db, """
        SELECT day_fi FROM co2_hourly WHERE residual_load_mw IS NOT NULL
        GROUP BY day_fi HAVING COUNT(*) >= 23 ORDER BY day_fi DESC LIMIT 1 OFFSET 1""")
    if row is None:
        pytest.skip("no complete day in the warehouse")
    return row[0]


def test_datasets_match_the_warehouse(client, db):
    body = client.get("/api/datasets").json()
    total, kinds = _one(db, "SELECT COUNT(*), (SELECT COUNT(*) FROM fingrid_dataset) FROM fingrid_observation")
    assert body["total_rows"] == total
    assert len(body["datasets"]) == kinds
    assert {"dataset_id", "key", "unit", "rows", "first_start", "last_end"} <= set(body["datasets"][0])


def test_latest_returns_the_newest_slot_per_dataset(client, db):
    rows = client.get("/api/latest").json()["latest"]
    wind = next(r for r in rows if r["dataset_id"] == 75)
    newest = _one(db, "SELECT max(start_time) FROM fingrid_observation WHERE dataset_id = 75")[0]
    assert wind["start_time"] == newest.isoformat()


def test_forecast_scorecard_equals_the_sql_file(client, db):
    from analysis_window import default_window

    body = client.get("/api/forecast-scorecard", params={"days": 30}).json()
    assert len(body["products"]) == 4
    with open(os.path.join(ROOT, "sql", "analysis", "13_forecast_scorecard.sql"), encoding="utf-8") as fh, db.cursor() as cur:
        cur.execute(fh.read(), default_window(days=30))
        direct = {(r[0], r[1]): r[3] for r in cur.fetchall()}
    db.rollback()
    for p in body["products"]:
        assert p["mae_mw"] == pytest.approx(direct[(p["variable"], p["product"])])
        assert p["mae_mw"] >= abs(p["bias_mw"])


def test_error_by_hour_filters_one_variable(client):
    body = client.get("/api/forecast-error-by-hour", params={"variable": "consumption", "days": 30}).json()
    assert {h["variable"] for h in body["hours"]} == {"consumption"}
    assert {h["hour_fi"] for h in body["hours"]} == set(range(24))


def test_co2_forecast_for_a_known_day(client, known_day):
    body = client.get("/api/co2-forecast", params={"day": known_day.isoformat()}).json()
    assert body["day"] == known_day.isoformat()
    assert 23 <= len(body["hours"]) <= 25
    assert sorted(h["rank_cleanest"] for h in body["hours"])[0] == 1
    assert all(h["co2_forecast"] > 0 for h in body["hours"])


def test_grid_events_kind_filter_and_limit(client):
    every = client.get("/api/grid-events", params={"days": 365, "limit": 1000}).json()
    lows = client.get("/api/grid-events", params={"days": 365, "kind": "frequency_low", "limit": 1000}).json()
    assert every["count"] == len(every["events"]), "limit 1000 must cover a year of events"
    assert lows["count"] == sum(e["kind"] == "frequency_low" for e in every["events"])
    assert all(e["kind"] == "frequency_low" and e["peak"] < 49.9 for e in lows["events"])
    assert len(client.get("/api/grid-events", params={"days": 365, "limit": 3}).json()["events"]) <= 3
    starts = [e["start_time"] for e in every["events"]]
    assert starts == sorted(starts, reverse=True)


def test_temperature_sensitivity_has_both_day_types(client):
    fits = client.get("/api/temperature-sensitivity").json()["fits"]
    assert {f["day_type"] for f in fits} == {"weekday", "weekend"}
    assert all(f["mw_per_degree"] > 0 and 5 <= f["balance_point_c"] <= 20 for f in fits)


@pytest.mark.parametrize("path,params", [
    ("/api/forecast-scorecard", {"days": 0}),
    ("/api/forecast-scorecard", {"days": 401}),
    ("/api/forecast-error-by-hour", {"variable": "solar"}),
    ("/api/grid-events", {"kind": "earthquake"}),
    ("/api/grid-events", {"limit": 0}),
    ("/api/temperature-sensitivity", {"days": 10}),
    ("/api/co2-forecast", {"day": "2001-01-01"}),
    ("/api/co2-forecast", {"day": "not-a-date"}),
])
def test_invalid_parameters_are_rejected(client, path, params):
    assert client.get(path, params=params).status_code == 422


def test_co2_forecast_without_inputs_is_404(client):
    """The day after tomorrow is allowed but never has inputs: Fingrid publishes one day ahead."""
    from datetime import timedelta

    from analysis_window import tomorrow_fi

    day = tomorrow_fi() + timedelta(days=1)
    assert client.get("/api/co2-forecast", params={"day": day.isoformat()}).status_code == 404
