"""Maven coordinate parsing for --resolve-build-deps.

Regression guard: dependency:list/tree lines are
groupId:artifactId:type[:classifier]:version[:scope], not bare
group:artifact:version triplets. The old regex captured the leading
`g:a:type` as `g:a:version`, so most dependencies landed with
artifact_id="jar" and a scope keyword for a version, severing CVE matching.
"""

from __future__ import annotations

import pytest

from src.pipeline.tasks.code_tasks import _parse_mvn_coordinate


@pytest.mark.parametrize(
    "line,expected",
    [
        (
            "   org.springframework.boot:spring-boot-starter-web:jar:2.0.5.RELEASE:compile",
            ("org.springframework.boot", "spring-boot-starter-web", "2.0.5.RELEASE"),
        ),
        (
            "+- org.jsoup:jsoup:jar:1.11.3:compile",
            ("org.jsoup", "jsoup", "1.11.3"),
        ),
        (
            "|  \\- com.fasterxml.jackson.core:jackson-databind:jar:2.9.7:compile",
            ("com.fasterxml.jackson.core", "jackson-databind", "2.9.7"),
        ),
        (
            # 6-field: type + classifier + version + scope
            "org.projectlombok:lombok:jar:test-jar:1.18.4:provided",
            ("org.projectlombok", "lombok", "1.18.4"),
        ),
        (
            "commons-lang:commons-lang:2.6",
            ("commons-lang", "commons-lang", "2.6"),
        ),
    ],
)
def test_parses_real_maven_coordinates(line, expected):
    assert _parse_mvn_coordinate(line) == expected


@pytest.mark.parametrize(
    "line",
    [
        "",
        "The following files have been resolved:",  # plain prose
        "org.example:artifact",  # too few fields
        "org.example:artifact:jar:${revision}:compile",  # unresolved property
    ],
)
def test_rejects_non_coordinates(line):
    assert _parse_mvn_coordinate(line) is None


def test_never_returns_type_keyword_as_artifact_or_version():
    result = _parse_mvn_coordinate("org.springframework:spring-core:jar:5.0.9.RELEASE:compile")
    assert result is not None
    _g, artifact, version = result
    assert artifact != "jar"
    assert version not in {"jar", "compile"}
