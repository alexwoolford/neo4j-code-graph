from __future__ import annotations

import logging
from pathlib import Path

from src.analysis.centrality import (
    create_call_graph_projection as cent_create_graph,
)
from src.analysis.centrality import (
    run_betweenness_analysis as cent_betweenness,
)
from src.analysis.centrality import (
    run_degree_analysis as cent_degree,
)
from src.analysis.centrality import (
    run_pagerank_analysis as cent_pagerank,
)
from src.analysis.git_analysis import load_history
from src.analysis.similarity import (
    create_index as sim_create_index,
)
from src.analysis.similarity import (
    run_knn as sim_run_knn,
)
from src.analysis.similarity import (
    run_louvain as sim_run_louvain,
)
from src.analysis.temporal_analysis import run_coupling
from src.data.schema_management import setup_complete_schema
from src.pipeline.prefect_compat import get_run_logger, task
from src.security.cve_analysis import CVEAnalyzer
from src.utils.common import create_neo4j_driver, resolve_neo4j_args


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


@task(retries=1)
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
        from src.analysis.code_analysis import main as code_to_graph_main

        code_to_graph_main()
    finally:
        sys.argv = old_argv

    try:
        from graphdatascience import GraphDataScience as _GDS  # type: ignore

        _uri, _user, _pwd, _db = resolve_neo4j_args(uri, username, password, database)
        from src.constants import EMBEDDING_PROPERTY as _EMB

        gds = _GDS(_uri, auth=(_user, _pwd), database=_db, arrow=False)
        df = gds.run_cypher(f"MATCH (m:Method) WHERE m.{_EMB} IS NOT NULL RETURN count(m) AS c")
        count = int(df.iloc[0]["c"]) if not df.empty else 0
        logger.info("Methods with embeddings (%s): %d", _EMB, count)
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
    load_history(
        repo_url=repo_path,
        branch="master",
        uri=_uri,
        username=_user,
        password=_pwd,
        database=_db,
        csv_export=None,
        max_commits=None,
        skip_file_changes=False,
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
    _uri, _user, _pwd, _db = resolve_neo4j_args(uri, username, password, database)
    from graphdatascience import GraphDataScience as _GDS  # type: ignore

    gds = _GDS(_uri, auth=(_user, _pwd), database=_db, arrow=False)
    try:
        gds.run_cypher("RETURN 1")
        sim_create_index(gds)
        # Guard: only run when nodes with embeddings exist to avoid 'Node-Query returned no nodes'
        from src.constants import EMBEDDING_PROPERTY as _EMB

        df = gds.run_cypher(f"MATCH (m:Method) WHERE m.{_EMB} IS NOT NULL RETURN count(m) AS c")
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
    _uri, _user, _pwd, _db = resolve_neo4j_args(uri, username, password, database)
    from graphdatascience import GraphDataScience as _GDS  # type: ignore

    gds = _GDS(_uri, auth=(_user, _pwd), database=_db, arrow=False)
    try:
        gds.run_cypher("RETURN 1")
        # Guard: ensure similarity graph has nodes
        from src.constants import EMBEDDING_PROPERTY as _EMB

        df = gds.run_cypher(f"MATCH (m:Method) WHERE m.{_EMB} IS NOT NULL RETURN count(m) AS c")
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
        cve_data = analyzer.cve_manager.fetch_targeted_cves(  # type: ignore[attr-defined]
            api_key=api_key,
            search_terms=search_terms,
            max_results=2000,
            days_back=365,
            max_concurrency=None,
        )
        if cve_data:
            analyzer.create_vulnerability_graph(list(cve_data))  # type: ignore[arg-type]
            impact = analyzer.analyze_vulnerability_impact(risk_threshold=7.0, max_hops=4)
            analyzer.generate_impact_report(impact)
