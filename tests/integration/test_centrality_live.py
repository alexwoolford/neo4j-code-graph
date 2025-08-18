import pytest


@pytest.mark.live
def test_pagerank_via_cypher_live():
    try:
        from src.utils.common import create_neo4j_driver, get_neo4j_config
    except Exception:
        pytest.skip("Utilities not available")

    uri, user, pwd, db = get_neo4j_config()
    try:
        driver = create_neo4j_driver(uri, user, pwd)
    except Exception:
        pytest.skip("Neo4j is not available for live tests (set NEO4J_* env vars)")

    with driver:
        with driver.session(database=db) as session:
            # Clear and create a tiny graph
            session.run("MATCH (n) DETACH DELETE n").consume()
            # Schema enforces presence of `method_signature` on :Method
            session.run(
                "CREATE (:Method {id:'A#a():void', name:'A', method_signature:'A#a():void'}), "
                "(:Method {id:'B#b():void', name:'B', method_signature:'B#b():void'}), "
                "(:Method {id:'C#c():void', name:'C', method_signature:'C#c():void'})"
            ).consume()
            session.run(
                "MATCH (a:Method {name:'A'}), (b:Method {name:'B'}), (c:Method {name:'C'}) "
                "CREATE (a)-[:CALLS]->(b), (a)-[:CALLS]->(c), (b)-[:CALLS]->(c)"
            ).consume()

            # Ensure GDS is present then project and run PageRank using Cypher GDS
            session.run("CALL gds.version()").consume()
            session.run("CALL gds.graph.drop('live_pr_graph', false)").consume()
            session.run(
                "CALL gds.graph.project('live_pr_graph', ['Method'], {CALLS: {orientation: 'NATURAL'}})"
            ).consume()
            df = session.run(
                "CALL gds.pageRank.stream('live_pr_graph') YIELD nodeId, score RETURN nodeId, score ORDER BY score DESC"
            ).data()
            assert len(df) >= 1
            session.run("CALL gds.graph.drop('live_pr_graph', false)").consume()


@pytest.mark.live
def test_pagerank_write_back_via_module_live():
    try:
        from graphdatascience import GraphDataScience  # type: ignore
    except Exception:
        pytest.skip("graphdatascience with pyarrow.flight not available in this environment")

    try:
        from src.utils.common import create_neo4j_driver, get_neo4j_config
    except Exception:
        pytest.skip("Utilities not available")

    from src.analysis.centrality import create_call_graph_projection, run_pagerank_analysis
    from src.data.schema_management import setup_complete_schema

    uri, user, pwd, db = get_neo4j_config()
    driver = create_neo4j_driver(uri, user, pwd)
    with driver:
        with driver.session(database=db) as session:
            session.run("MATCH (n) DETACH DELETE n").consume()
            setup_complete_schema(session)
            # Seed small directed call graph; C is the sink with highest expected rank
            session.run(
                """
                CREATE (:Method {id:'A#a():void', name:'A', method_signature:'A#a():void'}),
                       (:Method {id:'B#b():void', name:'B', method_signature:'B#b():void'}),
                       (:Method {id:'C#c():void', name:'C', method_signature:'C#c():void'})
                """
            ).consume()
            session.run(
                "MATCH (a:Method {name:'A'}), (b:Method {name:'B'}), (c:Method {name:'C'}) "
                "CREATE (a)-[:CALLS]->(b), (a)-[:CALLS]->(c), (b)-[:CALLS]->(c)"
            ).consume()

    gds = GraphDataScience(uri, auth=(user, pwd), database=db, arrow=False)
    try:
        G = create_call_graph_projection(gds)
        _ = run_pagerank_analysis(gds, G, top_n=3, write_back=True)
        # Assert write-back property exists and ordering is stable: C > B > A
        df = gds.run_cypher(
            "MATCH (m:Method) RETURN m.name AS n, m.pagerank_score AS s ORDER BY s DESC"
        )
        assert len(df) == 3 and df.iloc[0]["n"] == "C" and df.iloc[2]["n"] == "A"
    finally:
        try:
            gds.graph.drop("method_call_graph")
        except Exception:
            pass
        gds.close()


@pytest.mark.live
def test_pagerank_stream_on_bulk_graph_live():
    try:
        from graphdatascience import GraphDataScience  # type: ignore
    except Exception:
        pytest.skip("graphdatascience with pyarrow.flight not available in this environment")

    try:
        from src.utils.common import create_neo4j_driver, get_neo4j_config
    except Exception:
        pytest.skip("Utilities not available")

    from src.analysis.centrality import create_call_graph_projection, run_pagerank_analysis
    from src.analysis.code_analysis import bulk_create_nodes_and_relationships
    from src.data.schema_management import setup_complete_schema

    files_data = [
        {
            "path": "cent/A.java",
            "classes": [{"name": "A", "file": "cent/A.java", "line": 1, "implements": []}],
            "methods": [
                {
                    "name": "a",
                    "file": "cent/A.java",
                    "line": 10,
                    "method_signature": "c.A#a():void",
                    "class_name": "A",
                    "containing_type": "class",
                    "return_type": "void",
                    "parameters": [],
                    "code": "b();",
                    "calls": [{"method_name": "b", "target_class": "A", "call_type": "same_class"}],
                },
                {
                    "name": "b",
                    "file": "cent/A.java",
                    "line": 20,
                    "method_signature": "c.A#b():void",
                    "class_name": "A",
                    "containing_type": "class",
                    "return_type": "void",
                    "parameters": [],
                    "code": "",
                },
            ],
        }
    ]

    uri, user, pwd, db = get_neo4j_config()
    driver = create_neo4j_driver(uri, user, pwd)
    with driver:
        with driver.session(database=db) as session:
            session.run("MATCH (n) DETACH DELETE n").consume()
            setup_complete_schema(session)
            bulk_create_nodes_and_relationships(
                session,
                files_data,
                file_embeddings=[],
                method_embeddings=[],
                dependency_versions=None,
            )

    gds = GraphDataScience(uri, auth=(user, pwd), database=db, arrow=False)
    try:
        G = create_call_graph_projection(gds)
        top = run_pagerank_analysis(gds, G, top_n=2, write_back=False)
        assert not top.empty and set(top.columns) >= {"method_name", "class_name", "file"}
    finally:
        try:
            gds.graph.drop("method_call_graph")
        except Exception:
            pass
        gds.close()
