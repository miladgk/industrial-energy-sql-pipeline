"""
strike_effect.py
~~~~~~~~~~~~~~~~
Writes docs/data/strike_effect.json: how much electricity Finland did not use
during the 2024 political strikes, and how consumption that the weather does
not explain follows industrial output (method: src/strike_effect.py).

The events are over, so this is run by hand (about ten minutes: every placebo
refits the model), not by the daily refresh. It needs the warehouse back to
November 2023 (src/sync_fingrid.py --from 2023-11-01) and fetches Statistics
Finland's volume index of industrial output (StatFin 14mh, CC BY 4.0, no key).

Usage:
    python scripts/strike_effect.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

import numpy as np  # noqa: E402

import strike_effect as se  # noqa: E402

PANEL_SQL = "sql/analysis/28_consumption_hourly.sql"
STATFIN_URL = "https://pxdata.stat.fi/PXWeb/api/v1/en/StatFin/ttvi/14mh.px"
INDUSTRIES = {"C": "manufacturing", "C17": "paper", "C24": "basic_metals", "C19TC22": "chemicals"}
START = datetime(2023, 11, 1, tzinfo=timezone.utc)
USER_AGENT = "industrial-energy-sql-pipeline (open-source research project)"


def statfin_index(first_month: str) -> dict:
    """{industry: {YYYY-MM: seasonally adjusted index}} from first_month to the latest month published."""
    meta = json.load(urllib.request.urlopen(urllib.request.Request(STATFIN_URL, headers={"User-Agent": USER_AGENT}),
                                            timeout=60))  # nosec B310 (fixed https URL above)
    months = [m for m in next(v for v in meta["variables"] if v["code"] == "timeperiod_m")["values"] if m >= first_month]
    query = {"query": [
        {"code": "timeperiod_m", "selection": {"filter": "item", "values": months}},
        {"code": "toimiala_78_20180201", "selection": {"filter": "item", "values": list(INDUSTRIES)}},
        {"code": "contentscode", "selection": {"filter": "item", "values": ["ttvi-Kausitasoitettu"]}},
    ], "response": {"format": "json-stat2"}}
    req = urllib.request.Request(STATFIN_URL, data=json.dumps(query).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:  # nosec B310 (fixed https URL above)
        d = json.load(resp)
    times = list(d["dimension"]["timeperiod_m"]["category"]["index"])
    inds = list(d["dimension"]["toimiala_78_20180201"]["category"]["index"])
    out = {INDUSTRIES[i]: {} for i in inds}
    for ti, t in enumerate(times):
        for ii, i in enumerate(inds):
            v = d["value"][ti * len(inds) + ii]
            if v is not None:
                out[INDUSTRIES[i]][f"{t[:4]}-{t[5:]}"] = v
    return out


def main() -> None:
    from db_connection import get_connection
    import psycopg2.extras

    end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur, \
                open(os.path.join(ROOT, PANEL_SQL), encoding="utf-8") as fh:
            cur.execute(fh.read(), {"start": START, "end": end})
            rows = [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()
    df = se.panel(rows)
    if df["day_fi"].min() > se.EVENTS[0]["start"].replace(month=1, day=1):
        sys.exit("The warehouse does not reach back to the 2024 strikes: run src/sync_fingrid.py --from 2023-11-01")
    r1 = lambda v: round(float(v), 1)

    events = []
    for e in se.EVENTS:
        res = se.event_study(df, e)
        events.append({k: (str(v) if k in ("start", "end") else v) for k, v in e.items()}
                      | {"mean_mw": r1(res["mean_mw"]), "gwh": r1(res["gwh"]), "share_pct": r1(100 * res["share"]),
                         "hours": res["hours"], "placebo_n": res["placebo_n"],
                         "placebo_band_mw": [r1(x) for x in res["placebo_band_mw"]], "placebo_p": res["placebo_p"],
                         "daily": [{"day": x["day"], "actual_mw": r1(x["actual_mw"]),
                                    "counterfactual_mw": r1(x["counterfactual_mw"])} for x in res["daily"]]})
        print(f"{e['key']:15s} {res['mean_mw']:7.0f} MW  {res['gwh']:7.1f} GWh  {100 * res['share']:5.1f} %  "
              f"placebo 90% {res['placebo_band_mw'][0]:6.0f}..{res['placebo_band_mw'][1]:5.0f}  p={res['placebo_p']:.3f}")

    monthly = se.monthly_residual(df)
    index = statfin_index(monthly["month"].min().replace("-", "M"))
    monthly = monthly[monthly["hours"] >= 24 * 20]
    months = [m for m in monthly["month"] if m in index["manufacturing"]]
    m = monthly.set_index("month").loc[months]
    strike_months = {f"{e['start']:%Y-%m}" for e in se.EVENTS} | {f"{e['end']:%Y-%m}" for e in se.EVENTS}
    calm = [x for x in months if x not in strike_months]
    link = {name: {"all_months": se.trend_check(np.array([index[name][x] for x in months]), m["resid_mw"].to_numpy()),
                   "without_strike_months": se.trend_check(np.array([index[name][x] for x in calm]),
                                                           m.loc[calm, "resid_mw"].to_numpy())}
            for name in ("manufacturing", "paper")}
    print("monthly link:", {k: {kk: round(vv, 2) for kk, vv in v["all_months"].items()} for k, v in link.items()})

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "Fingrid Open Data (CC BY 4.0): consumption (124), temperatures (178, 182, 196, 185); Statistics "
                  "Finland, volume index of industrial output, seasonally adjusted (StatFin 14mh, CC BY 4.0); strike "
                  "dates from the unions' own announcements (links per event)",
        "method": f"Gradient-boosted counterfactual of hourly consumption from measured temperature (now, 24 h, 72 h), "
                  f"the Finnish calendar, the sun's elevation, the time of year and a slow trend, trained outside the "
                  f"strike periods (+/- {se.BUFFER_DAYS} days). Effect = measured minus counterfactual. Placebo test: "
                  f"the same, refitted, on {se.N_PLACEBO} strike-free periods of equal length and starting weekday in "
                  "October-April; p = share of placebo effects at least as large. A measured gap, not proof of cause.",
        "window_start": str(df["day_fi"].min()), "window_end": str(df["day_fi"].max()), "hours": len(df),
        "events": events,
        "monthly": [{"month": x, "resid_mw": r1(m.loc[x, "resid_mw"]),
                     **{name: index[name].get(x) for name in INDUSTRIES.values()}} for x in months],
        "monthly_link": {k: {kk: {kkk: (round(vvv, 3) if isinstance(vvv, float) else vvv) for kkk, vvv in vv.items()}
                             for kk, vv in v.items()} for k, v in link.items()},
        "code": ["scripts/strike_effect.py", "src/strike_effect.py"], "sql": [PANEL_SQL],
    }
    path = os.path.join(ROOT, "docs", "data", "strike_effect.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"✓ wrote {path}")


if __name__ == "__main__":
    main()
