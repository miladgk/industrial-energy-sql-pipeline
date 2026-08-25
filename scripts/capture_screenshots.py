import os
import pathlib
import sys
import time
from playwright.sync_api import sync_playwright

try:
    import yaml
except ImportError:
    yaml = None

def _load_config():
    cfg = {}
    config_path = pathlib.Path(__file__).parent.parent / "config.yaml"
    if yaml and config_path.exists():
        with open(config_path) as f:
            full = yaml.safe_load(f) or {}
        cfg = full.get("metabase", {})
    return cfg

_cfg = _load_config()
METABASE_URL = os.environ.get("METABASE_URL", _cfg.get("url", "http://localhost:3000"))
USER_EMAIL   = os.environ.get("METABASE_ADMIN_EMAIL", _cfg.get("admin_email", ""))
USER_PASS    = os.environ.get("METABASE_ADMIN_PASSWORD", _cfg.get("admin_password", ""))

if not USER_EMAIL or not USER_PASS:
    print("ERROR: Metabase credentials not set. Configure metabase.admin_email / "
          "metabase.admin_password in config.yaml (gitignored).")
    sys.exit(1)

SCREENSHOTS_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "screenshots")
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1600, "height": 1200})
        page = context.new_page()

        print("Navigating to Metabase login...")
        page.goto(f"{METABASE_URL}/auth/login")
        
        # Fill login form
        page.fill('input[name="username"]', USER_EMAIL)
        page.fill('input[name="password"]', USER_PASS)
        page.click('button[type="submit"]')
        
        # Wait for login redirect to complete
        time.sleep(5)
        
        print("Taking Dashboard screenshot...")
        page.goto(f"{METABASE_URL}/dashboard/5")
        page.wait_for_timeout(7000) # wait for all cards to render
        page.screenshot(path=os.path.join(SCREENSHOTS_DIR, "metabase_dashboard.png"), full_page=True)
        print("  ✓ Saved metabase_dashboard.png")

        cards = [
            (48, "facility_ranking.png"),
            (49, "monthly_anomaly_rate.png"),
            (50, "rolling_24h_average.png"),
            (51, "real_vs_synthetic_comparison.png")
        ]

        for card_id, filename in cards:
            print(f"Taking screenshot of Card {card_id} -> {filename}...")
            page.goto(f"{METABASE_URL}/question/{card_id}")
            page.wait_for_timeout(4000) # wait for query and chart rendering
            
            try:
                exploring_btn = page.get_by_text("Start exploring")
                if exploring_btn.is_visible():
                    exploring_btn.click()
                    page.wait_for_timeout(1000)
            except Exception:
                pass
                
            page.screenshot(path=os.path.join(SCREENSHOTS_DIR, filename))
            print(f"  ✓ Saved {filename}")

        browser.close()
    print("\nAll screenshots captured successfully into docs/screenshots/!")

if __name__ == "__main__":
    main()
