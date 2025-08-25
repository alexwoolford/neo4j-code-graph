from urllib.parse import urlparse, urlunparse


def ensure_port(uri: str, default: int = 7687) -> str:
    """Return the URI with a port, using ``default`` if none present.

    Args:
        uri: Neo4j URI that may or may not include a port
        default: Default port to use if none specified

    Returns:
        URI with port guaranteed to be present
    """
    parsed = urlparse(uri)
    # When the URI lacks a netloc, ``urlparse`` places the host in ``path``
    host = parsed.hostname or parsed.path
    port = parsed.port
    if port is None:
        auth = ""
        if parsed.username:
            auth = parsed.username
            if parsed.password:
                auth += f":{parsed.password}"
            auth += "@"
        netloc = f"{auth}{host}:{default}"
        parsed = parsed._replace(netloc=netloc, path="")
        uri = urlunparse(parsed)
    return uri


def get_neo4j_config() -> tuple[str, str, str, str]:
    """Return connection settings after loading environment variables.

    Returns:
        Tuple of (uri, username, password, database) loaded from environment
    """
    import os

    from dotenv import find_dotenv, load_dotenv

    # Load .env first, but allow real environment variables to override values from file
    # Use find_dotenv so execution from non-project CWD still picks up the repo .env
    try:
        env_path = find_dotenv(usecwd=True) or find_dotenv()
    except Exception:
        env_path = ""
    load_dotenv(dotenv_path=env_path if env_path else None, override=False)
    # Reload with override=True if explicitly requested via env flag (rare)
    if os.getenv("CODEGRAPH_ENV_OVERRIDE", "").lower() in {"1", "true", "yes"}:
        load_dotenv(override=True)
    # Treat empty strings as absent to allow sensible defaults when CI sets blank secrets
    uri_env = os.getenv("NEO4J_URI")
    user_env = os.getenv("NEO4J_USERNAME")
    pass_env = os.getenv("NEO4J_PASSWORD")
    db_env = os.getenv("NEO4J_DATABASE")

    # Do not silently default to localhost in production paths; prefer explicit config.
    # Fall back to localhost only if absolutely nothing provided (e.g., developer convenience).
    uri = ensure_port(uri_env or "bolt://localhost:7687")
    username = user_env or "neo4j"
    # Prefer strong default if none provided to satisfy password policy in containers
    password = pass_env or "Passw0rd!"
    database = db_env or "neo4j"
    # Optional diagnostic if database is defaulting
    if not db_env:
        try:
            import logging as _logging  # local import to avoid module-time side effects

            _logging.getLogger(__name__).info(
                "[config] NEO4J_DATABASE not set; defaulting to 'neo4j' (set it in .env)"
            )
        except Exception:
            pass
    return uri, username, password, database


from typing import Any


def check_capabilities(session: Any) -> dict[str, object]:
    """Detect availability of APOC and GDS features.

    Returns a dict with booleans and version strings when available:
      {
        'apoc': {'available': bool, 'version': str|None},
        'gds': {'available': bool, 'version': str|None, 'projection_ok': bool}
      }
    """
    caps: dict[str, object] = {
        "apoc": {"available": False, "version": None},
        "gds": {"available": False, "version": None, "projection_ok": False},
    }

    # APOC presence and version
    try:
        # apoc.version() returns map with version or a single row with string depending on build
        rec = session.run("CALL apoc.version()").single()
        if rec is not None:
            getter = getattr(rec, "get", None)
            val = getter("version") if callable(getter) else None
            if val is None:
                try:
                    vals = list(rec.values())  # type: ignore[call-arg]
                    val = vals[0] if vals else None
                except Exception:
                    val = None
            caps["apoc"] = {"available": True, "version": str(val) if val is not None else None}
    except Exception:
        pass

    # GDS presence and version
    gds_available = False
    try:
        rec = session.run("CALL gds.version()").single()
        if rec is not None:
            getter = getattr(rec, "get", None)
            val = getter("gdsVersion") if callable(getter) else None
            if val is None:
                try:
                    vals = list(rec.values())  # type: ignore[call-arg]
                    val = vals[0] if vals else None
                except Exception:
                    val = None
            caps["gds"] = {
                "available": True,
                "version": str(val) if val is not None else None,
                "projection_ok": False,
            }
            gds_available = True
    except Exception:
        gds_available = False

    # Probe minimal projection to catch server/plugin binary mismatch early
    if gds_available:
        try:
            session.run(
                """
                CALL gds.graph.project.cypher(
                  'cg_probe_cap',
                  'MATCH (n) RETURN id(n) AS id',
                  'MATCH (n)-[r]->(m) RETURN id(n) AS source, id(m) AS target'
                ) YIELD graphName
                """
            ).single()
            caps["gds"]["projection_ok"] = True  # type: ignore[index]
            try:
                session.run("CALL gds.graph.drop('cg_probe_cap', false)").consume()
            except Exception:
                pass
        except Exception:  # noqa: BLE001
            # Keep available=true but projection_ok=false; caller can choose to skip projection-based steps
            caps["gds"]["projection_ok"] = False  # type: ignore[index]

    return caps
