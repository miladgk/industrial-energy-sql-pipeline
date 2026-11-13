"""
test_detection_quality.py
~~~~~~~~~~~~~~~~~~~~~~~~~
Checks the detector scorecard served by GET /api/detection-quality against
the loaded database. The route function is called directly, so no HTTP
client is needed.

Run with:
    pytest tests/test_detection_quality.py -v
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from api import get_detection_quality


@pytest.fixture(scope="module")
def scorecard():
    return get_detection_quality(z_threshold=3.0)


def test_counts_are_consistent(scorecard):
    rows = scorecard["sensors"]
    assert rows, "no sensor types returned"
    for row in rows + [scorecard["total"]]:
        assert row["spikes"] + row["drops"] == row["injected"]
        assert row["true_positives"] == row["spikes_flagged"] + row["drops_flagged"]
        assert row["true_positives"] <= min(row["flagged"], row["injected"])
    for key in ("readings", "injected", "flagged", "true_positives"):
        assert scorecard["total"][key] == sum(row[key] for row in rows)


def test_every_spike_is_caught(scorecard):
    # Spikes are 3x the normal maximum, far beyond 3 standard deviations of a
    # uniform distribution, so the detector must flag all of them.
    total = scorecard["total"]
    assert total["spikes"] > 0
    assert total["spikes_flagged"] == total["spikes"]


def test_percentages_are_in_range(scorecard):
    for row in scorecard["sensors"] + [scorecard["total"]]:
        for key in ("precision_pct", "recall_pct"):
            assert row[key] is None or 0 <= row[key] <= 100


def test_stricter_threshold_flags_fewer(scorecard):
    strict = get_detection_quality(z_threshold=6.0)
    assert strict["total"]["flagged"] <= scorecard["total"]["flagged"]
