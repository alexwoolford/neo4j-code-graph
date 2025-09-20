from __future__ import annotations

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


def test_knn_and_louvain_live():
    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as session:
            # Clean slate
            session.run("MATCH (n) DETACH DELETE n").consume()

            # Create a few Method nodes with tiny embeddings
            session.run(
                """
            CREATE (:Method {id:'m1', name:'M1', method_signature:'p.A#a()', embedding:[0.9, 0.1]}),
                   (:Method {id:'m2', name:'M2', method_signature:'p.B#b()', embedding:[0.85, 0.15]}),
                   (:Method {id:'m3', name:'M3', method_signature:'p.C#c()', embedding:[0.1, 0.9]})
            """
            ).consume()

            # Create vector index for embeddings
            session.run(
                """
            CREATE VECTOR INDEX method_embeddings IF NOT EXISTS
            FOR (m:Method) ON (m.embedding)
            OPTIONS {indexConfig: {
              `vector.dimensions`: 2,
              `vector.similarity_function`: 'cosine'
            }}
            """
            ).consume()
            session.run("CALL db.awaitIndexes()").consume()

            # Ensure GDS is available (emit version)
            session.run("CALL gds.version()").consume()

            # Project in-memory graph with node property 'embedding' using native projection
            session.run(
                "CALL gds.graph.drop('simGraph', false) YIELD graphName RETURN graphName"
            ).consume()
            session.run(
                """
            CALL gds.graph.project(
              'simGraph',
              ['Method'],
              { DECLARES: { type: 'DECLARES', orientation: 'UNDIRECTED' } },
              { nodeProperties: ['embedding'] }
            )
            """
            ).consume()

            # Run kNN write using embedding property
            session.run(
                """
            CALL gds.knn.write('simGraph', {
              nodeProperties:['embedding'], topK:1, similarityCutoff:0.0,
              writeRelationshipType:'SIMILAR', writeProperty:'score'
            })
            """
            ).consume()

            # Verify SIMILAR relationships exist
            rec = session.run("MATCH ()-[r:SIMILAR]->() RETURN count(r) AS c").single()
            assert rec and int(rec["c"]) >= 1

            # Build a similarity graph and run Louvain via GDS
            session.run(
                "CALL gds.graph.drop('simComm', false) YIELD graphName RETURN graphName"
            ).consume()
            session.run(
                """
                CALL gds.graph.project(
                  'simComm',
                  ['Method'],
                  { SIMILAR: { type: 'SIMILAR', orientation: 'UNDIRECTED' } }
                )
                """
            ).consume()

            session.run(
                "CALL gds.louvain.write('simComm', {writeProperty:'similarity_community'})"
            ).consume()

            # Verify at least one community assignment
            rec = session.run(
                "MATCH (m:Method) WHERE m.similarity_community IS NOT NULL RETURN count(m) AS c"
            ).single()
            assert rec and int(rec["c"]) >= 1

            # Cleanup in-memory graphs
            session.run(
                "CALL gds.graph.drop('simGraph', false) YIELD graphName RETURN graphName"
            ).consume()
            session.run(
                "CALL gds.graph.drop('simComm', false) YIELD graphName RETURN graphName"
            ).consume()


def test_similarity_module_sets_model_property_live():
    """Use our module functions with a real GDS client and assert s.model is set."""
    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as session:
            # Clean slate and create methods with 2D embeddings
            session.run("MATCH (n) DETACH DELETE n").consume()
            from src.constants import EMBEDDING_PROPERTY

            session.run(
                f"""
                CREATE (:Method {{id:'m1', name:'M1', method_signature:'q.A#a()', {EMBEDDING_PROPERTY}:[0.95, 0.05]}}),
                       (:Method {{id:'m2', name:'M2', method_signature:'q.B#b()', {EMBEDDING_PROPERTY}:[0.90, 0.10]}}),
                       (:Method {{id:'m3', name:'M3', method_signature:'q.C#c()', {EMBEDDING_PROPERTY}:[0.05, 0.95]}})
                """
            ).consume()

    # Use our similarity helpers with a real client
    try:
        from graphdatascience import GraphDataScience  # type: ignore
    except Exception:
        pytest.skip("graphdatascience with pyarrow.flight not available in this environment")

    from src.analysis.similarity import create_index, run_knn, run_louvain
    from src.utils.neo4j_utils import get_neo4j_config

    uri, user, pwd, db = get_neo4j_config()
    gds = GraphDataScience(uri, auth=(user, pwd), database=db, arrow=False)
    try:
        create_index(gds)
        run_knn(gds, top_k=1, cutoff=0.0)
        # s.model should be present on SIMILAR edges
        model_rows = gds.run_cypher("MATCH ()-[s:SIMILAR]->() RETURN count(s.model) AS c")
        assert int(model_rows.iloc[0]["c"]) >= 1
        run_louvain(gds, threshold=0.0, community_property="similarity_community")
        comm_rows = gds.run_cypher(
            "MATCH (m:Method) WHERE m.similarity_community IS NOT NULL RETURN count(m) AS c"
        )
        assert int(comm_rows.iloc[0]["c"]) >= 1
    finally:
        try:
            gds.run_cypher(
                "CALL gds.graph.drop($name, false) YIELD graphName RETURN graphName",
                name="methodGraph",
            )
            gds.run_cypher(
                "CALL gds.graph.drop($name, false) YIELD graphName RETURN graphName",
                name="similarityGraph",
            )
        except Exception:
            pass
        gds.close()
