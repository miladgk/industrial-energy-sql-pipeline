"""
test_europe.py: Ember's European data (src/ember.py, sql/analysis/30, src/europe.py)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
  - only the price countries and the EU aggregate are kept from the world file
  - the comparison computes intensity and shares from known months and flags a
    country with a missing month as incomplete
  - the window ends at the last month complete in both files
  - ranks, rank correlation and the price check on known numbers
"""

import os
import sys
from datetime import date

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

import ember  # noqa: E402
import europe as eu  # noqa: E402

GEN_HEAD = ("Area,ISO 3 code,Date,Area type,Electricity source,Is aggregated source,Generation (TWh),"
            "Generation YoY change (TWh),Generation YoY change (%),Share of generation (%),"
            "Share of generation YoY change (% points),Emissions (MtCO2e),Emissions YoY change (MtCO2e),"
            "Emissions YoY change (%),Share of emissions (%),Emissions intensity (gCO2e/kWh),Continent,"
            "Ember region,EU member,OECD member,G20 member,G7 member,ASEAN member\n")


def _gen(area, iso, kind, month, source, twh, mt, eu_member):
    return f"{area},{iso},{month},{kind},{source},False,{twh},,,,,{mt},,,,,Europe,EU,{eu_member},True,False,False,False\n"


def _files():
    gen = GEN_HEAD
    for m in ("2026-01-01", "2026-02-01"):
        gen += _gen("Testland", "TST", "Country or economy", m, "Total generation", 10, 1, "True")    # 100 g/kWh
        gen += _gen("Testland", "TST", "Country or economy", m, "Wind and solar", 4, 0, "True")
        gen += _gen("Testland", "TST", "Country or economy", m, "Demand", 12, "", "True")
        gen += _gen("Testland", "TST", "Country or economy", m, "Net imports", 2, 0, "True")
        gen += _gen("Otherland", "OTH", "Country or economy", m, "Total generation", 5, 2, "False")    # 400 g/kWh
        gen += _gen("EU", "", "Region", m, "Total generation", 100, 20, "False")
        gen += _gen("Farland", "FAR", "Country or economy", m, "Total generation", 1, 1, "False")      # no price
        gen += _gen("Europe", "", "Region", m, "Total generation", 999, 99, "False")
    price = "Country,ISO3 Code,Date,Price (EUR/MWhe)\n"
    price += "Testland,TST,2026-01-01,40\nTestland,TST,2026-02-01,60\nOtherland,OTH,2026-02-01,90\n"
    return {ember.GENERATION_URL: gen, ember.PRICE_URL: price}


@pytest.mark.smoke
def test_only_price_countries_and_the_eu_are_kept():
    files = _files()
    meta, rows = ember.parse_generation(files[ember.GENERATION_URL], {"Testland", "Otherland"})
    assert set(meta) == {"Testland", "Otherland", "EU"} and meta["Testland"] == ("TST", True)
    assert {r[0] for r in rows} == {"Testland", "Otherland", "EU"}
    assert ember.parse_prices(files[ember.PRICE_URL])[0] == ("Testland", "TST", "2026-01-01", 40.0)
    with pytest.raises(ValueError):
        ember._get("https://example.com/x.csv")


@pytest.mark.integration
def test_the_comparison_from_known_months(db):
    files = _files()
    n = ember.load(db, getter=files.__getitem__, commit=False)
    assert n["areas"] == 3 and n["price_rows"] == 3
    with open(os.path.join(ROOT, "sql", "analysis", "30_europe_comparison.sql"), encoding="utf-8") as fh, \
            db.cursor() as cur:
        cur.execute(fh.read(), {"start": date(2026, 1, 1), "end": date(2026, 2, 1)})
        names = [c.name for c in cur.description]
        rows = {r[0]: dict(zip(names, r)) for r in cur.fetchall()}
    db.rollback()                                   # the real Ember tables come back untouched
    t, o = rows["Testland"], rows["Otherland"]
    assert t["price_eur_mwh"] == pytest.approx(50) and t["complete"]
    assert t["intensity_g_kwh"] == pytest.approx(100) and t["wind_solar_share"] == pytest.approx(0.4)
    assert t["net_import_share"] == pytest.approx(2 / 12)
    assert o["intensity_g_kwh"] == pytest.approx(400) and not o["complete"]   # January has no price
    assert rows["EU"]["intensity_g_kwh"] == pytest.approx(200) and rows["EU"]["price_eur_mwh"] is None


@pytest.mark.regression
def test_window_ranks_correlation_and_price_check():
    # prices run into the unfinished current month; generation ends a month earlier
    assert eu.window(date(2026, 10, 1), date(2026, 11, 1), date(2026, 11, 18)) == (date(2025, 11, 1), date(2026, 10, 1))
    assert eu.window(date(2026, 10, 1), date(2026, 9, 1), date(2026, 11, 18)) == (date(2025, 10, 1), date(2026, 9, 1))
    rows = [{"area": a, "complete": True, "price_eur_mwh": p, "intensity_g_kwh": i, "wind_solar_share": w,
             "clean_share": c, "eu_member": True, "demand_twh": d}
            for a, p, i, w, c, d in (("Finland", 50, 80, 0.3, 0.9, 10), ("B", 70, 200, 0.5, 0.6, 30),
                                     ("C", 90, 300, 0.2, 0.4, 60), ("D", 60, 50, 0.1, 0.95, 0))]
    rows.append({**rows[1], "area": "E", "complete": False})
    assert eu.ranks(rows) == {"of": 4, "price_eur_mwh": 1, "intensity_g_kwh": 2, "wind_solar_share": 2,
                              "clean_share": 2}
    assert eu.eu_price(rows) == pytest.approx((50 * 10 + 70 * 30 + 90 * 60) / 100)
    perfect = eu.spearman(range(12), [x * x for x in range(12)], n_perm=2000)
    assert perfect["r"] == pytest.approx(1) and perfect["p_value"] < 0.01
    none = eu.spearman(range(12), [5, 1, 9, 3, 11, 0, 7, 2, 10, 4, 8, 6], n_perm=2000)
    assert abs(none["r"]) < 0.3 and none["p_value"] > 0.3
    ck = eu.price_check({date(2026, 1, 1): (50.0, 52.0), date(2026, 2, 1): (40.0, 39.0)},
                        {date(2026, 1, 1): 50.5, date(2026, 2, 1): 40.0, date(2026, 3, 1): 1.0})
    assert ck["months"] == 2 and ck["mean_abs_diff_plain"] == pytest.approx(0.25)
    assert ck["max_abs_diff_plain"] == pytest.approx(0.5) and ck["mean_abs_diff_load_weighted"] == pytest.approx(1.25)
