from __future__ import annotations

import logging
from importlib import import_module
from pathlib import Path

from prefect import get_run_logger, task

try:
    _centrality = import_module("src.analysis.centrality")
    _git_analysis = import_module("src.analysis.git_analysis")
    _similarity = import_module("src.analysis.similarity")
    _temporal = import_module("src.analysis.temporal_analysis")
    _schema = import_module("src.data.schema_management")
    _cve = import_module("src.security.cve_analysis")
    _common = import_module("src.utils.common")
except Exception:  # pragma: no cover - installed package execution path
    _centrality = import_module("analysis.centrality")
    _git_analysis = import_module("analysis.git_analysis")
    _similarity = import_module("analysis.similarity")
    _temporal = import_module("analysis.temporal_analysis")
    _schema = import_module("data.schema_management")
    _cve = import_module("security.cve_analysis")
    _common = import_module("utils.common")
try:
    _caps_utils = import_module("src.utils.neo4j_utils")
except Exception:  # pragma: no cover
    _caps_utils = import_module("utils.neo4j_utils")

cent_create_graph = _centrality.create_call_graph_projection
cent_betweenness = _centrality.run_betweenness_analysis
cent_degree = _centrality.run_degree_analysis
cent_pagerank = _centrality.run_pagerank_analysis
load_history = _git_analysis.load_history
sim_create_index = _similarity.create_index
sim_run_knn = _similarity.run_knn
sim_run_louvain = _similarity.run_louvain
run_coupling = _temporal.run_coupling
setup_complete_schema = _schema.setup_complete_schema
CVEAnalyzer = _cve.CVEAnalyzer
create_neo4j_driver = _common.create_neo4j_driver
resolve_neo4j_args = _common.resolve_neo4j_args


def _build_args(base: list[str], overrides: dict[str, object] | None = None) -> list[str]:
    args = list(base)
    if overrides:
        for key, value in overrides.items():
            if isinstance(value, bool):
                if value:
                    args.append(str(key))
            else:
                args.extend([str(key), str(value)])
    return args


def _should_run_gds(
    uri: str | None,
    username: str | None,
    password: str | None,
    database: str | None,
    logger: logging.Logger,
) -> bool:
    """Return True if GDS is available on the target DB and minimal projection works.

    Skips gracefully and logs a clear message otherwise (works for AuraDB, AuraDS, self-managed).
    """
    try:
        _uri, _user, _pwd, _db = resolve_neo4j_args(uri, username, password, database)
        from contextlib import contextmanager

        @contextmanager
        def _session():
            drv = create_neo4j_driver(_uri, _user, _pwd)
            try:
                with drv.session(database=_db) as s:
                    yield s
            finally:
                try:
                    drv.close()
                except Exception:
                    pass

        with _session() as s:  # type: ignore[reportUnknownMemberType]
            caps = _caps_utils.check_capabilities(s)
            gds = caps.get("gds", {}) if isinstance(caps, dict) else {}
            available = bool(getattr(gds, "get", lambda *_: False)("available"))  # type: ignore[attr-defined]
            projection_ok = bool(getattr(gds, "get", lambda *_: False)("projection_ok"))  # type: ignore[attr-defined]
            if not available:
                logger.warning(
                    "GDS not available on target DB; skipping GDS tasks (use AuraDS or install GDS)"
                )
                return False
            if not projection_ok:
                # Proceed: tasks have their own guards (embedding/CALLS checks). Probe can be flaky on empty graphs.
                logger.info(
                    "GDS available but projection probe failed; proceeding with GDS tasks; task-level guards apply"
                )
            return True
    except Exception as e:  # noqa: BLE001
        logger.warning("Could not verify GDS capabilities; skipping GDS tasks: %s", e)
        return False


@task(retries=1, retry_delay_seconds=5)
def setup_schema_task(
    uri: str | None, username: str | None, password: str | None, database: str | None
) -> None:
    try:
        logger = get_run_logger()
    except Exception:
        logger = logging.getLogger(__name__)
    logger.info("Setting up database schema...")
    _uri, _user, _pwd, _db = resolve_neo4j_args(uri, username, password, database)
    with create_neo4j_driver(_uri, _user, _pwd) as driver:
        with driver.session(database=_db) as session:  # type: ignore[reportUnknownMemberType]
            setup_complete_schema(session)


@task(retries=0)
def selective_cleanup_task(
    uri: str | None, username: str | None, password: str | None, database: str | None
) -> None:
    try:
        logger = get_run_logger()
    except Exception:
        logger = logging.getLogger(__name__)
    logger.info("Selective cleanup before similarity/community stages...")
    try:
        from src.utils.cleanup import selective_cleanup as _sel  # type: ignore
    except Exception:  # pragma: no cover
        from utils.cleanup import selective_cleanup as _sel  # type: ignore
    _uri, _user, _pwd, _db = resolve_neo4j_args(uri, username, password, database)
    with create_neo4j_driver(_uri, _user, _pwd) as driver:
        with driver.session(database=_db) as session:  # type: ignore[reportUnknownMemberType]
            _sel(session, dry_run=False)


# Backward-compatible alias expected by some unit tests
cleanup_task = selective_cleanup_task


@task(retries=0)
def write_graph_task(
    repo_path: str,
    artifacts_dir: str,
    uri: str | None,
    username: str | None,
    password: str | None,
    database: str | None,
) -> None:
    try:
        logger = get_run_logger()
    except Exception:
        logger = logging.getLogger(__name__)
    logger.info("Writing extracted data and embeddings to Neo4j from %s", artifacts_dir)
    in_files = str(Path(artifacts_dir) / "files_data.json")
    in_deps = str(Path(artifacts_dir) / "dependencies.json")
    in_file_emb = str(Path(artifacts_dir) / "file_embeddings.npy")
    in_method_emb = str(Path(artifacts_dir) / "method_embeddings.npy")

    base = [
        "prog",
        repo_path,
        "--skip-embed",
        "--in-files-data",
        in_files,
        "--in-dependencies",
        in_deps,
        "--in-file-embeddings",
        in_file_emb,
        "--in-method-embeddings",
        in_method_emb,
    ]
    overrides: dict[str, object] = {}
    if uri:
        overrides["--uri"] = uri
    if username:
        overrides["--username"] = username
    if password:
        overrides["--password"] = password
    if database:
        overrides["--database"] = database
    import sys

    old_argv = sys.argv
    try:
        sys.argv = _build_args(base, overrides)
        try:
            _code_analysis = import_module("src.analysis.code_analysis")
        except Exception:  # pragma: no cover
            _code_analysis = import_module("analysis.code_analysis")
        try:
            _code_analysis.main()  # type: ignore[attr-defined]
        except ValueError as e:
            # Graceful fail-fast handling: show concise guidance without a long traceback
            msg = str(e).strip()
            if msg.startswith("Dependency resolution failed") or msg.startswith(
                "Unresolved external imports"
            ):
                logger.error("\n" + msg + "\n")
                return
            raise
    finally:
        sys.argv = old_argv

    try:
        from graphdatascience import GraphDataScience as _GDS  # type: ignore

        _uri, _user, _pwd, _db = resolve_neo4j_args(uri, username, password, database)
        try:
            _constants = import_module("src.constants")
        except Exception:  # pragma: no cover
            _constants = import_module("constants")
        _emb_name = _constants.EMBEDDING_PROPERTY

        gds = _GDS(_uri, auth=(_user, _pwd), database=_db, arrow=False)
        df = gds.run_cypher(
            f"MATCH (m:Method) WHERE m.{_emb_name} IS NOT NULL RETURN count(m) AS c"
        )
        count = int(df.iloc[0]["c"]) if not df.empty else 0
        logger.info("Methods with embeddings (%s): %d", _emb_name, count)
        gds.close()
    except Exception:
        pass


@task(retries=1)
def git_history_task(
    repo_path: str,
    uri: str | None,
    username: str | None,
    password: str | None,
    database: str | None,
) -> None:
    try:
        logger = get_run_logger()
    except Exception:
        logger = logging.getLogger(__name__)
    logger.info("Loading git history from %s", repo_path)
    _uri, _user, _pwd, _db = resolve_neo4j_args(uri, username, password, database)
    import os

    branch_env = os.getenv("CODE_GRAPH_BRANCH")
    branch = branch_env if branch_env else "master"
    load_history(
        repo_url=repo_path,
        branch=branch,
        uri=_uri,
        username=_user,
        password=_pwd,
        database=_db,
        csv_export=None,
        max_commits=None,
        skip_file_changes=False,  # Fixed: optimized relationship creation to avoid O(n²) performance
        file_changes_only=False,
    )


@task(retries=1)
def similarity_task(
    uri: str | None, username: str | None, password: str | None, database: str | None
) -> None:
    try:
        logger = get_run_logger()
    except Exception:
        logger = logging.getLogger(__name__)
    logger.info("Running similarity (kNN + optional Louvain)")
    if not _should_run_gds(uri, username, password, database, logger):
        return
    _uri, _user, _pwd, _db = resolve_neo4j_args(uri, username, password, database)
    from graphdatascience import GraphDataScience as _GDS  # type: ignore

    gds = _GDS(_uri, auth=(_user, _pwd), database=_db, arrow=False)
    try:
        gds.run_cypher("RETURN 1")
        sim_create_index(gds)
        # Guard: only run when nodes with embeddings exist
        try:
            _constants = import_module("src.constants")
        except Exception:  # pragma: no cover
            _constants = import_module("constants")
        _emb_name = _constants.EMBEDDING_PROPERTY

        df = gds.run_cypher(
            f"MATCH (m:Method) WHERE m.{_emb_name} IS NOT NULL RETURN count(m) AS c"
        )
        count = int(df.iloc[0]["c"]) if not df.empty else 0
        if count == 0:
            logger.info("No methods with embeddings present; skipping kNN")
            return
        sim_run_knn(gds, top_k=5, cutoff=0.8)
    finally:
        gds.close()


@task(retries=1)
def louvain_task(
    uri: str | None, username: str | None, password: str | None, database: str | None
) -> None:
    try:
        logger = get_run_logger()
    except Exception:
        logger = logging.getLogger(__name__)
    logger.info("Running community detection (Louvain)")
    if not _should_run_gds(uri, username, password, database, logger):
        return
    _uri, _user, _pwd, _db = resolve_neo4j_args(uri, username, password, database)
    from graphdatascience import GraphDataScience as _GDS  # type: ignore

    gds = _GDS(_uri, auth=(_user, _pwd), database=_db, arrow=False)
    try:
        gds.run_cypher("RETURN 1")
        # Guard: ensure similarity graph has nodes
        try:
            _constants = import_module("src.constants")
        except Exception:  # pragma: no cover
            _constants = import_module("constants")
        _emb_name = _constants.EMBEDDING_PROPERTY

        df = gds.run_cypher(
            f"MATCH (m:Method) WHERE m.{_emb_name} IS NOT NULL RETURN count(m) AS c"
        )
        count = int(df.iloc[0]["c"]) if not df.empty else 0
        if count == 0:
            logger.info("No methods with embeddings present; skipping Louvain")
            return
        sim_run_louvain(gds, threshold=0.8)
    finally:
        gds.close()


@task(retries=1)
def centrality_task(
    uri: str | None, username: str | None, password: str | None, database: str | None
) -> None:
    try:
        logger = get_run_logger()
    except Exception:
        logger = logging.getLogger(__name__)
    logger.info("Running centrality analysis")
    if not _should_run_gds(uri, username, password, database, logger):
        return
    _uri, _user, _pwd, _db = resolve_neo4j_args(uri, username, password, database)
    from graphdatascience import GraphDataScience as _GDS  # type: ignore

    gds = _GDS(_uri, auth=(_user, _pwd), database=_db, arrow=False)
    try:
        gds.run_cypher("RETURN 1")
        # Guard: ensure CALLS relationships exist
        rel_df = gds.run_cypher("MATCH ()-[r:CALLS]->() RETURN count(r) AS c")
        rel_count = int(rel_df.iloc[0]["c"]) if not rel_df.empty else 0
        if rel_count == 0:
            logger.info("No CALLS relationships present; skipping centrality")
            return
        graph = cent_create_graph(gds)
        cent_pagerank(gds, graph, top_n=15, write_back=True)
        cent_betweenness(gds, graph, top_n=15, write_back=True)
        cent_degree(gds, graph, top_n=15, write_back=True)
        try:
            graph.drop()
        except Exception:
            pass
    finally:
        gds.close()


@task(retries=1)
def calls_louvain_task(
    uri: str | None, username: str | None, password: str | None, database: str | None
) -> None:
    """Compute communities based on actual code dependencies.

    - Method-level Louvain on CALLS → write m.calls_community
    - Class-level Louvain on aggregated class dependencies → write c.class_calls_community
    """
    try:
        logger = get_run_logger()
    except Exception:
        logger = logging.getLogger(__name__)
    if not _should_run_gds(uri, username, password, database, logger):
        return
    _uri, _user, _pwd, _db = resolve_neo4j_args(uri, username, password, database)
    from graphdatascience import GraphDataScience as _GDS  # type: ignore

    gds = _GDS(_uri, auth=(_user, _pwd), database=_db, arrow=False)
    try:
        # Guard: ensure CALLS exist
        rel_df = gds.run_cypher("MATCH ()-[:CALLS]->() RETURN count(*) AS c")
        rel_count = int(rel_df.iloc[0]["c"]) if not rel_df.empty else 0
        if rel_count == 0:
            logger.info("No CALLS present; skipping calls-based Louvain")
            return

        # Method-level Louvain on CALLS (undirected for community structure)
        try:
            gds.graph.drop("G_METHOD_CALLS")
        except Exception:
            pass
        gds.graph.project("G_METHOD_CALLS", ["Method"], {"CALLS": {"orientation": "UNDIRECTED"}})
        gds.louvain.write("G_METHOD_CALLS", writeProperty="calls_community")
        try:
            gds.graph.drop("G_METHOD_CALLS")
        except Exception:
            pass

        # Class-level Louvain via Cypher projection of class-to-class edges derived from CALLS
        try:
            gds.graph.drop("G_CLASS_CALLS")
        except Exception:
            pass
        gds.run_cypher(
            "CALL gds.graph.project.cypher(\n"
            "  'G_CLASS_CALLS',\n"
            "  'MATCH (c:Class) RETURN id(c) AS id',\n"
            "  'MATCH (c1:Class)-[:CONTAINS_METHOD]->(:Method)-[:CALLS]->(:Method)<-[:CONTAINS_METHOD]-(c2:Class) WHERE c1<>c2 RETURN id(c1) AS source, id(c2) AS target'\n"
            ")"
        )
        gds.louvain.write("G_CLASS_CALLS", writeProperty="class_calls_community")
        try:
            gds.graph.drop("G_CLASS_CALLS")
        except Exception:
            pass
    finally:
        gds.close()


@task(retries=0)
def coupling_task(
    uri: str | None,
    username: str | None,
    password: str | None,
    database: str | None,
    min_support: int = 5,
    confidence_threshold: float = 0.6,
    create_relationships: bool = True,
) -> None:
    logger = get_run_logger()
    logger.info(
        "Running change coupling (min_support=%d, confidence>=%.2f)",
        min_support,
        confidence_threshold,
    )
    _uri, _user, _pwd, _db = resolve_neo4j_args(uri, username, password, database)
    with create_neo4j_driver(_uri, _user, _pwd) as driver:
        run_coupling(
            driver,
            database=_db,
            min_support=int(min_support),
            confidence_threshold=float(confidence_threshold),
            write=bool(create_relationships),
        )


@task(retries=0)
def cve_task(
    uri: str | None, username: str | None, password: str | None, database: str | None
) -> None:
    logger = get_run_logger()
    import os

    logger.info("Running CVE analysis (optional if NVD_API_KEY is present)")
    api_key = os.getenv("NVD_API_KEY")
    if not api_key:
        logger.warning("NVD_API_KEY not set; skipping CVE analysis")
        return
    _uri, _user, _pwd, _db = resolve_neo4j_args(uri, username, password, database)
    with create_neo4j_driver(_uri, _user, _pwd) as driver:
        analyzer = CVEAnalyzer(driver, _db)
        # Show cache, then fetch and build graph; rely on defaults for scope/limits
        analyzer.get_cache_status()
        deps_by_ecosystem, _langs = analyzer.extract_codebase_dependencies()
        search_terms = analyzer.create_universal_component_search_terms(deps_by_ecosystem)
        # Allow wider time window via env override (default 365)
        try:
            days_back_env = int(os.getenv("NVD_DAYS_BACK", "365"))
        except ValueError:
            days_back_env = 365

        cve_data = analyzer.cve_manager.fetch_targeted_cves(  # type: ignore[attr-defined]
            api_key=api_key,
            search_terms=search_terms,
            max_results=2000,
            days_back=days_back_env,
            max_concurrency=None,
        )
        if cve_data:
            # Create CVE nodes
            num_nodes = analyzer.create_vulnerability_graph(list(cve_data))  # type: ignore[arg-type]
            logger.info("Created %d CVE nodes", num_nodes)

            # Diagnostic: counts to ensure we're in the right database and that versions exist
            with driver.session(database=_db) as s:
                rec = s.run("MATCH (c:CVE) RETURN count(c) AS c").single()
                logger.info("CVE nodes currently in DB: %s", (rec["c"] if rec else 0))
                rec2 = s.run(
                    "MATCH (e:ExternalDependency) "
                    "RETURN count(e) AS total, "
                    "sum(CASE WHEN e.version IS NOT NULL AND e.version <> 'unknown' THEN 1 ELSE 0 END) AS versioned"
                ).single()
                if rec2:
                    logger.info(
                        "ExternalDependency totals: total=%s, versioned=%s",
                        rec2.get("total"),
                        rec2.get("versioned"),
                    )

            # Link CVEs strictly to versioned dependencies
            try:
                num_links = analyzer._link_cves_to_dependencies(list(cve_data))  # type: ignore[arg-type]
                logger.info("Created %d AFFECTS relationships", num_links)
            except Exception as link_err:
                logger.warning("Linking failed: %s", link_err)

            # Impact analysis (HIGH and above by default)
            impact = analyzer.analyze_vulnerability_impact(risk_threshold=7.0, max_hops=4)
            analyzer.generate_impact_report(impact)
