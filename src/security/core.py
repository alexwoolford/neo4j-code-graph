from __future__ import annotations

import logging
from collections.abc import Mapping
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

try:
    from src.security.cve_cache_manager import CVECacheManager  # type: ignore[attr-defined]
    from src.security.types import CleanCVE  # type: ignore[attr-defined]
    from src.utils.common import create_neo4j_driver  # type: ignore[attr-defined]
    from src.utils.neo4j_utils import get_neo4j_config  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    from security.cve_cache_manager import CVECacheManager  # type: ignore
    from security.types import CleanCVE  # type: ignore
    from utils.common import create_neo4j_driver  # type: ignore
    from utils.neo4j_utils import get_neo4j_config  # type: ignore

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
                "RETURN DISTINCT ed.package AS dependency_path, ed.artifact_id AS artifact, "
                "ed.language AS language, ed.ecosystem AS ecosystem "
                "ORDER BY dependency_path"
            )
            dependencies_by_ecosystem: dict[str, set[str]] = {}
            for record in result:
                rec: Mapping[str, Any] = dict(record)
                dep_path = str(rec.get("dependency_path", ""))
                artifact_val = rec.get("artifact")
                language = str(rec.get("language", "unknown"))
                ecosystem = str(rec.get("ecosystem", "unknown"))
                key = f"{language}:{ecosystem}" if language != "unknown" else "unknown"
                if key not in dependencies_by_ecosystem:
                    dependencies_by_ecosystem[key] = set()
                # Version-free identifiers only: NVD keyword search matches
                # names in descriptions/CPEs; versions are matched precisely by
                # the GAV/CPE matcher afterwards. "artifact:version" keywords
                # had near-zero recall.
                if dep_path:
                    dependencies_by_ecosystem[key].add(dep_path)
                if isinstance(artifact_val, str) and artifact_val:
                    dependencies_by_ecosystem[key].add(artifact_val)

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

    # Tokens too generic for NVD keyword search: they match enormous swathes of
    # the CVE corpus (timeouts + noise) without identifying a component.
    _GENERIC_TOKENS = {
        "com",
        "org",
        "net",
        "io",
        "www",
        "github",
        "api",
        "apache",
        "boot",
        "client",
        "common",
        "commons",
        "core",
        "data",
        "engine",
        "framework",
        "google",
        "impl",
        "jakarta",
        "java",
        "javax",
        "lang",
        "library",
        "misc",
        "model",
        "platform",
        "plugin",
        "release",
        "runtime",
        "security",
        "server",
        "service",
        "spring",
        "starter",
        "test",
        "tools",
        "util",
        "utils",
        "web",
    }

    @staticmethod
    def create_universal_component_search_terms(dependencies: dict[str, set[str]]) -> set[str]:
        """Build NVD keyword-search terms from version-free component names.

        Whole artifact names (e.g. ``jackson-databind``, ``xstream``) are the
        high-recall terms — NVD tokenizes hyphenated keywords, so splitting
        them only produced generic noise tokens. Dotted package paths are kept
        whole and additionally contribute their distinctive segments (vendor
        names like ``fasterxml``), never generic ones.
        """
        search_terms: set[str] = set()
        for _ecosystem, deps in dependencies.items():
            for dep in deps:
                if not dep:
                    continue
                dep_lower = dep.lower()
                search_terms.add(dep_lower)
                if "." in dep_lower:
                    for part in dep_lower.split("."):
                        if (
                            len(part) > 2
                            and part not in CVEAnalyzerCore._GENERIC_TOKENS
                            and not part.isdigit()
                        ):
                            search_terms.add(part)
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
