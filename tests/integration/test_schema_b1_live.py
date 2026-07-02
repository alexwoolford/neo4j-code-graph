"""Live regression for B1 schema additions: Field, Annotation, Exception, NESTED_IN,
Enum/Record secondary labels, expanded method modifiers (is_protected,
is_synchronized, is_default, is_package_private).
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.live


def _get_driver_or_skip():
    try:
        from src.utils.common import create_neo4j_driver, get_neo4j_config
    except Exception:
        pytest.skip("Utilities not available")
    uri, user, pwd, db = get_neo4j_config()
    try:
        driver = create_neo4j_driver(uri, user, pwd)
        return driver, db
    except Exception:
        pytest.skip("Neo4j is not available for live tests (set NEO4J_* env vars)")


JAVA_FIXTURE = """
package demo;

import java.io.IOException;
import org.example.Bar;

@Service
public class Demo {
    @Autowired
    private final Bar bar;

    protected static int counter = 0;
    public volatile transient String name;

    public Demo(Bar b) { this.bar = b; }

    @Override
    public synchronized String toString() throws IOException, RuntimeException {
        return "Demo";
    }

    protected void hidden() {}

    void packagePrivate() {}

    public static enum Color { RED, GREEN }

    public static record Point(int x, int y) {}

    public static class Inner {
        @Deprecated
        protected int innerField;
        protected void hide() {}
    }
}

interface Service {
    @Override
    default void run() {}
}
"""


def _ingest(session, repo: Path) -> None:
    """Run the part of the pipeline that exercises B1 writers, against tiny fixture."""
    from src.analysis.code_analysis import (
        bulk_create_nodes_and_relationships,
        extract_file_data,
    )
    from src.data.schema_management import setup_complete_schema

    setup_complete_schema(session)
    session.run("MATCH (n) DETACH DELETE n").consume()
    setup_complete_schema(session)

    files_data = []
    for p in repo.rglob("*.java"):
        fd = extract_file_data(p, repo)
        if fd:
            files_data.append(fd)
    bulk_create_nodes_and_relationships(
        session,
        files_data,
        method_embeddings=[],
    )


def test_b1_secondary_labels_and_extended_modifiers(tmp_path: Path) -> None:
    repo = tmp_path / "demo"
    src = repo / "src" / "main" / "java" / "demo"
    src.mkdir(parents=True, exist_ok=True)
    (src / "Demo.java").write_text(JAVA_FIXTURE, encoding="utf-8")

    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as s:
            _ingest(s, repo)

            # Enum gets the :Enum secondary label
            r = s.run("MATCH (e:Enum) RETURN e.name AS name, e.kind AS kind ORDER BY e.name").data()
            assert any(row["name"] == "Color" and row["kind"] == "enum" for row in r), r

            # Record gets the :Record secondary label
            r = s.run("MATCH (rec:Record) RETURN rec.name AS name, rec.kind AS kind").data()
            assert any(row["name"] == "Point" and row["kind"] == "record" for row in r), r

            # Method modifiers: protected, synchronized, default, package-private
            modifiers = {
                row["name"]: row
                for row in s.run(
                    """
                    MATCH (m:Method)
                    RETURN m.name AS name,
                           m.is_protected AS prot,
                           m.is_synchronized AS sync,
                           m.is_default AS dflt,
                           m.is_package_private AS pkg
                    """
                ).data()
            }
            assert modifiers["toString"]["sync"] is True
            assert modifiers["hidden"]["prot"] is True
            assert modifiers["packagePrivate"]["pkg"] is True
            assert modifiers["run"]["dflt"] is True


def test_b1_field_nodes_and_annotations(tmp_path: Path) -> None:
    repo = tmp_path / "demo"
    src = repo / "src" / "main" / "java" / "demo"
    src.mkdir(parents=True, exist_ok=True)
    (src / "Demo.java").write_text(JAVA_FIXTURE, encoding="utf-8")

    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as s:
            _ingest(s, repo)

            # Field nodes are created with modifiers
            r = s.run(
                """
                MATCH (f:Field)
                RETURN f.owner_name AS owner, f.name AS name,
                       f.type AS type, f.is_static AS stat,
                       f.is_protected AS prot, f.is_volatile AS vol,
                       f.is_transient AS trans, f.is_private AS priv
                """
            ).data()
            by_name = {(row["owner"], row["name"]): row for row in r}
            assert ("Demo", "bar") in by_name
            assert by_name[("Demo", "bar")]["priv"] is True
            assert by_name[("Demo", "counter")]["stat"] is True
            assert by_name[("Demo", "counter")]["prot"] is True
            assert by_name[("Demo", "name")]["vol"] is True
            assert by_name[("Demo", "name")]["trans"] is True
            assert ("Inner", "innerField") in by_name

            # DECLARES_FIELD edges from owning class to field
            count = s.run(
                "MATCH (:Class)-[:DECLARES_FIELD]->(:Field) RETURN count(*) AS c"
            ).single()["c"]
            assert count >= 4, f"expected >=4 DECLARES_FIELD edges, got {count}"

            # Annotation nodes are deduped
            anns = {
                row["name"] for row in s.run("MATCH (a:Annotation) RETURN a.name AS name").data()
            }
            assert {"Service", "Autowired", "Override", "Deprecated"} <= anns, anns

            # ANNOTATED edges from class, method, field
            r = s.run(
                """
                MATCH (cls:Class {name: 'Demo'})-[:ANNOTATED]->(a:Annotation {name: 'Service'})
                RETURN count(*) AS c
                """
            ).single()
            assert r["c"] == 1

            r = s.run(
                """
                MATCH (m:Method {name: 'toString'})-[:ANNOTATED]->(a:Annotation {name: 'Override'})
                RETURN count(*) AS c
                """
            ).single()
            assert r["c"] == 1

            r = s.run(
                """
                MATCH (f:Field {name: 'bar', owner_name: 'Demo'})-[:ANNOTATED]->(a:Annotation {name: 'Autowired'})
                RETURN count(*) AS c
                """
            ).single()
            assert r["c"] == 1


def test_b1_throws_and_nested_class_links(tmp_path: Path) -> None:
    repo = tmp_path / "demo"
    src = repo / "src" / "main" / "java" / "demo"
    src.mkdir(parents=True, exist_ok=True)
    (src / "Demo.java").write_text(JAVA_FIXTURE, encoding="utf-8")

    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as s:
            _ingest(s, repo)

            # toString throws IOException + RuntimeException -> 2 THROWS edges
            r = s.run(
                """
                MATCH (m:Method {name: 'toString'})-[:THROWS]->(e:Exception)
                RETURN collect(e.name) AS names
                """
            ).single()
            assert set(r["names"]) == {"IOException", "RuntimeException"}, r["names"]

            # Inner is NESTED_IN Demo (Color and Point too)
            r = s.run(
                """
                MATCH (child)-[:NESTED_IN]->(parent {name: 'Demo'})
                RETURN child.name AS name ORDER BY child.name
                """
            ).data()
            names = {row["name"] for row in r}
            assert {"Inner", "Color", "Point"} <= names, names
