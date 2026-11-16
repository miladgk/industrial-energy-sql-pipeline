"""
test_dashboard_data.py: DATA CONTRACT TESTS for docs/data/
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The dashboard is a static page that shows numbers from pre-built JSON files.
Those files are only trustworthy if they agree with each other and with the
repository. These tests need no database: they read the files and the SQL.

  - the SQL text shown on the page is byte-for-byte the SQL in the repo
    (fails when a .sql file is edited without re-running the export)
  - the numbers inside each file are internally consistent

Rebuild the files with scripts/export_dashboard_data.py (see its docstring).
Run only these:  pytest -m data
"""

import json
import os

import pytest

pytestmark = pytest.mark.data

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA = os.path.join(ROOT, "docs", "data")


def _load(name):
    with open(os.path.join(DATA, name), encoding="utf-8") as fh:
        return json.load(fh)


def test_sql_shown_on_page_matches_repository():
    for item in _load("sql_sources.json")["files"]:
        with open(os.path.join(ROOT, item["path"]), encoding="utf-8") as fh:
            assert item["sql"] == fh.read(), (
                f"{item['path']} changed: run scripts/export_dashboard_data.py --parts sql")
        assert item["url"].endswith(item["path"])


def test_engineering_facts_are_self_consistent():
    eng = _load("engineering.json")
    b = eng["benchmark"]
    assert b["indexed_ms"] < b["no_index_ms"] and b["partitioned_ms"] < b["no_index_ms"]
    assert b["speedup_index_vs_none"] == pytest.approx(b["no_index_ms"] / b["indexed_ms"], abs=0.1)   # times are rounded
    p = eng["partitioning"]
    assert p["partition_count"] == len(p["partitions"])
    assert sum(x["rows"] for x in p["partitions"]) == p["total_rows"]
    t = eng["tests"]
    assert t["total"] == sum(t["by_layer"].values()) and all(n > 0 for n in t["by_layer"].values())



# ── Fingrid warehouse files (built by refresh_fingrid.yml) ─────

def test_forecast_scorecard_is_complete_and_consistent():
    from datetime import date

    sc = _load("forecast_scorecard.json")
    days = (date.fromisoformat(sc["window_end_exclusive"]) - date.fromisoformat(sc["window_start"])).days
    assert days == 365
    products = {(r["variable"], r["product"]) for r in sc["summary"]}
    assert products == {(v, p) for v in ("wind", "consumption") for p in ("day_ahead", "intraday")}
    for r in sc["summary"]:
        assert r["slots"] >= 0.9 * days * 96, f"{r['variable']}/{r['product']}: too few 15-minute slots"
        assert r["mae_mw"] >= abs(r["bias_mw"]) - 0.1          # |mean error| can never exceed mean |error|
        assert r["rmse_mw"] >= r["mae_mw"] - 0.1
        assert (r["mae_pct_of_capacity"] is not None) == (r["variable"] == "wind")
    for v, p in products:
        hours = [r["hour_fi"] for r in sc["by_hour"] if r["variable"] == v and r["product"] == p]
        assert sorted(hours) == list(range(24))
    for v in ("wind", "consumption"):
        misses = [r for r in sc["biggest_misses"] if r["variable"] == v]
        assert [r["rank"] for r in misses] == [1, 2, 3, 4, 5]
        assert [r["mae_mw"] for r in misses] == sorted((r["mae_mw"] for r in misses), reverse=True)
    bins = sc["balancing"]["bins"]
    assert bins[0]["bin_from_mw"] is None and bins[-1]["bin_to_mw"] is None
    assert all(a["bin_to_mw"] == b["bin_from_mw"] for a, b in zip(bins, bins[1:]))
    for key in ("r_surprise_vs_mfrr_need", "r_surprise_vs_net_mfrr", "r_surprise_vs_price"):
        assert -1 <= sc["balancing"][key] <= 1, key
    assert all(b["mean_mfrr_up_mw"] >= 0 >= b["mean_mfrr_down_mw"] for b in bins)   # Fingrid's sign convention
    assert sc["sql"] and all(os.path.exists(os.path.join(ROOT, p)) for p in sc["sql"])


def test_recent_daily_grid_file_covers_the_last_year():
    recent = _load("fingrid_recent_daily.json")
    assert len(recent["days"]) >= 360
    assert recent["days"][-1]["day"] < recent["window_end_exclusive"]
    assert all(d["wind_mw"] >= 0 and d["consumption_mw"] > 0 for d in recent["days"])


def test_co2_forecast_is_complete_and_consistent():
    from datetime import date, timedelta

    c = _load("co2_forecast.json")
    generated = date.fromisoformat(c["generated_at"][:10])
    target = date.fromisoformat(c["target_day"])
    assert target - generated in (timedelta(0), timedelta(days=1), timedelta(days=2))   # today or tomorrow in Finland
    hours = c["hours"]
    assert 23 <= len(hours) <= 25                                  # DST days have 23 or 25 hours
    assert [h["hour_start"] for h in hours] == sorted(h["hour_start"] for h in hours)
    assert sorted(h["rank_cleanest"] for h in hours)[0] == 1
    by_start = {h["hour_start"]: h for h in hours}
    assert by_start[c["cleanest_hour"]["hour_start"]]["rank_cleanest"] == 1
    assert all(c["cleanest_hour"]["co2"] <= h["co2_forecast"] <= c["dirtiest_hour"]["co2"] for h in hours)
    assert min(h["co2_forecast"] for h in hours) <= c["best_3h"]["co2"] <= max(h["co2_forecast"] for h in hours)
    assert all(h["co2_forecast"] > 0 for h in hours)

    b = c["backtest"]
    assert b["days"] >= 300 and b["hours"] >= 23 * b["days"]
    assert b["mae_model_g"] < b["mae_naive_g"], "the model must beat the naive baseline to be published"
    assert b["best_hour_g"] <= b["co2_at_pick_g"] and b["saving_pct"] <= b["achievable_pct"]
    assert 0 <= b["pick_in_top3_pct"] <= 100
    assert date.fromisoformat(c["yesterday"]["day"]) == date.fromisoformat(c["target_day"]) - timedelta(
        days=2 if c["target_is_tomorrow"] else 1)


def test_grid_events_file_is_consistent():
    d = _load("grid_events.json")
    kinds = {"frequency_low", "frequency_high", "nuclear_drop", "low_inertia", "price_spike"}
    assert set(d["counts"]) == kinds == set(d["top"])
    for k, c in d["counts"].items():
        assert 0 <= c["last_30_days"] <= c["year"], k
    assert [m["minute_of_hour"] for m in d["frequency_by_minute"]] == list(range(60))
    assert all(0 <= m["pct_outside"] <= 100 for m in d["frequency_by_minute"])
    for e in d["recent"] + d["recent_frequency"]:
        assert e["start_time"] < e["end_time"] and e["kind"] in kinds
    assert [e["start_time"] for e in d["recent"]] == sorted((e["start_time"] for e in d["recent"]), reverse=True)
    lows = d["top"]["frequency_low"]
    assert all(e["peak"] < 49.9 and e["peak"] >= 45 for e in lows), "invalid 0 Hz samples must never become events"
    assert all(e["peak"] <= -400 and e["freq_min_nearby"] is not None for e in d["nuclear_crosscheck"])
    q = d["data_quality"]
    assert 0 < q["valid"] <= q["minutes_in_window"]


def test_temperature_file_is_consistent():
    t = _load("temperature.json")
    assert {f["day_type"] for f in t["fits"]} == {"weekday", "weekend"}
    for f in t["fits"]:
        assert 5 <= f["balance_point_c"] <= 20
        assert f["mw_per_degree"] > 0, "colder days must use more electricity"
        assert 0 <= f["r2"] <= 1
    assert sum(f["days"] for f in t["fits"]) == t["days"] >= 300
    assert sum(b["weekday_days"] + b["weekend_days"] for b in t["bins"]) == t["days"]
    assert all(b["to_c"] - b["from_c"] == 3 for b in t["bins"])
    assert t["coldest_day"]["temp_c"] < t["warmest_day"]["temp_c"]
