#!/usr/bin/env python3
"""
Centralized constants for the Neo4j Code Graph project.

This module contains all magic numbers, strings, and configuration
constants used throughout the codebase to avoid duplication and
improve maintainability.
"""

import os

# Database Configuration
DEFAULT_NEO4J_URI = "bolt://localhost:7687"
DEFAULT_NEO4J_USERNAME = "neo4j"
DEFAULT_NEO4J_PASSWORD = "neo4j"
DEFAULT_NEO4J_DATABASE = "neo4j"
DEFAULT_NEO4J_PORT = 7687

# CVE Analysis Configuration
DEFAULT_CVSS_THRESHOLD = 7.0
# Maximum internal CALLS hops for CVE reachability path search.
# Layered Java apps typically run controller -> service -> facade -> repository
# -> client-wrapper before touching an external API (~4-5 internal hops), so
# the old default of 4 truncated wrapper-heavy codebases; 6 leaves headroom.
# Values above ~8 explode the shortest-path search for negligible extra recall
# because CALLS is internal-only and receiver-class/arity pruned.
DEFAULT_MAX_HOPS = 6
DEFAULT_CVE_DAYS_BACK = 30

# Annotations that mark a method (or its declaring class) as an externally
# triggerable entry point for reachability analysis: Spring MVC/messaging,
# Kafka/JMS/Rabbit listeners, scheduling, Spring events, and JAX-RS.
DEFAULT_ENTRY_ANNOTATIONS = (
    "RestController",
    "Controller",
    "RequestMapping",
    "GetMapping",
    "PostMapping",
    "PutMapping",
    "DeleteMapping",
    "PatchMapping",
    "MessageMapping",
    "KafkaListener",
    "JmsListener",
    "RabbitListener",
    "Scheduled",
    "EventListener",
    "Path",
    "GET",
    "POST",
    "PUT",
    "DELETE",
)
DEFAULT_MAX_RESULTS = 1000
NVD_API_BASE_URL = "https://nvd.nist.gov/rest/json/cves/2.0"
CVE_CACHE_DIR = "data/cve_cache"

# File Processing
MAX_FILE_SIZE_MB = 100
SUPPORTED_JAVA_EXTENSIONS = {".java"}
BATCH_SIZE = 1000
MAX_WORKERS = 4

# Batching defaults derived from production-sized runs.
#
# Environment overrides: You can tune parameters without code changes by exporting
# environment variables before running the pipeline, e.g.:
#
#   export DEFAULT_PARALLEL_FILES=16
#   export DB_BATCH_SIMPLE=2000

# These are defaults; CLI flags still override.
DEFAULT_PARALLEL_FILES = int(os.getenv("DEFAULT_PARALLEL_FILES", "20"))

# Neo4j write batching
# Allow tuning via env without touching code
DB_BATCH_SIMPLE = int(os.getenv("DB_BATCH_SIMPLE", "2000"))

# Graph Analysis
PAGERANK_ALPHA = 0.85
PAGERANK_MAX_ITERATIONS = 100  # canonical default exposed via config/tests
PAGERANK_ANALYSIS_ITERATIONS = 20  # lighter default used by analysis scripts

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
