.PHONY: all test lint validate-alerts validate-dashboards docker-build clean

PYTHON ?= python

all: test

test:
	$(PYTHON) -m pytest tests/ -v

lint:
	$(PYTHON) -m flake8 scripts/ tests/ || true

docker-build:
	docker build -t ghcr.io/freefades2black/platform-sre-tools:latest .

validate-alerts:
	$(PYTHON) -c "import yaml; yaml.safe_load(open('monitoring/prometheus/lakehouse_sre_rules.yaml'))"
	@echo "Prometheus rules YAML valid."

validate-dashboards:
	$(PYTHON) -c "import json; json.load(open('monitoring/grafana/lakehouse_sre_dashboard.json'))"
	@echo "Grafana dashboard JSON valid."

clean:
	rm -rf .pytest_cache __pycache__ tests/__pycache__ scripts/__pycache__
