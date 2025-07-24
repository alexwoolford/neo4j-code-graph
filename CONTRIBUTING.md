# Contributing to Neo4j Code Graph

Thank you for your interest in contributing to Neo4j Code Graph! This document provides guidelines and information for contributors.

## 🚀 Quick Start for Contributors

### 1. Development Setup

```bash
# Clone the repository
git clone https://github.com/your-org/neo4j-code-graph.git
cd neo4j-code-graph

# Run the automated setup script
python scripts/dev_setup.py

# Or set up manually
make setup-dev
```

### 2. Development Workflow

```bash
# Create a feature branch
git checkout -b feature/your-feature-name

# Make your changes and run quality checks
make format          # Format code
make lint           # Run linting
make test           # Run tests
make pre-commit     # Run all pre-commit hooks

# Commit your changes
git add .
git commit -m "feat: add your feature"

# Push and create a pull request
git push origin feature/your-feature-name
```

## 📋 Development Guidelines

### Code Style

We use several tools to maintain code quality:

- **Black**: Code formatting (line length: 100)
- **isort**: Import sorting
- **flake8**: Linting and style checking
- **mypy**: Type checking
- **pre-commit**: Automated quality checks

Run `make format` before committing to ensure consistent formatting.

### Testing

- Write tests for new functionality
- Aim for >80% test coverage
- Use meaningful test names that describe what's being tested
- Prefer integration tests over mocks when practical

```bash
# Run all tests
make test

# Run specific test types
make test-unit
make test-integration

# Run tests without coverage (faster)
make test-fast
```

### Type Hints

- Add type hints to all new functions and methods
- Use `typing` module types when appropriate
- Run `make type-check` to verify type annotations

### Documentation

- Update docstrings for new/modified functions
- Update README.md if adding new features
- Add examples for complex functionality
- Keep documentation current with code changes

## 🏗️ Project Structure

Understanding the project structure helps with contributions:

```
src/
├── analysis/          # Core analysis modules
├── security/          # CVE and vulnerability analysis
├── data/             # Schema and data management
├── utils/            # Common utilities
└── pipeline/         # Pipeline orchestration

scripts/              # CLI tools and entry points
tests/               # Test suite
config/              # Configuration files
docs/                # Documentation
```

## 🧪 Testing Strategy

### Test Categories

Mark your tests with appropriate markers:

```python
import pytest

@pytest.mark.unit
def test_function_unit():
    """Test individual function behavior."""
    pass

@pytest.mark.integration
def test_with_database():
    """Test with real Neo4j database."""
    pass

@pytest.mark.slow
def test_large_repository():
    """Test that takes significant time."""
    pass
```

### Mock vs Real Testing

- **Prefer real tests** when practical (databases, file systems)
- **Use mocks** for external APIs, slow operations, or error conditions
- **Integration tests** should test actual workflows end-to-end

## 🔄 Continuous Integration

Our CI pipeline runs:

1. **Quality checks** (black, isort, flake8, mypy)
2. **Security scans** (bandit, safety)
3. **Tests** across Python 3.8-3.11
4. **Coverage reporting**

All checks must pass before merging.

## 📝 Commit Message Guidelines

We follow conventional commit format:

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

### Types:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting, etc.)
- `refactor`: Code refactoring
- `test`: Adding or updating tests
- `chore`: Build process or auxiliary tool changes

### Examples:
```
feat(analysis): add method similarity analysis
fix(cve): resolve property name mismatch in dependency extraction
docs(readme): update installation instructions
test(security): add integration tests for CVE analysis
```

## 🐛 Reporting Issues

When reporting issues:

1. **Check existing issues** first
2. **Use issue templates** when available
3. **Provide minimal reproduction** steps
4. **Include environment details** (Python version, OS, etc.)
5. **Add relevant logs** or error messages

## 🚀 Feature Requests

For new features:

1. **Open an issue** first to discuss the feature
2. **Explain the use case** and why it's valuable
3. **Consider the scope** - start with MVPs
4. **Be willing to contribute** the implementation

## 🔐 Security

- **Never commit secrets** (API keys, passwords, etc.)
- **Use environment variables** for sensitive configuration
- **Report security issues privately** via email
- **Follow security best practices** in code

## 📄 License

By contributing, you agree that your contributions will be licensed under the same license as the project (Apache 2.0).

## 🤝 Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](https://www.contributor-covenant.org/version/2/1/code_of_conduct/). By participating, you are expected to uphold this code.

## 💬 Getting Help

- **GitHub Issues**: For bugs and feature requests
- **GitHub Discussions**: For questions and general discussion
- **README.md**: For basic usage and setup

## 🎯 Good First Issues

Look for issues labeled:
- `good first issue`: Perfect for newcomers
- `help wanted`: Community contributions welcome
- `documentation`: Documentation improvements
- `tests`: Test coverage improvements

## 🔍 Review Process

Pull requests will be reviewed for:

1. **Functionality**: Does it work as intended?
2. **Code quality**: Is it readable and maintainable?
3. **Tests**: Are there appropriate tests?
4. **Documentation**: Is it properly documented?
5. **Performance**: Does it impact performance negatively?

Thank you for contributing to Neo4j Code Graph! 🎉
