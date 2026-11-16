"""
locustfile.py: LOAD TEST
~~~~~~~~~~~~~~~~~~~~~~~~
Load testing asks: "how does the API behave when many users use it at once?"
Locust simulates virtual users who repeatedly call the endpoints the way the
dashboard does, and measures response times and failures.

Task weights mimic real traffic: cheap endpoints are hit often, the heavy
year-long analyses (/api/forecast-scorecard) less often.

Pass/fail thresholds (checked when the run ends; exit code 1 if exceeded):
    LOAD_MAX_FAIL_RATIO   default 0.01   (1 % of requests may fail)
    LOAD_MAX_P95_MS       default 5000   (95th percentile response time)

Run headless (API must be running: `make api`):
    locust -f tests/load/locustfile.py --headless -u 20 -r 5 -t 30s \
           --host http://localhost:8000

Or with the live web UI at http://localhost:8089 :
    locust -f tests/load/locustfile.py --host http://localhost:8000
"""

import os

from locust import HttpUser, between, events, task

MAX_FAIL_RATIO = float(os.environ.get("LOAD_MAX_FAIL_RATIO", 0.01))
MAX_P95_MS = float(os.environ.get("LOAD_MAX_P95_MS", 5000))


class DashboardUser(HttpUser):
    wait_time = between(0.5, 2)  # think time between actions, like a real person

    @task(5)
    def latest(self):
        self.client.get("/api/latest", name="/api/latest")

    @task(3)
    def co2_forecast(self):
        # tomorrow until Fingrid publishes it at 12:00 Finnish time; a 404 then is expected
        with self.client.get("/api/co2-forecast", name="/api/co2-forecast", catch_response=True) as r:
            if r.status_code in (200, 404):
                r.success()

    @task(2)
    def grid_events(self):
        self.client.get("/api/grid-events?days=30", name="/api/grid-events")

    @task(2)
    def datasets(self):
        self.client.get("/api/datasets", name="/api/datasets")

    @task(1)
    def forecast_scorecard(self):
        self.client.get("/api/forecast-scorecard", name="/api/forecast-scorecard")

    @task(1)
    def health(self):
        self.client.get("/health", name="/health")


@events.quitting.add_listener
def enforce_thresholds(environment, **_kwargs):
    """Turn the statistics into a pass/fail verdict so CI can gate on it."""
    total = environment.stats.total
    if total.num_requests == 0:
        print("LOAD TEST FAILED: no requests were made")
        environment.process_exit_code = 1
        return
    p95 = total.get_response_time_percentile(0.95)
    problems = []
    if total.fail_ratio > MAX_FAIL_RATIO:
        problems.append(f"failure ratio {total.fail_ratio:.2%} > {MAX_FAIL_RATIO:.2%}")
    if p95 > MAX_P95_MS:
        problems.append(f"p95 {p95:.0f} ms > {MAX_P95_MS:.0f} ms")
    if problems:
        print("LOAD TEST FAILED: " + "; ".join(problems))
        environment.process_exit_code = 1
    else:
        print(f"LOAD TEST PASSED: {total.num_requests} requests, "
              f"p95 {p95:.0f} ms, failures {total.fail_ratio:.2%}")
