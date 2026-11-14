.PHONY: install install-pip up down db-reset generate-data ingest quality-checks test test-smoke test-api test-integration test-regression report api metabase setup-metabase pipeline clean

# Environment Setup
install:
	conda env create -f environment.yaml
	@echo "Run 'conda activate energy-analytics' to activate the environment."

install-pip:
	pip install -r requirements.txt
	pip install -r requirements-dev.txt

# Docker Database Management
up:
	docker-compose up -d

down:
	docker-compose down

db-reset:
	python src/setup_db.py

# Data Pipeline Steps
generate-data:
	python src/generate_data.py

ingest:
	python src/ingest.py

quality-checks:
	python src/run_quality_checks.py

# Run all pipeline steps in sequence
pipeline: generate-data ingest report

# Testing
test:
	pytest tests/ -v

# Test layers (see pytest.ini for what each marker means)
test-smoke:
	pytest -m smoke -v

test-api:
	pytest -m api -v

test-integration:
	pytest -m integration -v

test-regression:
	pytest -m regression -v

test-performance:
	pytest -m performance -v

test-security:
	pytest -m security -v

# Load test: start the API first (`make api`), then run this. Needs `pip install locust`.
load-test:
	locust -f tests/load/locustfile.py --headless -u 20 -r 5 -t 30s --host http://localhost:8000

# Static analysis + dependency CVE scan (pip install bandit pip-audit)
security:
	bandit -r src scripts -ll
	pip-audit -r requirements.txt --no-deps --disable-pip

# Reporting and API
report:
	python src/run_report.py

api:
	uvicorn src.api:app --reload --port 8000

# Metabase
metabase:
	docker compose up -d metabase

setup-metabase:
	python scripts/setup_metabase.py

# Maintenance
clean:
	rm -rf __pycache__ .pytest_cache outputs/*.csv data/raw/*.csv
