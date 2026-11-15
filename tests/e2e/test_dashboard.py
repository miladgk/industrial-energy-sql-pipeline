"""
test_dashboard.py: END-TO-END (E2E) TESTS
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
E2E tests drive the finished product the way a user does: a real browser opens
the dashboard, waits for data, clicks and hovers, and we check what is on screen.
Everything is real (Chromium, static page, FastAPI, PostgreSQL), so these catch
what unit and API tests cannot: a renamed JSON field that leaves a chart empty,
a JavaScript error, a broken tab, a layout that overflows on a phone.

Run only these:   pytest -m e2e          (needs: pip install playwright
                                          && playwright install chromium)
"""

import re

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e

LIVE = "API online"


def _number(text: str) -> int:
    """'518,400' -> 518400"""
    return int(re.sub(r"\D", "", text))


def _wait_until_live(page):
    expect(page.locator("#status")).to_contain_text(LIVE, timeout=15000)


# ── Page health ────────────────────────────────────────────────

def test_page_loads_without_javascript_errors(open_dashboard):
    page = open_dashboard()
    _wait_until_live(page)
    expect(page).to_have_title("Industrial Energy Analytics")
    expect(page.locator("h1")).to_contain_text("From telemetry to operational insight")
    assert page.problems == [], page.problems


# ── Live data: browser -> API -> database ──────────────────────

def test_kpis_match_the_database(open_dashboard, db):
    page = open_dashboard()
    _wait_until_live(page)
    with db.cursor() as cur:
        cur.execute("SELECT (SELECT COUNT(*) FROM facilities), (SELECT COUNT(*) FROM readings)")
        facilities, readings = cur.fetchone()
    db.rollback()
    assert _number(page.locator("#facility-count").inner_text()) == facilities
    assert _number(page.locator("#reading-count").inner_text()) == readings
    assert re.fullmatch(r"\d+(\.\d+)?%", page.locator("#anomaly-rate").inner_text())


def test_trend_chart_is_drawn(open_dashboard):
    page = open_dashboard()
    _wait_until_live(page)
    expect(page.locator("#trend-chart path").first).to_be_visible()
    expect(page.locator("#trend-window")).to_contain_text("(UTC)")


def test_detector_scorecard_lists_every_sensor_type(open_dashboard, client):
    page = open_dashboard()
    _wait_until_live(page)
    expected = len(client.get("/api/detection-quality").json()["sensors"])
    rows = page.locator("#detection tr")
    expect(rows).to_have_count(expected)
    expect(rows.first.locator("td").last).to_contain_text("%")


def test_anomaly_table_is_filled_from_the_api(open_dashboard):
    page = open_dashboard()
    expect(page.locator("#anomalies tr").first).to_be_visible(timeout=15000)
    assert page.locator("#anom-error").inner_text() == ""


# ── Interaction ────────────────────────────────────────────────

def test_hovering_a_chart_shows_a_tooltip(open_dashboard):
    page = open_dashboard()
    _wait_until_live(page)
    page.locator("#trend-chart").scroll_into_view_if_needed()
    page.locator("#trend-chart .tip-hit").hover()
    expect(page.locator("#trend-chart tspan").first).to_contain_text("UTC")
    expect(page.locator("#trend-chart tspan").nth(1)).to_contain_text("MW")


def test_grid_period_tabs_switch_the_dataset(open_dashboard):
    page = open_dashboard()
    tab_2023 = page.locator('#period-tabs [data-period="2023"]')
    expect(tab_2023).to_be_visible(timeout=15000)
    tab_2023.click()
    expect(tab_2023).to_have_attribute("aria-pressed", "true")
    expect(page.locator('#period-tabs [data-period="recent"]')).to_have_attribute("aria-pressed", "false")
    expect(page.locator("#grid-chart-title")).to_have_text("Daily average power, 2023 (MW)")
    expect(page.locator("#grid-kpis .kpi, #grid-kpis > *")).to_have_count(4)

    page.locator('#period-tabs [data-period="recent"]').click()
    expect(page.locator("#grid-chart-title")).to_contain_text(" to ")


def test_navigation_links_jump_to_their_sections(open_dashboard):
    page = open_dashboard()
    page.locator('.subnav a[href="#anomaly-detection"]').click()
    expect(page.locator("#anomaly-detection")).to_be_in_viewport()
    assert page.url.endswith("#anomaly-detection")


# ── Resilience & layout ────────────────────────────────────────

def test_falls_back_to_cached_snapshot_when_api_is_down(open_dashboard):
    page = open_dashboard(api="down")
    expect(page.locator("#status")).to_contain_text("API unavailable", timeout=15000)
    expect(page.locator("#status")).to_contain_text("snapshot")
    assert _number(page.locator("#facility-count").inner_text()) == 20  # from docs/data/api_snapshot.json
    expect(page.locator("#trend-chart path").first).to_be_visible()


def test_no_horizontal_scrolling_on_a_phone(open_dashboard):
    page = open_dashboard(viewport={"width": 375, "height": 812})
    _wait_until_live(page)
    overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    assert overflow <= 0, f"page is {overflow}px wider than a 375px screen"
