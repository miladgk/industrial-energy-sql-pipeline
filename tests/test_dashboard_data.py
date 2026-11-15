"""
test_dashboard_data.py: DATA CONTRACT TESTS for docs/data/
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The dashboard is a static page that shows numbers from pre-built JSON files.
Those files are only trustworthy if they agree with each other and with the
repository. These tests need no database: they read the files and the SQL.

  - the SQL text shown on the page is byte-for-byte the SQL in the repo
    (fails when a .sql file is edited without re-running the export)
  - every derived file was built from the same dataset as the API snapshot
  - the z = 3 row of the threshold sweep equals the published scorecard
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


@pytest.fixture(scope="module")
def snapshot():
    return _load("api_snapshot.json")


def test_sql_shown_on_page_matches_repository():
    for item in _load("sql_sources.json")["files"]:
        with open(os.path.join(ROOT, item["path"]), encoding="utf-8") as fh:
            assert item["sql"] == fh.read(), (
                f"{item['path']} changed: run scripts/export_dashboard_data.py --parts sql")
        assert item["url"].endswith(item["path"])


@pytest.mark.parametrize("name", [
    "detection_thresholds.json", "facility_ranking.json", "anomaly_examples.json",
    "zero_dropout_rules.json", "engineering.json",
])
def test_derived_files_come_from_the_snapshot_dataset(snapshot, name):
    dataset = _load(name)["dataset"]
    assert dataset["reading_count"] == snapshot["overview"]["reading_count"]
    assert dataset["anomaly_count"] == snapshot["overview"]["anomaly_count"]


def test_threshold_sweep_agrees_with_published_scorecard(snapshot):
    sweep = {t["z_threshold"]: t for t in _load("detection_thresholds.json")["thresholds"]}
    assert sorted(sweep) == [x / 2 for x in range(2, 21)]
    for key, value in snapshot["detection"]["total"].items():
        assert sweep[3.0]["total"][key] == value, key


def test_stricter_threshold_never_flags_more():
    flagged = [t["total"]["flagged"] for t in _load("detection_thresholds.json")["thresholds"]]
    assert flagged == sorted(flagged, reverse=True)


def test_anomaly_examples_are_complete_and_consistent():
    examples = _load("anomaly_examples.json")["examples"]
    assert {e["kind"] for e in examples} == {"strongest_flag", "injected_zero"}
    for e in examples:
        assert len(e["neighbourhood"]) == 25, "+/- 60 min at 5-minute resolution"
        centre = [p for p in e["neighbourhood"] if p["recorded_at"] == e["recorded_at"]]
        assert centre and centre[0]["value"] == e["value"]
        assert e["flagged"] == (e["z_score"] > 3)
        if e["kind"] == "injected_zero":
            assert e["value"] == 0 and e["is_anomaly"]


def test_zero_dropout_totals_match_per_sensor_rows():
    data = _load("zero_dropout_rules.json")
    for total in data["totals"]:
        rows = [r for r in data["by_sensor"] if r["rule"] == total["rule"]]
        assert total["caught"] == sum(r["caught"] for r in rows)
        assert total["injected_zeros"] == sum(r["injected_zeros"] for r in rows)


def test_engineering_facts_are_self_consistent():
    eng = _load("engineering.json")
    bench = eng["benchmark"]
    assert bench["speedup_composite_vs_single"] == round(
        bench["single_column_index_ms"] / bench["composite_index_ms"], 1)
    assert eng["partitioning"]["partition_count"] == len(eng["partitioning"]["partitions"])
    assert "(sensor_id, recorded_at)" in eng["partitioning"]["composite_index"]
    assert sum(eng["tests"]["by_layer"].values()) <= eng["tests"]["total"]
    rows = [p["rows"] for p in eng["partitioning"]["partitions"]]
    assert sum(rows) == eng["dataset"]["reading_count"], "every reading lives in exactly one partition"


def test_ranking_is_ordered():
    facilities = _load("facility_ranking.json")["facilities"]
    ranks = [f["overall_rank"] for f in facilities]
    assert ranks == sorted(ranks) and len(facilities) == _load("facility_ranking.json")["count"]
