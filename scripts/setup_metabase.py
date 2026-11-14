import os
import pathlib
import time
import requests
import sys

try:
    import yaml
except ImportError:
    yaml = None

def _load_config():
    """Load Metabase credentials from config.yaml (gitignored) or environment variables."""
    cfg = {}
    config_path = pathlib.Path(__file__).parent.parent / "config.yaml"
    if yaml and config_path.exists():
        with open(config_path) as f:
            full = yaml.safe_load(f) or {}
        cfg = full.get("metabase", {})
    return cfg

_cfg = _load_config()
# Every HTTP call gets a timeout so a hung Metabase can never block the script forever.
REQUEST_TIMEOUT = 30

METABASE_URL = os.environ.get("METABASE_URL", _cfg.get("url", "http://localhost:3000"))
USER_EMAIL   = os.environ.get("METABASE_ADMIN_EMAIL", _cfg.get("admin_email", ""))
USER_PASS    = os.environ.get("METABASE_ADMIN_PASSWORD", _cfg.get("admin_password", ""))

if not USER_EMAIL or not USER_PASS:
    print("ERROR: Metabase credentials not found. Set them in config.yaml (metabase.admin_email / "
          "metabase.admin_password) or via METABASE_ADMIN_EMAIL / METABASE_ADMIN_PASSWORD env vars.")
    sys.exit(1)

def wait_for_metabase():
    print("Waiting for Metabase to start up...")
    for _ in range(60):
        try:
            r = requests.get(f"{METABASE_URL}/api/health", timeout=REQUEST_TIMEOUT)
            if r.status_code == 200:
                print("Metabase is healthy!")
                return
        except requests.exceptions.ConnectionError:
            pass
        time.sleep(2)
    print("Metabase failed to start in time.")
    sys.exit(1)

def get_setup_token():
    r = requests.get(f"{METABASE_URL}/api/session/properties", timeout=REQUEST_TIMEOUT)
    props = r.json()
    if not props.get("has_user_setup"):
        return props.get("setup-token")
    return None

def initial_setup(token):
    payload = {
        "token": token,
        "user": {
            "first_name": "Admin",
            "last_name": "Energy",
            "email": USER_EMAIL,
            "password": USER_PASS
        },
        "prefs": {
            "site_name": "Energy Analytics",
            "allow_tracking": False
        },
        "database": {
            "engine": "postgres",
            "name": "Energy Postgres",
            "details": {
                "host": "energy_analytics_db",
                "port": 5432,
                "dbname": "energy_analytics",
                "user": "admin",
                "password": "password"
            }
        }
    }
    r = requests.post(f"{METABASE_URL}/api/setup", json=payload, timeout=REQUEST_TIMEOUT)
    if r.status_code == 200:
        return r.json().get("id") # session id
    else:
        print("Setup failed:", r.text)
        sys.exit(1)

def login():
    r = requests.post(f"{METABASE_URL}/api/session", json={
        "username": USER_EMAIL,
        "password": USER_PASS
    }, timeout=REQUEST_TIMEOUT)
    if r.status_code == 200:
        return r.json().get("id")
    return None

def create_card(session_id, db_id, name, query, display="line"):
    headers = {"X-Metabase-Session": session_id}
    payload = {
        "name": name,
        "dataset_query": {
            "database": db_id,
            "type": "native",
            "native": {
                "query": query
            }
        },
        "display": display,
        "visualization_settings": {}
    }
    r = requests.post(f"{METABASE_URL}/api/card", json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
    if r.status_code == 200:
        return r.json().get("id")
    print(f"Failed to create card '{name}': {r.text}")
    sys.exit(1)

def create_dashboard(session_id, name):
    headers = {"X-Metabase-Session": session_id}
    payload = {"name": name}
    r = requests.post(f"{METABASE_URL}/api/dashboard", json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
    if r.status_code == 200:
        return r.json().get("id")
    print("Failed to create dashboard:", r.text)
    sys.exit(1)

def set_dashboard_cards(session_id, dash_id, card_positions):
    headers = {"X-Metabase-Session": session_id}
    cards_payload = []
    idx = -1
    for card_id, x, y, w, h in card_positions:
        cards_payload.append({
            "id": idx,
            "card_id": card_id,
            "col": x,
            "row": y,
            "size_x": w,
            "size_y": h
        })
        idx -= 1
    r = requests.put(f"{METABASE_URL}/api/dashboard/{dash_id}/cards", json={"cards": cards_payload}, headers=headers, timeout=REQUEST_TIMEOUT)
    if r.status_code != 200:
        print("Failed to add cards to dashboard:", r.text)
        sys.exit(1)

def main():
    wait_for_metabase()
    
    token = get_setup_token()
    if token:
        print("Performing initial setup...")
        session_id = initial_setup(token)
    else:
        print("Already setup. Logging in...")
        session_id = login()
        
    if not session_id:
        print("Could not get session ID.")
        sys.exit(1)
        
    headers = {"X-Metabase-Session": session_id}
    
    # Get databases
    r = requests.get(f"{METABASE_URL}/api/database", headers=headers, timeout=REQUEST_TIMEOUT)
    databases = r.json().get("data", [])
    db_id = next((db["id"] for db in databases if db.get("name") == "Energy Postgres"), None)
    if not db_id:
        print("Adding Energy Postgres database...")
        r_db = requests.post(f"{METABASE_URL}/api/database", json={
            "engine": "postgres",
            "name": "Energy Postgres",
            "details": {
                "host": "energy_analytics_db",
                "port": 5432,
                "dbname": "energy_analytics",
                "user": "admin",
                "password": "password"
            }
        }, headers=headers, timeout=REQUEST_TIMEOUT)
        if r_db.status_code == 200:
            db_id = r_db.json().get("id")
        else:
            print("Failed to add database:", r_db.text)
            sys.exit(1)
        
    print(f"Using Database ID: {db_id}")
    
    q_ranking = """
SELECT facility_name, capacity_mw, ROUND(AVG(value / capacity_mw * 100)::numeric, 2) AS avg_efficiency_pct
FROM readings r
JOIN sensors s ON r.sensor_id = s.sensor_id
JOIN facilities f ON s.facility_id = f.facility_id
WHERE s.sensor_type = 'power_output'
GROUP BY facility_name, capacity_mw
ORDER BY avg_efficiency_pct DESC
LIMIT 10;
"""
    q_anomaly = """
SELECT DATE_TRUNC('month', recorded_at) AS month, 
       ROUND((COUNT(*) FILTER (WHERE is_anomaly = true)::numeric / COUNT(*)) * 100, 2) AS anomaly_rate_pct
FROM readings
GROUP BY month
ORDER BY month;
"""
    q_rolling = """
WITH hourly AS (
    SELECT DATE_TRUNC('hour', r.recorded_at) AS hour,
           f.facility_type,
           SUM(r.value) AS total_power
    FROM readings r
    JOIN sensors s ON r.sensor_id = s.sensor_id
    JOIN facilities f ON s.facility_id = f.facility_id
    WHERE s.sensor_type = 'power_output'
    GROUP BY 1, 2
)
SELECT hour, facility_type, 
       AVG(total_power) OVER (PARTITION BY facility_type ORDER BY hour ROWS BETWEEN 23 PRECEDING AND CURRENT ROW) AS rolling_24h_avg
FROM hourly
ORDER BY hour;
"""
    q_comparison = """
WITH real_monthly AS (
    SELECT DATE_TRUNC('month', recorded_at) AS month, 
           AVG(value) AS real_avg,
           MAX(AVG(value)) OVER() AS max_real_avg
    FROM grid_data
    WHERE metric = 'wind_production'
    GROUP BY 1
),
synthetic_monthly AS (
    SELECT DATE_TRUNC('month', r.recorded_at) AS month, 
           AVG(r.value) AS synthetic_avg,
           MAX(AVG(r.value)) OVER() AS max_synthetic_avg
    FROM readings r
    JOIN sensors s ON r.sensor_id = s.sensor_id
    JOIN facilities f ON s.facility_id = f.facility_id
    WHERE f.facility_type = 'wind' AND s.sensor_type = 'power_output'
    GROUP BY 1
)
SELECT 
    r.month,
    ROUND((r.real_avg / NULLIF(r.max_real_avg, 0) * 100)::numeric, 1) AS real_normalized_pct,
    ROUND((s.synthetic_avg / NULLIF(s.max_synthetic_avg, 0) * 100)::numeric, 1) AS synthetic_normalized_pct
FROM real_monthly r
JOIN synthetic_monthly s ON r.month = s.month
ORDER BY r.month;
"""

    c1 = create_card(session_id, db_id, "Top 10 Facilities by Efficiency", q_ranking, "bar")
    c2 = create_card(session_id, db_id, "Monthly Anomaly Rate Trend", q_anomaly, "line")
    c3 = create_card(session_id, db_id, "Rolling 24h Average Power by Type", q_rolling, "line")
    c4 = create_card(session_id, db_id, "Real vs Synthetic Wind Comparison", q_comparison, "line")

    d_id = create_dashboard(session_id, "Energy Analytics Executive Dashboard")
    
    set_dashboard_cards(session_id, d_id, [
        (c1, 0, 0, 12, 8),
        (c2, 12, 0, 12, 8),
        (c3, 0, 8, 12, 8),
        (c4, 12, 8, 12, 8)
    ])

    print(f"\nDashboard built successfully! Local URL: {METABASE_URL}/dashboard/{d_id}")
    print(f"Cards created: {c1}, {c2}, {c3}, {c4}")

if __name__ == "__main__":
    main()
