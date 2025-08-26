from __future__ import annotations

from pathlib import Path

from prefect import get_run_logger, task

from src.analysis.centrality import main as centrality_main
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
from src.security.cve_analysis import main as cve_main
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
    logger = get_run_logger()
    logger.info("Setting up database schema...")
    _uri, _user, _pwd, _db = resolve_neo4j_args(uri, username, password, database)
    with create_neo4j_driver(_uri, _user, _pwd) as driver:
        with driver.session(database=_db) as session:  # type: ignore[reportUnknownMemberType]
            setup_complete_schema(session)


@task(retries=0)
def selective_cleanup_task(
    uri: str | None, username: str | None, password: str | None, database: str | None
) -> None:
    logger = get_run_logger()
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
    logger = get_run_logger()
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
    logger = get_run_logger()
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
    logger = get_run_logger()
    logger.info("Running similarity (kNN + optional Louvain)")
    _uri, _user, _pwd, _db = resolve_neo4j_args(uri, username, password, database)
    # Use direct GDS calls to avoid CLI shims
    from graphdatascience import GraphDataScience as _GDS  # type: ignore

    gds = _GDS(_uri, auth=(_user, _pwd), database=_db, arrow=False)
    try:
        gds.run_cypher("RETURN 1")
        sim_create_index(gds)
        sim_run_knn(gds, top_k=5, cutoff=0.8)
    finally:
        gds.close()


@task(retries=1)
def louvain_task(
    uri: str | None, username: str | None, password: str | None, database: str | None
) -> None:
    logger = get_run_logger()
    logger.info("Running community detection (Louvain)")
    _uri, _user, _pwd, _db = resolve_neo4j_args(uri, username, password, database)
    from graphdatascience import GraphDataScience as _GDS  # type: ignore

    gds = _GDS(_uri, auth=(_user, _pwd), database=_db, arrow=False)
    try:
        gds.run_cypher("RETURN 1")
        sim_run_louvain(gds, threshold=0.8)
    finally:
        gds.close()


@task(retries=1)
def centrality_task(
    uri: str | None, username: str | None, password: str | None, database: str | None
) -> None:
    logger = get_run_logger()
    logger.info("Running centrality analysis")
    base = [
        "prog",
        "--algorithms",
        "pagerank",
        "betweenness",
        "degree",
        "--top-n",
        "15",
        "--write-back",
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
        centrality_main()
    finally:
        sys.argv = old_argv


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
    if not os.getenv("NVD_API_KEY"):
        logger.warning("NVD_API_KEY not set; skipping CVE analysis")
        return
    base = ["prog", "--risk-threshold", "7.0", "--max-hops", "4"]
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
        cve_main()
    finally:
        sys.argv = old_argv
