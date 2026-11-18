"""
ev_charging.py
~~~~~~~~~~~~~~
Do electric cars show up in Finland's electricity consumption?

1. The fleet. Traficom's quarterly count of cars and vans in traffic by driving
   power (battery electric; petrol and diesel plug-in hybrids), and how far they
   drive: the mean odometer reading at the first periodic inspection, at age
   four, divided by four (every car of that age is inspected, so the sample is
   not selected). Both from Traficom's statistics database (CC BY 4.0).

2. How much electricity that is. km per year x kWh per km at the plug (charging
   losses and Finnish winters included) x, for plug-in hybrids, the share of km
   driven on electricity. The last two are assumptions, not measurements; they
   are given as a low, central and high case (ASSUMPTIONS) and every figure
   derived from them comes as that range.

3. Whether the growth can be seen. Weather-adjusted consumption over the last
   365 days against the 365 before, hour by hour of the Finnish day:

       y = sum_h growth_h * [hour h, later year] + hour-of-day + heating degrees
           (by quarter of the day, and their 24 h mean) + sun elevation + holidays,
           eves, bridge days, Christmas + weekday + month

   on consumption, on electric boilers (Fingrid 371, measured since December
   2024) and on consumption without the boilers; Newey-West intervals. The
   fleet's growth between the middles of the two years, turned into MW, says
   how large an electric-car increase to expect, and where in the day it would
   land if cars charged mostly in the evening (17-22) or mostly at night
   (22-06). The contrast "night hours minus evening hours" of the measured
   growth tells those two cases apart, as far as nothing else grew unevenly
   over the day.

Everything else that grew in the same year (heat pumps, data centres, industry)
is in the same numbers; this cannot separate cars from them, only say whether
the cars are big enough to matter and whether the timing fits.
"""

from __future__ import annotations

import itertools
import json
import math
import urllib.request
from datetime import date, timedelta

import numpy as np

import wind_allocation as wa

TRAFICOM = "https://trafi2.stat.fi/PXWeb/api/v1/en/TraFi/"
STOCK_URL = TRAFICOM + "Liikennekaytossa_olevat_ajoneuvot/040_kanta_tau_104.px"
INSPECTION_URL = TRAFICOM + "Katsastuksen_vikatilastot/030_kats_tau_103.px"
USER_AGENT = "industrial-energy-sql-pipeline (open-source research project)"
FIRST_INSPECTION_AGE = 4

# (low, central, high). kWh drawn from the grid per km, charging losses and winter included;
# the share of a plug-in hybrid's km driven on electricity.
ASSUMPTIONS = {"kwh_per_km": (0.17, 0.20, 0.24), "phev_electric_share": (0.25, 0.35, 0.50)}
EVENING = range(17, 22)                     # 17:00-21:59 Finnish time
NIGHT = (22, 23, 0, 1, 2, 3, 4, 5)          # 22:00-05:59
NIGHT_BLOCK = range(0, 6)                   # the hours compared ...
EVENING_BLOCK = range(17, 22)               # ... with these


def _post(url: str, query: dict) -> dict:
    if not url.startswith(TRAFICOM):
        raise ValueError(f"unexpected URL {url}")
    req = urllib.request.Request(url, data=json.dumps(query).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:  # nosec B310 (fixed https TRAFICOM above)
        return json.load(resp)


def _cells(d: dict) -> dict:
    """json-stat2 -> {(category codes...): value}, without the contents dimension."""
    ids = d["id"]
    dims = [list(d["dimension"][i]["category"]["index"]) for i in ids]
    keep = [k for k, i in enumerate(ids) if i.lower() != "contentscode"]
    return {tuple(c[k] for k in keep): v for c, v in zip(itertools.product(*dims), d["value"])}


def fleet(post=_post) -> list[dict]:
    """Cars and vans in traffic in mainland Finland per quarter: battery electric and plug-in hybrid."""
    d = post(STOCK_URL, {"query": [
        {"code": "Maakunta", "selection": {"filter": "item", "values": ["MA1"]}},
        {"code": "Ajoneuvoluokka", "selection": {"filter": "item", "values": ["01", "02"]}},
        {"code": "Käyttövoima", "selection": {"filter": "item", "values": ["YH", "04", "39", "44"]}},
    ], "response": {"format": "json-stat2"}})
    cells = _cells(d)
    quarters = sorted({k[-1] for k in cells})
    out = []
    for q in quarters:
        get = lambda power: sum(cells.get(("MA1", cls, power, q)) or 0 for cls in ("01", "02"))
        if not get("YH"):
            continue
        out.append({"quarter": q, "bev": get("04"), "phev": get("39") + get("44"), "all": get("YH")})
    return out


def km_per_year(post=_post) -> dict:
    """Mean km per year of battery-electric and plug-in hybrid passenger cars at their first inspection."""
    meta = json.load(urllib.request.urlopen(urllib.request.Request(  # nosec B310 (fixed https URL)
        INSPECTION_URL, headers={"User-Agent": USER_AGENT}), timeout=60))
    year = max(next(v for v in meta["variables"] if v["code"] == "Katsastusvuosi")["values"])
    powers = {"bev": "Sähkö", "phev": "Bensiinihybridi (ladattava)"}
    d = post(INSPECTION_URL, {"query": [
        {"code": "Katsastusvuosi", "selection": {"filter": "item", "values": [year]}},
        {"code": "Ajoneuvoluokka", "selection": {"filter": "item", "values": ["Henkilöauto"]}},
        {"code": "Käyttövoima", "selection": {"filter": "item", "values": list(powers.values())}},
        {"code": "Ajoneuvon ikä", "selection": {"filter": "item", "values": [str(FIRST_INSPECTION_AGE)]}},
        {"code": "Tiedot", "selection": {"filter": "item", "values": ["Ka", "Ajon_kats_lkm"]}},
    ], "response": {"format": "json-stat2"}})
    cells = _cells(d)
    out = {"inspection_year": int(year)}
    for k, p in powers.items():
        odo = cells[(year, "Henkilöauto", p, str(FIRST_INSPECTION_AGE), "Ka")]
        out[k] = {"km_per_year": odo / FIRST_INSPECTION_AGE, "odometer_km": odo,
                  "cars": cells[(year, "Henkilöauto", p, str(FIRST_INSPECTION_AGE), "Ajon_kats_lkm")]}
    return out


def quarter_end(q: str) -> date:
    y, n = int(q[:4]), int(q[-1])
    return date(y, 3 * n, 1).replace(day=31 if n in (1, 4) else 30)


def fleet_at(rows: list[dict], day: date) -> dict:
    """Fleet on *day*, linear between quarter ends (the last quarter beyond the data)."""
    pts = [(quarter_end(r["quarter"]), r) for r in rows]
    if day >= pts[-1][0]:
        return {k: float(pts[-1][1][k]) for k in ("bev", "phev")}
    if day <= pts[0][0]:
        return {k: float(pts[0][1][k]) for k in ("bev", "phev")}
    for (d0, r0), (d1, r1) in zip(pts, pts[1:]):
        if d0 <= day <= d1:
            w = (day - d0).days / (d1 - d0).days
            return {k: r0[k] + w * (r1[k] - r0[k]) for k in ("bev", "phev")}
    raise ValueError(day)


def energy(bev: float, phev: float, km: dict) -> dict:
    """GWh a year and average MW for a fleet, in the low, central and high case."""
    out = {}
    for i, case in enumerate(("low", "central", "high")):
        kwh = ASSUMPTIONS["kwh_per_km"][i]
        gwh = (bev * km["bev"] * kwh + phev * km["phev"] * kwh * ASSUMPTIONS["phev_electric_share"][i]) / 1e6
        out[case] = {"gwh_per_year": gwh, "mw": gwh * 1000 / 8766}
    return out


def windows(last_day: date) -> tuple[tuple[date, date], tuple[date, date]]:
    """The 365 days ending *last_day*, and the 365 before (inclusive day ranges)."""
    b = (last_day - timedelta(days=364), last_day)
    a = (b[0] - timedelta(days=365), b[0] - timedelta(days=1))
    return a, b


def growth_by_hour(df, y) -> dict:
    """Weather- and calendar-adjusted growth of *y* from the earlier to the later year, per Finnish hour.
    df needs the columns of strike_effect.panel() plus a 0/1 column 'later'."""
    y = np.asarray(y, float)
    hour, later = df["hour_fi"].to_numpy(), df["later"].to_numpy()
    heat = np.maximum(15.0 - df["temp_c"].to_numpy(), 0.0)
    heat24 = np.maximum(15.0 - df["temp_24h"].to_numpy(), 0.0)
    month = df["hour_start"].dt.tz_convert("Europe/Helsinki").dt.month.to_numpy()
    cols = [np.ones(len(df))] + [((hour == h) & (later == 1)).astype(float) for h in range(24)]
    cols += wa._dummies(hour) + [heat * (hour // 6 == g) for g in range(4)] + [heat24, np.clip(df["sun_elevation"], 0, None)]
    cols += [df[k].astype(float).to_numpy() for k in ("holiday", "holiday_eve", "bridge_day", "christmas_period")]
    cols += wa._dummies(df["isodow"].to_numpy()) + wa._dummies(month)
    X = np.column_stack(cols)
    keep = ~np.isnan(y) & ~np.isnan(X).any(axis=1)
    X, y = X[keep], y[keep]
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    V = wa.newey_west(X, y - X @ beta)
    return {"hours": int(keep.sum()), "growth": beta[1:25].tolist(), "cov": V[1:25, 1:25].tolist()}


def contrast(fitted: dict, plus=NIGHT_BLOCK, minus=EVENING_BLOCK) -> dict:
    """Mean growth over *plus* hours minus mean growth over *minus* hours, with its 95 % interval."""
    g = np.zeros(24)
    g[list(plus)] += 1 / len(plus)
    g[list(minus)] -= 1 / len(minus)
    est = float(g @ np.array(fitted["growth"]))
    se = math.sqrt(float(g @ np.array(fitted["cov"]) @ g))
    return {"estimate": est, "ci_low": est - wa.Z95 * se, "ci_high": est + wa.Z95 * se}


def mean_growth(fitted: dict) -> dict:
    g = np.full(24, 1 / 24)
    est = float(g @ np.array(fitted["growth"]))
    se = math.sqrt(float(g @ np.array(fitted["cov"]) @ g))
    return {"estimate": est, "ci_low": est - wa.Z95 * se, "ci_high": est + wa.Z95 * se}


def scenario_contrast(added_mw: float, charging_hours) -> float:
    """Night-minus-evening contrast if *added_mw* of average load all fell, evenly, in *charging_hours*."""
    per_hour = np.zeros(24)
    per_hour[list(charging_hours)] = added_mw * 24 / len(charging_hours)
    return float(per_hour[list(NIGHT_BLOCK)].mean() - per_hour[list(EVENING_BLOCK)].mean())
