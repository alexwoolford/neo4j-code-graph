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

    from dotenv import load_dotenv

    # Use .env as a fallback; real environment variables win
    load_dotenv(override=False)
    # Treat empty strings as absent to allow sensible defaults when CI sets blank secrets
    uri_env = os.getenv("NEO4J_URI")
    user_env = os.getenv("NEO4J_USERNAME")
    pass_env = os.getenv("NEO4J_PASSWORD")
    db_env = os.getenv("NEO4J_DATABASE")

    uri = ensure_port(uri_env or "bolt://localhost:7687")
    username = user_env or "neo4j"
    password = pass_env or "neo4j"
    database = db_env or "neo4j"
    return uri, username, password, database
