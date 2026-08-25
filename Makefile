.PHONY: install install-pip up down db-reset generate-data ingest quality-checks test report api metabase setup-metabase pipeline clean

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
