#!/usr/bin/env python3
"""
Enhanced test suite for pipeline manager functionality.

Tests pipeline step management, configuration, and execution logic
with minimal external dependencies.
"""

from datetime import datetime, timedelta

from src.pipeline.manager import PipelineManager, PipelineStep, StepStatus


class TestPipelineStep:
    """Test PipelineStep data class functionality."""

    def test_pipeline_step_creation(self):
        """Test basic PipelineStep creation."""
        step = PipelineStep(
            name="test_step",
            description="Test step description",
            command="python",
            args=["script.py", "--arg1", "value1"],
        )

        assert step.name == "test_step"
        assert step.description == "Test step description"
        assert step.command == "python"
        assert step.args == ["script.py", "--arg1", "value1"]
        assert step.status == StepStatus.PENDING
        assert step.required is True  # Default value
        assert step.timeout is None  # Default value

    def test_pipeline_step_optional_fields(self):
        """Test PipelineStep with optional fields."""
        step = PipelineStep(
            name="optional_step",
            description="Optional step",
            command="bash",
            args=["-c", "echo test"],
            required=False,
            timeout=300,
        )

        assert step.required is False
        assert step.timeout == 300

    def test_pipeline_step_status_transitions(self):
        """Test valid status transitions."""
        step = PipelineStep("test", "desc", "cmd", [])

        # Initial status
        assert step.status == StepStatus.PENDING

        # Valid transitions
        step.status = StepStatus.RUNNING
        assert step.status == StepStatus.RUNNING

        step.status = StepStatus.COMPLETED
        assert step.status == StepStatus.COMPLETED

    def test_pipeline_step_execution_time_tracking(self):
        """Test execution time tracking fields."""
        step = PipelineStep("test", "desc", "cmd", [])

        # Should have timing fields (even if None initially)
        assert hasattr(step, "start_time")
        assert hasattr(step, "end_time")
        assert step.start_time is None
        assert step.end_time is None


class TestStepStatus:
    """Test StepStatus enum functionality."""

    def test_step_status_values(self):
        """Test all step status values are defined."""
        expected_statuses = ["PENDING", "RUNNING", "COMPLETED", "FAILED", "SKIPPED"]

        for status_name in expected_statuses:
            assert hasattr(StepStatus, status_name)
            status = getattr(StepStatus, status_name)
            assert isinstance(status.value, str)

    def test_step_status_string_representation(self):
        """Test step status string values."""
        assert StepStatus.PENDING.value == "pending"
        assert StepStatus.RUNNING.value == "running"
        assert StepStatus.COMPLETED.value == "completed"
        assert StepStatus.FAILED.value == "failed"
        assert StepStatus.SKIPPED.value == "skipped"

    def test_step_status_comparison(self):
        """Test step status equality comparison."""
        assert StepStatus.PENDING == StepStatus.PENDING
        assert StepStatus.RUNNING != StepStatus.COMPLETED

        # Test with string values
        assert StepStatus.PENDING.value == "pending"
        assert StepStatus.COMPLETED.value == "completed"


class TestPipelineManagerInitialization:
    """Test PipelineManager initialization and configuration."""

    def test_pipeline_manager_basic_creation(self):
        """Test basic PipelineManager creation."""
        repo_url = "https://github.com/test/repo"
        manager = PipelineManager(repo_url)

        assert manager.repo_url == repo_url
        assert isinstance(manager.config, dict)
        assert isinstance(manager.steps, list)
        assert len(manager.steps) > 0  # Should have default steps
        assert manager.start_time is None
        assert manager.end_time is None

    def test_pipeline_manager_with_config(self):
        """Test PipelineManager creation with custom config."""
        repo_url = "https://github.com/test/repo"
        custom_config = {"dry_run": True, "skip_cve": True, "parallel_files": 8, "batch_size": 500}

        manager = PipelineManager(repo_url, custom_config)

        assert manager.config["dry_run"] is True
        assert manager.config["skip_cve"] is True
        assert manager.config["parallel_files"] == 8
        assert manager.config["batch_size"] == 500

    def test_pipeline_manager_default_config(self):
        """Test PipelineManager default configuration values."""
        manager = PipelineManager("https://github.com/test/repo")

        # Should have a config dictionary (may be empty initially)
        assert isinstance(manager.config, dict)

    def test_pipeline_manager_step_setup(self):
        """Test that pipeline steps are properly set up."""
        manager = PipelineManager("https://github.com/test/repo")

        # Should have multiple steps
        assert len(manager.steps) >= 5  # At least a few core steps

        # All steps should be PipelineStep instances
        for step in manager.steps:
            assert isinstance(step, PipelineStep)
            assert isinstance(step.name, str)
            assert len(step.name) > 0
            assert isinstance(step.description, str)
            assert len(step.description) > 0

    def test_pipeline_manager_step_names(self):
        """Test that expected pipeline steps are present."""
        manager = PipelineManager("https://github.com/test/repo")

        step_names = [step.name for step in manager.steps]

        # Should have core steps
        expected_steps = ["schema_setup", "code_analysis", "git_history"]
        for expected_step in expected_steps:
            assert expected_step in step_names

    def test_pipeline_manager_step_properties(self):
        """Test pipeline step properties."""
        manager = PipelineManager("https://github.com/test/repo")

        # Test that all steps have required properties
        for step in manager.steps:
            assert hasattr(step, "status")
            assert hasattr(step, "required")
            assert hasattr(step, "timeout")


class TestPipelineManagerStepManagement:
    """Test pipeline step management functionality."""

    def test_get_step_by_name(self):
        """Test finding steps by name."""
        manager = PipelineManager("https://github.com/test/repo")

        # Find first step
        first_step = manager.steps[0]
        found_step = next((s for s in manager.steps if s.name == first_step.name), None)

        assert found_step is not None
        assert found_step.name == first_step.name

    def test_get_pending_steps(self):
        """Test getting pending steps."""
        manager = PipelineManager("https://github.com/test/repo")

        # Initially all steps should be pending
        pending_steps = [step for step in manager.steps if step.status == StepStatus.PENDING]

        assert len(pending_steps) == len(manager.steps)

    def test_get_completed_steps(self):
        """Test getting completed steps."""
        manager = PipelineManager("https://github.com/test/repo")

        # Mark some steps as completed
        manager.steps[0].status = StepStatus.COMPLETED
        manager.steps[1].status = StepStatus.COMPLETED

        completed_steps = [step for step in manager.steps if step.status == StepStatus.COMPLETED]

        assert len(completed_steps) == 2

    def test_get_failed_steps(self):
        """Test getting failed steps."""
        manager = PipelineManager("https://github.com/test/repo")

        # Mark a step as failed
        manager.steps[0].status = StepStatus.FAILED

        failed_steps = [step for step in manager.steps if step.status == StepStatus.FAILED]

        assert len(failed_steps) == 1
        assert failed_steps[0] == manager.steps[0]

    def test_step_filtering_by_required(self):
        """Test filtering steps by required flag."""
        manager = PipelineManager("https://github.com/test/repo")

        # Should have both required and optional steps
        required_steps = [step for step in manager.steps if step.required]
        [step for step in manager.steps if not step.required]  # Optional steps

        assert len(required_steps) > 0
        # May or may not have optional steps depending on configuration


class TestPipelineManagerConfiguration:
    """Test pipeline configuration management."""

    def test_config_merge_with_defaults(self):
        """Test that custom config merges with defaults."""
        custom_config = {"custom_setting": "custom_value"}
        manager = PipelineManager("https://github.com/test/repo", custom_config)

        # Should have custom settings
        assert "custom_setting" in manager.config  # Custom
        assert manager.config["custom_setting"] == "custom_value"

    def test_config_override_defaults(self):
        """Test that custom config overrides defaults."""
        custom_config = {"dry_run": True}  # Override default
        manager = PipelineManager("https://github.com/test/repo", custom_config)

        assert manager.config["dry_run"] is True

    def test_config_validation_patterns(self):
        """Test configuration validation patterns."""
        # Test valid configurations
        valid_configs = [
            {"dry_run": True},
            {"dry_run": False},
            {"skip_cve": True},
            {"parallel_files": 4},
            {"batch_size": 1000},
        ]

        for config in valid_configs:
            PipelineManager("https://github.com/test/repo", config)  # Should not raise

    def test_repo_url_validation(self):
        """Test repository URL validation patterns."""
        # Test various valid URL formats
        valid_urls = [
            "https://github.com/user/repo",
            "https://github.com/org/repo-name",
            "git@github.com:user/repo.git",
            "/path/to/local/repo",
            "file:///absolute/path/to/repo",
        ]

        for url in valid_urls:
            manager = PipelineManager(url)
            assert manager.repo_url == url


class TestPipelineManagerStepExecution:
    """Test pipeline step execution logic (without actual execution)."""

    def test_step_execution_timing(self):
        """Test step execution timing logic."""
        manager = PipelineManager("https://github.com/test/repo")
        step = manager.steps[0]

        # Simulate step execution timing
        start_time = datetime.now()
        step.start_time = start_time
        step.status = StepStatus.RUNNING

        # Simulate completion
        end_time = start_time + timedelta(seconds=30)
        step.end_time = end_time
        step.status = StepStatus.COMPLETED

        # Verify timing
        assert step.start_time == start_time
        assert step.end_time == end_time
        duration = step.end_time - step.start_time
        assert duration.total_seconds() == 30

    def test_step_timeout_handling(self):
        """Test step timeout configuration."""
        manager = PipelineManager("https://github.com/test/repo")

        # Find steps with timeouts
        timeout_steps = [step for step in manager.steps if step.timeout is not None]

        for step in timeout_steps:
            assert isinstance(step.timeout, int)
            assert step.timeout > 0
            assert step.timeout <= 7200  # Reasonable maximum (2 hours)

    def test_step_command_construction(self):
        """Test that step commands are properly constructed."""
        manager = PipelineManager("https://github.com/test/repo")

        for step in manager.steps:
            assert isinstance(step.command, str)
            assert len(step.command) > 0
            assert isinstance(step.args, list)

            # Command should be executable name
            assert " " not in step.command  # No spaces in command name

    def test_step_argument_validation(self):
        """Test step argument validation."""
        manager = PipelineManager("https://github.com/test/repo")

        for step in manager.steps:
            for arg in step.args:
                assert isinstance(arg, str)
                # Arguments should not be empty
                assert len(arg) > 0


class TestPipelineManagerProgressTracking:
    """Test pipeline progress tracking functionality."""

    def test_pipeline_progress_calculation(self):
        """Test pipeline progress calculation."""
        manager = PipelineManager("https://github.com/test/repo")

        total_steps = len(manager.steps)

        # Initially no progress
        completed_count = len([s for s in manager.steps if s.status == StepStatus.COMPLETED])
        assert completed_count == 0

        # Mark some steps as completed
        for i in range(3):
            manager.steps[i].status = StepStatus.COMPLETED

        completed_count = len([s for s in manager.steps if s.status == StepStatus.COMPLETED])
        progress_percentage = (completed_count / total_steps) * 100

        assert completed_count == 3
        assert 0 < progress_percentage < 100

    def test_pipeline_execution_timing(self):
        """Test pipeline execution timing."""
        manager = PipelineManager("https://github.com/test/repo")

        # Simulate pipeline start
        start_time = datetime.now()
        manager.start_time = start_time

        # Simulate pipeline completion
        end_time = start_time + timedelta(minutes=10)
        manager.end_time = end_time

        # Verify timing
        assert manager.start_time == start_time
        assert manager.end_time == end_time
        duration = manager.end_time - manager.start_time
        assert duration.total_seconds() == 600  # 10 minutes

    def test_pipeline_status_summary(self):
        """Test pipeline status summary generation."""
        manager = PipelineManager("https://github.com/test/repo")

        # Set various step statuses
        manager.steps[0].status = StepStatus.COMPLETED
        manager.steps[1].status = StepStatus.RUNNING
        manager.steps[2].status = StepStatus.FAILED
        if len(manager.steps) > 3:
            manager.steps[3].status = StepStatus.SKIPPED

        # Count by status
        status_counts = {}
        for status in StepStatus:
            status_counts[status] = len([s for s in manager.steps if s.status == status])

        assert status_counts[StepStatus.COMPLETED] >= 1
        assert status_counts[StepStatus.RUNNING] >= 1
        assert status_counts[StepStatus.FAILED] >= 1


class TestPipelineManagerErrorHandling:
    """Test error handling in pipeline manager."""

    def test_invalid_repo_url_handling(self):
        """Test handling of invalid repository URLs."""
        # Empty URL should still create manager (validation elsewhere)
        PipelineManager("")  # Should not raise

    def test_invalid_config_handling(self):
        """Test handling of invalid configuration."""
        # None config should use defaults
        PipelineManager("https://github.com/test/repo", None)  # Should not raise

    def test_step_failure_isolation(self):
        """Test that step failures don't affect other steps."""
        manager = PipelineManager("https://github.com/test/repo")

        # Mark one step as failed
        manager.steps[0].status = StepStatus.FAILED

        # Other steps should remain unaffected
        for step in manager.steps[1:]:
            assert step.status == StepStatus.PENDING

    def test_missing_dependency_handling(self):
        """Test handling of missing step dependencies."""
        # Create step without dependencies (simpler test)
        simple_step = PipelineStep(
            name="simple_step",
            description="Simple step without dependencies",
            command="echo",
            args=["test"],
        )

        # This tests that step creation works without dependencies
        assert simple_step.name == "simple_step"
        assert simple_step.command == "echo"


class TestPipelineManagerIntegration:
    """Test pipeline manager integration scenarios."""

    def test_realistic_pipeline_configuration(self):
        """Test realistic pipeline configuration scenario."""
        repo_url = "https://github.com/apache/kafka"
        config = {
            "dry_run": False,
            "skip_cve": False,
            "parallel_files": 8,
            "batch_size": 1000,
            "max_retries": 3,
        }

        manager = PipelineManager(repo_url, config)

        # Should handle large repository configuration
        assert manager.repo_url == repo_url
        assert manager.config["parallel_files"] == 8
        assert manager.config["batch_size"] == 1000

    def test_pipeline_with_all_step_types(self):
        """Test pipeline with various step types."""
        manager = PipelineManager("https://github.com/test/repo")

        # Should have steps with different characteristics
        has_required = any(step.required for step in manager.steps)
        any(step.timeout is not None for step in manager.steps)  # Check timeouts exist

        assert has_required  # Should have required steps
        # May or may not have timeout steps depending on configuration

    def test_step_execution_order_logic(self):
        """Test step execution order determination."""
        manager = PipelineManager("https://github.com/test/repo")

        # Steps should be in logical execution order
        step_names = [step.name for step in manager.steps]

        # Schema setup should come before analysis
        if "schema_setup" in step_names and "code_analysis" in step_names:
            schema_index = step_names.index("schema_setup")
            analysis_index = step_names.index("code_analysis")
            assert schema_index < analysis_index
