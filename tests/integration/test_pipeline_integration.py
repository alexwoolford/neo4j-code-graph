#!/usr/bin/env python3
"""
Integration tests for the complete neo4j-code-graph pipeline.

These tests use real components but against test data to ensure
the entire pipeline works together correctly.
"""

# CI utilities
import os

# Add src to path for testing
import sys
import tempfile
from pathlib import Path

import pytest

from src.analysis.code_analysis import extract_file_data
from src.data.schema_management import setup_complete_schema
from src.utils.common import create_neo4j_driver, get_neo4j_config

ROOT = Path(__file__).parent.parent.parent / "src"
sys.path.insert(0, str(ROOT))


@pytest.mark.integration
class TestPipelineIntegration:
    """Integration tests for the complete pipeline."""

    @pytest.fixture(scope="class")
    def neo4j_driver(self):
        """Create a Neo4j driver for testing."""
        try:
            # Use CI config if available, fallback to .env config
            ci_uri = os.getenv("NEO4J_URI")
            if ci_uri:
                config = (
                    ci_uri,
                    os.getenv("NEO4J_USERNAME", "neo4j"),
                    os.getenv("NEO4J_PASSWORD", "testpassword"),
                    os.getenv("NEO4J_DATABASE", "neo4j"),
                )
            else:
                config = get_neo4j_config()

            driver = create_neo4j_driver(config[0], config[1], config[2])
            try:
                driver.verify_connectivity()
            except Exception as e:
                driver.close()
                pytest.skip(f"Neo4j not available: {e}")
            yield driver
            driver.close()
        except Exception as e:
            pytest.skip(f"Neo4j not available: {e}")

    @pytest.fixture(scope="class")
    def test_database(self, neo4j_driver):
        """Setup test database with clean schema."""
        test_db = "test_code_graph"

        with neo4j_driver.session() as session:
            # Create test database
            try:
                session.run(f"CREATE DATABASE {test_db}")
            except Exception:
                pass  # Database might already exist

        # Setup schema in test database
        with neo4j_driver.session(database=test_db) as session:
            setup_complete_schema(session)

        yield test_db

        # Cleanup
        with neo4j_driver.session() as session:
            try:
                session.run(f"DROP DATABASE {test_db}")
            except Exception:
                pass

    @pytest.fixture
    def sample_java_repo(self):
        """Create a temporary directory with sample Java files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)

            # Create sample Java files
            java_file = repo_path / "src" / "main" / "java" / "com" / "example" / "Calculator.java"
            java_file.parent.mkdir(parents=True, exist_ok=True)

            java_content = """
package com.example;

import java.util.List;
import java.util.ArrayList;

/**
 * A simple calculator class for testing.
 */
public class Calculator {
    private List<Double> history;

    public Calculator() {
        this.history = new ArrayList<>();
    }

    /**
     * Add two numbers and store in history.
     */
    public double add(double a, double b) {
        double result = a + b;
        history.add(result);
        return result;
    }

    /**
     * Multiply two numbers.
     */
    public double multiply(double a, double b) {
        double result = a * b;
        history.add(result);
        return result;
    }

    /**
     * Get calculation history.
     */
    public List<Double> getHistory() {
        return new ArrayList<>(history);
    }

    /**
     * Clear the calculation history.
     */
    public void clearHistory() {
        history.clear();
    }
}
"""
            java_file.write_text(java_content)

            # Create another Java file with interface
            interface_file = (
                repo_path / "src" / "main" / "java" / "com" / "example" / "Processor.java"
            )
            interface_content = """
package com.example;

import java.util.List;

/**
 * Interface for data processing.
 */
public interface Processor<T> {
    /**
     * Process a list of items.
     */
    List<T> process(List<T> items);

    /**
     * Get processor name.
     */
    String getName();
}
"""
            interface_file.write_text(interface_content)

            yield repo_path

    def test_java_file_parsing(self, sample_java_repo):
        """Test that Java files are parsed correctly."""
        java_files = list(sample_java_repo.rglob("*.java"))
        assert len(java_files) == 2

        # Test parsing the Calculator class
        calculator_file = next(f for f in java_files if f.name == "Calculator.java")
        file_data = extract_file_data(calculator_file, sample_java_repo)

        assert file_data is not None
        assert file_data["path"] == "src/main/java/com/example/Calculator.java"
        assert len(file_data["classes"]) == 1
        assert file_data["classes"][0]["name"] == "Calculator"
        assert len(file_data["methods"]) >= 4  # Constructor + 4 methods

        # Check that methods were extracted
        method_names = [m["name"] for m in file_data["methods"]]
        assert "add" in method_names
        assert "multiply" in method_names
        assert "getHistory" in method_names
        assert "clearHistory" in method_names

    def test_interface_parsing(self, sample_java_repo):
        """Test that Java interfaces are parsed correctly."""
        processor_file = next(f for f in sample_java_repo.rglob("Processor.java"))
        file_data = extract_file_data(processor_file, sample_java_repo)

        assert file_data is not None
        assert len(file_data["interfaces"]) == 1
        assert file_data["interfaces"][0]["name"] == "Processor"
        assert len(file_data["methods"]) == 2  # Two interface methods

    @pytest.mark.skip(reason="Requires Neo4j connection and full pipeline setup")
    def test_end_to_end_pipeline(self, neo4j_driver, test_database, sample_java_repo):
        """Test the complete pipeline from code extraction to graph creation."""
        # This would test the full pipeline but requires significant setup
        # Including git initialization, running the full pipeline, etc.
        pass

    def test_schema_creation(self, neo4j_driver, test_database):
        """Test that database schema is created correctly."""
        with neo4j_driver.session(database=test_database) as session:
            # Check that constraints exist
            result = session.run("SHOW CONSTRAINTS")
            constraints = [record["name"] for record in result]

            # Should have constraints for key node types
            assert any("File" in constraint for constraint in constraints)
            assert any("Method" in constraint for constraint in constraints)

    def test_import_extraction(self, sample_java_repo):
        """Test that imports are extracted correctly from Java files."""
        calculator_file = next(sample_java_repo.rglob("Calculator.java"))
        file_data = extract_file_data(calculator_file, sample_java_repo)

        assert file_data is not None
        assert "imports" in file_data

        # Check that imports were extracted
        imports = file_data["imports"]
        import_paths = [imp["import_path"] for imp in imports]
        assert "java.util.List" in import_paths
        assert "java.util.ArrayList" in import_paths

    def test_method_signature_extraction(self, sample_java_repo):
        """Test that method signatures are extracted with proper details."""
        calculator_file = next(sample_java_repo.rglob("Calculator.java"))
        file_data = extract_file_data(calculator_file, sample_java_repo)

        assert file_data is not None
        methods = file_data["methods"]

        # Find the add method
        add_method = next((m for m in methods if m["name"] == "add"), None)
        assert add_method is not None
        assert add_method["return_type"] == "double"
        assert len(add_method["parameters"]) == 2
        assert add_method["parameters"][0]["type"] == "double"
        assert add_method["parameters"][1]["type"] == "double"

    def test_complexity_metrics(self, sample_java_repo):
        """Test that complexity metrics are calculated."""
        calculator_file = next(sample_java_repo.rglob("Calculator.java"))
        file_data = extract_file_data(calculator_file, sample_java_repo)

        assert file_data is not None
        assert "total_lines" in file_data
        assert "code_lines" in file_data
        assert "method_count" in file_data
        assert "class_count" in file_data

        assert file_data["total_lines"] > 0
        assert file_data["method_count"] >= 4
        assert file_data["class_count"] == 1


@pytest.mark.integration
class TestRealWorldScenarios:
    """Integration tests using real-world scenarios."""

    def test_error_handling_with_malformed_java(self):
        """Test that malformed Java files are handled gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)

            # Create malformed Java file
            bad_file = repo_path / "BadJava.java"
            bad_file.write_text("public class { // Malformed syntax")

            # Should not crash, should return None or handle gracefully
            result = extract_file_data(bad_file, repo_path)
            # The function should handle this gracefully
            assert result is None or isinstance(result, dict)

    def test_large_file_handling(self):
        """Test handling of large Java files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)

            # Create a large Java file
            large_file = repo_path / "LargeClass.java"
            content = "public class LargeClass {\n"

            # Add many methods
            for i in range(100):
                content += f"""
    public void method{i}() {{
        System.out.println(\"Method {i}\");
        int x = {i};
        if (x > 50) {{
            System.out.println(\"Large number\");
        }}
    }}
"""
            content += "}\n"

            large_file.write_text(content)

            # Should handle large files without issues
            result = extract_file_data(large_file, repo_path)
            assert result is not None
            assert len(result["methods"]) == 100

    def test_nested_package_structure(self):
        """Test handling of deeply nested package structures."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)

            # Create deeply nested structure
            nested_file = (
                repo_path
                / "src"
                / "main"
                / "java"
                / "com"
                / "company"
                / "product"
                / "module"
                / "NestedClass.java"
            )
            nested_file.parent.mkdir(parents=True, exist_ok=True)

            content = """
package com.company.product.module;

import java.util.Map;
import java.util.HashMap;

public class NestedClass {
    public Map<String, String> getData() {
        return new HashMap<>();
    }
}
"""
            nested_file.write_text(content)

            result = extract_file_data(nested_file, repo_path)
            assert result is not None
            assert result["path"] == "src/main/java/com/company/product/module/NestedClass.java"
            assert result["classes"][0]["package"] == "com.company.product.module"


@pytest.mark.integration
class TestCIPipelineIntegration:
    """CI-specific integration tests with minimal data."""

    def test_ci_data_available(self):
        """Test that CI test data is properly prepared."""
        ci_test_data_dir = Path("./test_cache/ci_data")
        if not ci_test_data_dir.exists():
            pytest.skip("CI test data not available")

        assert ci_test_data_dir.exists()
        config_file = ci_test_data_dir / "ci_test_config.json"
        assert config_file.exists()

    def test_ci_java_project_structure(self):
        """Test that CI sample Java project has expected structure."""
        ci_test_data_dir = Path("./test_cache/ci_data")
        if not ci_test_data_dir.exists():
            pytest.skip("CI test data not available")

        project_dir = ci_test_data_dir / "sample-java-project"
        if not project_dir.exists():
            pytest.skip("CI sample project not available")

        assert project_dir.exists()
        java_files = list(project_dir.rglob("*.java"))
        assert len(java_files) > 0

        pom_file = project_dir / "pom.xml"
        assert pom_file.exists()

    def test_ci_file_extraction(self):
        """Test file data extraction with CI minimal data."""
        ci_test_data_dir = Path("./test_cache/ci_data")
        project_dir = ci_test_data_dir / "sample-java-project"
        if not project_dir.exists():
            pytest.skip("CI test data not available")

        java_files = list(project_dir.rglob("*.java"))
        assert len(java_files) > 0

        java_file = java_files[0]
        result = extract_file_data(java_file, project_dir)

        assert result is not None
        assert "path" in result
        assert "methods" in result
        # CI minimal data should have at least one method
        assert len(result["methods"]) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
