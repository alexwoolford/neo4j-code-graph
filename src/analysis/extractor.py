#!/usr/bin/env python3

from __future__ import annotations

from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from src.analysis.types import FileData
from src.utils.progress import progress_iter


def list_java_files(repo_root: Path) -> list[Path]:
    return list(repo_root.rglob("*.java"))


def extract_files_concurrently(
    files_to_process: Iterable[Path],
    repo_root: Path,
    extract_file_data,
    max_workers: int,
) -> list[FileData]:
    files_data: list[FileData] = []
    files = list(files_to_process)
    if not files:
        return files_data

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_file = {
            executor.submit(extract_file_data, file_path, repo_root): file_path
            for file_path in files
        }
        for future in progress_iter(
            as_completed(future_to_file), total=len(files), desc="Extracting files"
        ):
            result = future.result()
            if result:
                files_data.append(result)  # type: ignore[arg-type]

    return files_data
