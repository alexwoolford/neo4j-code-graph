from urllib.parse import urlparse, urlunparse


def ensure_port(uri: str, default: int = 7687) -> str:
    """Return the URI with a port, using ``default`` if none present."""
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
