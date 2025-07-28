#!/usr/bin/env python3
"""
Centralized constants for the Neo4j Code Graph project.

This module contains all magic numbers, strings, and configuration
constants used throughout the codebase to avoid duplication and
improve maintainability.
"""

# Model Configuration
MODEL_NAME = "microsoft/graphcodebert-base"
EMBEDDING_TYPE = "graphcodebert"
EMBEDDING_DIMENSION = 768

# Database Configuration
DEFAULT_NEO4J_URI = "bolt://localhost:7687"
DEFAULT_NEO4J_USERNAME = "neo4j"
DEFAULT_NEO4J_PASSWORD = "neo4j"
DEFAULT_NEO4J_DATABASE = "neo4j"
DEFAULT_NEO4J_PORT = 7687

# CVE Analysis Configuration
DEFAULT_CVSS_THRESHOLD = 7.0
DEFAULT_MAX_HOPS = 4
DEFAULT_CVE_DAYS_BACK = 30
DEFAULT_MAX_RESULTS = 1000
NVD_API_BASE_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"
CVE_CACHE_DIR = "data/cve_cache"

# File Processing
MAX_FILE_SIZE_MB = 100
SUPPORTED_JAVA_EXTENSIONS = {".java"}
BATCH_SIZE = 1000
MAX_WORKERS = 4

# Graph Analysis
PAGERANK_ALPHA = 0.85
PAGERANK_MAX_ITERATIONS = 100
SIMILARITY_THRESHOLD = 0.8
KNN_NEIGHBORS = 5

# Logging
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
MAX_LOG_FILE_SIZE_MB = 50

# Pipeline Configuration
PIPELINE_TIMEOUT_SECONDS = 3600  # 1 hour
MAX_RETRIES = 2
CLEANUP_CONFIRMATION_REQUIRED = True

# Output Formatting
SUMMARY_LINE_LENGTH = 80
PROGRESS_BAR_WIDTH = 50

# Environment Variables
ENV_VARS = {
    "NEO4J_URI": DEFAULT_NEO4J_URI,
    "NEO4J_USERNAME": DEFAULT_NEO4J_USERNAME,
    "NEO4J_PASSWORD": DEFAULT_NEO4J_PASSWORD,
    "NEO4J_DATABASE": DEFAULT_NEO4J_DATABASE,
    "NVD_API_KEY": None,
}

# Status Messages
STATUS_ICONS = {
    "success": "✅",
    "error": "❌",
    "warning": "⚠️",
    "info": "ℹ️",
    "progress": "🔄",
    "completed": "✅",
    "failed": "❌",
    "skipped": "⏭️",
    "pending": "⏸️",
}

# File Patterns
DEPENDENCY_FILES = {
    "maven": ["pom.xml"],
    "gradle": ["build.gradle", "build.gradle.kts"],
    "sbt": ["build.sbt"],
}
