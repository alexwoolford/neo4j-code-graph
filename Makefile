.PHONY: help install install-dev test test-fast lint format type-check security clean setup-dev pipeline

help: ## Show this help message
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Targets:'
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-15s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install production dependencies
	pip install -r config/requirements.txt

install-dev: ## Install development dependencies
	pip install -e .[dev]
	pip install -r config/requirements.txt
	pre-commit install

test: ## Run all tests with coverage
	pytest tests/ -v --cov=src --cov-report=html --cov-report=term-missing

test-fast: ## Run tests without coverage (faster)
	pytest tests/ -v -x

test-unit: ## Run only unit tests
	pytest tests/ -v -m "unit"

test-integration: ## Run only integration tests
	pytest tests/ -v -m "integration"

lint: ## Run all linting checks
	flake8 src/ tests/
	mypy src/ --ignore-missing-imports

format: ## Format code with black and isort
	black --line-length=100 src/ tests/ scripts/
	isort src/ tests/ scripts/

format-check: ## Check code formatting without modifying files
	black --line-length=100 --check --diff src/ tests/ scripts/
	isort --check-only --diff src/ tests/ scripts/

type-check: ## Run type checking with mypy
	mypy src/ --ignore-missing-imports

security: ## Run security checks
	bandit -r src/
	safety check

pre-commit: ## Run all pre-commit hooks
	pre-commit run --all-files

clean: ## Clean up generated files
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	rm -rf build/ dist/ .coverage htmlcov/ .pytest_cache/ .mypy_cache/

setup-dev: install-dev ## Setup development environment
	@echo "Development environment setup complete!"
	@echo "Run 'make help' to see available commands"

# Pipeline shortcuts
pipeline: ## Run the complete analysis pipeline (requires repo URL)
ifndef REPO_URL
	@echo "Usage: make pipeline REPO_URL=https://github.com/user/repo"
else
	python scripts/run_pipeline.py $(REPO_URL)
endif

pipeline-shell: ## Run the shell-based pipeline (legacy)
ifndef REPO_URL
	@echo "Usage: make pipeline-shell REPO_URL=https://github.com/user/repo"
else
	./scripts/run_pipeline.sh $(REPO_URL)
endif

analyze: ## Run analysis on a repository (requires REPO_URL)
ifndef REPO_URL
	@echo "Usage: make analyze REPO_URL=https://github.com/user/repo"
else
	python scripts/code_to_graph.py $(REPO_URL)
endif

cve-scan: ## Run CVE analysis
	python scripts/cve_analysis.py --risk-threshold 7.0 --max-hops 4

schema: ## Setup Neo4j schema
	python scripts/schema_management.py

cleanup-db: ## Clean up Neo4j database
	python scripts/cleanup_graph.py

validate-env: ## Validate development environment
	python scripts/validate_environment.py
