#!/usr/bin/env python3

from __future__ import annotations

from collections.abc import Mapping


def run_preflight(
    uri: str | None, username: str | None, password: str | None, database: str | None
) -> dict[str, object]:
    try:
        from src.utils.common import create_neo4j_driver as _drv
        from src.utils.common import resolve_neo4j_args as _resolve
        from src.utils.neo4j_utils import check_capabilities as _check_caps
    except Exception:  # pragma: no cover
        from utils.common import create_neo4j_driver as _drv  # type: ignore
        from utils.common import resolve_neo4j_args as _resolve  # type: ignore
        from utils.neo4j_utils import check_capabilities as _check_caps  # type: ignore

    _uri, _user, _pwd, _db = _resolve(uri, username, password, database)
    try:
        with _drv(_uri, _user, _pwd) as driver:
            with driver.session(database=_db) as session:
                caps = _check_caps(session)
    except Exception:
        caps = {"apoc": {"available": False}, "gds": {"available": False, "projection_ok": False}}

    # Normalize to dicts
    apoc_obj = caps.get("apoc")
    gds_obj = caps.get("gds")
    apoc: Mapping[str, object] = apoc_obj if isinstance(apoc_obj, Mapping) else {}
    gds: Mapping[str, object] = gds_obj if isinstance(gds_obj, Mapping) else {}
    # Return as-is for callers to inspect
    return {"apoc": dict(apoc), "gds": dict(gds)}
