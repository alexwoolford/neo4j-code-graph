#!/usr/bin/env python3
"""
CVE Cache Manager

Features:
- Incremental caching (saves as it goes - no data loss!)
- Rate limiting with API-aware backoff
- Progress tracking with ETAs
- Resume capability from interruptions
- Bulk data source options
- Language-agnostic dependency analysis
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections.abc import Mapping
from datetime import timedelta
from pathlib import Path
from typing import Any, Protocol, cast

import aiohttp
from tqdm import tqdm

try:
    from security.types import CleanCVE
except Exception:  # pragma: no cover - fallback for module execution context
    from src.security.types import CleanCVE

try:  # runtime import with fallback for both repo and installed contexts
    from security.cve_cache_store import CVECacheStore  # type: ignore
except Exception:  # pragma: no cover
    from src.security.cve_cache_store import CVECacheStore  # type: ignore

try:
    from security.nvd_client import NVDClient  # type: ignore
except Exception:  # pragma: no cover
    from src.security.nvd_client import NVDClient  # type: ignore


class CVECacheStoreProtocol(Protocol):
    def load_complete(self, cache_key: str) -> list[dict[str, Any]] | None: ...

    def load_partial(self, cache_key: str) -> tuple[list[dict[str, Any]], set[str]]: ...

    def save_partial(
        self, cache_key: str, cves: list[dict[str, Any]], completed_terms: set[str]
    ) -> None: ...

    def cleanup_partial(self, cache_key: str) -> None: ...

    def save_complete(self, cache_key: str, data: list[dict[str, Any]]) -> None: ...

    def stats(self) -> dict[str, Any]: ...

    def clear(self, keep_complete: bool = True) -> None: ...


class NVDClientProtocol(Protocol):
    async def fetch(
        self,
        session: aiohttp.ClientSession,
        params: dict[str, Any],
        on_rate_limit: Any,
        timeout_s: int = 30,
    ) -> dict[str, Any] | None: ...


logger = logging.getLogger(__name__)


class CVECacheManager:
    """CVE manager with incremental caching and rate limiting."""

    def __init__(self, cache_dir: str = "./data/cve_cache", cache_ttl_hours: int = 24):
        self.cache_dir: Path = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_ttl: timedelta = timedelta(hours=cache_ttl_hours)
        self.store: CVECacheStoreProtocol = cast(
            CVECacheStoreProtocol, CVECacheStore(str(self.cache_dir), self.cache_ttl)
        )

        # NVD API Rate Limits (published rates)
        # Without API key: 5 requests per 30 seconds
        # With API key: 50 requests per 30 seconds
        self.requests_per_30s_no_key: int = 5
        self.requests_per_30s_with_key: int = 50
        self.request_window: float = 30.0  # 30 seconds

        # Track requests for rate limiting
        self.request_times: list[float] = []
        self.has_api_key: bool = False
        # Lock to coordinate concurrent calls when enforcing rate limits
        self._rate_lock = asyncio.Lock()

    def fetch_targeted_cves(
        self,
        api_key: str | None,
        search_terms: set[str],
        max_results: int = 1000,
        days_back: int = 365,
        max_concurrency: int | None = None,
    ) -> list[CleanCVE]:
        """Fetch CVEs using targeted searches for specific dependencies.

        Parameters
        ----------
        max_concurrency : Optional[int]
            Maximum number of concurrent requests. Defaults to the API rate
            limit if not provided.
        """

        self.has_api_key = bool(api_key)
        max_requests_per_window = (
            self.requests_per_30s_with_key if api_key else self.requests_per_30s_no_key
        )

        logger.info("🎯 **TARGETED CVE SEARCH** (not downloading entire database!)")
        logger.info(f"📊 Searching for {len(search_terms)} specific dependencies")
        logger.info(f"⚡ Rate limit: {max_requests_per_window} requests per {self.request_window}s")

        # Create cache key
        terms_hash = hashlib.md5(str(sorted(search_terms)).encode()).hexdigest()[:8]
        cache_key = f"targeted_cves_{terms_hash}_{days_back}d_{max_results}"

        # Check for existing complete cache
        store = self.store
        cached_data_obj = store.load_complete(cache_key)
        if cached_data_obj:
            cached_data = cast(list[CleanCVE], cached_data_obj)
            logger.info(f"📦 Loaded {len(cached_data)} CVEs from complete cache")
            return cached_data

        # Check for partial cache
        partial_raw, completed_raw = store.load_partial(cache_key)
        partial_data: list[CleanCVE] = cast(list[CleanCVE], partial_raw)
        completed_terms: set[str] = completed_raw
        remaining_terms: set[str] = search_terms - completed_terms

        if partial_data:
            logger.info(
                f"🔄 Resuming: {len(partial_data)} CVEs cached, "
                f"{len(remaining_terms)} terms remaining"
            )
        else:
            logger.info("🌐 Starting fresh targeted search")
            partial_data = []
            remaining_terms = search_terms

        # API key note
        if api_key:
            logger.info("🔑 Using NVD API key for faster searches")

        all_cves: list[CleanCVE] = list(partial_data)
        completed_terms_set: set[str] = set(completed_terms)

        # Convert search terms to effective search queries; we will generate as many as needed
        # to cover 100% of dependencies (not capped), while honoring rate limits.
        search_queries: list[tuple[str, set[str]]] = self._prepare_search_queries(remaining_terms)

        # If grouping returned fewer queries than terms, generate any remaining single-term queries
        # to guarantee 100% coverage.
        grouped_term_union: set[str] = set()
        for _, terms in search_queries:
            grouped_term_union |= terms
        missing_terms = list(remaining_terms - grouped_term_union)
        for t in missing_terms:
            search_queries.append((t, {t}))

        logger.info(f"🔍 Prepared {len(search_queries)} targeted search queries (100% coverage)")

        async def _run_async() -> None:
            concurrency_limit = max_concurrency or max_requests_per_window
            semaphore = asyncio.Semaphore(concurrency_limit)
            lock = asyncio.Lock()
            stop_event = asyncio.Event()

            client: NVDClientProtocol = cast(NVDClientProtocol, NVDClient(api_key))
            async with aiohttp.ClientSession() as session:

                async def fetch_query(idx: int, query_term: str, original_terms: set[str]) -> None:
                    if stop_event.is_set():
                        return
                    async with semaphore:
                        await self._async_enforce_rate_limit(max_requests_per_window)

                        params: dict[str, Any] = {
                            "keywordSearch": query_term,
                            "resultsPerPage": 100,
                            "startIndex": 0,
                        }

                        pbar.set_description(f"Searching: {query_term[:30]}...")

                        try:
                            data_opt: dict[str, Any] | None = await client.fetch(
                                session=session,
                                params=params,
                                on_rate_limit=self._async_handle_rate_limit,
                                timeout_s=30,
                            )
                            if data_opt is None:
                                return
                            data: dict[str, Any] = data_opt
                        except Exception as e:  # pragma: no cover - network errors
                            logger.error(f"❌ Error searching '{query_term}': {e}")
                            return

                    vulnerabilities = cast(list[dict[str, Any]], data.get("vulnerabilities", []))

                    query_cves: list[CleanCVE] = []
                    for vuln in vulnerabilities:
                        clean_cve = self._extract_clean_cve_data(vuln)
                        if clean_cve and self._is_relevant_to_terms(clean_cve, original_terms):
                            query_cves.append(clean_cve)

                    async with lock:
                        all_cves.extend(query_cves)
                        completed_terms_set.update(original_terms)
                        pbar.update(1)
                        postfix: dict[str, object] = {
                            "found": len(query_cves),
                            "total_cves": len(all_cves),
                            "completed": len(completed_terms_set),
                        }
                        pbar.set_postfix(postfix)

                        if (idx + 1) % 5 == 0:
                            store.save_partial(
                                cache_key, cast(list[dict[str, Any]], all_cves), completed_terms_set
                            )
                            logger.debug(
                                f"💾 Checkpoint: {len(all_cves)} CVEs, "
                                f"{len(completed_terms_set)} terms completed"
                            )

                        if len(all_cves) >= max_results:
                            stop_event.set()

                tasks = [
                    asyncio.create_task(fetch_query(i, q, terms))
                    for i, (q, terms) in enumerate(search_queries)
                ]
                await asyncio.gather(*tasks)

        with tqdm(
            desc="Searching dependencies", total=len(search_queries), unit=" queries"
        ) as pbar:
            try:
                asyncio.run(_run_async())
            except KeyboardInterrupt:
                logger.warning("⚠️  Search interrupted - saving progress...")
                store.save_partial(
                    cache_key, cast(list[dict[str, Any]], all_cves), completed_terms_set
                )
                logger.info(
                    f"💾 Saved {len(all_cves)} CVEs, " f"{len(completed_terms_set)} terms completed"
                )
                raise

        # Remove duplicates and finalize
        unique_cves = self._deduplicate_cves(all_cves)

        logger.info("📊 **SEARCH COMPLETE**")
        logger.info(
            f"📊 Found {len(unique_cves)} unique CVEs from {len(completed_terms_set)} dependencies"
        )
        logger.info(
            f"📊 Relevance rate: {len(unique_cves)}/{len(all_cves)} = "
            f"{len(unique_cves) / max(len(all_cves), 1) * 100:.1f}%"
        )
        # Final coverage log
        covered = len(completed_terms_set)
        total = len(search_terms)
        remaining = max(total - covered, 0)
        pct = (covered / max(total, 1)) * 100.0
        logger.info(
            f"📈 Coverage: processed {covered}/{total} dependency terms ({pct:.1f}%); {remaining} remaining"
        )

        # Save final results
        store.save_complete(cache_key, cast(list[dict[str, Any]], unique_cves))
        store.cleanup_partial(cache_key)

        return unique_cves

    def _prepare_search_queries(self, search_terms: set[str]) -> list[tuple[str, set[str]]]:
        """Convert dependency names into effective NVD search queries."""
        queries: list[tuple[str, set[str]]] = []

        # Group terms by common patterns for efficient searching
        term_groups: dict[str, set[str]] = {}

        for term in search_terms:
            # Special handling for specific known libraries to avoid false positives
            if "jetbrains.annotations" in term.lower():
                # Search for "jetbrains annotations" specifically, not just "jetbrains"
                search_key = "jetbrains annotations"
                if search_key not in term_groups:
                    term_groups[search_key] = set()
                term_groups[search_key].add(term)
                continue

            # Extract the most meaningful part for searching
            if "." in term:
                # Java-style: com.fasterxml.jackson -> "jackson fasterxml" or just "jackson"
                parts = term.split(".")
                if len(parts) >= 2:
                    # For well-known libraries, use compound searches
                    if "fasterxml" in parts and "jackson" in parts:
                        search_key = "jackson fasterxml"
                    elif "springframework" in parts or "spring" in parts:
                        search_key = "spring framework"
                    elif "testcontainers" in parts:
                        search_key = "testcontainers"
                    else:
                        # Use the most specific non-generic part
                        meaningful_parts = [
                            p for p in parts if len(p) > 3 and p not in ["com", "org", "net", "io"]
                        ]
                        if meaningful_parts:
                            search_key = meaningful_parts[-1]  # Usually the most specific
                        else:
                            search_key = term
                else:
                    search_key = term
            else:
                search_key = term

            # Group similar terms
            if search_key not in term_groups:
                term_groups[search_key] = set()
            term_groups[search_key].add(term)

        # Create search queries from grouped terms
        for search_key, related_terms in term_groups.items():
            if len(search_key) > 2:  # Only search meaningful terms
                queries.append((search_key, related_terms))

        # Add some compound searches for common patterns, but be specific
        java_terms = [
            t
            for t in search_terms
            if "." in t and any(t.startswith(prefix) for prefix in ["com.", "org.", "io.", "net."])
        ]
        if java_terms:
            compound_searches = self._create_compound_searches(java_terms)
            queries.extend(compound_searches)

        return queries

    def _create_compound_searches(self, java_terms: list[str]) -> list[tuple[str, set[str]]]:
        """Create compound search terms for better Java library detection."""
        compounds: list[tuple[str, set[str]]] = []

        # Common Java library patterns
        library_patterns: dict[str, list[str]] = {
            "jackson": [t for t in java_terms if "jackson" in t],
            "spring": [t for t in java_terms if "spring" in t],
            "junit": [t for t in java_terms if "junit" in t],
            "mockito": [t for t in java_terms if "mockito" in t],
            "apache": [t for t in java_terms if "apache" in t],
        }

        for lib_name, related_terms in library_patterns.items():
            if related_terms:
                compounds.append((lib_name, set(related_terms)))

        return compounds

    def _is_relevant_to_terms(self, cve: Mapping[str, Any], terms: set[str]) -> bool:
        """Check if a CVE is relevant to the given search terms with precise matching."""
        # Extract text from multiple possible locations
        description_text = ""
        if "descriptions" in cve:
            for desc in cve["descriptions"]:
                if desc.get("lang") == "en":
                    description_text += desc.get("value", "")
        description_text += cve.get("description", "")

        # Also check configurations for CPE matches
        config_text = ""
        if "configurations" in cve:
            for config in cve["configurations"]:
                for node in config.get("nodes", []):
                    for cpe_match in node.get("cpeMatch", []):
                        config_text += cpe_match.get("criteria", "")

        cve_text = f"{description_text} {cve.get('id', '')} {config_text}".lower()

        for term in terms:
            term_lower = term.lower()

            # For compound library names (like org.jetbrains.annotations), be very specific
            if "." in term and "jetbrains" in term_lower:
                # Only match if the CVE specifically mentions annotations, not IDE tools
                if "annotation" in cve_text:
                    return True
                # Exclude JetBrains IDE/tool vulnerabilities
                elif any(
                    ide_tool in cve_text
                    for ide_tool in [
                        "teamcity",
                        "intellij",
                        "idea",
                        "youtrack",
                        "space",
                        "hub",
                        "kotlin",
                        "resharper",
                        "rider",
                        "webstorm",
                        "phpstorm",
                        "pycharm",
                        "rubymine",
                        "clion",
                        "goland",
                    ]
                ):
                    return False
                # If it's just generic "jetbrains" mention without library context, skip it
                elif "jetbrains" in cve_text and not any(
                    lib_term in cve_text
                    for lib_term in ["annotation", "library", "maven", "gradle", "jar"]
                ):
                    return False

            # For other compound terms, check more precisely
            elif "." in term:
                # For java packages like com.fasterxml.jackson, check for the specific library
                parts = [p for p in term.split(".") if len(p) > 2]

                # Require at least 2 parts to match for compound names
                if len(parts) >= 2:
                    matches = sum(1 for part in parts if part.lower() in cve_text)
                    if matches >= 2:  # At least 2 parts must match
                        return True

                # Also check the full term
                if term_lower in cve_text:
                    return True

            # For simple terms, require exact match
            else:
                if term_lower in cve_text:
                    return True

        return False

    def _deduplicate_cves(self, cves: list[CleanCVE]) -> list[CleanCVE]:
        """Remove duplicate CVEs based on ID."""
        seen_ids: set[str] = set()
        unique_cves: list[CleanCVE] = []

        for cve in cves:
            cve_id = cve.get("id", "")
            if cve_id and cve_id not in seen_ids:
                seen_ids.add(cve_id)
                unique_cves.append(cve)

        return unique_cves

    def _enforce_rate_limit(self, max_requests: int) -> None:
        """Enforce NVD API rate limits properly."""
        now = time.time()

        # Remove requests older than the window
        self.request_times = [t for t in self.request_times if now - t < self.request_window]

        # Check if we need to wait
        if len(self.request_times) >= max_requests:
            # Calculate how long to wait
            oldest_request = min(self.request_times)
            wait_time = self.request_window - (now - oldest_request)
            if wait_time > 0:
                logger.debug(f"⏰ Rate limiting: waiting {wait_time:.1f}s")
                time.sleep(wait_time + 0.1)  # Small buffer

        # Record this request
        self.request_times.append(now)

    async def _async_enforce_rate_limit(self, max_requests: int) -> None:
        """Asynchronous version of rate limit enforcement."""
        async with self._rate_lock:
            now = time.time()

            self.request_times = [t for t in self.request_times if now - t < self.request_window]

            if len(self.request_times) >= max_requests:
                oldest_request = min(self.request_times)
                wait_time = self.request_window - (now - oldest_request)
                if wait_time > 0:
                    logger.debug(f"⏰ Rate limiting: waiting {wait_time:.1f}s")
                    await asyncio.sleep(wait_time + 0.1)

            self.request_times.append(time.time())

    async def _async_handle_rate_limit(self, response: Any) -> None:
        """Asynchronous rate limit handling."""
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                wait_time = int(retry_after)
                logger.warning(f"⏰ API rate limited - waiting {wait_time}s (from server)")
                await asyncio.sleep(wait_time)
                return
            except ValueError:
                pass

        wait_time = (
            self.request_window / self.requests_per_30s_with_key
            if self.has_api_key
            else self.request_window / self.requests_per_30s_no_key
        )
        logger.warning(f"⏰ Rate limited - waiting {wait_time:.1f}s")
        await asyncio.sleep(wait_time)

    def _extract_clean_cve_data(self, vuln_entry: dict[str, Any]) -> CleanCVE | None:
        """Extract clean, normalized CVE data."""
        try:
            cve = vuln_entry.get("cve", {})

            # Basic info
            cve_id = cve.get("id", "")
            if not cve_id:
                return None

            # Description
            descriptions = cve.get("descriptions", [])
            description = ""
            for desc in descriptions:
                if desc.get("lang") == "en":
                    description = desc.get("value", "")
                    break

            # CVSS Score
            metrics = cast(dict[str, Any], cve.get("metrics", {}))
            cvss_score: float = 0.0
            severity: str = "UNKNOWN"

            if "cvssMetricV31" in metrics and metrics["cvssMetricV31"]:
                cvss_data = metrics["cvssMetricV31"][0]["cvssData"]
                cvss_score = cvss_data.get("baseScore", 0.0)
                severity = cvss_data.get("baseSeverity", "UNKNOWN")
            elif "cvssMetricV30" in metrics and metrics["cvssMetricV30"]:
                cvss_data = metrics["cvssMetricV30"][0]["cvssData"]
                cvss_score = cvss_data.get("baseScore", 0.0)
                severity = cvss_data.get("baseSeverity", "UNKNOWN")

            # Only keep meaningful CVEs (MEDIUM+)
            if cvss_score < 4.0:
                return None

            return {
                "id": cve_id,
                "description": description,
                "cvss_score": cvss_score,
                "severity": severity,
                "published": cve.get("published", ""),
                "modified": cve.get("lastModified", ""),
            }

        except Exception as e:
            logger.debug(f"Error extracting CVE data: {e}")
            return None

    # Delegate cache operations to the store
    def _save_partial_targeted_cache(
        self, cache_key: str, cves: list[CleanCVE], completed_terms: set[str]
    ) -> None:
        self.store.save_partial(cache_key, cast(list[dict[str, Any]], cves), completed_terms)

    def load_partial_targeted_cache(self, cache_key: str) -> tuple[list[CleanCVE], set[str]]:
        cves, completed = self.store.load_partial(cache_key)
        return cast(list[CleanCVE], cves), completed

    def _cleanup_partial_targeted_cache(self, cache_key: str) -> None:
        self.store.cleanup_partial(cache_key)

    def _save_complete_cache(self, cache_key: str, data: list[CleanCVE]) -> None:
        self.store.save_complete(cache_key, cast(list[dict[str, Any]], data))

    def load_complete_cache(self, cache_key: str) -> list[CleanCVE] | None:
        data = self.store.load_complete(cache_key)
        return cast(list[CleanCVE], data) if data is not None else None

    def get_cache_stats(self) -> dict[str, Any]:
        return self.store.stats()

    def clear_cache(self, keep_complete: bool = True) -> None:
        self.store.clear(keep_complete=keep_complete)

    # --- Thin compatibility layer for legacy tests ---
    def is_cve_relevant(self, cve: Mapping[str, Any], components: set[str]) -> bool:  # type: ignore[override]
        return self._is_relevant_to_terms(cve, components)

    def get_cache_file_path(self, cache_key: str) -> Path:  # pragma: no cover (compat shim)
        # Legacy filename expected by tests
        return (self.cache_dir / f"{cache_key}.json.gz").resolve()
