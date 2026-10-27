.PHONY: install run test lint typecheck demo bench check

install:   ## install runtime and dev dependencies
	pip install -r requirements.txt ruff mypy

run:       ## start the API and both web apps on :8000
	uvicorn saakshi.app:app --port 8000

test:      ## unit, property, contract, security, perf and e2e tests with coverage
	python3 -m pytest --cov=saakshi --cov-report=term-missing

lint:      ## strict ruff rule set (see pyproject.toml)
	ruff check saakshi scripts tests api main.py

typecheck: ## mypy over the saakshi package ([tool.mypy] in pyproject.toml)
	mypy

demo:      ## the 3-minute demo with pass/fail checks
	python3 scripts/demo.py

bench:     ## verification and console latency on 20k events
	python3 scripts/bench.py --n 20000

check: lint typecheck test demo  ## everything CI runs
