#!/usr/bin/env python3

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


def test_knn_params_topk_and_cutoff_live():
    from src.data.schema_management import setup_complete_schema

    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as session:
            # Clean slate and ensure schema
            session.run("MATCH (n) DETACH DELETE n").consume()
            setup_complete_schema(session)

            # Seed: three methods with 2D embeddings
            session.run(
                """
                CREATE (:Method {id:'m1', name:'M1', method_signature:'p.A#a()', embedding:[0.95, 0.05]}),
                       (:Method {id:'m2', name:'M2', method_signature:'p.B#b()', embedding:[0.90, 0.10]}),
                       (:Method {id:'m3', name:'M3', method_signature:'p.C#c()', embedding:[0.05, 0.95]})
                """
            ).consume()

            # Vector index for 2-d embeddings
            session.run(
                """
                CREATE VECTOR INDEX method_embeddings_params IF NOT EXISTS
                FOR (m:Method) ON (m.embedding)
                OPTIONS {indexConfig: {
                  `vector.dimensions`: 2,
                  `vector.similarity_function`: 'cosine'
                }}
                """
            ).consume()
            session.run("CALL db.awaitIndexes()").consume()

            # GDS available?
            session.run("CALL gds.version()")

            # Project with node property
            session.run(
                "CALL gds.graph.drop('simParams', false) YIELD graphName RETURN graphName"
            ).consume()
            session.run(
                """
                CALL gds.graph.project(
                  'simParams',
                  ['Method'],
                  { DECLARES: { type: 'DECLARES', orientation: 'UNDIRECTED' } },
                  { nodeProperties: ['embedding'] }
                )
                """
            ).consume()

            # Baseline: topK=1, cutoff=0.0
            session.run(
                "CALL gds.knn.write('simParams', {nodeProperties:['embedding'], topK:1, similarityCutoff:0.0, writeRelationshipType:'SIMILAR', writeProperty:'score'})"
            ).consume()
            c1 = session.run("MATCH ()-[r:SIMILAR]->() RETURN count(r) AS c").single()
            count_top1 = int(c1["c"]) if c1 else 0
            assert count_top1 > 0

            # Clear relationships
            session.run("MATCH ()-[r:SIMILAR]->() DELETE r").consume()

            # topK=2, same cutoff
            session.run(
                "CALL gds.knn.write('simParams', {nodeProperties:['embedding'], topK:2, similarityCutoff:0.0, writeRelationshipType:'SIMILAR', writeProperty:'score'})"
            ).consume()
            c2 = session.run("MATCH ()-[r:SIMILAR]->() RETURN count(r) AS c").single()
            count_top2 = int(c2["c"]) if c2 else 0
            assert count_top2 >= count_top1

            # Clear relationships
            session.run("MATCH ()-[r:SIMILAR]->() DELETE r").consume()

            # High cutoff reduces edges
            session.run(
                "CALL gds.knn.write('simParams', {nodeProperties:['embedding'], topK:2, similarityCutoff:0.995, writeRelationshipType:'SIMILAR', writeProperty:'score'})"
            ).consume()
            c3 = session.run("MATCH ()-[r:SIMILAR]->() RETURN count(r) AS c").single()
            count_cut_high = int(c3["c"]) if c3 else 0
            assert count_cut_high < count_top2

            # Cleanup
            session.run(
                "CALL gds.graph.drop('simParams', false) YIELD graphName RETURN graphName"
            ).consume()
