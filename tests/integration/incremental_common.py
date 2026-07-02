"""Shared helpers for WP4 incremental-ingest live tests.

Not a test module (no ``test_`` prefix) — imported by the equivalence,
footprint and provenance live tests.

The correctness invariant these helpers support:

    full_ingest(HEAD)  ==  full_ingest(BASE); incremental(BASE -> HEAD)

compared as canonical multisets via :func:`snapshot_graph`, which keys nodes by
their natural key (never by analytics scores / community ids / provenance) and
relationships by ``(type, src-key, dst-key)``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Git fixture helpers
# ---------------------------------------------------------------------------


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "dev@example.com")
    git(repo, "config", "user.name", "Dev")
    git(repo, "config", "commit.gpgsign", "false")


def write(repo: Path, rel: str, content: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def remove(repo: Path, rel: str) -> None:
    (repo / rel).unlink()


def commit_all(repo: Path, msg: str) -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)
    return git(repo, "rev-parse", "HEAD")


def checkout(repo: Path, ref: str) -> None:
    git(repo, "checkout", "-q", ref)


# ---------------------------------------------------------------------------
# Extraction / ingest helpers (production code paths)
# ---------------------------------------------------------------------------


def extract_all(repo_root: Path) -> list[dict[str, Any]]:
    """Extract every Java file in the working tree (production extractor)."""
    from src.analysis.extractor import extract_files_concurrently, list_java_files
    from src.analysis.parser import extract_file_data

    java = list_java_files(repo_root)
    files_data, _errors = extract_files_concurrently(java, repo_root, extract_file_data, 4)
    return files_data


def extract_subset(repo_root: Path, rel_paths: list[str]) -> list[dict[str, Any]]:
    """Extract only the given repo-relative Java files (subset extract)."""
    from src.analysis.extractor import extract_files_concurrently
    from src.analysis.parser import extract_file_data

    paths = [repo_root / r for r in rel_paths if (repo_root / r).exists()]
    files_data, _errors = extract_files_concurrently(paths, repo_root, extract_file_data, 4)
    return files_data


def _git_ingest(driver: Any, database: str, repo_root: Path, since_sha: str | None) -> None:
    from src.analysis.git_bulk_writer import bulk_load_to_neo4j
    from src.analysis.git_dataframes import create_dataframes
    from src.analysis.git_reader import extract_git_history

    rev_range = f"{since_sha}..HEAD" if since_sha else None
    commits, changes = extract_git_history(repo_root, "HEAD", None, rev_range=rev_range)
    if not commits:
        # Empty incremental range (no new commits) — nothing to load.
        return
    cdf, ddf, fdf, fcdf = create_dataframes(commits, changes)
    bulk_load_to_neo4j(cdf, ddf, fdf, fcdf, driver, database, False, False)


def wipe(session: Any) -> None:
    session.run("MATCH (n) DETACH DELETE n").consume()
    try:
        from src.data.schema_management import setup_complete_schema

        setup_complete_schema(session)
    except Exception:
        pass


def full_ingest(driver: Any, database: str, repo_root: Path) -> None:
    """Full ingest of the working tree at the current checkout: code + git."""
    from src.data.graph_writer import bulk_create_nodes_and_relationships

    files_data = extract_all(repo_root)
    with driver.session(database=database) as session:
        bulk_create_nodes_and_relationships(session, files_data, dependency_versions={})
    _git_ingest(driver, database, repo_root, since_sha=None)


def incremental_ingest(
    driver: Any,
    database: str,
    repo_root: Path,
    since_sha: str,
) -> tuple[list[str], list[str]]:
    """Incremental patch of the current checkout against ``since_sha``.

    Runs the real delta detection + footprint reconcile + subset write + the
    incremental (since_sha..HEAD) git history. Returns ``(changed, deleted)``.
    """
    from src.analysis.delta import changed_and_deleted, diff_changed_files
    from src.data.incremental import patch_changed_files

    delta = diff_changed_files(repo_root, since_sha, "HEAD")
    changed, deleted = changed_and_deleted(delta)
    files_data = extract_subset(repo_root, changed)
    with driver.session(database=database) as session:
        patch_changed_files(
            session,
            str(repo_root),
            files_data,
            changed,
            deleted,
            dependency_versions={},
        )
    _git_ingest(driver, database, repo_root, since_sha=since_sha)
    return changed, deleted


# ---------------------------------------------------------------------------
# Canonical graph snapshot
# ---------------------------------------------------------------------------

NODE_KEYS: dict[str, tuple[str, ...]] = {
    "Method": ("method_signature",),
    "Parameter": ("method_signature", "index"),
    "Field": ("owner_name", "name", "file"),
    "Class": ("name", "file"),
    "Interface": ("name", "file"),
    "File": ("path",),
    "Directory": ("path",),
    "Package": ("name",),
    "Import": ("import_path",),
    "ExternalDependency": ("group_id", "artifact_id", "version", "package"),
    "Annotation": ("name",),
    "Exception": ("name",),
    "Doc": ("id",),
    "Commit": ("sha",),
    "Developer": ("email",),
    "FileVer": ("sha", "path"),
}

# Highest-priority label wins when a node carries several (e.g. Class:Record).
_PRIORITY = [
    "Method",
    "Parameter",
    "Field",
    "Class",
    "Interface",
    "File",
    "Directory",
    "Package",
    "Import",
    "ExternalDependency",
    "Annotation",
    "Exception",
    "Doc",
    "Commit",
    "Developer",
    "FileVer",
]

# Provenance nodes are excluded from the invariant (they are metadata, not the
# code/git subgraph). Their relationships (HAS_INGEST) drop out too because an
# endpoint resolves to None.
_PROVENANCE_LABELS = {"Repository", "Ingest"}


def _nid(labels: Any, props: dict[str, Any]) -> str | None:
    label_set = set(labels)
    if label_set & _PROVENANCE_LABELS:
        return None
    for lab in _PRIORITY:
        if lab in label_set:
            keyvals = "|".join(str(props.get(k)) for k in NODE_KEYS[lab])
            return f"{lab}::{keyvals}"
    return None


def snapshot_graph(session: Any) -> dict[str, list[str]]:
    """Return canonical sorted multisets of nodes and relationships.

    Excluded from the comparison (per the WP4 invariant):
      - analytics float scores (pagerank/degree/betweenness) — node props, never
        part of a natural key.
      - Louvain community ids (calls_community / class_calls_community) — ditto.
      - CO_CHANGED temporal coupling — derived; not materialized by these tests.
      - Ingest / Repository provenance nodes and their relationships.
      - Method line numbers, complexity, and every non-key property.

    The documented globally-unique-name CALLS-fallback exception is avoided by
    construction in the fixtures (distinct names; cross-file calls target stable
    methods resolved by exact class match).
    """
    nodes: list[str] = []
    for rec in session.run("MATCH (n) RETURN labels(n) AS l, properties(n) AS p"):
        nid = _nid(rec["l"], rec["p"])
        if nid is not None:
            nodes.append(nid)

    rels: list[str] = []
    for rec in session.run(
        "MATCH (a)-[r]->(b) "
        "RETURN type(r) AS t, labels(a) AS la, properties(a) AS pa, "
        "labels(b) AS lb, properties(b) AS pb"
    ):
        a = _nid(rec["la"], rec["pa"])
        b = _nid(rec["lb"], rec["pb"])
        if a is None or b is None:
            continue
        rels.append(f"{rec['t']}::{a}=>{b}")

    return {"nodes": sorted(nodes), "rels": sorted(rels)}


def diff_snapshots(full: dict[str, list[str]], incr: dict[str, list[str]]) -> str:
    """Human-readable diff for assertion messages."""
    lines: list[str] = []
    for key in ("nodes", "rels"):
        only_full = sorted(set(full[key]) - set(incr[key]))
        only_incr = sorted(set(incr[key]) - set(full[key]))
        if only_full:
            lines.append(f"{key} only in FULL(HEAD):")
            lines.extend(f"  - {x}" for x in only_full)
        if only_incr:
            lines.append(f"{key} only in INCREMENTAL:")
            lines.extend(f"  + {x}" for x in only_incr)
    return "\n".join(lines) if lines else "(snapshots identical)"


# ---------------------------------------------------------------------------
# Base fixture repo + scenario mutations
# ---------------------------------------------------------------------------

# Base fixture. The ``java.util.List`` import is intentionally unused so the
# change-imports scenario can drop it without touching any method. Cross-file
# calls (B -> A) target STABLE methods resolved by exact class match, so the
# globally-unique-name CALLS fallback is never exercised.
_A_BASE = """package pkg;
import java.util.List;
public class A {
    public int stable() { return 1; }
    public int alpha() { return stable(); }
    public int beta() { return alpha(); }
    public int other() { return 2; }
}
"""

_B_BASE = """package pkg;
public class B {
    public int callsStable() { A a = new A(); return a.stable(); }
    public int localOnly() { return 42; }
}
"""


def build_base_repo(repo: Path) -> str:
    """Create the two-file base repo and return the BASE commit sha."""
    init_repo(repo)
    write(repo, "pkg/A.java", _A_BASE)
    write(repo, "pkg/B.java", _B_BASE)
    return commit_all(repo, "base")


# Scenario mutations: each returns the HEAD commit sha. All A-mutations keep the
# cross-file target A.stable() so B's incoming edge stays valid.

_A_MODIFY = """package pkg;
import java.util.List;
public class A {
    public int stable() { return 1; }
    public int alpha() { return other(); }
    public int beta() { return alpha(); }
    public int other() { return 2; }
}
"""

_A_ADD = """package pkg;
import java.util.List;
public class A {
    public int stable() { return 1; }
    public int alpha() { return stable(); }
    public int beta() { return gamma(); }
    public int gamma() { return other(); }
    public int other() { return 2; }
}
"""

_A_DELETE_METHOD = """package pkg;
import java.util.List;
public class A {
    public int stable() { return 1; }
    public int beta() { return other(); }
    public int other() { return 2; }
}
"""

_A_DROP_IMPORT = """package pkg;
public class A {
    public int stable() { return 1; }
    public int alpha() { return stable(); }
    public int beta() { return alpha(); }
    public int other() { return 2; }
}
"""


def mutate_modify_body(repo: Path) -> str:
    write(repo, "pkg/A.java", _A_MODIFY)
    return commit_all(repo, "modify alpha body")


def mutate_add_method(repo: Path) -> str:
    write(repo, "pkg/A.java", _A_ADD)
    return commit_all(repo, "add gamma; beta->gamma")


def mutate_delete_method(repo: Path) -> str:
    write(repo, "pkg/A.java", _A_DELETE_METHOD)
    return commit_all(repo, "delete alpha; beta->other")


def mutate_change_imports(repo: Path) -> str:
    write(repo, "pkg/A.java", _A_DROP_IMPORT)
    return commit_all(repo, "drop unused List import")


def mutate_delete_file(repo: Path) -> str:
    remove(repo, "pkg/B.java")
    return commit_all(repo, "delete B.java")
