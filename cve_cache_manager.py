#!/usr/bin/env python3
"""
Universal CVE Cache Manager

Intelligent CVE data management that works with ANY programming language 
and dependency ecosystem without hardcoded mappings.

Features:
- Language-agnostic dependency analysis
- Smart content-based CVE relevance detection
- Efficient caching with TTL
- Rate limit optimization
- Universal pattern matching
"""

import json
import logging
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Set, Any, Optional

import requests
from tqdm import tqdm

logger = logging.getLogger(__name__)


class UniversalCVEManager:
    """Universal CVE manager that works with any language ecosystem."""

    def __init__(self, cache_dir: str = "./cve_cache", cache_ttl_hours: int = 24):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        self.cache_ttl = timedelta(hours=cache_ttl_hours)

    def fetch_targeted_cves(self, api_key: Optional[str], search_terms: Set[str],
                          max_results: int = 2000, days_back: int = 365) -> List[Dict]:
        """Fetch CVEs relevant to any technology stack using universal matching."""
        
        # Create cache key based on search terms and parameters
        terms_hash = hashlib.md5(str(sorted(search_terms)).encode()).hexdigest()[:8]
        cache_key = f"universal_cves_{terms_hash}_{days_back}d_{max_results}"

        # Try to load from cache first
        cached_data = self.load_from_cache(cache_key)
        if cached_data:
            logger.info(f"📦 Loaded {len(cached_data)} CVEs from cache")
            return cached_data

        logger.info(f"🌐 Fetching CVEs for {len(search_terms)} technology terms...")

        # NVD API setup
        base_url = "https://services.nvd.nist.gov/rest/json/cves/2.0"
        headers = {
            "User-Agent": "universal-cve-analyzer/1.0",
        }
        
        if api_key:
            headers["apiKey"] = api_key
            logger.info("🔑 Using NVD API key for requests")

        # Fetch CVEs in batches
        all_cves = []
        relevant_cves = []
        results_per_page = 20 if api_key else 10  # Conservative batch sizes
        start_index = 0
        
        # Calculate date range for recent CVEs
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days_back)

        with tqdm(desc="Fetching CVEs", unit=" CVEs") as pbar:
            while len(relevant_cves) < max_results:
                try:
                    # Use minimal parameters for maximum API compatibility
                    params = {
                        "resultsPerPage": results_per_page,
                        "startIndex": start_index
                    }

                    response = requests.get(base_url, headers=headers, params=params, timeout=30)
                    
                    if response.status_code == 429:
                        logger.warning("⏰ Rate limited - waiting 60 seconds...")
                        import time
                        time.sleep(60)
                        continue
                    
                    response.raise_for_status()
                    data = response.json()

                    vulnerabilities = data.get("vulnerabilities", [])
                    if not vulnerabilities:
                        logger.info("📊 No more CVEs available")
                        break

                    all_cves.extend(vulnerabilities)

                    # Filter for relevance using universal matching
                    batch_relevant = []
                    for vuln in vulnerabilities:
                        cve = vuln.get("cve", {})
                        
                        # Only process recent, high-severity CVEs
                        if self._is_recent_and_severe(cve, start_date):
                            if self._is_universally_relevant(cve, search_terms):
                                batch_relevant.append(vuln)

                    relevant_cves.extend(batch_relevant)

                    pbar.update(len(vulnerabilities))
                    pbar.set_postfix({
                        'total': len(all_cves),
                        'relevant': len(relevant_cves),
                        'relevance_rate': f"{len(relevant_cves)/len(all_cves)*100:.1f}%" if all_cves else "0%"
                    })

                    # Check if we've reached the end
                    total_results = data.get("totalResults", 0)
                    if start_index + len(vulnerabilities) >= total_results:
                        break

                    start_index += results_per_page

                    # Be respectful of API limits
                    if not api_key:
                        import time
                        time.sleep(2)  # 2-second delay without API key

                except Exception as e:
                    logger.error(f"❌ Error fetching CVEs: {e}")
                    break

        logger.info(f"📊 Processed {len(all_cves)} total CVEs, found {len(relevant_cves)} relevant")

        # Cache the relevant results
        self.save_to_cache(cache_key, relevant_cves)
        return relevant_cves

    def _is_recent_and_severe(self, cve: Dict, cutoff_date: datetime) -> bool:
        """Check if CVE is recent and has significant severity."""
        try:
            # Check publication date
            published_str = cve.get("published", "")
            if published_str:
                published_date = datetime.fromisoformat(published_str.replace('Z', '+00:00'))
                if published_date < cutoff_date:
                    return False

            # Check severity - only consider meaningful CVEs
            metrics = cve.get("metrics", {})
            cvss_score = 0.0

            if "cvssMetricV31" in metrics and metrics["cvssMetricV31"]:
                cvss_score = metrics["cvssMetricV31"][0]["cvssData"]["baseScore"]
            elif "cvssMetricV30" in metrics and metrics["cvssMetricV30"]:
                cvss_score = metrics["cvssMetricV30"][0]["cvssData"]["baseScore"]

            # Only consider MEDIUM+ severity (4.0+)
            return cvss_score >= 4.0

        except Exception as e:
            logger.debug(f"Error checking CVE date/severity: {e}")
            return False

    def _is_universally_relevant(self, cve: Dict, search_terms: Set[str]) -> bool:
        """Universal relevance check that works across all technology stacks."""
        try:
            # Extract all textual content from CVE
            all_text = self._extract_all_cve_text(cve).lower()
            
            # Extract structured component information
            cpe_components = self._extract_cpe_components(cve)
            
            # Combine all searchable content
            searchable_content = f"{all_text} {' '.join(cpe_components)}"
            
            # Check for matches using fuzzy and exact matching
            return self._matches_any_term(searchable_content, search_terms, cpe_components)

        except Exception as e:
            logger.debug(f"Error checking CVE relevance: {e}")
            return False

    def _extract_all_cve_text(self, cve: Dict) -> str:
        """Extract all textual content from a CVE for analysis."""
        text_parts = []
        
        # Descriptions
        descriptions = cve.get("descriptions", [])
        for desc in descriptions:
            if desc.get("lang") == "en":
                text_parts.append(desc.get("value", ""))
        
        # References
        references = cve.get("references", [])
        for ref in references:
            url = ref.get("url", "")
            if url:
                text_parts.append(url)
        
        return " ".join(text_parts)

    def _extract_cpe_components(self, cve: Dict) -> Set[str]:
        """Extract component information from CPE data."""
        components = set()
        
        configurations = cve.get("configurations", [])
        for config in configurations:
            for node in config.get("nodes", []):
                for cpe_match in node.get("cpeMatch", []):
                    cpe = cpe_match.get("criteria", "")
                    if cpe.startswith("cpe:2.3:"):
                        # Parse CPE: cpe:2.3:a:vendor:product:version:...
                        parts = cpe.split(":")
                        if len(parts) >= 6:
                            vendor = parts[3].lower()
                            product = parts[4].lower()
                            
                            # Add individual components
                            if vendor != "*" and len(vendor) > 1:
                                components.add(vendor)
                            if product != "*" and len(product) > 1:
                                components.add(product)
                            
                            # Add combined forms
                            if vendor != "*" and product != "*":
                                components.add(f"{vendor}:{product}")
                                components.add(f"{vendor}-{product}")
                                components.add(f"{vendor}_{product}")
        
        return components

    def _matches_any_term(self, content: str, search_terms: Set[str], cpe_components: Set[str]) -> bool:
        """Check if content matches any search term using multiple strategies."""
        
        # Strategy 1: Direct exact matches
        for term in search_terms:
            if term in content:
                return True
        
        # Strategy 2: CPE component intersection
        term_lower = {term.lower() for term in search_terms}
        if term_lower.intersection(cpe_components):
            return True
        
        # Strategy 3: Fuzzy matching for compound terms
        content_words = set(content.split())
        for term in search_terms:
            # Split compound terms and check for partial matches
            term_parts = []
            for sep in ['.', '-', '_', '/', '::']:
                if sep in term:
                    term_parts.extend(term.split(sep))
            
            if term_parts:
                # Check if any significant part matches
                significant_parts = [p for p in term_parts if len(p) > 3]
                if any(part in content_words for part in significant_parts):
                    return True
        
        return False

    def get_cache_file_path(self, cache_key: str) -> Path:
        """Generate cache file path for a given key."""
        key_hash = hashlib.md5(cache_key.encode()).hexdigest()
        return self.cache_dir / f"cve_cache_{key_hash}.json"

    def is_cache_valid(self, cache_file: Path) -> bool:
        """Check if cache file exists and is within TTL."""
        if not cache_file.exists():
            return False

        file_time = datetime.fromtimestamp(cache_file.stat().st_mtime)
        return datetime.now() - file_time < self.cache_ttl

    def load_from_cache(self, cache_key: str) -> Optional[List[Dict]]:
        """Load CVE data from cache if valid."""
        cache_file = self.get_cache_file_path(cache_key)

        if self.is_cache_valid(cache_file):
            try:
                with open(cache_file, 'r') as f:
                    data = json.load(f)
                logger.info(f"📦 Loaded {len(data)} CVEs from cache")
                return data
            except Exception as e:
                logger.warning(f"⚠️  Failed to load cache: {e}")

        return None

    def save_to_cache(self, cache_key: str, data: List[Dict]):
        """Save CVE data to cache."""
        cache_file = self.get_cache_file_path(cache_key)

        try:
            with open(cache_file, 'w') as f:
                json.dump(data, f, indent=2)
            logger.info(f"💾 Cached {len(data)} CVEs to {cache_file}")
        except Exception as e:
            logger.warning(f"⚠️  Failed to save cache: {e}")

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        cache_files = list(self.cache_dir.glob("cve_cache_*.json"))
        
        total_size = sum(f.stat().st_size for f in cache_files)
        total_files = len(cache_files)
        
        valid_files = sum(1 for f in cache_files if self.is_cache_valid(f))
        
        return {
            "total_files": total_files,
            "valid_files": valid_files,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "cache_dir": str(self.cache_dir)
        }

    def clear_cache(self):
        """Clear all cached CVE data."""
        cache_files = list(self.cache_dir.glob("cve_cache_*.json"))
        
        for cache_file in cache_files:
            try:
                cache_file.unlink()
            except Exception as e:
                logger.warning(f"Failed to delete {cache_file}: {e}")
        
        logger.info(f"🗑️  Cleared {len(cache_files)} cache files")
