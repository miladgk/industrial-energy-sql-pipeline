"""
fingrid_api.py
~~~~~~~~~~~~~~
Minimal client for the Fingrid Open Data API (https://data.fingrid.fi).

  load_api_key()          FINGRID_API_KEY, else fingrid_api_key in the git-ignored config.yaml
  fetch_dataset_chunk()   one page of one dataset for a time window, with retries:
                          requests are spaced 2 s apart and HTTP 429 backs off

Used by src/sync_fingrid.py (the warehouse) and by the hourly "latest values"
export in scripts/export_dashboard_data.py.
"""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

import yaml

API_URL = "https://data.fingrid.fi/api/datasets/{dataset_id}/data"
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config.yaml")


def load_api_key() -> str:
    """Return the Fingrid API key from FINGRID_API_KEY, else from config.yaml."""
    env_key = os.environ.get("FINGRID_API_KEY", "").strip()
    if env_key:
        return env_key
    if not os.path.exists(CONFIG_PATH):
        return ""
    with open(CONFIG_PATH, "r") as fh:
        try:
            cfg = yaml.safe_load(fh)
            return (cfg.get("fingrid_api_key") or "").strip()
        except Exception:
            return ""


def fetch_dataset_chunk(dataset_id: int, api_key: str, start_time: str, end_time: str) -> list:
    """Fetch data for a specific dataset ID and time chunk with retry logic and rate limit compliance."""
    params = {
        "startTime": start_time,
        "endTime": end_time,
        "pageSize": 20000
    }
    query_string = urllib.parse.urlencode(params)
    url = f"{API_URL.format(dataset_id=dataset_id)}?{query_string}"
    
    if not url.startswith("https://"):
        raise ValueError("Fingrid API URL must use https")
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/json")
    req.add_header("x-api-key", api_key)
    
    max_retries = 3
    backoff = 2.0
    
    for attempt in range(max_retries):
        time.sleep(2.0)
        try:
            with urllib.request.urlopen(req, timeout=30) as response:  # nosec B310 (https enforced above)
                if response.status == 200:
                    data = json.loads(response.read().decode("utf-8"))
                    return data.get("data", [])
                else:
                    print(f"  Warning: Received status code {response.status}. Retrying...")
        except urllib.error.HTTPError as e:
            if e.code == 429:
                print(f"  [429 Too Many Requests] Rate limit hit. Backing off for {backoff}s...")
                time.sleep(backoff)
                backoff *= 2.0
            elif e.code in (401, 403):
                raise PermissionError("Fingrid API key is unauthorized or invalid (401/403).")
            else:
                print(f"  HTTP error: {e.code}. Retrying in {backoff}s...")
                time.sleep(backoff)
                backoff *= 2.0
        except Exception as e:
            print(f"  Network error: {e}. Retrying in {backoff}s...")
            time.sleep(backoff)
            backoff *= 2.0
            
    raise RuntimeError(f"Failed to fetch dataset {dataset_id} for range {start_time} to {end_time} after {max_retries} attempts.")


