"""
test_dashboard.py: END-TO-END (E2E) TESTS
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A real browser opens the dashboard the way a visitor does and checks what is on
screen: that every number comes from the published data files, that the page
talks to no server but its own, that charts, tooltips, keyboard use, theme and
the inspector drawer, the phone layout work, and that one broken data file does
not take the rest of the page down.

Run only these:   pytest -m e2e          (needs: pip install playwright
                                          && playwright install chromium)
"""

import json
import math
import os
import re

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
FONT_HOSTS = ("https://fonts.googleapis.com/", "https://fonts.gstatic.com/")


def js_round(x):
    """Math.round, which the page uses: halves go up (Python's round() goes to the even neighbour)."""
    return math.floor(x + 0.5)


def _day_word(iso_day):
    """What the page calls a day: "today" or "tomorrow" in Finland, otherwise its date."""
    from datetime import date, datetime, timedelta
    from zoneinfo import ZoneInfo
    today = datetime.now(ZoneInfo("Europe/Helsinki")).date()
    day = date.fromisoformat(iso_day)
    return "today" if day == today else "tomorrow" if day == today + timedelta(days=1) else day.strftime("%-d %b %Y")


def _data(name):
    with open(os.path.join(ROOT, "docs", "data", name), encoding="utf-8") as fh:
        return json.load(fh)


# ── Page health ────────────────────────────────────────────────

def _open_pane(page, pane):
    """Open the inspector drawer on one pane, the way a visitor does: the tile's inspect button."""
    button = page.locator(f'.inspect-btn[data-open-drawer="{pane}"]')
    if button.count():
        button.click()
    else:                                     # e.g. Forecasts: reached from the hero's past-year view or a tab
        page.locator("#hero-inspect").click()
        page.locator(f'.drawer-tabs .dtab[data-pane="{pane}"]').click()
    expect(page.locator(f"#{pane}")).to_be_visible()


def test_page_loads_without_javascript_errors(open_dashboard):
    page = open_dashboard()
    expect(page).to_have_title(re.compile("Grid in SQL"))
    expect(page.locator("h1")).to_contain_text("Finland's electricity grid")
    expect(page.locator("#mk-craft-tests")).not_to_have_text("–")      # the last file has rendered
    assert page.problems == [], page.problems


def test_page_calls_no_server_but_its_own(open_dashboard):
    """The page is static: no API, no third party, apart from the web fonts."""
    page = open_dashboard()
    expect(page.locator("#mk-ev-freq")).not_to_have_text("–")
    page.wait_for_load_state("networkidle")
    others = [u for u in page.foreign_requests if not u.startswith(FONT_HOSTS)]
    assert others == [], others


# ── Every number comes from the data files ─────────────────────

def test_hero_numbers_equal_the_data_files(open_dashboard):
    eng, sc, co2, ev = (_data(f) for f in ("engineering.json", "forecast_scorecard.json", "co2_forecast.json", "grid_events.json"))
    wind = next(r for r in sc["summary"] if r["variable"] == "wind" and r["product"] == "day_ahead")
    page = open_dashboard()
    expect(page.locator("#proof-rows")).to_have_text(f"{eng['partitioning']['total_rows']:,}")
    expect(page.locator("#proof-wind")).to_have_text(f"{js_round(wind['mae_mw']):,} MW")
    expect(page.locator("#proof-co2")).to_have_text(f"{co2['backtest']['saving_pct']:.1f}%")
    expect(page.locator("#proof-events")).to_have_text(f"{sum(c['year'] for c in ev['counts'].values()):,}")
    expect(page.locator(".n-datasets").first).to_have_text(str(eng["datasets"]))


def test_numbers_are_not_hard_coded_in_the_html(open_dashboard):
    """With every data file missing, the headline and tile numbers stay a dash."""
    page = open_dashboard(block=("*",))
    page.wait_for_load_state("networkidle")
    for tile in ("proof-rows", "proof-wind", "proof-co2", "proof-events", "mk-co2-best", "mk-co2-low",
                 "mk-ev-freq", "mk-ev-peak-min", "mk-cold-slope", "mk-cold-r2", "mk-wa-imports", "mk-wa-cons", "mk-craft-speedup", "mk-craft-tests"):
        assert page.locator(f"#{tile}").inner_text() == "–", tile


def test_hero_chart_shows_the_published_grid_summary(open_dashboard):
    recent = _data("fingrid_recent_daily.json")
    page = open_dashboard()
    page.locator('#hero-view button[data-view="grid"]').click()
    expect(page.locator("#bento-hero-chart path").first).to_be_visible()
    expect(page.locator("#hero-mini-kpis strong").first).to_have_text(f"{recent['summary']['wind_mean_mw']:,.0f} MW")


def test_hero_opens_on_tomorrows_ranges(open_dashboard):
    r = _data("forecast_ranges.json")
    page = open_dashboard()
    expect(page.locator('#hero-view button[data-view="ranges"]')).to_have_attribute("aria-pressed", "true")
    for v, chart in (("wind", "#range-wind-chart"), ("consumption", "#range-cons-chart")):
        expect(page.locator(f"#mk-range-{v}")).to_have_text(f"±{js_round(r[v]['mean_width80_mw'] / 2):,} MW")
        expect(page.locator(f"{chart} path.band")).to_have_count(2)             # 95 % and 80 %
    expect(page.locator("#bento-hero-chart")).to_be_hidden()
    page.locator("#hero-inspect").click()
    expect(page.locator("#pane-ranges")).to_be_visible()
    expect(page.locator("#rg-backtest tr")).to_have_count(4)
    adaptive = r["wind"]["backtest"]["methods"]["adaptive"]["0.8"]
    expect(page.locator("#rg-backtest tr").last).to_contain_text(f"{adaptive['coverage'] * 100:.1f}%")
    expect(page.locator("#rg-record-wind path.band")).to_have_count(1)


def test_range_tooltip_names_both_ranges(open_dashboard):
    page = open_dashboard()
    hit = page.locator("#range-cons-chart .tip-hit")
    hit.focus()
    page.keyboard.press("Home")
    expect(hit).to_have_attribute("aria-valuetext", re.compile(r"80%: [\d,]+ MW – [\d,]+ MW, 95%: "))


def test_hero_falls_back_to_the_past_year_without_ranges(open_dashboard):
    page = open_dashboard(block=("forecast_ranges.json",))
    expect(page.locator("#bento-hero-chart path").first).to_be_visible()
    expect(page.locator('#hero-view button[data-view="grid"]')).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#hero-inspect")).to_have_attribute("data-open-drawer", "pane-forecasts")


def test_latest_fingrid_ticker_shows_finnish_time(open_dashboard):
    page = open_dashboard()
    row = page.locator("#live-ticker")
    expect(row).to_be_visible()
    expect(row).to_contain_text("6,603 MW")
    expect(row).to_contain_text("11,455 MW")
    expect(row).to_contain_text("08:15–08:30 Finnish time")   # 06:15 UTC = 08:15 in Helsinki (EET)


def test_latest_fingrid_ticker_hides_without_its_file(open_dashboard):
    page = open_dashboard(latest="missing")
    expect(page.locator("#mk-ev-freq")).not_to_have_text("–")
    expect(page.locator("#live-ticker")).to_be_hidden()


def test_forecast_scorecard_shows_the_published_numbers(open_dashboard):
    sc = _data("forecast_scorecard.json")
    wind = next(r for r in sc["summary"] if r["variable"] == "wind" and r["product"] == "day_ahead")
    cons = next(r for r in sc["summary"] if r["variable"] == "consumption" and r["product"] == "day_ahead")
    page = open_dashboard()
    _open_pane(page, "pane-forecasts")
    kpis = page.locator("#fc-kpis .kpi strong")
    expect(kpis.first).to_have_text(f"{js_round(wind['mae_mw']):,} MW")
    expect(page.locator("#fc-hour-chart path").first).to_be_visible()
    expect(page.locator("#fc-misses tr")).to_have_count(5)
    page.locator('#fc-tabs button[data-var="consumption"]').click()
    expect(kpis.first).to_have_text(f"{js_round(cons['mae_mw']):,} MW")
    expect(page.locator("#fc-takeaway")).to_contain_text("consumption")


def test_co2_forecast_names_the_published_cleanest_hour(open_dashboard):
    c = _data("co2_forecast.json")
    page = open_dashboard()
    best = c["best_3h"]["hour_fi"]
    expect(page.locator("#mk-co2-best")).to_have_text(f"{best:02d}:00–{(best + 3) % 24:02d}:00")
    _open_pane(page, "pane-co2")
    start = c["cleanest_hour"]["hour_fi"]
    expect(page.locator("#co2-kpis .kpi strong").first).to_have_text(f"{start:02d}:00–{(start + 1) % 24:02d}:00")
    expect(page.locator("#co2-title")).to_contain_text(_day_word(c["target_day"]))
    expect(page.locator("#co2-past-chart path")).to_have_count(2)
    expect(page.locator("#co2-record .kpi")).to_have_count(4)


def test_grid_event_log_shows_the_published_counts(open_dashboard):
    d = _data("grid_events.json")
    c = d["counts"]
    freq = f"{c['frequency_low']['year'] + c['frequency_high']['year']:,}"
    page = open_dashboard()
    expect(page.locator("#mk-ev-freq")).to_have_text(freq)
    _open_pane(page, "pane-events")
    expect(page.locator("#ev-kpis .kpi strong").first).to_have_text(f"{c['nuclear_drop']['year']:,}")
    expect(page.locator("#ev-kpis")).not_to_contain_text("frequency")          # that count is on the tile only
    expect(page.locator("#ev-recent tr")).to_have_count(len(d["recent"]))
    expect(page.locator("#ev-top tr")).to_have_count(sum(1 for v in d["top"].values() if v))


def test_cold_chapter_shows_the_fitted_model(open_dashboard):
    t = _data("temperature.json")
    wd = next(f for f in t["fits"] if f["day_type"] == "weekday")
    page = open_dashboard()
    expect(page.locator("#mk-cold-slope")).to_have_text(f"+{js_round(wd['mw_per_degree']):,} MW")
    expect(page.locator("#bento-cold-chart path")).to_have_count(3)
    we = next(f for f in t["fits"] if f["day_type"] == "weekend")
    _open_pane(page, "pane-cold")
    expect(page.locator("#cold-kpis .kpi strong").first).to_have_text(f"+{js_round(we['mw_per_degree']):,} MW")
    expect(page.locator("#cold-takeaway")).to_contain_text(f"{wd['balance_point_c']} °C")


def test_wind_balance_shows_the_published_shares(open_dashboard):
    d = _data("wind_allocation.json")
    pct = lambda v: f"{js_round(v * 100)}%"
    page = open_dashboard()
    expect(page.locator("#mk-wa-imports")).to_have_text(pct(d["wind"]["imports"]["share"]))
    expect(page.locator("#mk-wa-cons")).to_have_text(pct(d["wind"]["consumption"]["share"]))
    rows = page.locator("#alloc-bars .alloc-row")
    expect(rows).to_have_count(2 + len(d["seasons"]))                       # wind, each season, nuclear
    expect(rows.first.locator(".alloc-track i")).to_have_count(4)
    _open_pane(page, "pane-wind")
    expect(page.locator("#wa-table tr")).to_have_count(4)
    expect(page.locator("#wa-table tr").first).to_contain_text(pct(d["wind"]["imports"]["share"]))
    expect(page.locator("#wa-seasons tr")).to_have_count(len(d["seasons"]))
    expect(page.locator("#wa-checks")).to_contain_text(f"{abs(d['net_import_check']['r_identity_vs_measured_194']):.4f}")


def test_wind_balance_rows_can_be_read_with_the_keyboard(open_dashboard):
    d = _data("wind_allocation.json")
    page = open_dashboard()
    row = page.locator("#alloc-bars .alloc-row").first
    expect(row).to_have_attribute("aria-label", re.compile(rf"lower imports {js_round(d['wind']['imports']['share'] * 100)}%"))
    row.focus()
    tip = page.locator("#alloc-bars .alloc-tip")
    expect(tip).to_be_visible()
    expect(tip).to_contain_text("Wind · year")
    page.keyboard.press("Tab")
    expect(tip).to_contain_text(next(s["season"] for s in d["seasons"]).capitalize())


def test_engineering_shows_partitions_benchmark_and_tests(open_dashboard):
    eng = _data("engineering.json")
    page = open_dashboard()
    expect(page.locator("#mk-craft-tests")).to_have_text(str(eng["tests"]["total"]))
    _open_pane(page, "pane-craft")
    months = [p for p in eng["partitioning"]["partitions"] if p["partition"] != "fingrid_observation_default"]
    expect(page.locator("#parts .prow")).to_have_count(len(months))
    expect(page.locator("#parts-summary")).to_contain_text(f"prunes {len(months) - 1} partitions")
    page.locator('#parts-mode button[data-mode="all"]').click()
    expect(page.locator("#parts-summary")).to_contain_text(f"all {len(months)}")
    expect(page.locator("#bench .bar-row")).to_have_count(3)
    expect(page.locator("#tests-title")).to_have_text(f"{eng['tests']['total']} Automated CI Tests")


# ── Interaction & accessibility ────────────────────────────────

def test_hovering_a_chart_shows_a_tooltip(open_dashboard):
    page = open_dashboard()
    chart = page.locator("#range-wind-chart")
    chart.scroll_into_view_if_needed()
    chart.locator(".tip-hit").hover()
    expect(chart.locator("tspan").nth(1)).to_contain_text("MW")


def test_chart_values_can_be_read_with_the_keyboard(open_dashboard):
    page = open_dashboard()
    _open_pane(page, "pane-forecasts")
    hit = page.locator("#fc-hour-chart .tip-hit")
    hit.focus()
    page.keyboard.press("Home")
    expect(hit).to_have_attribute("aria-valuenow", "0")
    first = hit.get_attribute("aria-valuetext")
    page.keyboard.press("ArrowRight")
    expect(hit).to_have_attribute("aria-valuenow", "1")
    assert hit.get_attribute("aria-valuetext") != first and "MW" in first
    page.set_viewport_size({"width": 1000, "height": 800})     # a redraw keeps the place and the focus
    expect(hit).to_be_focused()
    expect(hit).to_have_attribute("aria-valuenow", "1")


def test_inspector_drawer_opens_switches_and_closes_with_escape(open_dashboard):
    page = open_dashboard()
    opener = page.locator('.inspect-btn[data-open-drawer="pane-co2"]')
    opener.click()
    expect(page.locator(".drawer")).to_be_in_viewport()
    expect(page.locator("#drawer-close")).to_be_focused()
    page.locator('.drawer-tabs .dtab[data-pane="pane-events"]').click()
    expect(page.locator("#pane-events")).to_be_visible()
    expect(page.locator("#pane-co2")).to_be_hidden()
    page.keyboard.press("Escape")
    expect(page.locator("#drawer-mask")).to_have_attribute("aria-hidden", "true")
    expect(opener).to_be_focused()                             # focus goes back where it was


def test_copy_button_keeps_the_pane_open(open_dashboard):
    page = open_dashboard()
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    _open_pane(page, "pane-craft")
    page.locator("#copy-cmd").click()
    expect(page.locator("#copy-cmd")).to_have_text("Copied!")
    expect(page.locator("#pane-craft")).to_be_visible()


def test_drawer_panes_do_not_repeat_the_tile_charts(open_dashboard):
    """Each tile shows its headline chart; the drawer adds detail instead of drawing it again."""
    page = open_dashboard()
    _open_pane(page, "pane-co2")
    for pane in ("pane-co2", "pane-events", "pane-cold"):
        page.locator(f'.drawer-tabs .dtab[data-pane="{pane}"]').click()
        expect(page.locator(f"#{pane} .kpi").first).to_be_visible()
    assert page.locator("#pane-co2 svg.chart").count() == 1                  # only yesterday's replay
    assert page.locator("#pane-events svg.chart, #pane-cold svg.chart").count() == 0


def test_drawer_tabs_fit_without_a_scrollbar(open_dashboard):
    for width in (1400, 375):
        page = open_dashboard(viewport={"width": width, "height": 800})
        _open_pane(page, "pane-forecasts")
        overflow = page.evaluate("(() => { const t = document.querySelector('.drawer-tabs'); return t.scrollWidth - t.clientWidth; })()")
        assert overflow <= 0, (width, overflow)


def test_sql_drawers_show_the_repository_sql(open_dashboard):
    page = open_dashboard()
    with open(os.path.join(ROOT, "sql", "schema", "14_co2_forecast.sql"), encoding="utf-8") as fh:
        expected = fh.read()
    _open_pane(page, "pane-co2")
    drawer = page.locator("#sql-14")
    drawer.locator("summary").click()
    expect(drawer.locator("pre")).to_have_text(expected, use_inner_text=False, timeout=10000)


def test_inspect_tags_name_files_that_exist(open_dashboard):
    page = open_dashboard()
    for tag in page.locator(".inspect-btn .tag").all_inner_texts():
        for name in re.findall(r"\d\d_\w+\.sql", tag):
            assert any(os.path.exists(os.path.join(ROOT, "sql", d, name)) for d in ("schema", "analysis")), name


def test_pipeline_stages_are_keyboard_buttons(open_dashboard):
    page = open_dashboard()
    _open_pane(page, "pane-craft")
    stages = page.locator("#pipeline button.step")
    expect(stages).to_have_count(7)
    stages.nth(2).focus()
    page.keyboard.press("Enter")
    expect(stages.nth(2)).to_have_attribute("aria-current", "step")
    expect(page.locator("#inspector")).to_contain_text("partitions by month")


def test_theme_toggle_switches_and_is_remembered(open_dashboard):
    page = open_dashboard()
    html = page.locator("html")
    start = html.get_attribute("data-theme")
    page.locator("#theme-toggle").click()
    flipped = "light" if start == "dark" else "dark"
    expect(html).to_have_attribute("data-theme", flipped)
    page.reload()
    expect(html).to_have_attribute("data-theme", flipped)


def test_headline_fits_on_one_line_on_desktop(open_dashboard):
    page = open_dashboard()
    lines = page.evaluate("(() => { const h = document.querySelector('h1'); return Math.round(h.getBoundingClientRect().height / parseFloat(getComputedStyle(h).lineHeight)); })()")
    assert lines == 1


# ── Resilience & layout ────────────────────────────────────────

def test_one_missing_data_file_does_not_break_the_rest(open_dashboard):
    page = open_dashboard(block=("forecast_scorecard.json",))
    expect(page.locator("#mk-co2-best")).not_to_have_text("–")
    expect(page.locator("#mk-ev-freq")).not_to_have_text("–")
    expect(page.locator("#range-wind-chart path").first).to_be_visible()
    _open_pane(page, "pane-forecasts")
    expect(page.locator("#fc-error")).to_contain_text("could not be loaded")
    assert not [p for p in page.problems if p.startswith("uncaught")], page.problems


def test_no_horizontal_scrolling_on_a_phone(open_dashboard):
    page = open_dashboard(viewport={"width": 375, "height": 812})
    expect(page.locator("#mk-ev-freq")).not_to_have_text("–")
    overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    assert overflow <= 0, f"page is {overflow}px wider than a 375px screen"
    box = page.locator("#theme-toggle").bounding_box()
    assert box and box["x"] + box["width"] <= 375, box
    _open_pane(page, "pane-events")
    page.wait_for_function("document.querySelector('.drawer').getBoundingClientRect().x < 0.01")   # slide-in done
    box = page.locator(".drawer").bounding_box()
    assert box["x"] >= 0 and box["x"] + box["width"] <= 375.5, box


@pytest.mark.parametrize("width,height", [(1442, 900), (1440, 840), (1536, 864), (1920, 1080), (1366, 768)])
def test_tiles_never_cut_off_their_content(open_dashboard, width, height):
    """Every tile shows all it holds, buttons stay on one line, charts are drawn at their real size."""
    page = open_dashboard(viewport={"width": width, "height": height})
    expect(page.locator("#mk-craft-tests")).not_to_have_text("–")
    page.wait_for_timeout(400)                               # let the size observer redraw
    problems = page.evaluate("""(() => { const out = [];
      document.querySelectorAll('.tile').forEach(t => { const tb = t.getBoundingClientRect();
        t.querySelectorAll('*').forEach(c => { const b = c.getBoundingClientRect();
          if (b.width && (b.bottom > tb.bottom + 1 || b.right > tb.right + 1)) out.push('cut: ' + t.querySelector('h2').textContent); });
        if (tb.right > innerWidth + 1) out.push('off screen: ' + t.querySelector('h2').textContent); });
      document.querySelectorAll('.inspect-btn').forEach(b => { if (b.getBoundingClientRect().height > 44) out.push('button wraps: ' + b.textContent.trim()); });
      document.querySelectorAll('svg.chart').forEach(s => { const r = s.getBoundingClientRect(), vb = (s.getAttribute('viewBox') || '').split(' ').map(Number);
        if (r.width && vb.length === 4 && (Math.abs(r.width - vb[2]) > 2 || Math.abs(r.height - vb[3]) > 2)) out.push('chart scaled: ' + s.id); });
      return [...new Set(out)]; })()""")
    assert problems == [], problems
    assert page.evaluate("document.documentElement.scrollWidth - window.innerWidth") <= 0


def test_charts_name_their_units(open_dashboard):
    page = open_dashboard()
    expect(page.locator("#range-wind-chart text.unit")).to_have_text("MW")
    expect(page.locator("#bento-co2-chart text.unit")).to_have_text("g CO₂ per kWh")
    expect(page.locator("#bento-ev-chart text.unit")).to_contain_text("% of minutes")
    expect(page.locator("#bento-cold-chart text.unit")).to_contain_text("MW")
