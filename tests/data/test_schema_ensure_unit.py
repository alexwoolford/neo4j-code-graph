#!/usr/bin/env python3


def test_ensure_constraints_exist_or_fail_creates_when_missing():
    from src.data.schema_management import ensure_constraints_exist_or_fail

    # Fake session with simple behavior for SHOW/CREATE calls
    class FakeSession:
        def __init__(self):
            self.created = []
            self.phase = 0

        def run(self, query, **_k):
            if query.strip().upper().startswith("SHOW CONSTRAINTS"):
                # First call: return empty -> missing
                # Second call: return a subset including required names
                if self.phase == 0:
                    self.phase = 1
                    return []
                else:
                    # Simulate presence of a few required names; suffices for function logic
                    return [
                        {
                            "name": n,
                            "type": "UNIQUENESS",
                            "entityType": "NODE",
                            "labelsOrTypes": ["X"],
                            "properties": ["p"],
                        }
                        for n in [
                            "directory_path",
                            "file_path",
                            "class_name_file",
                            "interface_name_file",
                            "method_signature_unique",
                            "commit_sha",
                            "developer_email",
                            "file_ver_sha_path",
                            "import_path",
                            "cve_id_unique",
                        ]
                    ]
            elif query.strip().upper().startswith("CREATE "):
                self.created.append(query)
                return None
            return None

    session = FakeSession()
    ensure_constraints_exist_or_fail(session)
    # Should have attempted some creations, but not raise since second SHOW returns all
    assert len(session.created) > 0
