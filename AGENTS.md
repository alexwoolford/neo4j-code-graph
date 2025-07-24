# AGENTS Instructions

## Development Setup

1. **Environment Setup**:
```bash
# Activate the project conda environment
conda activate neo4j-code-graph

# Install dependencies
pip install -e .[dev]
pip install -r requirements.txt

# Setup environment variables
cp .env.example .env
# Edit .env with your Neo4j credentials
```

2. **Code Quality Tools**:
```bash
# CRITICAL: Fix import sorting (prevents CI failures)
isort src/ tests/ scripts/

# Format code (required before commits)
black src/ tests/ scripts/

# Check import sorting (CI requirement)
isort --check-only --diff src/ tests/ scripts/

# Check code formatting
black --check --diff src/ tests/ scripts/

# Check style
flake8 src/ tests/ --max-line-length=100

# Type checking
mypy src/ --ignore-missing-imports

# Run all quality checks at once
make format-check  # Check formatting without changes
make lint         # Run flake8 and mypy

# Auto-fix formatting issues
make format       # Runs both black and isort

# Run tests
python -m pytest tests/ -v
```

3. **⚠️ IMPORT SORTING CRITICAL**:
```bash
# ALWAYS run before committing to prevent CI failures:
isort src/ tests/ scripts/

# The project uses isort with "black" profile for consistent import ordering:
# - Standard library imports first (alphabetically sorted)
# - Third-party imports second (alphabetically sorted)  
# - Local imports last (alphabetically sorted)
# - Blank lines between groups
# - Imports within 'from' statements alphabetically sorted

# Example of correct import order:
import argparse
import logging
import sys

import pandas as pd
import torch

from utils.common import create_neo4j_driver, setup_logging
```

## Architecture Overview

- **`code_to_graph.py`**: Loads Java code structure with embeddings (GPU accelerated)
- **`git_history_to_graph.py`**: Imports Git commit history and developer data (15-30x faster)
- **`create_method_similarity.py`**: Creates method similarity relationships using KNN
- **`cleanup_graph.py`**: Flexible cleanup tool (selective or complete database reset)
- **`analyze.py`**: Advanced analysis tools (coupling, metrics, hotspots)
- **`common.py`**: Shared utilities to reduce code duplication
- **`utils.py`**: Core utility functions (port handling, config)
- **`run_pipeline.sh`**: Complete pipeline automation script

## Testing Strategy

Tests use mocked database connections for execution without requiring a running Neo4j instance. For integration testing:

1. Setup test Neo4j instance
2. Create `.env` file with test database credentials
3. Run individual scripts against test data
4. Verify results using Neo4j Browser

## Performance Considerations

### **GPU Optimizations**
- **Apple Silicon**: MPS batch size 256 (4x faster) with high-performance mode
- **CUDA**: Automatic detection with mixed-precision support
- **Memory management**: Efficient cache clearing prevents OOM errors

### **Git History Performance**
- **15-30x faster**: 3-step CREATE vs 5-step MERGE operations
- **Large batches**: 25K records per batch with progress reporting
- **Memory efficient**: Handles 300K+ nodes without memory issues

### **General Performance**
- **Git extraction**: ~9,600 commits/sec using git log commands
- **Bulk loading**: Uses UNWIND queries for efficient Neo4j writes
- **Session management**: Scripts use fresh sessions and retry logic for resilience
- **Smart fallbacks**: Automatic branch detection (main/master/HEAD)

## Dependency Management

- **GraphDataScience version**: Ensure GDS version matches `requirements.txt`
- **PyArrow compatibility**: Must be `>=17.0,<21.0` for GDS compatibility
- **CUDA/MPS support**: PyTorch automatically detects GPU acceleration

## Common Issues

1. **Session timeouts**: Use `--skip-file-changes` for testing
2. **Memory issues**: Large repositories may hit cloud Neo4j memory limits
   - Use `cleanup_graph.py --complete` for fresh start
   - Reduce `--max-commits` for git history loading
3. **Import errors**: Ensure all dependencies are installed in correct environment
   - Always use `conda activate neo4j-code-graph`
   - Check `pip list` for missing packages
4. **Connection failures**: Verify Neo4j credentials and network connectivity
   - Check `.env` file configuration
   - Test with `python -c "from utils import get_neo4j_config; print(get_neo4j_config())"`
5. **OpenMP conflicts on macOS**: Set `export KMP_DUPLICATE_LIB_OK=TRUE`
6. **Branch not found**: Script auto-detects main/master/HEAD branches
7. **Slow performance**: Ensure proper environment and GPU detection
8. **🚨 CI Failures - Import Sorting**: Always run `isort src/ tests/ scripts/` before committing
9. **Type Checking**: mypy configuration is currently lenient to allow gradual type annotation adoption

## Commit Checklist

- [ ] **Import sorting fixed**: `isort src/ tests/ scripts/` (CRITICAL for CI)
- [ ] Code formatted with `black src/ tests/ scripts/`
- [ ] No import sorting violations: `isort --check-only --diff src/ tests/ scripts/`
- [ ] No formatting violations: `black --check --diff src/ tests/ scripts/`
- [ ] No flake8 violations: `flake8 src/ tests/`
- [ ] Type checking passes: `mypy src/ --ignore-missing-imports`
- [ ] All tests pass: `pytest tests/ -v`
- [ ] Documentation updated if adding new features
- [ ] No sensitive data in commits (`.env` is gitignored)
- [ ] Environment activated: `conda activate neo4j-code-graph`

## Quick Quality Check Commands

```bash
# One-liner to check everything before commit:
make format-check && make lint && pytest tests/ -v

# One-liner to fix most issues:
make format

# Check only what CI checks for quality job:
isort --check-only --diff src/ tests/ && black --check --diff src/ tests/ && flake8 src/ tests/ && mypy src/ --ignore-missing-imports
``` 