from __future__ import annotations

import tempfile
from importlib import import_module
from pathlib import Path

from prefect import get_run_logger, task

try:
    code_to_graph_main = import_module("src.analysis.code_analysis").main  # type: ignore[attr-defined]
except Exception:  # pragma: no cover - installed package execution path
    code_to_graph_main = import_module("analysis.code_analysis").main  # type: ignore[attr-defined]


@task(retries=1)
def clone_repo_task(repo_url: str) -> str:
    logger = get_run_logger()
    temp_dir = tempfile.mkdtemp()
    logger.info("Cloning %s into %s", repo_url, temp_dir)
    import git

    git.Repo.clone_from(repo_url, temp_dir)
    return temp_dir


@task(retries=1)
def extract_code_task(repo_path: str, out_dir: str) -> str:
    logger = get_run_logger()
    logger.info("Extracting code structure from %s", repo_path)
    out_files = str(Path(out_dir) / "files_data.json")
    out_deps = str(Path(out_dir) / "dependencies.json")
    base = [
        "prog",
        repo_path,
        "--skip-embed",
        "--skip-db",
        "--out-files-data",
        out_files,
        "--out-dependencies",
        out_deps,
    ]
    import sys

    old_argv = sys.argv
    try:
        sys.argv = base
        code_to_graph_main()
    finally:
        sys.argv = old_argv
    return out_dir


@task(retries=1)
def resolve_build_dependencies_task(repo_path: str, artifacts_dir: str) -> str:
    """Optional: run Maven/Gradle to resolve full dependency versions and update artifacts.

    This task is safe to skip; when enabled it attempts to call the repo's build tool to
    generate a comprehensive dependency report (including test scope) and persists an
    enriched dependency_versions JSON alongside the artifacts.
    """
    logger = get_run_logger()
    out_deps = Path(artifacts_dir) / "dependencies.json"
    if not out_deps.exists():
        logger.info("No dependencies.json found at %s; skipping build-based resolution", out_deps)
        return artifacts_dir

    repo = Path(repo_path)
    mvn = repo / "mvnw"
    gradlew = repo / "gradlew"
    have_mvn = (repo / "pom.xml").exists() and (mvn.exists() or True)
    have_gradle = any(repo.rglob("build.gradle*")) and (gradlew.exists() or True)

    # Best-effort: prefer wrapper if present; else rely on system mvn/gradle
    cmds: list[list[str]] = []
    if have_mvn:
        cmd = [str(mvn)] if mvn.exists() else ["mvn"]
        cmds.append(
            cmd
            + [
                "-q",
                "-DincludeScope=test",
                "dependency:list",
                f"-DoutputFile={artifacts_dir}/mvn_deps.txt",
            ]
        )
    if have_gradle:
        gcmd = [str(gradlew)] if gradlew.exists() else ["gradle"]
        cmds.append(gcmd + ["-q", "dependencies", "--configuration", "testRuntimeClasspath"])

    import subprocess

    for c in cmds:
        try:
            logger.info("Resolving dependencies via: %s", " ".join(c))
            subprocess.run(c, cwd=repo_path, check=False, capture_output=True)
        except Exception as e:  # pragma: no cover
            logger.warning("Dependency resolution command failed: %s", e)

    # Re-extract enriched dependencies using our enhanced extractor, which also considers lockfiles
    base = [
        "prog",
        repo_path,
        "--skip-embed",
        "--skip-db",
        "--in-files-data",
        str(Path(artifacts_dir) / "files_data.json"),
        "--out-dependencies",
        str(out_deps),
    ]
    import sys

    old_argv = sys.argv
    try:
        sys.argv = base
        code_to_graph_main()
    finally:
        sys.argv = old_argv
    return artifacts_dir


@task(retries=1)
def embed_files_task(repo_path: str, artifacts_dir: str) -> str:
    logger = get_run_logger()
    logger.info("Computing file embeddings for %s", repo_path)
    in_files = str(Path(artifacts_dir) / "files_data.json")
    out_file_emb = str(Path(artifacts_dir) / "file_embeddings.npy")
    base = [
        "prog",
        repo_path,
        "--skip-db",
        "--embed-target",
        "files",
        "--in-files-data",
        in_files,
        "--out-file-embeddings",
        out_file_emb,
    ]
    import sys

    old_argv = sys.argv
    try:
        sys.argv = base
        code_to_graph_main()
    finally:
        sys.argv = old_argv
    return artifacts_dir


@task(retries=0)
def cleanup_artifacts_task(artifacts_dir: str) -> None:
    logger = get_run_logger()
    try:
        import shutil

        shutil.rmtree(artifacts_dir, ignore_errors=True)
        logger.info("Cleaned up artifacts directory: %s", artifacts_dir)
    except Exception as e:  # pragma: no cover - non-critical cleanup
        logger.warning("Failed to remove artifacts directory %s: %s", artifacts_dir, e)


@task(retries=1)
def embed_methods_task(repo_path: str, artifacts_dir: str) -> str:
    logger = get_run_logger()
    logger.info("Computing method embeddings for %s", repo_path)
    in_files = str(Path(artifacts_dir) / "files_data.json")
    out_method_emb = str(Path(artifacts_dir) / "method_embeddings.npy")
    base = [
        "prog",
        repo_path,
        "--skip-db",
        "--embed-target",
        "methods",
        "--in-files-data",
        in_files,
        "--out-method-embeddings",
        out_method_emb,
    ]
    import sys

    old_argv = sys.argv
    try:
        sys.argv = base
        code_to_graph_main()
    finally:
        sys.argv = old_argv
    return artifacts_dir
