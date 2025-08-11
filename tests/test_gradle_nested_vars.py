from __future__ import annotations

import sys
from pathlib import Path


def add_src_to_path() -> None:
    root = Path(__file__).parent
    src = root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))


add_src_to_path()

from analysis.dependency_extraction import extract_enhanced_dependencies_for_neo4j  # noqa: E402


def test_gradle_nested_variable_resolution(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    (repo_root / "build.gradle").write_text(
        """
        ext {
            coreVersion = '1.2.3'
            apiVersion = "$coreVersion"
        }
        dependencies {
            implementation "org.demo:demo-api:$apiVersion"
        }
        """.strip(),
        encoding="utf-8",
    )

    deps = extract_enhanced_dependencies_for_neo4j(repo_root)
    assert deps.get("org.demo:demo-api:1.2.3") == "1.2.3"
