from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp


class NVDClient:
    """Lightweight async client for the NVD CVE API v2 endpoints."""

    def __init__(self, api_key: str | None = None) -> None:
        self.base_url: str = "https://services.nvd.nist.gov/rest/json/cves/2.0"
        self.headers: dict[str, str] = {"User-Agent": "neo4j-code-graph/1.0"}
        if api_key:
            self.headers["apiKey"] = api_key

    async def fetch(
        self,
        session: aiohttp.ClientSession,
        params: dict[str, Any],
        on_rate_limit: Callable[[aiohttp.ClientResponse], Awaitable[None]],
        timeout_s: int = 30,
    ) -> dict[str, Any] | None:
        """
        Perform a GET request to the CVE search endpoint.

        Returns parsed JSON dict on success.
        If a rate limit (429) is hit, calls on_rate_limit and returns None.
        """
        async with session.get(
            self.base_url, headers=self.headers, params=params, timeout=timeout_s
        ) as resp:
            if resp.status == 429:
                await on_rate_limit(resp)
                return None
            resp.raise_for_status()
            data: dict[str, Any] = await resp.json()
            return data
