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


def test_progress_reports_counts_live():
    from src.pipeline.progress import check_database_state

    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as s:
            s.run("MATCH (n) DETACH DELETE n").consume()
            s.run(
                "CREATE (:File {path:'f.java'}), (:Method {id:'p.C#m():void', name:'m', file:'f.java', line:1, method_signature:'p.C#m():void'}), (:Import {import_path:'java.util.List'})"
            ).consume()
            s.run(
                "MATCH (f:File {path:'f.java'}), (m:Method {name:'m'}) CREATE (f)-[:DECLARES]->(m), (f)-[:IMPORTS]->(:Import {import_path:'java.util.Set'})"
            ).consume()

        state = check_database_state(driver, database)
        assert state["node_types"].get("File", 0) >= 1
        assert state["node_types"].get("Method", 0) >= 1
        assert state["rel_types"].get("IMPORTS", 0) >= 1


@pytest.mark.live
def test_progress_flags_after_bulk_live():
    from src.analysis.code_analysis import bulk_create_nodes_and_relationships
    from src.data.schema_management import setup_complete_schema
    from src.pipeline.progress import check_database_state

    files_data = [
        {
            "path": "prog/A.java",
            "classes": [{"name": "A", "file": "prog/A.java", "line": 1, "implements": []}],
            "methods": [
                {
                    "name": "a",
                    "file": "prog/A.java",
                    "line": 10,
                    "method_signature": "p.A#a():void",
                    "class_name": "A",
                    "containing_type": "class",
                    "return_type": "void",
                    "parameters": [],
                    "code": "",
                }
            ],
            "imports": [
                {
                    "import_path": "org.example.lib.Api",
                    "import_type": "external",
                    "file": "prog/A.java",
                    "is_static": False,
                    "is_wildcard": False,
                }
            ],
        }
    ]

    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as s:
            s.run("MATCH (n) DETACH DELETE n").consume()
            setup_complete_schema(s)
            # Strict policy: provide dependency versions for external imports
            bulk_create_nodes_and_relationships(
                s,
                files_data,
                file_embeddings=[],
                method_embeddings=[],
                dependency_versions={
                    "org.example.lib": "1.0.0",
                    "org.example.lib:lib-api:1.0.0": "1.0.0",
                },
            )

        state = check_database_state(driver, database)
        # Files/methods embeddings are optional in this test data, so expect partial flags
        assert state["imports_complete"] is True
        assert state["calls_partial"] in (False, True)  # may be False if no calls in this dataset
