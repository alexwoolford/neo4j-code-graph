# Neo4j Code Graph - Coding Style Guide

This document defines consistent coding patterns for the Neo4j Code Graph project to improve maintainability and reduce confusion.

## 🎯 **Core Principles**

1. **Use Helper Functions**: Always prefer existing helper functions over manual implementations
2. **Consistent Patterns**: Same problems should be solved the same way throughout the codebase
3. **No Duplication**: Don't reimplement what already exists in `utils/common.py`
4. **Clear Imports**: Use clean import patterns without conditional try/except blocks

---

## 📝 **Logging Standards**

### ✅ **ALWAYS USE: setup_logging() Helper**

```python
# ✅ CORRECT - Use the helper function
from utils.common import setup_logging

def main():
    args = parse_args()
    setup_logging(args.log_level, args.log_file)

    logger = logging.getLogger(__name__)
    logger.info("Starting process...")
```

### ❌ **NEVER USE: Manual logging.basicConfig()**

```python
# ❌ WRONG - Manual configuration
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
```

**Why**: The helper ensures consistent format, handles file logging, and provides proper error handling.

---

## 🔌 **Neo4j Connection Standards**

### ✅ **ALWAYS USE: create_neo4j_driver() Helper**

```python
# ✅ CORRECT - Use the helper function
from utils.common import create_neo4j_driver

with create_neo4j_driver(uri, username, password) as driver:
    # Connection is automatically managed
    with driver.session(database=database) as session:
        result = session.run("MATCH (n) RETURN count(n)")
```

### ❌ **NEVER USE: Direct GraphDatabase.driver()**

```python
# ❌ WRONG - Manual connection
from neo4j import GraphDatabase

with GraphDatabase.driver(uri, auth=(username, password)) as driver:
    driver.verify_connectivity()  # Manual verification needed
    # ... rest of code
```

**Why**: The helper includes automatic connectivity verification, consistent error handling, and proper connection management.

---

## 🎛️ **Argument Parsing Standards**

### ✅ **ALWAYS USE: add_common_args() Helper**

```python
# ✅ CORRECT - Use the helper for standard args
from utils.common import add_common_args

def parse_args():
    parser = argparse.ArgumentParser(description="My Analysis Tool")
    add_common_args(parser)  # Adds --uri, --username, --password, --database, --log-level, --log-file

    # Add tool-specific arguments
    parser.add_argument("--my-option", help="Tool-specific option")
    return parser.parse_args()
```

### ❌ **NEVER USE: Manual Common Arguments**

```python
# ❌ WRONG - Manually defining common args
def parse_args():
    parser = argparse.ArgumentParser(description="My Analysis Tool")
    parser.add_argument("--uri", default="bolt://localhost:7687", help="Neo4j URI")
    parser.add_argument("--username", default="neo4j", help="Neo4j username")
    parser.add_argument("--password", default="password", help="Neo4j password")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    # ... duplicate definitions
```

**Why**: The helper ensures consistency, reduces duplication, and automatically includes all necessary connection arguments.

---

## 📦 **Import Standards**

### ✅ **CORRECT: Clean Import Patterns**

```python
# ✅ For library modules (src/**)
from ..utils.common import setup_logging, create_neo4j_driver
from ..utils.neo4j_utils import get_neo4j_config

# ✅ For scripts (scripts/**)
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from utils.common import setup_logging
```

### ❌ **NEVER USE: Conditional Import Patterns**

```python
# ❌ WRONG - Messy conditional imports
try:
    from utils.common import setup_logging
except ImportError:
    from ..utils.common import setup_logging
```

**Why**: Conditional imports make code harder to understand and indicate poor module structure.

---

## 🏗️ **Module Structure Standards**

### **Library Modules** (`src/` directory)
- Use **relative imports** (`from ..utils.common import`)
- Include `if __name__ == "__main__":` blocks for testing
- Always use helper functions from `utils.common`

### **Script Files** (`scripts/` directory)
- Use **absolute imports** after adding `src/` to path
- Minimal argument parsing (delegate complex logic to library modules)
- Always use helper functions from `utils.common`

### **Test Files** (`tests/` directory)
- Use **absolute imports** with proper path setup
- Mock external dependencies consistently
- Test helper function usage, not internal implementations

---

## 🚨 **Error Handling Standards**

### ✅ **CORRECT: Consistent Error Patterns**

```python
# ✅ CORRECT - Use helper and proper error handling
try:
    with create_neo4j_driver(uri, username, password) as driver:
        result = process_data(driver)
        logger.info("✅ Processing completed successfully")
except Exception as e:
    logger.error(f"❌ Processing failed: {e}")
    raise
```

### ❌ **NEVER USE: Inconsistent Error Handling**

```python
# ❌ WRONG - Manual connection with poor error handling
try:
    driver = GraphDatabase.driver(uri, auth=(username, password))
    driver.verify_connectivity()
    # Missing proper cleanup and error context
except:
    print("Something went wrong")  # Poor error reporting
```

---

## 🔧 **Configuration Standards**

### ✅ **ALWAYS USE: get_neo4j_config() Helper**

```python
# ✅ CORRECT - Use configuration helper
from utils.neo4j_utils import get_neo4j_config

uri, username, password, database = get_neo4j_config()
```

### ❌ **NEVER USE: Hardcoded or Manual Config**

```python
# ❌ WRONG - Hardcoded values
NEO4J_URI = "bolt://localhost:7687"
NEO4J_USERNAME = "neo4j"
NEO4J_PASSWORD = "password"
```

**Why**: The helper reads from environment variables and provides proper defaults.

---

## 📋 **Checklist for New Code**

Before submitting new code, verify:

- [ ] Uses `setup_logging()` instead of `logging.basicConfig()`
- [ ] Uses `create_neo4j_driver()` instead of `GraphDatabase.driver()`
- [ ] Uses `add_common_args()` instead of manual argument definitions
- [ ] Uses `get_neo4j_config()` for configuration
- [ ] No conditional try/except import patterns
- [ ] Proper relative imports for library modules
- [ ] Consistent error handling and logging
- [ ] All pre-commit checks pass

---

## 🔍 **Common Anti-Patterns to Avoid**

1. **Logging Format Drift**: Different log formats across modules
2. **Argument Duplication**: Redefining common arguments in each module
3. **Connection Inconsistency**: Some modules using helpers, others using manual patterns
4. **Import Confusion**: Mixing relative and absolute imports inconsistently
5. **Configuration Scattering**: Hardcoding values instead of using config helpers

---

## 📈 **Benefits of Consistent Patterns**

- **Maintainability**: Changes to common functionality only need to be made in one place
- **Readability**: Developers know what to expect across the codebase
- **Debugging**: Consistent logging and error handling makes issues easier to trace
- **Testing**: Consistent patterns make mocking and testing more straightforward
- **Onboarding**: New developers can quickly understand patterns

---

## 🚀 **Enforcement**

This style guide is enforced by:

1. **Pre-commit hooks**: Automated linting catches many violations
2. **Code reviews**: Manual review ensures adherence to patterns
3. **Documentation**: This guide serves as the canonical reference

For questions about these patterns, refer to the implementations in `src/utils/common.py` and `src/utils/neo4j_utils.py`.
