from __future__ import annotations

from pathlib import Path

import numpy as np

from src.analysis.io import (
    load_dependencies_from_json,
    load_embeddings,
    read_files_data,
    save_dependencies_to_json,
    save_embeddings,
    write_files_data,
)


def test_json_roundtrip_tmp(tmp_path: Path):
    files = [
        {
            "path": "a",
            "code": "",
            "methods": [],
            "classes": [],
            "interfaces": [],
            "imports": [],
            "language": "java",
            "ecosystem": "maven",
            "total_lines": 0,
            "code_lines": 0,
            "method_count": 0,
            "class_count": 0,
            "interface_count": 0,
        }
    ]
    deps = {"org.example": "1.0.0"}

    fpath = tmp_path / "dir" / "files.json"
    dpath = tmp_path / "dir" / "deps.json"

    write_files_data(fpath, files)
    save_dependencies_to_json(dpath, deps)

    assert read_files_data(fpath) == files
    assert load_dependencies_from_json(dpath) == deps


def test_embeddings_roundtrip(tmp_path: Path):
    arr = [[0.1, 0.2], [0.3, 0.4]]
    npy = tmp_path / "embeddings.npy"
    save_embeddings(npy, arr)
    loaded = load_embeddings(npy)
    assert loaded.shape == (2, 2)
    assert np.allclose(loaded, np.array(arr, dtype="float32"))
