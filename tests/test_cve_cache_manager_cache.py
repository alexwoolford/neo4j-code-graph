#!/usr/bin/env python3
from datetime import datetime, timedelta

from src.security.cve_cache_manager import CVECacheManager


def test_partial_and_complete_cache_roundtrip(tmp_path):
    m = CVECacheManager(cache_dir=str(tmp_path), cache_ttl_hours=24)

    key = "targeted_cves_testhash_30d_100"
    cves = [{"id": "CVE-2024-0001"}, {"id": "CVE-2024-0002"}]
    terms = {"jackson", "spring"}

    # save partial
    m._save_partial_targeted_cache(key, cves, terms)
    pc, completed = m.load_partial_targeted_cache(key)
    assert {c["id"] for c in pc} == {"CVE-2024-0001", "CVE-2024-0002"}
    assert completed == terms

    # save complete and load
    m._save_complete_cache(key, cves)
    loaded = m.load_complete_cache(key)
    assert loaded is not None
    assert {c["id"] for c in loaded} == {"CVE-2024-0001", "CVE-2024-0002"}

    # cleanup partial
    m._cleanup_partial_targeted_cache(key)
    pc2, completed2 = m.load_partial_targeted_cache(key)
    assert pc2 == [] and completed2 == set()


def test_complete_cache_expiry(tmp_path, monkeypatch):
    m = CVECacheManager(cache_dir=str(tmp_path), cache_ttl_hours=1)
    key = "targeted_cves_testhash_30d_100"
    cves = [{"id": "CVE-2024-0003"}]
    m._save_complete_cache(key, cves)

    # Manually age the file beyond TTL by adjusting mtime (the loader checks mtime)
    import os

    cache_file = tmp_path / f"{key}_complete.json.gz"
    past = datetime.now() - timedelta(hours=2)
    old_ts = past.timestamp()
    os.utime(cache_file, (old_ts, old_ts))

    assert m.load_complete_cache(key) is None
