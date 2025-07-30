#!/usr/bin/env python3
"""
Test suite for constants module.

Tests configuration values, types, and relationships between constants
to ensure consistency and detect configuration issues early.
"""

from src.constants import (
    BATCH_SIZE,
    CVE_CACHE_DIR,
    DEFAULT_CVE_DAYS_BACK,
    DEFAULT_CVSS_THRESHOLD,
    DEFAULT_MAX_HOPS,
    DEFAULT_MAX_RESULTS,
    DEFAULT_NEO4J_DATABASE,
    DEFAULT_NEO4J_PASSWORD,
    DEFAULT_NEO4J_PORT,
    DEFAULT_NEO4J_URI,
    DEFAULT_NEO4J_USERNAME,
    DEPENDENCY_FILES,
    EMBEDDING_DIMENSION,
    EMBEDDING_TYPE,
    ENV_VARS,
    KNN_NEIGHBORS,
    LOG_FORMAT,
    MAX_FILE_SIZE_MB,
    MAX_LOG_FILE_SIZE_MB,
    MAX_RETRIES,
    MAX_WORKERS,
    MODEL_NAME,
    NVD_API_BASE_URL,
    PAGERANK_ALPHA,
    PAGERANK_MAX_ITERATIONS,
    PIPELINE_TIMEOUT_SECONDS,
    PROGRESS_BAR_WIDTH,
    SIMILARITY_THRESHOLD,
    STATUS_ICONS,
    SUMMARY_LINE_LENGTH,
    SUPPORTED_JAVA_EXTENSIONS,
)


class TestModelConfiguration:
    """Test model-related constants."""

    def test_model_name_is_valid(self):
        """Test that model name follows expected format."""
        assert isinstance(MODEL_NAME, str)
        assert "/" in MODEL_NAME  # Hugging Face format: org/model
        assert MODEL_NAME == "microsoft/graphcodebert-base"

    def test_embedding_type_consistency(self):
        """Test embedding type matches model name."""
        assert EMBEDDING_TYPE == "graphcodebert"
        assert "graphcodebert" in MODEL_NAME.lower()

    def test_embedding_dimension_is_valid(self):
        """Test embedding dimension is reasonable."""
        assert isinstance(EMBEDDING_DIMENSION, int)
        assert EMBEDDING_DIMENSION > 0
        assert EMBEDDING_DIMENSION == 768  # Standard transformer size


class TestDatabaseConfiguration:
    """Test database-related constants."""

    def test_default_neo4j_uri_format(self):
        """Test Neo4j URI follows bolt protocol."""
        assert DEFAULT_NEO4J_URI.startswith("bolt://")
        assert "localhost" in DEFAULT_NEO4J_URI

    def test_default_neo4j_port_is_valid(self):
        """Test port number is in valid range."""
        assert isinstance(DEFAULT_NEO4J_PORT, int)
        assert 1 <= DEFAULT_NEO4J_PORT <= 65535
        assert DEFAULT_NEO4J_PORT == 7687  # Standard Neo4j bolt port

    def test_uri_port_consistency(self):
        """Test URI contains the default port."""
        assert str(DEFAULT_NEO4J_PORT) in DEFAULT_NEO4J_URI

    def test_default_credentials_are_strings(self):
        """Test default credentials are proper strings."""
        assert isinstance(DEFAULT_NEO4J_USERNAME, str)
        assert isinstance(DEFAULT_NEO4J_PASSWORD, str)
        assert isinstance(DEFAULT_NEO4J_DATABASE, str)
        assert len(DEFAULT_NEO4J_USERNAME) > 0
        assert len(DEFAULT_NEO4J_DATABASE) > 0


class TestCVEConfiguration:
    """Test CVE analysis constants."""

    def test_cvss_threshold_range(self):
        """Test CVSS threshold is in valid range."""
        assert isinstance(DEFAULT_CVSS_THRESHOLD, float)
        assert 0.0 <= DEFAULT_CVSS_THRESHOLD <= 10.0
        assert DEFAULT_CVSS_THRESHOLD == 7.0  # High severity

    def test_max_hops_is_reasonable(self):
        """Test max hops is a reasonable number for graph traversal."""
        assert isinstance(DEFAULT_MAX_HOPS, int)
        assert 1 <= DEFAULT_MAX_HOPS <= 10
        assert DEFAULT_MAX_HOPS == 4

    def test_days_back_is_positive(self):
        """Test days back is a positive integer."""
        assert isinstance(DEFAULT_CVE_DAYS_BACK, int)
        assert DEFAULT_CVE_DAYS_BACK > 0
        assert DEFAULT_CVE_DAYS_BACK == 30

    def test_max_results_is_reasonable(self):
        """Test max results prevents excessive API calls."""
        assert isinstance(DEFAULT_MAX_RESULTS, int)
        assert 1 <= DEFAULT_MAX_RESULTS <= 10000
        assert DEFAULT_MAX_RESULTS == 1000

    def test_nvd_api_url_format(self):
        """Test NVD API URL is valid HTTPS."""
        assert NVD_API_BASE_URL.startswith("https://")
        assert "nvd.nist.gov" in NVD_API_BASE_URL
        assert "cves" in NVD_API_BASE_URL

    def test_cve_cache_dir_format(self):
        """Test cache directory path format."""
        assert isinstance(CVE_CACHE_DIR, str)
        assert "/" in CVE_CACHE_DIR or "\\" in CVE_CACHE_DIR
        assert "cve" in CVE_CACHE_DIR.lower()


class TestFileProcessingConfiguration:
    """Test file processing constants."""

    def test_max_file_size_reasonable(self):
        """Test max file size is reasonable for processing."""
        assert isinstance(MAX_FILE_SIZE_MB, int)
        assert 1 <= MAX_FILE_SIZE_MB <= 1000
        assert MAX_FILE_SIZE_MB == 100

    def test_supported_extensions_format(self):
        """Test supported extensions are properly formatted."""
        assert isinstance(SUPPORTED_JAVA_EXTENSIONS, set)
        assert len(SUPPORTED_JAVA_EXTENSIONS) > 0
        for ext in SUPPORTED_JAVA_EXTENSIONS:
            assert ext.startswith(".")
            assert ext == ".java"

    def test_batch_size_performance(self):
        """Test batch size is optimized for performance."""
        assert isinstance(BATCH_SIZE, int)
        assert 100 <= BATCH_SIZE <= 10000  # Reasonable batch size
        assert BATCH_SIZE == 1000

    def test_max_workers_reasonable(self):
        """Test max workers is reasonable for parallelism."""
        assert isinstance(MAX_WORKERS, int)
        assert 1 <= MAX_WORKERS <= 32
        assert MAX_WORKERS == 4


class TestGraphAnalysisConfiguration:
    """Test graph analysis algorithm constants."""

    def test_pagerank_alpha_range(self):
        """Test PageRank alpha is in valid range."""
        assert isinstance(PAGERANK_ALPHA, float)
        assert 0.0 < PAGERANK_ALPHA < 1.0
        assert PAGERANK_ALPHA == 0.85  # Standard PageRank value

    def test_pagerank_iterations_reasonable(self):
        """Test PageRank max iterations is reasonable."""
        assert isinstance(PAGERANK_MAX_ITERATIONS, int)
        assert 10 <= PAGERANK_MAX_ITERATIONS <= 1000
        assert PAGERANK_MAX_ITERATIONS == 100

    def test_similarity_threshold_range(self):
        """Test similarity threshold is in valid range."""
        assert isinstance(SIMILARITY_THRESHOLD, float)
        assert 0.0 <= SIMILARITY_THRESHOLD <= 1.0
        assert SIMILARITY_THRESHOLD == 0.8

    def test_knn_neighbors_reasonable(self):
        """Test KNN neighbors count is reasonable."""
        assert isinstance(KNN_NEIGHBORS, int)
        assert 1 <= KNN_NEIGHBORS <= 100
        assert KNN_NEIGHBORS == 5


class TestLoggingConfiguration:
    """Test logging-related constants."""

    def test_log_format_structure(self):
        """Test log format contains required components."""
        assert isinstance(LOG_FORMAT, str)
        assert "%(asctime)s" in LOG_FORMAT
        assert "%(levelname)s" in LOG_FORMAT
        assert "%(message)s" in LOG_FORMAT

    def test_max_log_file_size_reasonable(self):
        """Test max log file size is reasonable."""
        assert isinstance(MAX_LOG_FILE_SIZE_MB, int)
        assert 1 <= MAX_LOG_FILE_SIZE_MB <= 1000
        assert MAX_LOG_FILE_SIZE_MB == 50


class TestPipelineConfiguration:
    """Test pipeline execution constants."""

    def test_pipeline_timeout_reasonable(self):
        """Test pipeline timeout is reasonable for large repos."""
        assert isinstance(PIPELINE_TIMEOUT_SECONDS, int)
        assert 60 <= PIPELINE_TIMEOUT_SECONDS <= 86400  # 1 min to 24 hours
        assert PIPELINE_TIMEOUT_SECONDS == 3600  # 1 hour

    def test_max_retries_reasonable(self):
        """Test max retries is reasonable for fault tolerance."""
        assert isinstance(MAX_RETRIES, int)
        assert 0 <= MAX_RETRIES <= 10
        assert MAX_RETRIES == 2


class TestOutputFormattingConfiguration:
    """Test output formatting constants."""

    def test_summary_line_length_standard(self):
        """Test summary line length follows standard terminal width."""
        assert isinstance(SUMMARY_LINE_LENGTH, int)
        assert 40 <= SUMMARY_LINE_LENGTH <= 120
        assert SUMMARY_LINE_LENGTH == 80  # Standard terminal width

    def test_progress_bar_width_reasonable(self):
        """Test progress bar width fits in terminal."""
        assert isinstance(PROGRESS_BAR_WIDTH, int)
        assert 10 <= PROGRESS_BAR_WIDTH <= 100
        assert PROGRESS_BAR_WIDTH == 50


class TestEnvironmentVariablesConfiguration:
    """Test environment variables configuration."""

    def test_env_vars_structure(self):
        """Test ENV_VARS dictionary structure."""
        assert isinstance(ENV_VARS, dict)
        assert len(ENV_VARS) > 0

    def test_required_env_vars_present(self):
        """Test required environment variables are defined."""
        required_vars = ["NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD", "NEO4J_DATABASE"]
        for var in required_vars:
            assert var in ENV_VARS

    def test_env_vars_default_values(self):
        """Test environment variables have appropriate default values."""
        assert ENV_VARS["NEO4J_URI"] == DEFAULT_NEO4J_URI
        assert ENV_VARS["NEO4J_USERNAME"] == DEFAULT_NEO4J_USERNAME
        assert ENV_VARS["NEO4J_PASSWORD"] == DEFAULT_NEO4J_PASSWORD
        assert ENV_VARS["NEO4J_DATABASE"] == DEFAULT_NEO4J_DATABASE
        assert ENV_VARS["NVD_API_KEY"] is None  # Should be set by user


class TestStatusIconsConfiguration:
    """Test status icons for consistent UI."""

    def test_status_icons_completeness(self):
        """Test all required status icons are defined."""
        required_icons = ["success", "error", "warning", "info", "progress"]
        for icon in required_icons:
            assert icon in STATUS_ICONS

    def test_status_icons_are_unicode(self):
        """Test status icons are Unicode emoji."""
        for icon_name, icon_value in STATUS_ICONS.items():
            assert isinstance(icon_value, str)
            assert len(icon_value) > 0
            # Unicode emoji typically have ord > 127
            assert any(ord(char) > 127 for char in icon_value)

    def test_status_icon_uniqueness(self):
        """Test status icons are visually distinct."""
        icons = list(STATUS_ICONS.values())
        # Note: Some icons may be duplicated intentionally (e.g., success/completed)
        # Test that we have reasonable diversity
        unique_icons = set(icons)
        assert len(unique_icons) >= 5  # At least 5 distinct icons


class TestDependencyFilesConfiguration:
    """Test dependency file patterns."""

    def test_dependency_files_structure(self):
        """Test dependency files dictionary structure."""
        assert isinstance(DEPENDENCY_FILES, dict)
        assert len(DEPENDENCY_FILES) > 0

    def test_build_systems_supported(self):
        """Test common Java build systems are supported."""
        expected_systems = ["maven", "gradle"]
        for system in expected_systems:
            assert system in DEPENDENCY_FILES

    def test_dependency_file_patterns(self):
        """Test dependency file patterns are valid."""
        for build_system, patterns in DEPENDENCY_FILES.items():
            assert isinstance(patterns, list)
            assert len(patterns) > 0
            for pattern in patterns:
                assert isinstance(pattern, str)
                assert len(pattern) > 0
                assert "." in pattern  # Should have file extension


class TestConfigurationConsistency:
    """Test relationships and consistency between constants."""

    def test_batch_size_worker_relationship(self):
        """Test batch size is reasonable relative to worker count."""
        items_per_worker = BATCH_SIZE // MAX_WORKERS
        assert items_per_worker >= 1  # Each worker should get some work

    def test_timeout_retry_relationship(self):
        """Test timeout allows for retries."""
        max_time_with_retries = PIPELINE_TIMEOUT_SECONDS // (MAX_RETRIES + 1)
        assert max_time_with_retries >= 60  # At least 1 minute per attempt

    def test_similarity_knn_relationship(self):
        """Test similarity threshold and KNN neighbors are compatible."""
        # High threshold with reasonable neighbor count makes sense
        assert SIMILARITY_THRESHOLD >= 0.5  # Not too permissive
        assert KNN_NEIGHBORS <= 20  # Not too many neighbors

    def test_graph_analysis_ranges(self):
        """Test graph analysis parameters are in valid ranges."""
        assert 0.5 <= PAGERANK_ALPHA <= 0.99
        assert 0.1 <= SIMILARITY_THRESHOLD <= 0.95
        assert 2 <= KNN_NEIGHBORS <= 50
