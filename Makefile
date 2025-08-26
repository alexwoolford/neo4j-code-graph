.PHONY: help install install-dev pre-commit format format-check test test-fast test-unit test-integration test-ci clean pipeline validate-env

help: ## Show this help message
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Targets:'
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-18s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install production dependencies
	pip install -r config/requirements.txt

install-dev: ## Install dev deps, pins, and pre-commit hooks
	pip install -e '.[dev]'
	pip install -r config/requirements.txt
	pre-commit install

pre-commit: ## Run all pre-commit hooks (ruff, black, mypy, etc.)
	pre-commit run --all-files

format: ## Format code with black and isort
	black --line-length=100 src/ tests/ scripts/
	isort src/ tests/ scripts/

format-check: ## Check code formatting (no changes)
	black --line-length=100 --check --diff src/ tests/ scripts/
	isort --check-only --diff src/ tests/ scripts/

test: ## Run all tests with coverage
	pytest tests/ -v --cov=src --cov-report=html --cov-report=term-missing

test-fast: ## Run tests without coverage
	pytest tests/ -v -x

test-unit: ## Run only unit tests
	pytest tests/ -v -m 'unit'

test-integration: ## Run only integration tests
	pytest tests/ -v -m 'integration'

test-ci: ## Run unit tests; if NEO4J env present, run integration too
	pytest tests/ -v --cov=src --cov-report=term-missing -k 'not integration'
	@if [ -n "$(NEO4J_URI)" ]; then echo "Running integration tests..."; pytest tests/ -v -m 'integration'; else echo "Skipping integration tests (NEO4J_URI not set)"; fi

clean: ## Clean generated files/artifacts
	find . -type f -name '*.pyc' -delete
	find . -type d -name '__pycache__' -delete
	find . -type d -name '*.egg-info' -exec rm -rf {} +
	rm -rf build/ dist/ .coverage htmlcov/ .pytest_cache/ .mypy_cache/

pipeline: ## Run the Prefect pipeline (requires REPO_URL)
ifndef REPO_URL
	@echo "Usage: make pipeline REPO_URL=https://github.com/user/repo"
else
	python -m src.pipeline.prefect_flow --repo-url $(REPO_URL)
endif

validate-env: ## Validate dev env (hooks + a quick pytest)
	pre-commit run --all-files
	pytest -q
