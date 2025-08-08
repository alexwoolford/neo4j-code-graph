#!/usr/bin/env python3

from pathlib import Path

from src.analysis.dependency_extraction import (
    EnhancedDependencyExtractor,
    PropertyResolver,
)


def test_property_resolver_basic_cases():
    r = PropertyResolver()
    props = {"junit.version": "4.13.2"}
    assert r.resolve_version("1.0.0", props) == "1.0.0"
    assert r.resolve_version("${junit.version}", props) == "4.13.2"
    assert r.resolve_version("${unknown}", props) == "${unknown}"


def test_extract_gradle_scope_parsing(tmp_path: Path):
    extractor = EnhancedDependencyExtractor()
    content = """
    dependencies {
        implementation 'org.slf4j:slf4j-api:1.7.36'
        runtime 'com.fasterxml.jackson.core:jackson-databind:2.15.0'
        testImplementation 'junit:junit:4.13.2'
    }
    """
    f = tmp_path / "build.gradle"
    f.write_text(content)
    deps = extractor._extract_gradle_dependencies_enhanced(f)
    # three entries
    assert len(deps) == 3
    scopes = sorted(d.scope for d in deps)
    assert scopes == ["compile", "runtime", "test"]
