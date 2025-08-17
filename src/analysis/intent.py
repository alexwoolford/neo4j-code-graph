"""
Intent summarization and intent-level similarity for methods.

Adds:
- Method.summary (one-line intent summary)
- Method.summary_embedding_unixcoder (768-d vector from UniXcoder)
- [:INTENT_SIMILAR {score}] relationships via kNN on summary embeddings

Note: Only `summary` is persisted for metadata; model/version timestamps are not stored per user request.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import torch
from neo4j import GraphDatabase

try:
    from transformers import RobertaTokenizer, T5ForConditionalGeneration
except Exception:  # pragma: no cover
    RobertaTokenizer = None  # type: ignore
    T5ForConditionalGeneration = None  # type: ignore


def _load_codet5() -> tuple[Any, Any]:
    if RobertaTokenizer is None or T5ForConditionalGeneration is None:
        raise RuntimeError("transformers is required for summarization")
    tok = RobertaTokenizer.from_pretrained("Salesforce/codet5-base-multi-sum")
    mdl = T5ForConditionalGeneration.from_pretrained("Salesforce/codet5-base-multi-sum")
    mdl.eval()
    return tok, mdl


@torch.no_grad()
def _summarize(tok: Any, mdl: Any, src: str) -> str:
    enc = tok(src, return_tensors="pt", truncation=True, max_length=512)
    out = mdl.generate(
        **enc, num_beams=4, max_new_tokens=32, no_repeat_ngram_size=3
    )
    text = tok.decode(out[0], skip_special_tokens=True).strip()
    return text[:120].rstrip(".")


def _read_method_source(repo_root: str, file_path: str, start_line: int | None, est_lines: int | None) -> str:
    """Best-effort slice of method source based on file+line info.

    Falls back to a small window around start_line if estimated length is missing.
    """
    abs_path = Path(repo_root) / file_path
    try:
        lines = abs_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return f"{file_path}:{start_line or 0}"

    if start_line is None or start_line <= 0:
        # Return header window
        window = lines[:80]
        return "\n".join(window)

    idx = max(0, start_line - 1)
    length = est_lines if (est_lines and est_lines > 0) else 60
    end = min(len(lines), idx + length)
    # include a few lines of tail context
    tail_extra = min(len(lines), end + 10)
    return "\n".join(lines[idx:tail_extra])


def summarize_methods_codet5(repo_root: str, uri: str, user: str, pwd: str, database: str | None) -> int:
    tok, mdl = _load_codet5()
    updated = 0
    with GraphDatabase.driver(uri, auth=(user, pwd)) as driver:
        with driver.session(database=database) as session:
            # Fetch methods missing summary
            result = session.run(
                """
                MATCH (m:Method)
                WHERE m.summary IS NULL
                RETURN id(m) AS id, m.file AS file, m.line AS line, m.estimated_lines AS est, m.method_signature AS sig
                """
            )
            methods: Iterable[dict[str, Any]] = (r.data() for r in result)
            for row in methods:
                src = _read_method_source(repo_root, row.get("file", ""), row.get("line"), row.get("est"))
                # prepend signature if present
                sig = row.get("sig")
                if sig:
                    src = f"{sig}\n{src}"
                try:
                    summary = _summarize(tok, mdl, src)
                except Exception:
                    summary = sig or ""
                session.run(
                    "MATCH (m:Method) WHERE id(m) = $id SET m.summary = $s",
                    id=row["id"],
                    s=summary,
                ).consume()
                updated += 1
    return updated


def _load_unixcoder():
    try:
        from unixcoder import UniXcoder  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError("unixcoder library is required for summary embedding") from e
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = UniXcoder("microsoft/unixcoder-base")
    return model.to(device), device


@torch.no_grad()
def _embed_unixcoder(model: Any, device: Any, text: str) -> list[float]:
    # encoder-only mode
    ids = model.tokenize([text], max_length=512, mode="<encoder-only>")
    src = torch.tensor(ids).to(device)
    _, emb = model(src)
    return emb[0].detach().cpu().tolist()


def embed_method_summaries_unixcoder(uri: str, user: str, pwd: str, database: str | None) -> int:
    model, device = _load_unixcoder()
    written = 0
    with GraphDatabase.driver(uri, auth=(user, pwd)) as driver:
        with driver.session(database=database) as session:
            res = session.run(
                """
                MATCH (m:Method)
                WHERE m.summary IS NOT NULL AND m.summary_embedding_unixcoder IS NULL
                RETURN id(m) AS id, m.summary AS s
                """
            )
            for row in (r.data() for r in res):
                vec = _embed_unixcoder(model, device, row["s"])
                session.run(
                    "MATCH (m:Method) WHERE id(m) = $id SET m.summary_embedding_unixcoder = $v",
                    id=row["id"],
                    v=vec,
                ).consume()
                written += 1
    return written


def build_intent_similarity(uri: str, user: str, pwd: str, database: str | None, top_k: int = 8, cutoff: float = 0.75) -> None:
    # Prefer GDS kNN over summary_embedding_unixcoder
    from graphdatascience import GraphDataScience  # type: ignore

    gds = GraphDataScience(uri, auth=(user, pwd), database=database, arrow=False)
    try:
        # Ensure index exists
        gds.run_cypher(
            """
            CREATE VECTOR INDEX method_summary_vec IF NOT EXISTS
            FOR (m:Method) ON (m.summary_embedding_unixcoder)
            OPTIONS {indexConfig: {
              `vector.dimensions`: 768,
              `vector.similarity_function`: 'cosine'
            }}
            """
        )
        gds.run_cypher("CALL db.awaitIndex('method_summary_vec')")

        # Drop old edges to avoid duplication
        gds.run_cypher("MATCH ()-[r:INTENT_SIMILAR]-() DELETE r")

        graph_name = "intentGraph"
        exists = gds.graph.exists(graph_name)
        try:
            exists = bool(getattr(exists, "iloc", lambda *_: None)(0)["exists"])  # type: ignore
        except Exception:
            exists = bool(exists)
        if exists:
            gds.graph.drop(graph_name)

        # Project methods with summary vectors, alias to 'embedding'
        graph, _ = gds.graph.project.cypher(
            graph_name,
            (
                "MATCH (m:Method) WHERE m.summary_embedding_unixcoder IS NOT NULL "
                "RETURN id(m) AS id, m.summary_embedding_unixcoder AS embedding"
            ),
            "RETURN null AS source, null AS target LIMIT 0",
        )

        gds.knn.write(
            graph,
            nodeProperties="embedding",
            topK=top_k,
            similarityCutoff=cutoff,
            writeRelationshipType="INTENT_SIMILAR",
            writeProperty="score",
        )
        graph.drop()
    finally:
        gds.close()


