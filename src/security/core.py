from __future__ import annotations

import logging
from collections.abc import Mapping
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from src.security.cve_cache_manager import CVECacheManager
from src.security.types import CleanCVE
from src.utils.common import create_neo4j_driver
from src.utils.neo4j_utils import get_neo4j_config

if TYPE_CHECKING:
    from neo4j import Driver

logger = logging.getLogger(__name__)


class CVEAnalyzerCore:
    def __init__(self, driver: Driver | None = None, database: str | None = None):
        self.driver: Driver | None = driver
        if database is None:
            _, _, _, database = get_neo4j_config()
        self.database: str = database
        self.cve_manager = CVECacheManager()

    @contextmanager
    def _session(self):  # type: ignore[no-untyped-def]
        if self.driver is not None:
            with self.driver.session(database=self.database) as s:  # type: ignore[reportUnknownMemberType]
                yield s
        else:
            uri, username, password, database = get_neo4j_config()
            with create_neo4j_driver(uri, username, password) as drv:
                with drv.session(database=database) as s:  # type: ignore[reportUnknownMemberType]
                    yield s

    def get_cache_status(self):
        return self.cve_manager.get_cache_stats()

    def extract_codebase_dependencies(self) -> tuple[dict[str, set[str]], set[str]]:
        logger.info("Extracting dependencies from codebase...")
        with self._session() as session:
            result = session.run(
                "MATCH (ed:ExternalDependency) "
                "RETURN DISTINCT ed.package AS dependency_path, ed.language AS language, "
                "ed.ecosystem AS ecosystem, ed.version AS version "
                "ORDER BY dependency_path"
            )
            dependencies_by_ecosystem: dict[str, set[str]] = {}
            for record in result:
                rec: Mapping[str, Any] = dict(record)
                dep_path = str(rec.get("dependency_path", ""))
                language = str(rec.get("language", "unknown"))
                ecosystem = str(rec.get("ecosystem", "unknown"))
                version_val = rec.get("version")
                version = str(version_val) if version_val is not None else None
                key = f"{language}:{ecosystem}" if language != "unknown" else "unknown"
                if key not in dependencies_by_ecosystem:
                    dependencies_by_ecosystem[key] = set()
                dep_info = dep_path
                if version:
                    dep_info = f"{dep_path}:{version}"
                dependencies_by_ecosystem[key].add(dep_info)

            result = session.run(
                "MATCH (f:File) "
                "WHERE f.path =~ '.*\\.(py|js|ts|go|rs|cpp|c|h|java|cs|php|rb)$' "
                "RETURN DISTINCT f.path AS file_path, f.language AS language "
                "LIMIT 1000"
            )
            file_languages: set[str] = set()
            for record in result:
                rec = dict(record)
                lang = rec.get("language")
                if isinstance(lang, str) and lang:
                    file_languages.add(lang.lower())

            return dependencies_by_ecosystem, file_languages

    def create_universal_component_search_terms(
        self, dependencies: dict[str, set[str]]
    ) -> set[str]:
        search_terms: set[str] = set()
        specific_vendor_terms: set[str] = set()
        for _ecosystem, deps in dependencies.items():
            for dep in deps:
                if dep:
                    search_terms.add(dep.lower())
                parts: list[str] = []
                if "." in dep:
                    parts.extend(dep.split("."))
                    if any(
                        vendor in dep.lower()
                        for vendor in ["jetbrains", "springframework", "fasterxml"]
                    ):
                        vendor_parts = [
                            p
                            for p in dep.split(".")
                            if p.lower() in ["jetbrains", "springframework", "fasterxml"]
                        ]
                        for vendor_part in vendor_parts:
                            specific_vendor_terms.add(vendor_part.lower())
                if "-" in dep:
                    parts.extend(dep.split("-"))
                if "_" in dep:
                    parts.extend(dep.split("_"))
                if "/" in dep:
                    parts.extend(dep.split("/"))
                if "::" in dep:
                    parts.extend(dep.split("::"))
                for part in parts:
                    part_lower: str = str(part).lower()
                    if (
                        part
                        and len(part) > 2
                        and part not in ["com", "org", "net", "io", "www", "github"]
                        and part_lower not in specific_vendor_terms
                    ):
                        search_terms.add(part_lower)
        return search_terms

    def fetch_relevant_cves(
        self, search_terms: set[str], api_key: str | None = None, max_concurrency: int | None = None
    ) -> list[CleanCVE]:
        return self.cve_manager.fetch_targeted_cves(
            api_key=api_key,
            search_terms=search_terms,
            max_results=2000,
            days_back=365,
            max_concurrency=max_concurrency,
        )
