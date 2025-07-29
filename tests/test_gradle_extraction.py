import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from src.analysis.code_analysis import _extract_gradle_dependencies


def test_standard_dependency(tmp_path):
    gradle_file = tmp_path / "build.gradle"
    gradle_file.write_text("dependencies { implementation 'org.example:lib:1.2.3' }")

    deps = _extract_gradle_dependencies(gradle_file)
    assert deps["org.example.lib"] == "1.2.3"
    assert deps["org.example"] == "1.2.3"


def test_map_style_dependency(tmp_path):
    gradle_file = tmp_path / "build.gradle"
    gradle_file.write_text(
        "dependencies { implementation group: 'junit', name: 'junit', version: '4.13.2' }"
    )

    deps = _extract_gradle_dependencies(gradle_file)
    assert deps["junit.junit"] == "4.13.2"
    assert deps["junit"] == "4.13.2"
