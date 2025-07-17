import sys
import types
from unittest import mock
from pathlib import Path
import tempfile

# Provide stub modules for heavy dependencies before importing the module under test
sys.modules['transformers'] = types.ModuleType('transformers')
sys.modules['transformers'].AutoTokenizer = object
sys.modules['transformers'].AutoModel = object

sys.modules['neo4j'] = types.ModuleType('neo4j')
sys.modules['neo4j'].GraphDatabase = mock.MagicMock()
sys.modules['dotenv'] = types.ModuleType('dotenv')
sys.modules['dotenv'].load_dotenv = lambda override=True: None

sys.modules['torch'] = types.ModuleType('torch')
class _NoGrad:
    def __enter__(self):
        pass
    def __exit__(self, exc_type, exc, tb):
        pass
sys.modules['torch'].no_grad = lambda: _NoGrad()

import code_to_graph


def test_process_java_file_runs_expected_queries():
    java_code = """public class Test {\n    public void foo() {}\n}\n"""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = Path(tmpdir) / "Test.java"
        file_path.write_text(java_code)

        session = mock.MagicMock()
        with mock.patch.object(code_to_graph, 'compute_embedding', return_value=[0]*code_to_graph.EMBEDDING_DIM):
            code_to_graph.process_java_file(file_path, None, None, session, Path(tmpdir))

        # Expect two Cypher queries: one for File node and one for Method node
        assert session.run.call_count == 2
        file_query = session.run.call_args_list[0].args[0]
        method_query = session.run.call_args_list[1].args[0]
        assert "MERGE (f:File" in file_query
        assert "MERGE (m:Method" in method_query
