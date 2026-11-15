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

import json
import os
import re

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _number(text: str) -> int:
    """'518,400' -> 518400"""
    return int(re.sub(r"\D", "", text))


def _wait_until_live(page):
    # The page exposes the API state as an attribute, so tests do not depend on wording.
    expect(page.locator("#status")).to_have_attribute("data-api-state", "live", timeout=15000)


def _data(name):
    with open(os.path.join(ROOT, "docs", "data", name), encoding="utf-8") as fh:
        return json.load(fh)


# ── Page health ────────────────────────────────────────────────

def test_page_loads_without_javascript_errors(open_dashboard):
    page = open_dashboard()
    _wait_until_live(page)
    expect(page).to_have_title(re.compile("Industrial Energy SQL Pipeline"))
    expect(page.locator("h1")).to_contain_text("Machines fail in two ways")
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


def test_anomaly_table_lists_every_facility_and_sensor_pair(open_dashboard):
    page = open_dashboard()
    strongest = [e for e in _data("anomaly_examples.json")["examples"] if e["kind"] == "strongest_flag"]
    expect(page.locator("#anomalies tr")).to_have_count(len(strongest), timeout=15000)
    assert page.locator("#anom-error").inner_text() == ""


def test_selecting_an_anomaly_redraws_its_neighbourhood(open_dashboard):
    page = open_dashboard()
    rows = page.locator("#anomalies tr")
    expect(rows.first).to_be_visible(timeout=15000)
    rows.nth(2).click()
    expect(rows.nth(2)).to_have_attribute("aria-selected", "true")
    facility = rows.nth(2).locator("td").nth(1).inner_text()
    expect(page.locator("#spark-title")).to_contain_text(facility)
    expect(page.locator("#anom-spark path").first).to_be_visible()


def test_facility_filter_keeps_only_that_type(open_dashboard):
    page = open_dashboard()
    expect(page.locator("#anomalies tr").first).to_be_visible(timeout=15000)
    page.locator('#anom-filter [data-type="solar"]').click()
    facilities = page.locator("#anomalies tr td:nth-child(2)").all_inner_texts()
    assert facilities and all(f.startswith("SolarPlant") for f in facilities), facilities


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
    page.locator('.nav a[href="#anomaly-detection"]').click()
    expect(page.locator("#anomaly-detection")).to_be_in_viewport()
    assert page.url.endswith("#anomaly-detection")


def test_threshold_slider_shows_the_exported_scorecard(open_dashboard):
    page = open_dashboard()
    sweep = {t["z_threshold"]: t["total"] for t in _data("detection_thresholds.json")["thresholds"]}
    slider = page.locator("#thr-input")
    for z in (1.0, 3.0, 9.0):
        slider.fill(f"{z:g}")
        expect(page.locator("#thr-z")).to_have_text(f"{z:.1f}")
        expect(page.locator("#thr-recall")).to_have_text(f"{sweep[z]['recall_pct']:.1f}%")
        expect(page.locator("#thr-precision")).to_have_text(f"{sweep[z]['precision_pct']:.1f}%")


def test_sql_drawers_show_the_repository_sql(open_dashboard):
    page = open_dashboard()
    with open(os.path.join(ROOT, "sql", "analysis", "11_detection_quality.sql"), encoding="utf-8") as fh:
        expected = fh.read()
    drawer = page.locator("#sql-11")
    drawer.locator("summary").click()
    expect(drawer.locator("pre")).to_have_text(expected, use_inner_text=False, timeout=10000)


def test_pipeline_stages_are_keyboard_buttons(open_dashboard):
    page = open_dashboard()
    stages = page.locator("#pipeline button.step")
    expect(stages).to_have_count(7)
    stages.nth(3).focus()
    page.keyboard.press("Enter")
    expect(stages.nth(3)).to_have_attribute("aria-current", "step")
    expect(page.locator("#inspector")).to_contain_text("partitioned")


def test_chart_values_can_be_read_with_the_keyboard(open_dashboard):
    page = open_dashboard()
    _wait_until_live(page)
    hit = page.locator("#trend-chart .tip-hit")
    hit.focus()
    page.keyboard.press("Home")
    first = hit.get_attribute("aria-valuetext")
    page.keyboard.press("ArrowRight")
    assert hit.get_attribute("aria-valuenow") == "1"
    assert hit.get_attribute("aria-valuetext") != first and "MW" in first


def test_theme_toggle_switches_and_is_remembered(open_dashboard):
    page = open_dashboard()
    html = page.locator("html")
    start = html.get_attribute("data-theme")
    page.locator("#theme-toggle").click()
    flipped = "light" if start == "dark" else "dark"
    expect(html).to_have_attribute("data-theme", flipped)
    page.reload()
    expect(html).to_have_attribute("data-theme", flipped)


def test_numbers_come_from_the_data_files_not_the_html(open_dashboard):
    """Before any data arrives the KPIs show a dash, never a hard-coded number."""
    page = open_dashboard(api="down", block_data=True)
    for kpi in ("facility-count", "reading-count", "anomaly-rate", "latest-reading"):
        assert page.locator(f"#{kpi}").inner_text() == "–"


def test_glance_answer_is_built_from_the_scorecard(open_dashboard):
    page = open_dashboard()
    total = _data("api_snapshot.json")["detection"]["total"]
    zeros = f"{total['drops_flagged'] / total['drops'] * 100:.1f}%"
    expect(page.locator("#glance-answer")).to_contain_text(zeros, timeout=15000)


def test_sections_animate_again_when_scrolling_back(open_dashboard):
    page = open_dashboard()
    panel = page.locator("#grid .panel")
    panel.scroll_into_view_if_needed()
    expect(panel).to_have_class(re.compile(r"\bin\b"))
    page.locator("#engineering").scroll_into_view_if_needed()
    expect(panel).not_to_have_class(re.compile(r"\bin\b"))      # reset once out of view
    expect(panel).to_have_class(re.compile(r"\babove\b"))        # left through the top
    panel.scroll_into_view_if_needed()
    expect(panel).to_have_class(re.compile(r"\bin\b"))           # animates in again on the way up


def test_headline_fits_on_one_line_on_desktop(open_dashboard):
    page = open_dashboard()
    lines = page.evaluate("(() => { const h = document.querySelector('h1'); return Math.round(h.getBoundingClientRect().height / parseFloat(getComputedStyle(h).lineHeight)); })()")
    assert lines == 1


# ── Resilience & layout ────────────────────────────────────────

def test_falls_back_to_cached_snapshot_when_api_is_down(open_dashboard):
    page = open_dashboard(api="down")
    expect(page.locator("#status")).to_have_attribute("data-api-state", "down", timeout=15000)
    expect(page.locator("#status")).to_contain_text("API unavailable")
    expect(page.locator("#status")).to_contain_text("snapshot")
    assert _number(page.locator("#facility-count").inner_text()) == 20  # from docs/data/api_snapshot.json
    expect(page.locator("#trend-chart path").first).to_be_visible()


def test_no_horizontal_scrolling_on_a_phone(open_dashboard):
    page = open_dashboard(viewport={"width": 375, "height": 812})
    _wait_until_live(page)
    overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    assert overflow <= 0, f"page is {overflow}px wider than a 375px screen"
