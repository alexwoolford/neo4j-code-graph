#!/usr/bin/env python3
"""
Centralized constants for the Neo4j Code Graph project.

This module contains all magic numbers, strings, and configuration
constants used throughout the codebase to avoid duplication and
improve maintainability.
"""

# Model Configuration
# Switchable embedding backbone. Default to UniXcoder (structure + NL aware).
MODEL_NAME = "microsoft/unixcoder-base"
EMBEDDING_TYPE = "unixcoder"
EMBEDDING_DIMENSION = 768
# Canonical vector property name for this embedding type
EMBEDDING_PROPERTY = f"embedding_{EMBEDDING_TYPE}"

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

# Embedding & batching defaults derived from production-sized runs.
#
# Environment overrides: You can tune parameters without code changes by exporting
# environment variables before running the pipeline, e.g.:
#
#   export DEFAULT_PARALLEL_FILES=16
#   export DB_BATCH_WITH_EMBEDDINGS=400
#   export DB_BATCH_SIMPLE=2000
#   export SIMILARITY_TOP_K=10
#   export SIMILARITY_CUTOFF=0.85

import os

# These are defaults; CLI flags and device heuristics still override.
DEFAULT_PARALLEL_FILES = int(os.getenv("DEFAULT_PARALLEL_FILES", "20"))
DEFAULT_EMBED_BATCH_CPU = int(os.getenv("DEFAULT_EMBED_BATCH_CPU", "32"))
DEFAULT_EMBED_BATCH_MPS = int(os.getenv("DEFAULT_EMBED_BATCH_MPS", "256"))
DEFAULT_EMBED_BATCH_CUDA_SMALL = int(os.getenv("DEFAULT_EMBED_BATCH_CUDA_SMALL", "128"))
DEFAULT_EMBED_BATCH_CUDA_LARGE = int(os.getenv("DEFAULT_EMBED_BATCH_CUDA_LARGE", "256"))
DEFAULT_EMBED_BATCH_CUDA_VERY_LARGE = int(os.getenv("DEFAULT_EMBED_BATCH_CUDA_VERY_LARGE", "512"))

# Neo4j write batching
# Allow tuning via env without touching code
DB_BATCH_WITH_EMBEDDINGS = int(os.getenv("DB_BATCH_WITH_EMBEDDINGS", "600"))
DB_BATCH_SIMPLE = int(os.getenv("DB_BATCH_SIMPLE", "2000"))

# Graph Analysis
PAGERANK_ALPHA = 0.85
PAGERANK_MAX_ITERATIONS = 100  # canonical default exposed via config/tests
PAGERANK_ANALYSIS_ITERATIONS = 20  # lighter default used by analysis scripts
SIMILARITY_THRESHOLD = 0.8
KNN_NEIGHBORS = 5
COMMUNITY_PROPERTY = "similarityCommunity"

# Similarity defaults (can be overridden by env)
SIMILARITY_TOP_K = int(os.getenv("SIMILARITY_TOP_K", os.getenv("SIM_TOP_K", "5")))
SIMILARITY_CUTOFF = float(os.getenv("SIMILARITY_CUTOFF", os.getenv("SIM_CUTOFF", "0.8")))

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
