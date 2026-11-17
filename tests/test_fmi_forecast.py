"""
test_fmi_forecast.py: the FMI weather forecast archive (src/fmi_forecast.py)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
No network: a recorded FMI response is parsed and stored through a fake fetcher.
  - the 'simple' feature XML becomes (parameter, valid time, value); NaN -> NULL
  - fetching twice in the same minute stores nothing new (idempotent)
  - the archive survives a dump + restore, which is how it outlives the daily runner
"""

import os
import sys
from datetime import datetime, timezone

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

import fmi_forecast as fmi  # noqa: E402

SAMPLE = b"""<?xml version="1.0" encoding="UTF-8"?>
<wfs:FeatureCollection xmlns:wfs="http://www.opengis.net/wfs/2.0" xmlns:gml="http://www.opengis.net/gml/3.2"
    xmlns:BsWfs="http://xml.fmi.fi/schema/wfs/2.0">
  <wfs:member><BsWfs:BsWfsElement gml:id="a"><BsWfs:Time>2001-01-02T10:00:00Z</BsWfs:Time>
    <BsWfs:ParameterName>temperature</BsWfs:ParameterName><BsWfs:ParameterValue>-3.5</BsWfs:ParameterValue></BsWfs:BsWfsElement></wfs:member>
  <wfs:member><BsWfs:BsWfsElement gml:id="b"><BsWfs:Time>2001-01-02T10:00:00Z</BsWfs:Time>
    <BsWfs:ParameterName>windspeedms</BsWfs:ParameterName><BsWfs:ParameterValue>NaN</BsWfs:ParameterValue></BsWfs:BsWfsElement></wfs:member>
</wfs:FeatureCollection>"""
ISSUED = datetime(2001, 1, 1, 10, 53, tzinfo=timezone.utc)


@pytest.mark.smoke
def test_parse_reads_parameter_time_and_value():
    assert fmi.parse(SAMPLE) == [("temperature", datetime(2001, 1, 2, 10, tzinfo=timezone.utc), -3.5),
                                 ("windspeedms", datetime(2001, 1, 2, 10, tzinfo=timezone.utc), None)]


@pytest.fixture
def archive(db):
    yield db
    with db.cursor() as cur:
        cur.execute("DELETE FROM weather_forecast WHERE issued_at = %s", (ISSUED,))
    db.commit()


def _count(db):
    with db.cursor() as cur:
        cur.execute("SELECT count(*), count(value) FROM weather_forecast WHERE issued_at = %s", (ISSUED,))
        n = cur.fetchone()
    db.rollback()
    return n


@pytest.mark.integration
def test_fetch_stores_every_model_and_place_once(archive):
    fake = lambda model, place, now: SAMPLE
    rows = fmi.fetch(archive, now=ISSUED, getter=fake, pause=0)
    assert rows == 2 * len(fmi.MODELS) * len(fmi.PLACES)
    assert _count(archive) == (rows, rows // 2)                 # the NaN wind speeds are stored as NULL
    fmi.fetch(archive, now=ISSUED, getter=fake, pause=0)
    assert _count(archive) == (rows, rows // 2)


@pytest.mark.integration
def test_archive_survives_dump_and_restore(archive, tmp_path):
    fmi.fetch(archive, now=ISSUED, getter=lambda m, p, n: SAMPLE, pause=0)
    before = _count(archive)
    path = str(tmp_path / "weather_forecast.csv.gz")
    fmi.dump(archive, path)
    with archive.cursor() as cur:
        cur.execute("DELETE FROM weather_forecast WHERE issued_at = %s", (ISSUED,))
    archive.commit()
    assert fmi.restore(archive, path) >= before[0]
    assert _count(archive) == before
