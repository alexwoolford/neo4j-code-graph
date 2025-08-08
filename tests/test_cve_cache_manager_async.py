#!/usr/bin/env python3

import asyncio
import time

import pytest

from src.security.cve_cache_manager import CVECacheManager


@pytest.mark.asyncio
async def test_async_rate_limit_enforcement(monkeypatch):
    m = CVECacheManager(cache_ttl_hours=1)

    # accelerate sleeps during test
    real_sleep = asyncio.sleep

    async def fast_sleep(seconds: float):
        await real_sleep(0)  # yield control only without recursion

    monkeypatch.setattr(asyncio, "sleep", fast_sleep)

    # Pretend we already hit the window limit
    now = time.time()
    m.request_times = [now - 1] * (m.requests_per_30s_no_key)

    start = time.time()
    await m._async_enforce_rate_limit(m.requests_per_30s_no_key)
    end = time.time()

    # Should not block significantly due to patched sleep
    assert end - start < 0.05
