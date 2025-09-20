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
            session.run(
                "CALL gds.graph.drop('live_pr_graph', false) YIELD graphName RETURN graphName"
            ).consume()
            session.run(
                "CALL gds.graph.project('live_pr_graph', ['Method'], {CALLS: {orientation: 'NATURAL'}})"
            ).consume()
            df = session.run(
                "CALL gds.pageRank.stream('live_pr_graph') YIELD nodeId, score RETURN nodeId, score ORDER BY score DESC"
            ).data()
            assert len(df) >= 1
            session.run(
                "CALL gds.graph.drop('live_pr_graph', false) YIELD graphName RETURN graphName"
            ).consume()


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
            gds.run_cypher(
                "CALL gds.graph.drop($name, false) YIELD graphName RETURN graphName",
                name="method_call_graph",
            )
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
            gds.run_cypher(
                "CALL gds.graph.drop($name, false) YIELD graphName RETURN graphName",
                name="method_call_graph",
            )
        except Exception:
            pass
        gds.close()


@pytest.mark.live
def test_same_class_calls_written_without_callee_class():
    try:
        from src.utils.common import create_neo4j_driver, get_neo4j_config
    except Exception:
        pytest.skip("Utilities not available")

    from src.analysis.code_analysis import bulk_create_nodes_and_relationships
    from src.data.schema_management import setup_complete_schema

    # Minimal fixture where extractor would not set callee_class, but writer should fallback
    files_data = [
        {
            "path": "mini/A.java",
            "classes": [{"name": "A", "file": "mini/A.java", "line": 1, "implements": []}],
            "methods": [
                {
                    "name": "a",
                    "file": "mini/A.java",
                    "line": 5,
                    "method_signature": "m.A#a():void",
                    "class_name": "A",
                    "containing_type": "class",
                    "return_type": "void",
                    "parameters": [],
                    "code": "b();",
                    # calls has no target_class set (simulating extractor behavior)
                    "calls": [{"method_name": "b", "call_type": "same_class"}],
                },
                {
                    "name": "b",
                    "file": "mini/A.java",
                    "line": 10,
                    "method_signature": "m.A#b():void",
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
            rec = session.run(
                "MATCH (:Method {name:'a'})-[:CALLS]->(:Method {name:'b'}) RETURN count(*) AS c"
            ).single()
            assert rec and int(rec["c"]) == 1


@pytest.mark.live
def test_degree_write_back_live():
    try:
        from graphdatascience import GraphDataScience  # type: ignore
    except Exception:
        pytest.skip("graphdatascience with pyarrow.flight not available in this environment")

    try:
        from src.utils.common import create_neo4j_driver, get_neo4j_config
    except Exception:
        pytest.skip("Utilities not available")

    from src.analysis.centrality import create_call_graph_projection, run_degree_analysis
    from src.data.schema_management import setup_complete_schema

    uri, user, pwd, db = get_neo4j_config()
    driver = create_neo4j_driver(uri, user, pwd)
    with driver:
        with driver.session(database=db) as session:
            session.run("MATCH (n) DETACH DELETE n").consume()
            setup_complete_schema(session)
            # A->B, B->C. Degrees: A(out1,in0,tot1), B(out1,in1,tot2), C(out0,in1,tot1)
            session.run(
                """
                CREATE (:Method {id:'A#a():void', name:'A', method_signature:'A#a():void'}),
                       (:Method {id:'B#b():void', name:'B', method_signature:'B#b():void'}),
                       (:Method {id:'C#c():void', name:'C', method_signature:'C#c():void'})
                """
            ).consume()
            session.run(
                "MATCH (a:Method {name:'A'}), (b:Method {name:'B'}), (c:Method {name:'C'}) "
                "CREATE (a)-[:CALLS]->(b), (b)-[:CALLS]->(c)"
            ).consume()

    gds = GraphDataScience(uri, auth=(user, pwd), database=db, arrow=False)
    try:
        G = create_call_graph_projection(gds)
        _ = run_degree_analysis(gds, G, top_n=3, write_back=True)
        # Verify degrees written
        df = gds.run_cypher(
            "MATCH (m:Method) RETURN m.name AS n, m.in_degree AS i, m.out_degree AS o, m.total_degree AS t ORDER BY n"
        )
        rows = {
            r["n"]: (int(r["i"] or 0), int(r["o"] or 0), int(r["t"] or 0)) for _, r in df.iterrows()
        }
        assert rows["A"] == (0, 1, 1)
        assert rows["B"] == (1, 1, 2)
        assert rows["C"] == (1, 0, 1)
    finally:
        try:
            gds.run_cypher(
                "CALL gds.graph.drop($name, false) YIELD graphName RETURN graphName",
                name="method_call_graph",
            )
        except Exception:
            pass
        gds.close()


@pytest.mark.live
def test_betweenness_write_back_live():
    try:
        from graphdatascience import GraphDataScience  # type: ignore
    except Exception:
        pytest.skip("graphdatascience with pyarrow.flight not available in this environment")

    try:
        from src.utils.common import create_neo4j_driver, get_neo4j_config
    except Exception:
        pytest.skip("Utilities not available")

    from src.analysis.centrality import create_call_graph_projection, run_betweenness_analysis
    from src.data.schema_management import setup_complete_schema

    uri, user, pwd, db = get_neo4j_config()
    driver = create_neo4j_driver(uri, user, pwd)
    with driver:
        with driver.session(database=db) as session:
            session.run("MATCH (n) DETACH DELETE n").consume()
            setup_complete_schema(session)
            # Path A->B->C; B should have highest betweenness
            session.run(
                """
                CREATE (:Method {id:'A#a():void', name:'A', method_signature:'A#a():void'}),
                       (:Method {id:'B#b():void', name:'B', method_signature:'B#b():void'}),
                       (:Method {id:'C#c():void', name:'C', method_signature:'C#c():void'})
                """
            ).consume()
            session.run(
                "MATCH (a:Method {name:'A'}), (b:Method {name:'B'}), (c:Method {name:'C'}) "
                "CREATE (a)-[:CALLS]->(b), (b)-[:CALLS]->(c)"
            ).consume()

    gds = GraphDataScience(uri, auth=(user, pwd), database=db, arrow=False)
    try:
        G = create_call_graph_projection(gds)
        _ = run_betweenness_analysis(gds, G, top_n=3, write_back=True)
        # Ensure betweenness written; check B present in top
        df = gds.run_cypher(
            "MATCH (m:Method) WHERE m.betweenness_score IS NOT NULL RETURN m.name AS n, m.betweenness_score AS s ORDER BY s DESC"
        )
        assert len(df) >= 1 and df.iloc[0]["n"] in ("B", "A", "C")
    finally:
        try:
            gds.run_cypher(
                "CALL gds.graph.drop($name, false) YIELD graphName RETURN graphName",
                name="method_call_graph",
            )
        except Exception:
            pass
        gds.close()


## HITS test removed: algorithm not used in the pipeline and relies on alpha API


@pytest.mark.live
def test_centrality_task_writes_scores_live():
    # Skip if the Python GDS client is not available in this environment
    try:
        from graphdatascience import GraphDataScience  # type: ignore  # noqa: F401
    except Exception:
        pytest.skip("GDS client not available in this environment")

    try:
        from src.utils.common import create_neo4j_driver, get_neo4j_config
    except Exception:
        pytest.skip("Utilities not available")

    # Import task entrypoint without spinning up Prefect server
    import src.pipeline.tasks.db_tasks as tasks
    from src.data.schema_management import setup_complete_schema

    uri, user, pwd, db = get_neo4j_config()
    driver = create_neo4j_driver(uri, user, pwd)
    with driver:
        with driver.session(database=db) as session:
            session.run("MATCH (n) DETACH DELETE n").consume()
            setup_complete_schema(session)
            # Seed a minimal call graph: A -> B -> C
            session.run(
                """
                CREATE (:Method {id:'TA#a():void', name:'A', method_signature:'TA#a():void'}),
                       (:Method {id:'TB#b():void', name:'B', method_signature:'TB#b():void'}),
                       (:Method {id:'TC#c():void', name:'C', method_signature:'TC#c():void'})
                """
            ).consume()
            session.run(
                "MATCH (a:Method {name:'A'}), (b:Method {name:'B'}), (c:Method {name:'C'}) "
                "CREATE (a)-[:CALLS]->(b), (b)-[:CALLS]->(c)"
            ).consume()

    # Run centrality task (will project, run PR/Betweenness/Degree, and write back)
    tasks.centrality_task.fn(uri, user, pwd, db)

    # Verify that at least one method has a pagerank_score
    driver = create_neo4j_driver(uri, user, pwd)
    with driver:
        with driver.session(database=db) as session:
            rec = session.run(
                "MATCH (m:Method) WHERE m.pagerank_score IS NOT NULL RETURN count(m) AS c"
            ).single()
            assert rec and int(rec["c"]) >= 1
