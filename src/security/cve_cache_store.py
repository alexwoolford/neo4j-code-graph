from __future__ import annotations

import gzip
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast

logger = logging.getLogger(__name__)


class CVECacheStore:
    def __init__(self, cache_dir: str, cache_ttl: timedelta):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_ttl = cache_ttl

    def save_partial(
        self, cache_key: str, cves: list[dict[str, Any]], completed_terms: set[str]
    ) -> None:
        partial_file = self.cache_dir / f"{cache_key}_partial.json.gz"
        try:
            cache_data: dict[str, Any] = {
                "cves": cves,
                "completed_terms": list(completed_terms),
                "timestamp": datetime.now().isoformat(),
                "count": len(cves),
                "completed_count": len(completed_terms),
            }
            with gzip.open(partial_file, "wt", encoding="utf-8") as f:
                json.dump(cache_data, f, indent=2)
        except Exception as e:  # pragma: no cover - IO errors are logged
            logger.warning(f"Failed to save partial cache: {e}")

    def load_partial(self, cache_key: str) -> tuple[list[dict[str, Any]], set[str]]:
        partial_file = self.cache_dir / f"{cache_key}_partial.json.gz"
        if not partial_file.exists():
            return [], set()
        try:
            with gzip.open(partial_file, "rt", encoding="utf-8") as f:
                cache_data = json.load(f)
            timestamp = datetime.fromisoformat(
                cast(str, cache_data.get("timestamp", "")) or datetime.min.isoformat()
            )
            if datetime.now() - timestamp > self.cache_ttl:
                logger.info("⏰ Partial cache expired, starting fresh")
                return [], set()
            cves = cast(list[dict[str, Any]], cache_data.get("cves", []))
            completed_terms = set(cast(list[str], cache_data.get("completed_terms", [])))
            return cves, completed_terms
        except Exception as e:  # pragma: no cover
            logger.warning(f"Failed to load partial cache: {e}")
            return [], set()

    def cleanup_partial(self, cache_key: str) -> None:
        partial_file = self.cache_dir / f"{cache_key}_partial.json.gz"
        if partial_file.exists():
            try:
                partial_file.unlink()
            except Exception as e:
                logger.debug(f"Failed to cleanup partial cache: {e}")

    def save_complete(self, cache_key: str, data: list[dict[str, Any]]) -> None:
        cache_file = self.cache_dir / f"{cache_key}_complete.json.gz"
        try:
            cache_data: dict[str, Any] = {
                "data": data,
                "timestamp": datetime.now().isoformat(),
                "count": len(data),
                "version": "2.0",
            }
            with gzip.open(cache_file, "wt", encoding="utf-8") as f:
                json.dump(cache_data, f, indent=2)
        except Exception as e:  # pragma: no cover
            logger.error(f"Failed to save complete cache: {e}")

    def load_complete(self, cache_key: str) -> list[dict[str, Any]] | None:
        cache_file = self.cache_dir / f"{cache_key}_complete.json.gz"
        if not cache_file.exists():
            return None
        try:
            file_time = datetime.fromtimestamp(cache_file.stat().st_mtime)
            if datetime.now() - file_time > self.cache_ttl:
                logger.info("⏰ Complete cache expired")
                return None
            with gzip.open(cache_file, "rt", encoding="utf-8") as f:
                cache_data = json.load(f)
            data = cast(list[dict[str, Any]], cache_data.get("data", []))
            return data
        except Exception as e:  # pragma: no cover
            logger.warning(f"Failed to load complete cache: {e}")
            return None

    def stats(self) -> dict[str, Any]:
        cache_files = list(self.cache_dir.glob("*_complete.json.gz"))
        partial_files = list(self.cache_dir.glob("*_partial.json.gz"))
        total_size = sum(f.stat().st_size for f in cache_files + partial_files)
        stats: dict[str, Any] = {
            "complete_caches": len(cache_files),
            "partial_caches": len(partial_files),
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "cache_dir": str(self.cache_dir),
        }
        for cache_file in cache_files:
            try:
                with gzip.open(cache_file, "rt", encoding="utf-8") as f:
                    cache_data = json.load(f)
                stats[cache_file.stem] = {
                    "count": cache_data.get("count", 0),
                    "timestamp": cache_data.get("timestamp", ""),
                    "size_kb": round(cache_file.stat().st_size / 1024, 1),
                }
            except Exception:
                pass
        return stats

    def clear(self, keep_complete: bool = True) -> None:
        if keep_complete:
            partial_files = list(self.cache_dir.glob("*_partial.json.gz"))
            for cache_file in partial_files:
                try:
                    cache_file.unlink()
                except Exception as e:
                    logger.warning(f"Failed to delete {cache_file}: {e}")
        else:
            cache_files = list(self.cache_dir.glob("*.json.gz"))
            for cache_file in cache_files:
                try:
                    cache_file.unlink()
                except Exception as e:
                    logger.warning(f"Failed to delete {cache_file}: {e}")
