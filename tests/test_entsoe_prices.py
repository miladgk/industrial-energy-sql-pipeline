"""
test_entsoe_prices.py: the ENTSO-E day-ahead price archive (src/entsoe_prices.py)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
No network:
  - an A44 answer becomes (start, end, EUR/MWh) slots; points omitted under
    curve type A03 repeat the previous price
  - where hourly and 15-minute prices cover the same time, the 15-minute ones win
  - "no matching data" is an empty answer; any other refusal is an error
  - the token never appears in an error message
  - fetching twice stores nothing new; a dump + restore gives the rows back
"""

import gzip
import io
import os
import sys
import urllib.error
from datetime import datetime, timedelta, timezone

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

import entsoe_prices as ep  # noqa: E402

NS = "urn:iec62325.351:tc57wg16:451-3:publicationdocument:7:3"
UTC = timezone.utc


def _period(start: str, end: str, resolution: str, points: dict) -> str:
    pts = "".join(f"<Point><position>{k}</position><price.amount>{v}</price.amount></Point>" for k, v in points.items())
    return (f"<Period><timeInterval><start>{start}</start><end>{end}</end></timeInterval>"
            f"<resolution>{resolution}</resolution>{pts}</Period>")


def _doc(*periods: str, currency: str = "EUR", seq: int | None = None) -> str:
    seq_xml = f"<classificationSequence_AttributeInstanceComponent.position>{seq}</classificationSequence_AttributeInstanceComponent.position>" if seq else ""
    return (f'<Publication_MarketDocument xmlns="{NS}"><TimeSeries><curveType>A03</curveType>{seq_xml}'
            f"<currency_Unit.name>{currency}</currency_Unit.name><price_Measure_Unit.name>MWH</price_Measure_Unit.name>"
            f"{''.join(periods)}</TimeSeries></Publication_MarketDocument>")


def _ack(code: str, text: str = "x") -> str:
    return (f'<Acknowledgement_MarketDocument xmlns="urn:iec62325.351:tc57wg16:451-1:acknowledgementdocument:7:0">'
            f"<Reason><code>{code}</code><text>{text}</text></Reason></Acknowledgement_MarketDocument>")


@pytest.mark.smoke
def test_points_omitted_under_a03_repeat_the_previous_price():
    slots = ep.parse(_doc(_period("2024-01-01T23:00Z", "2024-01-02T03:00Z", "PT60M", {1: 50.5, 3: -1.25})))
    t0 = datetime(2024, 1, 1, 23, tzinfo=UTC)
    assert slots == [(t0 + timedelta(hours=h), t0 + timedelta(hours=h + 1), p)
                     for h, p in enumerate([50.5, 50.5, -1.25, -1.25])]


@pytest.mark.smoke
def test_fifteen_minute_prices_replace_an_hourly_price_for_the_same_time():
    hourly = _period("2025-10-01T00:00Z", "2025-10-01T02:00Z", "PT60M", {1: 40.0, 2: 60.0})
    quarter = _period("2025-10-01T00:00Z", "2025-10-01T01:00Z", "PT15M", {1: 10.0, 2: 20.0, 3: 30.0, 4: 40.0})
    slots = ep.parse(_doc(hourly, quarter))
    t0 = datetime(2025, 10, 1, tzinfo=UTC)
    assert [(s - t0, e - s, p) for s, e, p in slots] == [
        (timedelta(minutes=15 * i), timedelta(minutes=15), 10.0 * (i + 1)) for i in range(4)
    ] + [(timedelta(hours=1), timedelta(hours=1), 60.0)]          # the hour with no 15-minute prices stays


@pytest.mark.smoke
def test_no_data_is_empty_and_other_refusals_and_currencies_are_errors():
    assert ep.parse(_ack("999", "No matching data found")) == []
    with pytest.raises(ep.EntsoeError, match="999|refused"):
        ep.parse(_ack("Z01", "bad domain"))
    with pytest.raises(ep.EntsoeError, match="EUR"):
        ep.parse(_doc(_period("2024-01-01T00:00Z", "2024-01-01T01:00Z", "PT60M", {1: 1}), currency="SEK"))


@pytest.mark.security
def test_the_token_never_appears_in_an_error(monkeypatch):
    secret = "11111111-2222-3333-4444-555555555555"

    def refuse(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, io.BytesIO(b""))

    monkeypatch.setattr(ep.urllib.request, "urlopen", refuse)
    with pytest.raises(ep.EntsoeError) as err:
        ep._get("FI", datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 2, tzinfo=UTC), secret)
    assert secret not in str(err.value) and err.value.__cause__ is None and err.value.__suppress_context__


@pytest.mark.smoke
def test_windows_cover_the_range_without_gaps():
    a, b = datetime(2023, 11, 1, tzinfo=UTC), datetime(2024, 6, 1, tzinfo=UTC)
    w = list(ep.windows(a, b, 100))
    assert w[0][0] == a and w[-1][1] == b and all(x[1] == y[0] for x, y in zip(w, w[1:]))
    assert all(e - s <= timedelta(days=100) for s, e in w)


def _fake_api(calls):
    """Hourly prices before 1 Oct 2025, 15-minute after; price = hour of day (to check values come back)."""
    switch = datetime(2025, 10, 1, tzinfo=UTC)

    def getter(area, start, end, token):
        calls.append((area, start, end))
        periods = []
        for a, b, res in ((start, min(end, switch), 60), (max(start, switch), end, 15)):
            if a >= b:
                continue
            n = int((b - a) / timedelta(minutes=res))
            pts = {i + 1: float((a + i * timedelta(minutes=res)).hour) for i in range(n)}
            periods.append(_period(f"{a:%Y-%m-%dT%H:%MZ}", f"{b:%Y-%m-%dT%H:%MZ}", f"PT{res}M", pts))
        return _doc(*periods) if periods else _ack("999")
    return getter


@pytest.fixture
def prices(db, monkeypatch):
    monkeypatch.setattr(ep, "AREAS", {"T1": "x"})
    monkeypatch.setattr(ep, "HISTORY_FROM", datetime(2025, 9, 28, tzinfo=UTC))
    yield db
    with db.cursor() as cur:
        cur.execute("DELETE FROM entsoe_price WHERE area = 'T1'")
    db.commit()


@pytest.mark.integration
def test_fetch_twice_then_dump_and_restore(prices, tmp_path):
    db, calls, now = prices, [], datetime(2025, 10, 3, 12, tzinfo=UTC)
    first = ep.fetch(db, "t", _fake_api(calls), now=now, pause=0)
    # 28-30 Sep hourly (72) + 1-4 Oct in 15 minutes (4 x 96); fetched up to the day after tomorrow
    assert first == {"T1": (72 + 4 * 96, 72 + 4 * 96)}
    again = ep.fetch(db, "t", _fake_api(calls), now=now, pause=0)
    assert again["T1"][1] == 0 and calls[-1][0] == "T1"
    assert calls[-1][1] >= now - timedelta(days=ep.REFETCH_DAYS + 2)     # a re-fetch, not the whole history
    with db.cursor() as cur:
        cur.execute("SELECT count(*), count(*) FILTER (WHERE end_time - start_time = interval '15 minutes'), "
                    "max(eur_mwh) FROM entsoe_price WHERE area = 'T1'")
        assert cur.fetchone() == (72 + 4 * 96, 4 * 96, 23.0)
    db.rollback()

    path = str(tmp_path / "p.csv.gz")
    assert ep.dump(db, path) >= 72 + 4 * 96
    with gzip.open(path, "rt") as fh:
        assert fh.readline().strip() == "area,start_time,end_time,eur_mwh"
    with db.cursor() as cur:
        cur.execute("DELETE FROM entsoe_price WHERE area = 'T1'")
    db.commit()
    assert ep.restore(db, path) >= 72 + 4 * 96
