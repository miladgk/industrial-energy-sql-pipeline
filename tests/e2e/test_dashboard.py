"""
test_dashboard.py: END-TO-END (E2E) TESTS
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A real browser opens the dashboard (web/, built to web/dist/) the way a
visitor does and checks what is on screen: that every number comes from the
published data files, that the page talks to no server but its own, that the
chapters, charts, keyboard use, theme, command palette and the SQL lenses work,
that each chapter fits the screen on a desktop and does not scroll sideways on
a phone, and that one broken data file does not take the rest of the page down.

Run only these:   pytest -m e2e          (needs: pip install playwright
                                          && playwright install chromium,
                                          and a built page: npm --prefix web run build)
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

CHAPTERS = ["overview", "forecasts", "ranges", "model", "co2", "cold", "events",
            "strikes", "wind", "price", "europe", "ev", "craft"]


def js_round(x):
    """Math.round, which the page uses: halves go up (Python's round() goes to the even neighbour)."""
    return math.floor(x + 0.5)


def fmt(v, digits=0):
    """The page's fmt(): en-US grouping, a fixed number of decimals."""
    scaled = math.floor(abs(v) * 10 ** digits + 0.5) / 10 ** digits
    return f"{'-' if v < 0 and scaled else ''}{scaled:,.{digits}f}"


def _data(name):
    with open(os.path.join(ROOT, "docs", "data", name), encoding="utf-8") as fh:
        return json.load(fh)


def _ordinal(n):
    return f"{n}{'st' if n % 10 == 1 and n % 100 != 11 else 'nd' if n % 10 == 2 and n % 100 != 12 else 'rd' if n % 10 == 3 and n % 100 != 13 else 'th'}"


def _goto(page, chapter):
    """Switch chapter the way a deep link does (the URL hash)."""
    page.evaluate(f"location.hash = '{chapter}'")
    expect(page.locator("main")).to_be_visible()


def _lens(page, name):
    """Click a chapter's lens switch (some chapters mark them up as tabs, some as plain buttons)."""
    page.locator("main button").filter(has_text=re.compile(rf"^\s*{re.escape(name)}\s*$")).first.click()


def _ready(page):
    """The data have rendered once the headline row count is filled in."""
    expect(page.locator("#proof-rows")).not_to_have_text("–")


def _badges(page):
    """{chapter label: badge} from the desktop chapter rail."""
    out = {}
    for button in page.locator("aside nav button").all():
        label, badge = [s.strip() for s in button.inner_text().split("\n") if s.strip()]
        out[label] = badge
    return out


# ── Page health ────────────────────────────────────────────────

def test_page_loads_without_javascript_errors(open_dashboard):
    page = open_dashboard()
    expect(page).to_have_title(re.compile("Grid in SQL"))
    expect(page.locator("h1")).to_contain_text("Finland's electricity grid")
    _ready(page)
    assert page.problems == [], page.problems


def test_page_calls_no_server_but_its_own(open_dashboard):
    """The page is static: no API, no third party, apart from the web fonts."""
    page = open_dashboard()
    _ready(page)
    page.wait_for_load_state("networkidle")
    others = [u for u in page.foreign_requests if not u.startswith(FONT_HOSTS)]
    assert others == [], others


def test_rail_lists_every_chapter(open_dashboard):
    page = open_dashboard()
    _ready(page)
    assert len(_badges(page)) == len(CHAPTERS)


# ── Every number comes from the data files ─────────────────────

def test_hero_numbers_equal_the_data_files(open_dashboard):
    eng, sc, co2, ev = (_data(f) for f in ("engineering.json", "forecast_scorecard.json", "co2_forecast.json", "grid_events.json"))
    wind = next(r for r in sc["summary"] if r["variable"] == "wind" and r["product"] == "day_ahead")
    page = open_dashboard()
    expect(page.locator("#proof-rows")).to_have_text(f"{eng['partitioning']['total_rows']:,}")
    expect(page.locator("#proof-wind")).to_have_text(f"{js_round(wind['mae_mw']):,} MW")
    expect(page.locator("#proof-co2")).to_have_text(f"{co2['backtest']['saving_pct']:.1f}%")
    expect(page.locator("#proof-events")).to_have_text(f"{sum(c['year'] for c in ev['counts'].values()):,}")
    expect(page.locator("main")).to_contain_text(f"{eng['datasets']} LIVE SQL STREAMS", ignore_case=True)


def test_chapter_badges_equal_the_data_files(open_dashboard):
    eng, sc, ranges, wm, co2, temp, events, strikes, wa, pw, eu, cars = (_data(f) for f in (
        "engineering.json", "forecast_scorecard.json", "forecast_ranges.json", "weather_model.json",
        "co2_forecast.json", "temperature.json", "grid_events.json", "strike_effect.json",
        "wind_allocation.json", "price_wind.json", "europe.json", "ev_charging.json"))
    wind = next(r for r in sc["summary"] if r["variable"] == "wind" and r["product"] == "day_ahead")
    weekday = next(f for f in temp["fits"] if f["day_type"] == "weekday")
    biggest = max(strikes["events"], key=lambda e: abs(e["gwh"]))
    expected = {
        "Executive Overview": f"{eng['datasets']} sets",
        "Forecasts vs. Reality": f"{fmt(js_round(wind['mae_mw']))} MW",
        "Tomorrow's Ranges": f"±{fmt(js_round(ranges['wind']['mean_width80_mw'] / 2))} MW",
        "Public Data vs. Fingrid": f"{fmt(js_round(wm['wind']['backtest']['mae_mw']['weather']))} MW",
        "CO₂ Intensity Model": f"{fmt(co2['cleanest_hour']['co2'], 1)} g",
        "Thermodynamics of Cold": f"+{fmt(js_round(weekday['mw_per_degree']))} MW/°C",
        "Grid Events (50 Hz)": fmt(events["counts"]["frequency_low"]["year"] + events["counts"]["frequency_high"]["year"]),
        "The 2024 Strikes": f"{fmt(abs(biggest['gwh']))} GWh",
        "Wind Power Balance": f"{js_round(wa['wind']['imports']['share'] * 100)}%",
        "Wind & Spot Price": f"−{fmt(pw['per_gw']['eur_per_gw'], 1)} €",
        "Finland in Europe": f"{eu['finland_rank']['price_eur_mwh']} of {eu['finland_rank']['of']}",
        "Electric Cars": f"+{fmt(cars['added_mw']['central'])} MW",
        "Engineering & SQL": f"{fmt(js_round(eng['benchmark']['speedup_index_vs_none']))}×",
    }
    page = open_dashboard()
    _ready(page)
    assert _badges(page) == expected


def test_numbers_are_not_hard_coded_in_the_html(open_dashboard):
    """With every data file missing, the headline and chapter numbers stay a dash."""
    page = open_dashboard(block=("*",))
    expect(page.locator("#proof-rows")).to_have_text("–")
    for tile in ("proof-rows", "proof-wind", "proof-co2", "proof-events"):
        assert page.locator(f"#{tile}").inner_text() == "–", tile
    assert set(_badges(page).values()) == {"–"}, _badges(page)
    expect(page.locator("#header-rows")).to_have_text("– rows")


@pytest.mark.parametrize("chapter", ["forecasts", "ranges", "model", "co2", "cold", "events",
                                     "strikes", "wind", "price", "craft"])
def test_chapter_shows_its_published_number(open_dashboard, chapter):
    if chapter == "forecasts":
        sc = _data("forecast_scorecard.json")
        wind = next(r for r in sc["summary"] if r["variable"] == "wind" and r["product"] == "day_ahead")
        text = f"{fmt(js_round(wind['mae_mw']))} MW"
    elif chapter == "ranges":
        text = f"±{fmt(js_round(_data('forecast_ranges.json')['wind']['mean_width80_mw'] / 2))} MW"
    elif chapter == "model":
        text = f"{fmt(js_round(_data('weather_model.json')['wind']['backtest']['mae_mw']['weather']))} MW"
    elif chapter == "co2":
        text = f"{fmt(_data('co2_forecast.json')['cleanest_hour']['co2'], 1)} g/kWh"
    elif chapter == "cold":
        weekday = next(f for f in _data("temperature.json")["fits"] if f["day_type"] == "weekday")
        text = f"+{fmt(js_round(weekday['mw_per_degree']))} MW"
    elif chapter == "events":
        c = _data("grid_events.json")["counts"]
        text = fmt(c["frequency_low"]["year"] + c["frequency_high"]["year"])
    elif chapter == "strikes":
        biggest = max(_data("strike_effect.json")["events"], key=lambda e: abs(e["gwh"]))
        text = f"{fmt(abs(biggest['gwh']))} GWh"
    elif chapter == "wind":
        text = f"{js_round(_data('wind_allocation.json')['wind']['imports']['share'] * 100)}%"
    elif chapter == "price":
        text = f"−{fmt(_data('price_wind.json')['per_gw']['eur_per_gw'], 1)} €/MWh"
    else:
        text = f"{_data('engineering.json')['partitioning']['total_rows']:,}"
    page = open_dashboard(chapter=chapter)
    expect(page.locator("main")).to_contain_text(text)


def test_europe_chapter_ranks_finland(open_dashboard):
    eu = _data("europe.json")
    fi = next(c for c in eu["countries"] if c["area"] == "Finland")
    rk = eu["finland_rank"]
    page = open_dashboard(chapter="europe")
    expect(page.locator("#eu-rank-price")).to_have_text(f"{_ordinal(rk['price_eur_mwh'])} of {rk['of']}")
    expect(page.locator("main")).to_contain_text(f"{fmt(fi['price'], 1)} €/MWh (EU {fmt(eu['eu']['price_demand_weighted'], 1)})")
    expect(page.locator("#eu-intensity")).to_have_text(f"{fmt(fi['intensity'])} g")
    expect(page.locator("#eu-wind-solar")).to_have_text(f"{js_round(fi['wind_solar'] * 100)}%")
    expect(page.locator('svg[aria-label="Yearly wholesale price, Finland and the EU"]')).to_be_visible()

    _lens(page, "Country Matrix")
    rows = page.locator("#eu-table tbody tr")
    expect(rows).to_have_count(len(eu["countries"]))
    expect(rows.filter(has_text="Finland")).to_contain_text(fmt(fi["price"], 1))
    expect(page.locator("#eu-check")).to_contain_text(f"{eu['price_check']['months']} months")


def test_electric_car_chapter_sets_the_estimate_against_the_growth(open_dashboard):
    d = _data("ev_charging.json")
    last = d["fleet"][-1]
    c = d["growth"]["without_boilers"]["night_minus_evening"]
    page = open_dashboard(chapter="ev")
    expect(page.locator("#car-bev")).to_have_text(f"{fmt(last['bev'] / 1000)}k")
    expect(page.locator("#car-twh")).to_have_text(f"{fmt(d['energy_now']['central']['gwh_per_year'] / 1000, 1)} TWh")
    expect(page.locator("#car-added")).to_have_text(f"+{fmt(d['added_mw']['central'])} MW")
    expect(page.locator("#car-takeaway")).to_contain_text(f"{fmt(abs(c['estimate']))} MW")
    expect(page.locator("#car-takeaway")).to_contain_text(f"{fmt(c['ci_low'])} to {fmt(c['ci_high'])}")
    expect(page.locator('svg[aria-label^="Weather-adjusted growth of consumption by hour"]')).to_be_visible()

    _lens(page, "Estimate & Timing Matrix")
    expect(page.locator("#car-timing-table tbody tr")).to_have_count(3)
    expect(page.locator("#car-energy")).to_contain_text(f"{fmt(d['km']['bev']['km_per_year'])} km")


# ── Latest Fingrid values (hourly Pages deploy) ────────────────

def test_latest_fingrid_ticker_shows_finnish_time(open_dashboard):
    """conftest.SAMPLE_LATEST: wind 6,603.0 MW and consumption 11,454.5 MW, 06:15–06:30 UTC on 16 November."""
    page = open_dashboard()
    expect(page.locator("#live-ticker")).to_be_visible()
    expect(page.locator("#tick-wind")).to_have_text("6,603 MW")
    expect(page.locator("#tick-cons")).to_have_text("11,455 MW")       # Math.round(11454.5)
    # 06:15–06:30 UTC on 16 November is 08:15–08:30 in Finland (UTC+2 in winter)
    expect(page.locator("#tick-age")).to_have_text("08:15–08:30 Finnish time")


def test_latest_fingrid_ticker_hides_without_its_file(open_dashboard):
    page = open_dashboard(latest="missing")
    _ready(page)
    page.wait_for_load_state("networkidle")
    expect(page.locator("#live-ticker")).to_have_count(0)


# ── SQL lenses ─────────────────────────────────────────────────

@pytest.mark.parametrize("chapter", ["forecasts", "ranges", "model", "co2", "cold", "events",
                                     "strikes", "wind", "price", "europe", "ev", "craft"])
def test_sql_lens_shows_the_repository_files(open_dashboard, chapter):
    """Every file tab in a chapter's SQL lens shows that file exactly as it is in the repository."""
    sources = {f["path"]: f["sql"] for f in _data("sql_sources.json")["files"]}
    page = open_dashboard(chapter=chapter)
    _lens(page, "SQL Warehouse & Local CLI" if chapter == "craft" else "SQL & Engine")
    panel = page.locator("pre[data-path]")
    expect(panel).to_be_visible()
    tabs = panel.locator("xpath=..").locator("button", has_text="·")
    assert tabs.count() >= 1
    for i in range(tabs.count()):
        tabs.nth(i).click()
        path = panel.get_attribute("data-path")
        assert path in sources, f"{chapter}: {path} is not in data/sql_sources.json"
        assert panel.inner_text().strip() == sources[path].strip(), path


# ── Interaction & accessibility ────────────────────────────────

def test_hovering_a_chart_shows_a_tooltip(open_dashboard):
    page = open_dashboard(chapter="ev")
    hit = page.locator(".tip-hit").first
    hit.hover()
    expect(page.locator(".tip-text").first).to_be_visible()


def test_chart_values_can_be_read_with_the_keyboard(open_dashboard):
    page = open_dashboard(chapter="europe")
    slider = page.get_by_role("slider").first
    slider.focus()
    expect(page.locator(".tip-text").first).to_be_visible()
    before = slider.get_attribute("aria-valuenow")
    page.keyboard.press("ArrowLeft")
    expect(slider).not_to_have_attribute("aria-valuenow", before)


def test_theme_toggle_switches_and_is_remembered(open_dashboard):
    page = open_dashboard()
    _ready(page)
    html = page.locator("html")
    expect(html).to_have_class(re.compile(r"\bdark\b"))
    page.get_by_role("button", name="Toggle color theme").click()
    expect(html).not_to_have_class(re.compile(r"\bdark\b"))
    assert page.evaluate("localStorage.getItem('theme')") == "light"
    page.reload()
    _ready(page)
    expect(html).not_to_have_class(re.compile(r"\bdark\b"))


def test_command_palette_jumps_to_a_chapter(open_dashboard):
    page = open_dashboard()
    _ready(page)
    page.keyboard.press("Control+k")
    search = page.get_by_role("textbox", name="Search chapters and actions")
    expect(search).to_be_focused()
    search.fill("electric cars")
    page.keyboard.press("Enter")
    expect(page.locator("#chapter-ev")).to_be_visible()
    assert page.evaluate("location.hash") == "#ev"


def test_deep_link_opens_the_chapter_and_the_rail_updates_the_link(open_dashboard):
    page = open_dashboard(chapter="europe")
    expect(page.locator("#chapter-europe")).to_be_visible()
    page.locator("aside nav button", has_text="Electric Cars").click()
    expect(page.locator("#chapter-ev")).to_be_visible()
    assert page.evaluate("location.hash") == "#ev"


def test_overview_links_reach_the_new_chapters(open_dashboard):
    page = open_dashboard()
    _ready(page)
    page.locator("main").get_by_role("button", name="Europe →").click()
    expect(page.locator("#chapter-europe")).to_be_visible()
    _goto(page, "overview")
    page.locator("main").get_by_role("button", name="Electric cars →").click()
    expect(page.locator("#chapter-ev")).to_be_visible()


def test_price_chapter_links_to_europe(open_dashboard):
    page = open_dashboard(chapter="price")
    page.locator("main").get_by_role("button", name=re.compile("compares with the rest of Europe")).click()
    expect(page.locator("#chapter-europe")).to_be_visible()


# ── Resilience & layout ────────────────────────────────────────

def test_one_missing_data_file_does_not_break_the_rest(open_dashboard):
    page = open_dashboard(block=("europe.json",), chapter="europe")
    expect(page.locator("main [role=alert]")).to_contain_text("data/europe.json could not be loaded")
    _goto(page, "ev")
    expect(page.locator("#car-bev")).not_to_have_text("–")
    _goto(page, "overview")
    _ready(page)
    uncaught = [p for p in page.problems if not p.startswith("console: Failed to load resource")]
    assert uncaught == [], uncaught


def test_no_horizontal_scrolling_on_a_phone(open_dashboard):
    page = open_dashboard(viewport={"width": 390, "height": 844})
    _ready(page)
    for chapter in CHAPTERS:
        _goto(page, chapter)
        page.wait_for_timeout(250)                       # the chapter transition
        overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
        assert overflow <= 0, f"{chapter}: {overflow}px of sideways scrolling"


def test_desktop_chapters_fit_the_screen_without_scrolling(open_dashboard):
    """The cockpit is one screen high on a desktop: no chapter makes the page scroll."""
    page = open_dashboard(viewport={"width": 1400, "height": 900})
    _ready(page)
    for chapter in CHAPTERS:
        _goto(page, chapter)
        page.wait_for_timeout(250)
        extra = page.evaluate("document.documentElement.scrollHeight - window.innerHeight")
        assert extra <= 0, f"{chapter}: page scrolls by {extra}px"
