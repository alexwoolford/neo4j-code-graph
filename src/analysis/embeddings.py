#!/usr/bin/env python3

from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache
from typing import Any


def compute_embeddings_bulk(
    snippets: Sequence[str],
    tokenizer: Any,
    model: Any,
    device: Any,
    batch_size: int,
) -> list[list[float]]:
    import gc
    import os

    import torch

    if not snippets:
        return []

    model.eval()
    if hasattr(torch, "backends") and hasattr(torch.backends, "cudnn"):
        torch.backends.cudnn.benchmark = True

    all_embeddings: list[list[float]] = []
    use_amp = device.type == "cuda" and hasattr(torch.cuda, "amp")

    max_length = 512

    for i in range(0, len(snippets), batch_size):
        batch_snippets = snippets[i : i + batch_size]

        valid_snippets: list[str] = []
        valid_indices: list[int] = []
        for j, snippet in enumerate(batch_snippets):
            if snippet and len(snippet.strip()) > 10:
                valid_snippets.append(snippet)
                valid_indices.append(j)

        if not valid_snippets:
            from constants import EMBEDDING_DIMENSION as _EMB_DIM

            zero_embedding = [0.0] * _EMB_DIM
            all_embeddings.extend([zero_embedding] * len(batch_snippets))
            continue

        prev_tok_parallel = os.environ.get("TOKENIZERS_PARALLELISM")
        prev_rayon = os.environ.get("RAYON_NUM_THREADS")
        try:
            os.environ["TOKENIZERS_PARALLELISM"] = "true"
            if prev_rayon is None:
                os.environ["RAYON_NUM_THREADS"] = str(os.cpu_count() or 4)
        except Exception:
            pass

        tokens = tokenizer(
            valid_snippets,
            padding=True,
            truncation=True,
            max_length=max_length,
            return_tensors="pt",
            add_special_tokens=True,
        )

        try:
            if prev_tok_parallel is not None:
                os.environ["TOKENIZERS_PARALLELISM"] = prev_tok_parallel
            else:
                del os.environ["TOKENIZERS_PARALLELISM"]
            if prev_rayon is not None:
                os.environ["RAYON_NUM_THREADS"] = prev_rayon
            else:
                del os.environ["RAYON_NUM_THREADS"]
        except Exception:
            pass

        if device.type == "cuda":
            tokens = {k: v.to(device, non_blocking=True) for k, v in tokens.items()}
        else:
            tokens = {k: v.to(device) for k, v in tokens.items()}

        with torch.inference_mode():
            if use_amp:
                with torch.amp.autocast("cuda", dtype=torch.float16):
                    outputs = model(**tokens)
            else:
                outputs = model(**tokens)

            embeddings = outputs.last_hidden_state[:, 0, :].detach()
            if device.type in ["cuda", "mps"]:
                embeddings = embeddings.cpu()
            embeddings_np = embeddings.numpy()

        batch_embeddings: list[list[float]] = []
        valid_idx = 0
        zero_embedding = [0.0] * embeddings_np.shape[1]
        for j in range(len(batch_snippets)):
            if j in valid_indices:
                batch_embeddings.append(embeddings_np[valid_idx].tolist())
                valid_idx += 1
            else:
                batch_embeddings.append(zero_embedding)

        all_embeddings.extend(batch_embeddings)

        del tokens, outputs, embeddings, embeddings_np
        if device.type == "cuda" and i % (batch_size * 2) == 0:
            torch.cuda.empty_cache()
            gc.collect()
        elif device.type == "mps" and i % (batch_size * 2) == 0:
            torch.mps.empty_cache()
            gc.collect()
        elif i % (batch_size * 4) == 0:
            gc.collect()

    return all_embeddings


@lru_cache(maxsize=1)
def load_embedding_model() -> tuple[Any, Any]:
    """Load and cache the tokenizer/model for reuse.

    Keeps one instance cached to avoid duplicate downloads/initialization.
    """
    from transformers import AutoModel, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained("microsoft/unixcoder-base")
    model = AutoModel.from_pretrained("microsoft/unixcoder-base")
    return tokenizer, model
