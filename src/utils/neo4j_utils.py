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
    password = pass_env or "neo4j"
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
