from __future__ import annotations

import json
import re
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

    gradle_stdout: list[str] = []
    for c in cmds:
        try:
            logger.info("Resolving dependencies via: %s", " ".join(c))
            res = subprocess.run(c, cwd=repo_path, check=False, capture_output=True, text=True)
            # Capture Gradle output for parsing when we didn't write a file
            if "gradle" in c[0] or "gradlew" in c[0]:
                gradle_stdout.append(res.stdout or "")
        except Exception as e:  # pragma: no cover
            logger.warning("Dependency resolution command failed: %s", e)

    # Parse Maven output file if present
    gleaned_versions: dict[str, str] = {}
    mvn_out = Path(artifacts_dir) / "mvn_deps.txt"
    if mvn_out.exists():
        try:
            for line in mvn_out.read_text(encoding="utf-8").splitlines():
                # Typical: group:artifact:packaging:version:scope
                if ":" in line and not line.strip().startswith("#"):
                    parts = [p.strip() for p in line.split(":")]
                    if len(parts) >= 4:
                        g, a, _pkg, v = parts[0], parts[1], parts[2], parts[3]
                        if g and a and v and not any(t in v for t in (" ", "${")):
                            gleaned_versions[f"{g}:{a}"] = v
        except Exception as e:  # pragma: no cover
            logger.debug("Failed to parse mvn_deps.txt: %s", e)

    # Parse Gradle dependency tree output for resolved coordinates
    gradle_text = "\n".join(gradle_stdout)
    if gradle_text:
        try:
            # Lines often contain tokens like group:artifact:version or group:artifact:version -> resolved
            token_pattern = re.compile(
                r"\b([A-Za-z0-9_.-]+):([A-Za-z0-9_.-]+):([A-Za-z0-9+_.-]+)\b"
            )
            arrow_pattern = re.compile(
                r"\b([A-Za-z0-9_.-]+):([A-Za-z0-9_.-]+):([A-Za-z0-9+_.-]+)\s*->\s*([A-Za-z0-9+_.-]+)"
            )
            for line in gradle_text.splitlines():
                line = line.strip()
                if not line or line.startswith(("+---", "\\---", "|", "project ")):
                    # Still examine, as coords are on these lines too
                    pass
                # Prefer the resolved version on arrows
                m_arrow = arrow_pattern.search(line)
                if m_arrow:
                    g, a, _v, v2 = m_arrow.groups()
                    if g and a and v2:
                        gleaned_versions[f"{g}:{a}"] = v2
                        continue
                # Fallback: direct token
                m = token_pattern.search(line)
                if m:
                    g, a, v = m.groups()
                    if g and a and v and not v.endswith(":") and not v.startswith("project "):
                        gleaned_versions[f"{g}:{a}"] = v
        except Exception as e:  # pragma: no cover
            logger.debug("Failed to parse Gradle output: %s", e)

    if gleaned_versions:
        # Merge into artifacts dependencies.json so downstream write step sees versions
        try:
            existing: dict[str, str] = {}
            if out_deps.exists():
                existing = json.loads(out_deps.read_text(encoding="utf-8"))
            updates = 0
            for ga, ver in gleaned_versions.items():
                if not ver or "${" in ver:
                    continue
                # Write multiple keys that our writers consult
                g, a = ga.split(":", 1)
                existing[ga] = ver
                existing[f"{ga}:{ver}"] = ver
                existing[a] = ver
                existing[g] = ver
                updates += 1
            out_deps.write_text(json.dumps(existing, indent=2, sort_keys=True), encoding="utf-8")
            logger.info("Augmented dependencies.json with %d resolved coordinates", updates)
        except Exception as e:  # pragma: no cover
            logger.warning("Failed to augment dependencies.json: %s", e)

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
