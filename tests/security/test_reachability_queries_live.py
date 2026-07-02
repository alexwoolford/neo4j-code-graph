#!/usr/bin/env python3
"""Live tests for the canned reachability query module.

Seeds a miniature but shape-accurate graph (CVE/AFFECTS/DEPENDS_ON/IMPORTS,
Methods with CALLS + CALLS_EXTERNAL, annotations, git history + CO_CHANGED)
and exercises every public function in src/security/reachability.py against a
real Neo4j (testcontainer via tests/conftest.py).
"""

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


# Method signatures used across assertions
ENTRY_SIG = "com.example.PaymentController#handle():void"
MID_SIG = "com.example.PaymentService#process():void"
FRONTIER_SIG = "com.example.JsonUtil#parse():void"
DIRECT_FRONTIER_SIG = "com.example.WebhookController#ingest():void"
LOW_FRONTIER_SIG = "com.example.LegacyJson#dump():void"
TEST_ENTRY_SIG = "com.example.JsonUtilTest#testParse():void"

FRONTIER_FILE = "src/main/java/com/example/JsonUtil.java"


def _seed_graph(session) -> None:
    session.run("MATCH (n) DETACH DELETE n").consume()

    # --- CVE 1: full chain -> REACHABLE ------------------------------------
    session.run(
        """
        MERGE (dep:ExternalDependency {package: 'com.fasterxml.jackson'})
        SET dep.group_id = 'com.fasterxml.jackson.core',
            dep.artifact_id = 'jackson-databind',
            dep.version = '2.9.10'
        MERGE (cve:CVE {id: 'CVE-2099-0001'})
        SET cve.cvss_score = 9.8, cve.severity = 'CRITICAL'
        MERGE (cve)-[:AFFECTS {confidence: 0.95, match_type: 'precise_gav'}]->(dep)
        MERGE (imp:Import {import_path: 'com.fasterxml.jackson.databind.ObjectMapper'})
        MERGE (imp)-[:DEPENDS_ON]->(dep)
        MERGE (f:File {path: $frontier_file})
        MERGE (f)-[:IMPORTS]->(imp)
        """,
        frontier_file=FRONTIER_FILE,
    ).consume()

    # Methods: entry -> mid -> frontier CALLS chain; frontier CALLS_EXTERNAL
    session.run(
        """
        UNWIND $methods AS m
        MERGE (mm:Method {method_signature: m.sig})
        SET mm.id = m.sig, mm.name = m.name, mm.file = m.file, mm.line = m.line,
            mm.is_public = m.is_public, mm.is_static = m.is_static,
            mm.is_test_method = m.is_test_method
        MERGE (ff:File {path: m.file})
        MERGE (ff)-[:DECLARES]->(mm)
        """,
        methods=[
            {
                "sig": ENTRY_SIG,
                "name": "handle",
                "file": "src/main/java/com/example/PaymentController.java",
                "line": 10,
                "is_public": True,
                "is_static": False,
                "is_test_method": False,
            },
            {
                "sig": MID_SIG,
                "name": "process",
                "file": "src/main/java/com/example/PaymentService.java",
                "line": 20,
                "is_public": True,
                "is_static": False,
                "is_test_method": False,
            },
            {
                "sig": FRONTIER_SIG,
                "name": "parse",
                "file": FRONTIER_FILE,
                "line": 42,
                "is_public": True,
                "is_static": False,
                "is_test_method": False,
            },
            {
                "sig": DIRECT_FRONTIER_SIG,
                "name": "ingest",
                "file": "src/main/java/com/example/WebhookController.java",
                "line": 15,
                "is_public": True,
                "is_static": False,
                "is_test_method": False,
            },
            {
                "sig": LOW_FRONTIER_SIG,
                "name": "dump",
                "file": "src/main/java/com/example/LegacyJson.java",
                "line": 7,
                "is_public": True,
                "is_static": False,
                "is_test_method": False,
            },
            {
                "sig": TEST_ENTRY_SIG,
                "name": "testParse",
                "file": "src/test/java/com/example/JsonUtilTest.java",
                "line": 30,
                "is_public": True,
                "is_static": False,
                "is_test_method": True,
            },
        ],
    ).consume()

    # Entry annotations: real entry + direct frontier + test entry
    session.run(
        """
        MERGE (a:Annotation {name: 'GetMapping'})
        WITH a
        UNWIND $sigs AS sig
        MATCH (m:Method {method_signature: sig})
        MERGE (m)-[:ANNOTATED]->(a)
        """,
        sigs=[ENTRY_SIG, DIRECT_FRONTIER_SIG, TEST_ENTRY_SIG],
    ).consume()

    # CALLS chain: entry -> mid -> frontier; entry -> lowFrontier;
    # testEntry -> frontier (1 hop, only visible with include_tests=True)
    session.run(
        """
        UNWIND $edges AS e
        MATCH (a:Method {method_signature: e[0]}), (b:Method {method_signature: e[1]})
        MERGE (a)-[:CALLS]->(b)
        """,
        edges=[
            [ENTRY_SIG, MID_SIG],
            [MID_SIG, FRONTIER_SIG],
            [ENTRY_SIG, LOW_FRONTIER_SIG],
            [TEST_ENTRY_SIG, FRONTIER_SIG],
        ],
    ).consume()

    # CALLS_EXTERNAL frontier edges: HIGH from frontier + direct frontier,
    # LOW from the legacy method (min_confidence_rank filter target).
    session.run(
        """
        MATCH (imp:Import {import_path: 'com.fasterxml.jackson.databind.ObjectMapper'})
        MATCH (hi:Method {method_signature: $frontier})
        MERGE (hi)-[:CALLS_EXTERNAL {method_name: 'readValue', target_class: 'ObjectMapper',
                                     call_type: 'instance', confidence: 'HIGH',
                                     confidence_rank: 3, call_count: 2}]->(imp)
        WITH imp
        MATCH (direct:Method {method_signature: $direct_frontier})
        MERGE (direct)-[:CALLS_EXTERNAL {method_name: 'readTree', target_class: 'ObjectMapper',
                                         call_type: 'instance', confidence: 'HIGH',
                                         confidence_rank: 3, call_count: 1}]->(imp)
        WITH imp
        MATCH (low:Method {method_signature: $low_frontier})
        MERGE (low)-[:CALLS_EXTERNAL {method_name: 'writeValue', target_class: 'ObjectMapper',
                                      call_type: 'instance', confidence: 'LOW',
                                      confidence_rank: 1, call_count: 1}]->(imp)
        """,
        frontier=FRONTIER_SIG,
        direct_frontier=DIRECT_FRONTIER_SIG,
        low_frontier=LOW_FRONTIER_SIG,
    ).consume()

    # --- CVE 2: dep imported but never called -> NO_FRONTIER ----------------
    session.run(
        """
        MERGE (dep2:ExternalDependency {package: 'org.apache.commons.lang3'})
        SET dep2.group_id = 'org.apache.commons',
            dep2.artifact_id = 'commons-lang3',
            dep2.version = '3.5'
        MERGE (cve2:CVE {id: 'CVE-2099-0002'})
        SET cve2.cvss_score = 8.1, cve2.severity = 'HIGH'
        MERGE (cve2)-[:AFFECTS {confidence: 0.9, match_type: 'precise_gav'}]->(dep2)
        MERGE (imp2:Import {import_path: 'org.apache.commons.lang3.StringUtils'})
        MERGE (imp2)-[:DEPENDS_ON]->(dep2)
        MERGE (f2:File {path: 'src/main/java/com/example/PaymentService.java'})
        MERGE (f2)-[:IMPORTS]->(imp2)
        """
    ).consume()

    # --- CVE 3: dep has no inbound DEPENDS_ON -> NOT_IMPORTED ---------------
    session.run(
        """
        MERGE (dep3:ExternalDependency {package: 'org.hsqldb'})
        SET dep3.group_id = 'org.hsqldb',
            dep3.artifact_id = 'hsqldb',
            dep3.version = '2.3.4'
        MERGE (cve3:CVE {id: 'CVE-2099-0003'})
        SET cve3.cvss_score = 7.5, cve3.severity = 'HIGH'
        MERGE (cve3)-[:AFFECTS {confidence: 0.85, match_type: 'precise_gav'}]->(dep3)
        """
    ).consume()

    # --- Git history + CO_CHANGED around the frontier file ------------------
    # alice: 3 commits, bob: 1 commit -> bus_factor 1 (3 of 4 >= 50%).
    session.run(
        """
        MERGE (alice:Developer {email: 'alice@example.com'}) SET alice.name = 'Alice'
        MERGE (bob:Developer {email: 'bob@example.com'}) SET bob.name = 'Bob'
        MERGE (f:File {path: $frontier_file})
        WITH alice, bob, f
        UNWIND $commits AS cm
        MERGE (c:Commit {sha: cm.sha}) SET c.date = datetime(cm.date)
        MERGE (fv:FileVer {sha: cm.sha, path: $frontier_file})
        MERGE (c)-[:CHANGED]->(fv)
        MERGE (fv)-[:OF_FILE]->(f)
        WITH alice, bob, c, cm
        FOREACH (_ IN CASE WHEN cm.author = 'alice' THEN [1] ELSE [] END |
            MERGE (alice)-[:AUTHORED]->(c))
        FOREACH (_ IN CASE WHEN cm.author = 'bob' THEN [1] ELSE [] END |
            MERGE (bob)-[:AUTHORED]->(c))
        """,
        frontier_file=FRONTIER_FILE,
        commits=[
            {"sha": "c1", "date": "2024-01-10T09:00:00Z", "author": "alice"},
            {"sha": "c2", "date": "2024-03-05T09:00:00Z", "author": "alice"},
            {"sha": "c3", "date": "2024-06-20T09:00:00Z", "author": "alice"},
            {"sha": "c4", "date": "2024-02-14T09:00:00Z", "author": "bob"},
        ],
    ).consume()

    # CO_CHANGED partners in canonical direction (f1.path < f2.path):
    # Alpha.java -> JsonUtil.java (frontier file on the RHS) and
    # JsonUtil.java -> PaymentService.java (frontier file on the LHS),
    # plus a sub-min_support partner that must be filtered out.
    session.run(
        """
        MERGE (f:File {path: $frontier_file})
        MERGE (alpha:File {path: 'src/main/java/com/example/Alpha.java'})
        MERGE (svc:File {path: 'src/main/java/com/example/PaymentService.java'})
        MERGE (noise:File {path: 'src/main/java/com/example/Zeta.java'})
        MERGE (alpha)-[cc1:CO_CHANGED]->(f) SET cc1.support = 6, cc1.confidence = 0.8
        MERGE (f)-[cc2:CO_CHANGED]->(svc) SET cc2.support = 3, cc2.confidence = 0.5
        MERGE (f)-[cc3:CO_CHANGED]->(noise) SET cc3.support = 1, cc3.confidence = 0.1
        """,
        frontier_file=FRONTIER_FILE,
    ).consume()


def _import_module():
    try:
        from src.security import reachability
    except Exception:
        from security import reachability  # type: ignore

    return reachability


def test_linked_cves_live():
    reach = _import_module()
    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as session:
            _seed_graph(session)
            rows = reach.linked_cves(session)
            assert {r["id"] for r in rows} == {
                "CVE-2099-0001",
                "CVE-2099-0002",
                "CVE-2099-0003",
            }
            first = rows[0]
            assert first["id"] == "CVE-2099-0001"  # highest CVSS first
            assert first["cvss_score"] == 9.8
            assert first["severity"] == "CRITICAL"
            assert first["group_id"] == "com.fasterxml.jackson.core"
            assert first["artifact_id"] == "jackson-databind"
            assert first["version"] == "2.9.10"
            assert first["affects_confidence"] == 0.95
            assert first["match_type"] == "precise_gav"

            # min_cvss filters
            high_only = reach.linked_cves(session, min_cvss=9.0)
            assert {r["id"] for r in high_only} == {"CVE-2099-0001"}


def test_frontier_for_cve_live():
    reach = _import_module()
    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as session:
            _seed_graph(session)
            rows = reach.frontier_for_cve(session, "CVE-2099-0001")
            sigs = {r["method_signature"] for r in rows}
            assert sigs == {FRONTIER_SIG, DIRECT_FRONTIER_SIG, LOW_FRONTIER_SIG}

            by_sig = {r["method_signature"]: r for r in rows}
            frontier = by_sig[FRONTIER_SIG]
            assert frontier["file"] == FRONTIER_FILE
            assert frontier["line"] == 42
            assert frontier["confidence_rank"] == 3
            assert frontier["confidence"] == "HIGH"
            evidence = frontier["evidence"]
            assert evidence and evidence[0]["import_path"] == (
                "com.fasterxml.jackson.databind.ObjectMapper"
            )
            assert evidence[0]["target_class"] == "ObjectMapper"
            assert evidence[0]["method_name"] == "readValue"
            assert evidence[0]["confidence"] == "HIGH"

            # min_confidence_rank excludes the LOW frontier
            filtered = reach.frontier_for_cve(session, "CVE-2099-0001", min_confidence_rank=2)
            assert {r["method_signature"] for r in filtered} == {
                FRONTIER_SIG,
                DIRECT_FRONTIER_SIG,
            }


def test_reachability_for_cve_live():
    reach = _import_module()
    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as session:
            _seed_graph(session)
            rows = reach.reachability_for_cve(session, "CVE-2099-0001")
            by_frontier = {r["frontier_method"]: r for r in rows}

            # entry -> mid -> frontier: min 2 hops through mid
            frontier = by_frontier[FRONTIER_SIG]
            assert frontier["min_hops"] == 2
            assert frontier["cve_id"] == "CVE-2099-0001"
            assert frontier["frontier_file"] == FRONTIER_FILE
            assert frontier["frontier_line"] == 42
            assert frontier["confidence_rank"] == 3
            assert frontier["confidence"] == "HIGH"
            routes = frontier["example_routes"]
            assert routes and routes[0]["entry"] == ENTRY_SIG
            assert routes[0]["hops"] == 2
            assert routes[0]["path"] == [ENTRY_SIG, MID_SIG, FRONTIER_SIG]
            assert frontier["evidence"][0]["method_name"] == "readValue"

            # hop 0: a frontier method that is itself an annotated entry
            direct = by_frontier[DIRECT_FRONTIER_SIG]
            assert direct["min_hops"] == 0
            assert direct["example_routes"][0]["path"] == [DIRECT_FRONTIER_SIG]

            # LOW frontier reachable at 1 hop with the default rank threshold
            low = by_frontier[LOW_FRONTIER_SIG]
            assert low["min_hops"] == 1
            assert low["confidence"] == "LOW"


def test_reachability_min_confidence_rank_filter_live():
    reach = _import_module()
    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as session:
            _seed_graph(session)
            rows = reach.reachability_for_cve(session, "CVE-2099-0001", min_confidence_rank=2)
            sigs = {r["frontier_method"] for r in rows}
            assert LOW_FRONTIER_SIG not in sigs
            assert sigs == {FRONTIER_SIG, DIRECT_FRONTIER_SIG}


def test_reachability_include_tests_live():
    reach = _import_module()
    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as session:
            _seed_graph(session)
            # Default: the annotated test method is NOT an entry, so the
            # frontier's best path stays entry -> mid -> frontier (2 hops).
            default_rows = reach.reachability_for_cve(session, "CVE-2099-0001")
            frontier = {r["frontier_method"]: r for r in default_rows}[FRONTIER_SIG]
            assert frontier["min_hops"] == 2
            entries = {route["entry"] for r in default_rows for route in r["example_routes"]}
            assert TEST_ENTRY_SIG not in entries

            # include_tests=True admits testEntry -> frontier (1 hop).
            with_tests = reach.reachability_for_cve(session, "CVE-2099-0001", include_tests=True)
            frontier = {r["frontier_method"]: r for r in with_tests}[FRONTIER_SIG]
            assert frontier["min_hops"] == 1
            assert frontier["example_routes"][0]["entry"] == TEST_ENTRY_SIG


def test_triage_summary_live():
    reach = _import_module()
    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as session:
            _seed_graph(session)
            triage = reach.triage_summary(session)
            by_id = {row["cve_id"]: row for row in triage["cves"]}
            assert by_id["CVE-2099-0001"]["status"] == "REACHABLE"
            assert by_id["CVE-2099-0001"]["reachable_frontier_count"] == 3
            assert by_id["CVE-2099-0001"]["min_hops"] == 0
            assert by_id["CVE-2099-0002"]["status"] == "NO_FRONTIER"
            assert by_id["CVE-2099-0002"]["import_count"] == 1
            assert by_id["CVE-2099-0003"]["status"] == "NOT_IMPORTED"
            assert by_id["CVE-2099-0003"]["import_count"] == 0

            summary = triage["summary"]
            assert summary["total"] == 3
            assert summary["reachable"] == 1
            assert summary["frontier_unreachable"] == 0
            assert summary["no_frontier"] == 1
            assert summary["not_imported"] == 1
            assert summary["triage_reduction_pct"] == pytest.approx(66.7, abs=0.1)

            # risk_threshold trims low-CVSS CVEs before classification
            high = reach.triage_summary(session, risk_threshold=9.0)
            assert high["summary"]["total"] == 1
            assert high["summary"]["reachable"] == 1
            assert high["summary"]["triage_reduction_pct"] == 0.0


def test_triage_frontier_unreachable_live():
    reach = _import_module()
    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as session:
            _seed_graph(session)
            # Cut every entry path to CVE-1's frontier: drop CALLS into the
            # 2-hop frontier and the low frontier, and un-annotate the direct
            # frontier + test entry.
            session.run("MATCH (:Method)-[r:CALLS]->(:Method) DELETE r").consume()
            session.run(
                """
                MATCH (m:Method)-[r:ANNOTATED]->(:Annotation)
                WHERE m.method_signature IN $sigs
                DELETE r
                """,
                sigs=[DIRECT_FRONTIER_SIG, TEST_ENTRY_SIG],
            ).consume()
            triage = reach.triage_summary(session)
            by_id = {row["cve_id"]: row for row in triage["cves"]}
            assert by_id["CVE-2099-0001"]["status"] == "FRONTIER_UNREACHABLE"
            assert by_id["CVE-2099-0001"]["frontier_method_count"] == 3
            assert triage["summary"]["frontier_unreachable"] == 1
            assert triage["summary"]["reachable"] == 0
            assert triage["summary"]["triage_reduction_pct"] == pytest.approx(100.0)


def test_blast_radius_ownership_live():
    reach = _import_module()
    driver, database = _get_driver_or_skip()
    with driver:
        with driver.session(database=database) as session:
            _seed_graph(session)
            result = reach.blast_radius_ownership(session, FRONTIER_FILE)

            partners = {p["path"]: p for p in result["co_changed_files"]}
            # Both canonical directions are found; sub-min_support noise is not.
            assert "src/main/java/com/example/Alpha.java" in partners
            assert "src/main/java/com/example/PaymentService.java" in partners
            assert "src/main/java/com/example/Zeta.java" not in partners
            assert result["co_change_count"] == 2
            alpha = partners["src/main/java/com/example/Alpha.java"]
            assert alpha["support"] == 6
            assert alpha["confidence"] == pytest.approx(0.8)
            # Ordered by support desc
            assert result["co_changed_files"][0]["path"] == ("src/main/java/com/example/Alpha.java")

            ownership = result["ownership"]
            committers = ownership["top_committers"]
            assert [c["email"] for c in committers] == [
                "alice@example.com",
                "bob@example.com",
            ]
            assert committers[0]["name"] == "Alice"
            assert committers[0]["commits"] == 3
            assert committers[0]["last_touched"].startswith("2024-06-20")
            assert ownership["total_commits"] == 4
            assert ownership["last_touched"].startswith("2024-06-20")
            # alice alone covers 3/4 >= 50%
            assert ownership["bus_factor"] == 1

            # top_committers limit applies to the list, not the bus factor
            top1 = reach.blast_radius_ownership(session, FRONTIER_FILE, top_committers=1)
            assert len(top1["ownership"]["top_committers"]) == 1
            assert top1["ownership"]["bus_factor"] == 1

            # min_support raises the partner bar
            strict = reach.blast_radius_ownership(session, FRONTIER_FILE, min_support=5)
            assert [p["path"] for p in strict["co_changed_files"]] == [
                "src/main/java/com/example/Alpha.java"
            ]
