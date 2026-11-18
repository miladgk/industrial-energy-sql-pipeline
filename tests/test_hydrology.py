"""
test_hydrology.py: the water archive (src/hydrology.py) and the storage model (src/hydro_flex.py)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
No network:
  - SYKE's 500-row pages are followed to the end; links off the API are refused
  - NVE's weekly filling becomes one series per Norwegian price area
  - fetching twice stores nothing new; a dump + restore gives the rows back
REGRESSION, synthetic year with a known answer:
  - when hydro absorbs more wind on full-reservoir days, the interaction model finds it
  - the shares at a given storage come with intervals that cover the truth
  - each hour gets the water state of the day before, never of its own day
"""

import os
import sys
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

import hydro_flex as hf  # noqa: E402
import hydrology as hy  # noqa: E402


def _fake_api(pages: int = 3):
    """SYKE answers in pages of two rows with nextLinks; NVE answers once."""
    def getter(url):
        if url.startswith(hy.NVE_URL):
            return [{"omrType": "EL", "omrnr": 1, "dato_Id": "2001-01-07", "fyllingsgrad": 0.5},
                    {"omrType": "VASS", "omrnr": 1, "dato_Id": "2001-01-07", "fyllingsgrad": 0.9},
                    {"omrType": "EL", "omrnr": 4, "dato_Id": "2001-01-07", "fyllingsgrad": 0.7}]
        k = int(url.split("skip=")[1]) if "skip=" in url else 0
        rows = [{"Aika": f"2001-01-{k * 2 + i + 1:02d}T00:00:00", "Arvo": f"{100 + k * 2 + i}.00"} for i in range(2)]
        nxt = {"odata.nextLink": f"{hy.SYKE_URL}/X?skip={k + 1}"} if k + 1 < pages else {}
        return {"value": rows, **nxt}
    return getter


@pytest.mark.smoke
def test_syke_pages_are_followed_and_foreign_links_refused():
    rows = hy.syke_rows("level_lokka", date(2001, 1, 1), _fake_api(3), pause=0)
    assert [r[1] for r in rows] == [date(2001, 1, d) for d in range(1, 7)]
    assert rows[-1] == ("level_lokka", date(2001, 1, 6), 105.0)
    with pytest.raises(ValueError):
        hy._get("https://example.com/odata")
    assert hy.nve_rows(_fake_api()) == [("nve_no1", date(2001, 1, 7), 0.5), ("nve_no4", date(2001, 1, 7), 0.7)]


@pytest.fixture
def archive(db, monkeypatch):
    monkeypatch.setattr(hy, "SERIES", {"test_level": ("Vedenkorkeus", 1, "cm", "test")})
    monkeypatch.setattr(hy, "NVE_AREAS", (99,))                    # no NVE rows in the test
    yield db
    with db.cursor() as cur:
        cur.execute("DELETE FROM hydrology_daily WHERE series = 'test_level'")
    db.commit()


@pytest.mark.integration
def test_fetch_is_idempotent_and_survives_dump_restore(archive, tmp_path):
    first = hy.fetch(archive, _fake_api(3), pause=0)
    assert first["test_level"] == 6
    hy.fetch(archive, _fake_api(3), pause=0)
    with archive.cursor() as cur:
        cur.execute("SELECT count(*) FROM hydrology_daily WHERE series = 'test_level'")
        assert cur.fetchone()[0] == 6
    archive.rollback()
    path = str(tmp_path / "h.csv.gz")
    hy.dump(archive, path)
    with archive.cursor() as cur:
        cur.execute("DELETE FROM hydrology_daily WHERE series = 'test_level'")
    archive.commit()
    assert hy.restore(archive, path) == 6


# ── The storage model ──────────────────────────────────────────

START = datetime(2024, 1, 1, tzinfo=timezone.utc)
TRUE_HYDRO = 0.10          # share of +1 MW of wind hydro absorbs at normal storage ...
TRUE_PER_SD = 0.08         # ... and how much more per standard deviation fuller


def _synthetic(days=400, seed=2):
    rng = np.random.default_rng(seed)
    storage = np.cumsum(rng.normal(0, 0.15, days)); storage = (storage - storage.mean()) / storage.std()
    inflow = rng.normal(0, 1, days)
    state = [{"day": (START + timedelta(days=d)).date(), "storage_z": storage[d], "inflow_z": inflow[d]} for d in range(days)]
    rows = []
    for h in range(24 * days):
        t = START + timedelta(hours=h)
        d = (t.astimezone(hf.HELSINKI).date() - START.date()).days
        s = storage[d - 1] if d >= 1 else 0.0                       # the model sees yesterday's state
        wind = 3000 + 2500 * np.sin(h / 41.0) + rng.normal(0, 500)
        nuclear = 4000 + rng.normal(0, 200)
        hydro = 2000 - (TRUE_HYDRO + TRUE_PER_SD * s) * wind + 150 * s + rng.normal(0, 120)
        rows.append({"hour_start": t, "hour_fi": t.hour, "isodow_fi": t.isoweekday(), "month_fi": t.month,
                     "wind_mw": wind, "nuclear_mw": nuclear, "temp_c": 8 + 10 * np.sin(h / 900.0) + rng.normal(0, 2), "hydro_mw": hydro,
                     "net_import_mw": 1000 - 0.5 * wind + rng.normal(0, 200), "other_mw": 1500 + rng.normal(0, 100),
                     "consumption_mw": 9000 + rng.normal(0, 100)})
    return rows, state


@pytest.mark.regression
def test_the_storage_interaction_is_recovered():
    rows, state = _synthetic()
    joined = hf.join_state(rows, state)
    fitted = hf.fit(joined, ("hydro_mw",))
    inter = hf.interaction(fitted, "hydro_mw")
    assert inter["per_sd"] == pytest.approx(TRUE_PER_SD, abs=0.02)
    assert inter["ci_low"] < TRUE_PER_SD < inter["ci_high"] and inter["p_value"] < 0.001
    for s in (-1.0, 0.0, 1.0):
        sh = hf.share_at(fitted, "hydro_mw", s)
        truth = TRUE_HYDRO + TRUE_PER_SD * s
        assert sh["ci_low"] < truth < sh["ci_high"], s


@pytest.mark.regression
def test_each_hour_gets_yesterdays_water_state():
    rows, state = _synthetic(days=5)
    joined = hf.join_state(rows, state)
    by_day = {s["day"]: s["storage_z"] for s in state}
    for r in joined:
        local = r["hour_start"].astimezone(hf.HELSINKI).date()
        assert r["storage_z"] == by_day[local - timedelta(days=1)]
    assert all(r["hour_start"].astimezone(hf.HELSINKI).date() > state[0]["day"] for r in joined)
