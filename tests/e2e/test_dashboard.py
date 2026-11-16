"""
test_dashboard.py: END-TO-END (E2E) TESTS
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A real browser opens the dashboard the way a visitor does and checks what is on
screen: that every number comes from the published data files, that the page
talks to no server but its own, that charts, tooltips, keyboard use, theme and
the phone layout work, and that one broken data file does not take the rest of
the page down.

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
FONT_HOSTS = ("https://fonts.googleapis.com/", "https://fonts.gstatic.com/")


def _data(name):
    with open(os.path.join(ROOT, "docs", "data", name), encoding="utf-8") as fh:
        return json.load(fh)


# ── Page health ────────────────────────────────────────────────

def test_page_loads_without_javascript_errors(open_dashboard):
    page = open_dashboard()
    expect(page).to_have_title(re.compile("Industrial Energy SQL Pipeline"))
    expect(page.locator("h1")).to_contain_text("Finland's electricity grid")
    expect(page.locator("#co2-kpis .kpi").first).to_be_visible()      # the last file has rendered
    assert page.problems == [], page.problems


def test_page_calls_no_server_but_its_own(open_dashboard):
    """The page is static: no API, no third party, apart from the web fonts."""
    page = open_dashboard()
    expect(page.locator("#ev-kpis .kpi").first).to_be_visible()
    page.wait_for_load_state("networkidle")
    others = [u for u in page.foreign_requests if not u.startswith(FONT_HOSTS)]
    assert others == [], others


# ── Every number comes from the data files ─────────────────────

def test_hero_numbers_equal_the_data_files(open_dashboard):
    eng, sc, co2, ev = (_data(f) for f in ("engineering.json", "forecast_scorecard.json", "co2_forecast.json", "grid_events.json"))
    wind = next(r for r in sc["summary"] if r["variable"] == "wind" and r["product"] == "day_ahead")
    page = open_dashboard()
    expect(page.locator("#proof-rows")).to_have_text(f"{eng['partitioning']['total_rows']:,}")
    expect(page.locator("#proof-wind")).to_have_text(f"{round(wind['mae_mw']):,} MW")
    expect(page.locator("#proof-co2")).to_have_text(f"{co2['backtest']['saving_pct']:.1f}%")
    expect(page.locator("#proof-events")).to_have_text(f"{sum(c['year'] for c in ev['counts'].values()):,}")


def test_numbers_are_not_hard_coded_in_the_html(open_dashboard):
    """With every data file missing, the headline numbers stay a dash."""
    page = open_dashboard(block=("*",))
    page.wait_for_load_state("networkidle")
    for tile in ("proof-rows", "proof-wind", "proof-co2", "proof-events"):
        assert page.locator(f"#{tile}").inner_text() == "–"


def test_daily_grid_chart_shows_the_published_summary(open_dashboard):
    recent = _data("fingrid_recent_daily.json")
    page = open_dashboard()
    expect(page.locator("#grid-chart path").first).to_be_visible()
    expect(page.locator("#grid-kpis .kpi strong").first).to_have_text(f"{recent['summary']['wind_mean_mw']:,.0f} MW")


def test_latest_fingrid_row_shows_finnish_time(open_dashboard):
    page = open_dashboard()
    row = page.locator("#grid-latest")
    expect(row).to_be_visible()
    expect(row).to_contain_text("6,603 MW")
    expect(row).to_contain_text("11,455 MW")
    expect(row).to_contain_text("08:15–08:30 Finnish time")   # 06:15 UTC = 08:15 in Helsinki (EET)


def test_latest_fingrid_row_hides_without_its_file(open_dashboard):
    page = open_dashboard(latest="missing")
    expect(page.locator("#grid-kpis .kpi").first).to_be_visible()
    expect(page.locator("#grid-latest")).to_be_hidden()


def test_forecast_scorecard_shows_the_published_numbers(open_dashboard):
    sc = _data("forecast_scorecard.json")
    wind = next(r for r in sc["summary"] if r["variable"] == "wind" and r["product"] == "day_ahead")
    cons = next(r for r in sc["summary"] if r["variable"] == "consumption" and r["product"] == "day_ahead")
    page = open_dashboard()
    kpis = page.locator("#fc-kpis .kpi strong")
    expect(kpis.first).to_have_text(f"{round(wind['mae_mw']):,} MW")
    expect(page.locator("#fc-hour-chart path").first).to_be_visible()
    expect(page.locator("#fc-misses tr")).to_have_count(5)
    page.locator('#fc-tabs button[data-var="consumption"]').click()
    expect(kpis.first).to_have_text(f"{round(cons['mae_mw']):,} MW")
    expect(page.locator("#fc-hour-title")).to_contain_text("consumption")


def test_co2_forecast_names_the_published_cleanest_hour(open_dashboard):
    c = _data("co2_forecast.json")
    page = open_dashboard()
    start = c["cleanest_hour"]["hour_fi"]
    expect(page.locator("#co2-kpis .kpi strong").first).to_have_text(f"{start:02d}:00–{(start + 1) % 24:02d}:00")
    expect(page.locator("#co2-title")).to_contain_text("tomorrow" if c["target_is_tomorrow"] else "today")
    expect(page.locator("#co2-past-chart path")).to_have_count(2)
    expect(page.locator("#co2-record .kpi")).to_have_count(4)


def test_grid_event_log_shows_the_published_counts(open_dashboard):
    d = _data("grid_events.json")
    c = d["counts"]
    page = open_dashboard()
    expect(page.locator("#ev-kpis .kpi strong").first).to_have_text(f"{c['frequency_low']['year'] + c['frequency_high']['year']:,}")
    expect(page.locator("#ev-recent tr")).to_have_count(len(d["recent"]))
    expect(page.locator("#ev-top tr")).to_have_count(sum(1 for v in d["top"].values() if v))


def test_engineering_shows_partitions_benchmark_and_tests(open_dashboard):
    eng = _data("engineering.json")
    page = open_dashboard()
    months = [p for p in eng["partitioning"]["partitions"] if p["partition"] != "fingrid_observation_default"]
    expect(page.locator("#parts .prow")).to_have_count(len(months))
    expect(page.locator("#parts-summary")).to_contain_text(f"Reads 1 of {len(months)} partitions")
    page.locator('#parts-mode button[data-mode="all"]').click()
    expect(page.locator("#parts-summary")).to_contain_text(f"all {len(months)}")
    expect(page.locator("#bench .bar-row")).to_have_count(3)
    expect(page.locator("#tests-title")).to_have_text(f"{eng['tests']['total']} automated tests")


# ── Interaction & accessibility ────────────────────────────────

def test_hovering_a_chart_shows_a_tooltip(open_dashboard):
    page = open_dashboard()
    chart = page.locator("#grid-chart")
    chart.scroll_into_view_if_needed()
    chart.locator(".tip-hit").hover()
    expect(chart.locator("tspan").nth(1)).to_contain_text("MW")


def test_chart_values_can_be_read_with_the_keyboard(open_dashboard):
    page = open_dashboard()
    hit = page.locator("#fc-hour-chart .tip-hit")
    hit.focus()
    page.keyboard.press("Home")
    first = hit.get_attribute("aria-valuetext")
    page.keyboard.press("ArrowRight")
    assert hit.get_attribute("aria-valuenow") == "1"
    assert hit.get_attribute("aria-valuetext") != first and "MW" in first


def test_header_chips_explain_themselves_on_hover_and_focus(open_dashboard):
    page = open_dashboard()
    chips = page.locator(".chips .chip")
    expect(chips).to_have_count(2)
    for i in range(2):
        chip = chips.nth(i)
        tip = page.locator("#" + chip.get_attribute("aria-describedby"))
        expect(tip).to_be_hidden()
        chip.hover()
        expect(tip).to_be_visible()
        page.mouse.move(0, 0)
        expect(tip).to_be_hidden()
    chips.nth(1).focus()                      # keyboard users get the same text
    expect(page.locator("#tip-fresh")).to_contain_text("GitHub Action")


def test_navigation_links_jump_to_their_sections(open_dashboard):
    page = open_dashboard()
    page.locator('.nav a[href="#co2-ch"]').click()
    expect(page.locator("#co2-ch")).to_be_in_viewport()
    assert page.url.endswith("#co2-ch")


def test_sql_drawers_show_the_repository_sql(open_dashboard):
    page = open_dashboard()
    with open(os.path.join(ROOT, "sql", "schema", "14_co2_forecast.sql"), encoding="utf-8") as fh:
        expected = fh.read()
    drawer = page.locator("#sql-14")
    drawer.locator("summary").click()
    expect(drawer.locator("pre")).to_have_text(expected, use_inner_text=False, timeout=10000)


def test_pipeline_stages_are_keyboard_buttons(open_dashboard):
    page = open_dashboard()
    stages = page.locator("#pipeline button.step")
    expect(stages).to_have_count(7)
    stages.nth(2).focus()
    page.keyboard.press("Enter")
    expect(stages.nth(2)).to_have_attribute("aria-current", "step")
    expect(page.locator("#inspector")).to_contain_text("partitioned by month")


def test_theme_toggle_switches_and_is_remembered(open_dashboard):
    page = open_dashboard()
    html = page.locator("html")
    start = html.get_attribute("data-theme")
    page.locator("#theme-toggle").click()
    flipped = "light" if start == "dark" else "dark"
    expect(html).to_have_attribute("data-theme", flipped)
    page.reload()
    expect(html).to_have_attribute("data-theme", flipped)


def test_sections_animate_again_when_scrolling_back(open_dashboard):
    page = open_dashboard()
    panel = page.locator("#grid .panel").first
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

def test_one_missing_data_file_does_not_break_the_rest(open_dashboard):
    page = open_dashboard(block=("forecast_scorecard.json",))
    expect(page.locator("#fc-error")).to_contain_text("could not be loaded")
    expect(page.locator("#co2-kpis .kpi").first).to_be_visible()
    expect(page.locator("#ev-kpis .kpi").first).to_be_visible()
    expect(page.locator("#grid-chart path").first).to_be_visible()
    assert not [p for p in page.problems if p.startswith("uncaught")], page.problems


def test_no_horizontal_scrolling_on_a_phone(open_dashboard):
    page = open_dashboard(viewport={"width": 375, "height": 812})
    expect(page.locator("#ev-kpis .kpi").first).to_be_attached()
    overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    assert overflow <= 0, f"page is {overflow}px wider than a 375px screen"
    chip = page.locator(".chips .chip").nth(1)
    chip.scroll_into_view_if_needed()
    chip.focus()                              # what a tap does on a touch screen
    box = page.locator("#tip-fresh").bounding_box()
    assert box and box["x"] >= 0 and box["x"] + box["width"] <= 375, box
