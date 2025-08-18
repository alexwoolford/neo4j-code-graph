#!/usr/bin/env python3

from __future__ import annotations


def test_setup_logging_creates_logger(tmp_path, monkeypatch):
    from src.utils.common import setup_logging

    log_file = tmp_path / "test.log"
    setup_logging("INFO", str(log_file))
    # Write a test log entry via root logger
    import logging

    logging.getLogger().info("hello")
    # Ensure file was created
    assert log_file.exists()


def test_get_neo4j_config_env_precedence(monkeypatch):
    from src.utils.common import get_neo4j_config

    # Clear possibly set envs first
    for k in ["NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD", "NEO4J_DATABASE"]:
        monkeypatch.delenv(k, raising=False)

    # Set explicit values
    monkeypatch.setenv("NEO4J_URI", "neo4j://db.example:7687")
    monkeypatch.setenv("NEO4J_USERNAME", "neo")
    monkeypatch.setenv("NEO4J_PASSWORD", "pass")
    monkeypatch.setenv("NEO4J_DATABASE", "neo4j")

    uri, user, pwd, db = get_neo4j_config()
    assert uri.endswith(":7687") and user == "neo" and pwd == "pass" and db == "neo4j"
