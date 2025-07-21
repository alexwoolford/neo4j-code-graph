# AGENTS Instructions

## Development Setup

1. **Environment Setup**:
   ```bash
   # Install dependencies
   pip install -r requirements.txt
   pip install -r dev-requirements.txt
   
   # Setup environment variables
   cp .env.example .env
   # Edit .env with your Neo4j credentials
   ```

2. **Code Quality Tools**:
   ```bash
   # Format code (required before commits)
   black --line-length 100 *.py
   
   # Check style
   flake8 --max-line-length=100 --exclude=.git,__pycache__,.pytest_cache .
   
   # Run tests
   python -m pytest tests/ -v
   ```

## Architecture Overview

- **`code_to_graph.py`**: Loads Java code structure with embeddings
- **`git_history_to_graph.py`**: Imports Git commit history and developer data  
- **`create_method_similarity.py`**: Creates method similarity relationships using KNN
- **`cleanup_graph.py`**: Removes analysis results while preserving base data
- **`common.py`**: Shared utilities to reduce code duplication
- **`utils.py`**: Core utility functions (port handling, config)

## Testing Strategy

Tests use mocked database connections for fast execution without requiring a running Neo4j instance. For integration testing:

1. Setup test Neo4j instance
2. Create `.env` file with test database credentials
3. Run individual scripts against test data
4. Verify results using Neo4j Browser

## Performance Considerations

- **Git extraction**: ~2,000 commits/sec using direct git log commands
- **Bulk loading**: Uses UNWIND queries for efficient Neo4j writes
- **Session management**: Scripts use fresh sessions and retry logic for resilience
- **Memory management**: Processes data in configurable batches

## Dependency Management

- **GraphDataScience version**: Ensure GDS version matches `requirements.txt`
- **PyArrow compatibility**: Must be `>=17.0,<21.0` for GDS compatibility
- **CUDA/MPS support**: PyTorch automatically detects GPU acceleration

## Common Issues

1. **Session timeouts**: Use `--skip-file-changes` for faster testing
2. **Memory issues**: Reduce batch sizes for large repositories  
3. **Import errors**: Ensure all dependencies are installed in correct environment
4. **Connection failures**: Verify Neo4j credentials and network connectivity

## Commit Checklist

- [ ] Code formatted with `black --line-length 100`
- [ ] No flake8 violations
- [ ] All tests pass (`pytest tests/ -v`)
- [ ] Documentation updated if adding new features
- [ ] No sensitive data in commits (.env is gitignored)
