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
            session.run("CALL db.awaitIndex('method_embeddings')").consume()

            # Ensure GDS is available (emit version)
            session.run("CALL gds.version()").consume()

            # Project in-memory graph with node property 'embedding' using native projection
            session.run("CALL gds.graph.drop('simGraph', false)").consume()
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
            session.run("CALL gds.graph.drop('simComm', false)").consume()
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
                "CALL gds.louvain.write('simComm', {writeProperty:'similarityCommunity'})"
            ).consume()

            # Verify at least one community assignment
            rec = session.run(
                "MATCH (m:Method) WHERE m.similarityCommunity IS NOT NULL RETURN count(m) AS c"
            ).single()
            assert rec and int(rec["c"]) >= 1

            # Cleanup in-memory graphs
            session.run("CALL gds.graph.drop('simGraph', false)").consume()
            session.run("CALL gds.graph.drop('simComm', false)").consume()
