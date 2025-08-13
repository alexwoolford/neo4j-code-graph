def test_degree_query_shape():
    from src.analysis.centrality import run_degree_analysis

    class FakeGDS:
        def run_cypher(self, query, params=None):  # minimal shape
            import pandas as pd

            # Return a tiny, deterministic frame mimicking Neo4j results
            data = [
                {
                    "nodeId": 1,
                    "method_name": "a",
                    "class_name": "C",
                    "file": "F",
                    "out_degree": 1,
                    "in_degree": 2,
                    "total_degree": 3,
                },
                {
                    "nodeId": 2,
                    "method_name": "b",
                    "class_name": "C",
                    "file": "F",
                    "out_degree": 0,
                    "in_degree": 1,
                    "total_degree": 1,
                },
            ]
            return pd.DataFrame(data)

    fake_gds = FakeGDS()
    result = run_degree_analysis(fake_gds, graph=None, top_n=2, write_back=False)
    assert not result.empty
    assert {
        "nodeId",
        "method_name",
        "class_name",
        "file",
        "out_degree",
        "in_degree",
        "total_degree",
    }.issubset(result.columns)
