#!/usr/bin/env python3

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FileData = dict[str, Any]  # runtime type alias (avoid mypy no-redef)


def read_files_data(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_files_data(path: Path, files_data: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(files_data, ensure_ascii=False), encoding="utf-8")


def load_dependencies_from_json(path: Path) -> dict[str, str]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_dependencies_to_json(path: Path, deps: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(deps, ensure_ascii=False), encoding="utf-8")


def load_embeddings(path: Path) -> Any:
    import numpy as _np  # lazy import

    return _np.load(str(path), allow_pickle=False)


def save_embeddings(path: Path, embeddings: list[list[float]]) -> None:
    import numpy as _np  # lazy import

    path.parent.mkdir(parents=True, exist_ok=True)
    _np.save(str(path), _np.array(embeddings, dtype="float32"))
