.PHONY: install install-pip up down db-setup sync snapshot-restore quality-checks report export benchmark api test test-smoke test-api test-integration test-regression test-e2e test-performance test-security test-data load-test security clean site site-dev

SNAPSHOT_URL = https://github.com/miladgk/industrial-energy-sql-pipeline/releases/download/warehouse-snapshot/fingrid_observation.csv.gz

# Environment
install:
	conda env create -f environment.yaml
	@echo "Run 'conda activate energy-analytics' to activate the environment."

install-pip:
	pip install -r requirements.txt
	pip install -r requirements-dev.txt

# PostgreSQL in Docker
up:
	docker compose up -d

down:
	docker compose down

# Warehouse
db-setup:            ## create tables, partitions, views and functions (idempotent)
	python src/setup_db.py

snapshot-restore:    ## load the published warehouse snapshot (no Fingrid key needed)
	curl -fsSL -o /tmp/fingrid_observation.csv.gz $(SNAPSHOT_URL)
	python src/warehouse_snapshot.py restore /tmp/fingrid_observation.csv.gz

sync:                ## fetch new data from Fingrid (needs fingrid_api_key in config.yaml)
	python src/sync_fingrid.py

quality-checks:
	python src/run_quality_checks.py

report:              ## every analysis query -> outputs/*.csv
	python src/run_report.py

export:              ## rebuild the dashboard data files in docs/data/
	python scripts/export_dashboard_data.py

site:                ## build the dashboard (web/) into web/dist/ (needs Node.js 20+)
	npm --prefix web ci
	npm --prefix web run build

site-dev:            ## dashboard dev server on http://localhost:3000 (reads docs/data/)
	npm --prefix web run dev

benchmark:           ## re-measure benchmarks/index_benchmark.md
	python scripts/benchmark_warehouse.py

api:
	uvicorn src.api:app --reload --port 8000

# Tests (see pytest.ini for what each layer means)
test:
	pytest tests/ -v

test-smoke:
	pytest -m smoke -v

test-api:
	pytest -m api -v

test-integration:
	pytest -m integration -v

test-regression:
	pytest -m regression -v

test-e2e: site
	pytest -m e2e -v   # needs: pip install playwright && playwright install chromium

test-performance:
	pytest -m performance -v

test-security:
	pytest -m security -v

test-data:
	pytest -m data -v

# Load test: start the API first (`make api`), then run this. Needs `pip install locust`.
load-test:
	locust -f tests/load/locustfile.py --headless -u 20 -r 5 -t 30s --host http://localhost:8000

# Static analysis + dependency CVE scan (pip install bandit pip-audit)
security:
	bandit -r src scripts -ll
	pip-audit -r requirements.txt --no-deps --disable-pip

clean:
	rm -rf __pycache__ .pytest_cache outputs/*.csv
