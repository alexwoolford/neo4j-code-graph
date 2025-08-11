#!/usr/bin/env python3
"""
Neo4j Code Graph Pipeline Manager

A Python-based pipeline orchestrator that replaces the shell script
with proper error handling, logging, and progress tracking.
"""

import argparse
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from utils.common import setup_logging

# Add src to path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


class StepStatus(Enum):
    """Pipeline step status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class PipelineStep:
    """Represents a single pipeline step."""

    name: str
    description: str
    command: str
    args: list[str] = field(default_factory=list)
    required: bool = True
    timeout: int | None = None
    retry_count: int = 0
    max_retries: int = 2
    status: StepStatus = StepStatus.PENDING
    start_time: datetime | None = None
    end_time: datetime | None = None
    error_message: str | None = None
    output: str | None = None

    @property
    def duration(self) -> float | None:
        """Get step duration in seconds."""
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return None

    @property
    def full_command(self) -> str:
        """Get the full command with arguments."""
        return f"{self.command} {' '.join(self.args)}"


class PipelineManager:
    """Manages the complete Neo4j code graph analysis pipeline.

    Orchestrates the execution of all analysis steps including schema setup,
    code analysis, git history analysis, CVE analysis, and centrality analysis.
    Provides robust error handling, retry logic, and progress tracking.

    Attributes:
        repo_url (str): URL of the repository to analyze
        config (Dict[str, Any]): Pipeline configuration options
        logger (logging.Logger): Logger instance for the pipeline
        steps (List[PipelineStep]): List of pipeline steps to execute
        start_time (Optional[datetime]): When pipeline execution started
        end_time (Optional[datetime]): When pipeline execution finished

    Example:
        >>> config = {"dry_run": False, "skip_cve": False}
        >>> pipeline = PipelineManager("https://github.com/user/repo", config)
        >>> success = pipeline.run()
    """

    def __init__(self, repo_url: str, config: dict[str, Any] | None = None):
        """Initialize the pipeline manager.

        Args:
            repo_url: URL of the repository to analyze
            config: Optional configuration dictionary with pipeline options
        """
        self.repo_url = repo_url
        self.config = config or {}
        self.logger = logging.getLogger(__name__)
        self.steps: list[PipelineStep] = []
        self.start_time: datetime | None = None
        self.end_time: datetime | None = None

        # Pipeline configuration
        self.dry_run = self.config.get("dry_run", False)
        self.skip_cleanup = self.config.get("skip_cleanup", False)
        self.skip_cve = self.config.get("skip_cve", False)
        self.continue_on_error = self.config.get("continue_on_error", False)

        self._setup_pipeline_steps()

    def _setup_pipeline_steps(self):
        """Define the pipeline steps."""
        script_dir = Path(__file__).parent.parent.parent / "scripts"

        self.steps = [
            PipelineStep(
                name="schema_setup",
                description="Setting up database schema",
                command="python",
                args=[str(script_dir / "schema_management.py")],
            ),
            PipelineStep(
                name="cleanup_prompt",
                description="Database cleanup (interactive)",
                command="python",
                args=[str(script_dir / "cleanup_graph.py"), "--dry-run"],
                required=False,
            ),
            PipelineStep(
                name="code_analysis",
                description="Loading code structure with embeddings",
                command="python",
                args=[str(script_dir / "code_to_graph.py"), self.repo_url],
                timeout=3600,  # 1 hour timeout
            ),
            PipelineStep(
                name="git_history",
                description="Loading Git commit history",
                command="python",
                args=[str(script_dir / "git_history_to_graph.py"), self.repo_url],
                timeout=1800,  # 30 minutes timeout
            ),
            PipelineStep(
                name="method_similarity",
                description="Creating method similarities using KNN",
                command="python",
                args=[
                    str(script_dir / "create_method_similarity.py"),
                    "--top-k",
                    "5",
                    "--cutoff",
                    "0.8",
                ],
            ),
            PipelineStep(
                name="community_detection",
                description="Detecting communities using Louvain",
                command="python",
                args=[
                    str(script_dir / "create_method_similarity.py"),
                    "--no-knn",
                    "--community-threshold",
                    "0.8",
                ],
            ),
            PipelineStep(
                name="centrality_analysis",
                description="Running centrality analysis",
                command="python",
                args=[
                    str(script_dir / "centrality_analysis.py"),
                    "--algorithms",
                    "pagerank",
                    "betweenness",
                    "degree",
                    "--top-n",
                    "15",
                    "--write-back",
                ],
            ),
            PipelineStep(
                name="coupling_analysis",
                description="Analyzing file change coupling",
                command="python",
                args=[
                    "-m",
                    "src.analysis.temporal_analysis",
                    "coupling",
                    "--min-support",
                    "5",
                    "--create-relationships",
                ],
            ),
            PipelineStep(
                name="hotspot_analysis",
                description="Analyzing code hotspots",
                command="python",
                args=[
                    "-m",
                    "src.analysis.temporal_analysis",
                    "hotspots",
                    "--days",
                    "365",
                    "--min-changes",
                    "3",
                    "--top-n",
                    "15",
                ],
            ),
            PipelineStep(
                name="cve_analysis",
                description="Universal vulnerability analysis",
                command="python",
                args=[
                    str(script_dir / "cve_analysis.py"),
                    "--risk-threshold",
                    "7.0",
                    "--max-hops",
                    "4",
                ],
                required=False,  # Optional if no NVD API key
            ),
        ]

    def _execute_step(self, step: PipelineStep) -> bool:
        """Execute a single pipeline step."""
        import subprocess

        self.logger.info(f"🔄 Step: {step.description}...")
        step.status = StepStatus.RUNNING
        step.start_time = datetime.now()

        if self.dry_run:
            self.logger.info(f"DRY RUN: Would execute: {step.full_command}")
            step.status = StepStatus.COMPLETED
            step.end_time = datetime.now()
            return True

        try:
            # Special handling for cleanup step
            if step.name == "cleanup_prompt" and not self.skip_cleanup:
                return self._handle_cleanup_step(step)

            # Special handling for CVE step
            if step.name == "cve_analysis" and (self.skip_cve or not self._has_nvd_api_key()):
                step.status = StepStatus.SKIPPED
                step.end_time = datetime.now()
                self.logger.info("⚠️  Skipping CVE analysis (no API key or disabled)")
                return True

            # Execute the command
            result = subprocess.run(
                [step.command] + step.args,
                capture_output=True,
                text=True,
                timeout=step.timeout,
                check=False,
            )

            step.output = result.stdout
            step.end_time = datetime.now()

            if result.returncode == 0:
                step.status = StepStatus.COMPLETED
                self.logger.info(f"✅ {step.description} completed in {step.duration:.2f}s")
                return True
            else:
                step.status = StepStatus.FAILED
                step.error_message = result.stderr
                self.logger.error(f"❌ {step.description} failed: {result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            step.status = StepStatus.FAILED
            step.error_message = f"Step timed out after {step.timeout} seconds"
            step.end_time = datetime.now()
            self.logger.error(f"❌ {step.description} timed out")
            return False

        except Exception as e:
            step.status = StepStatus.FAILED
            step.error_message = str(e)
            step.end_time = datetime.now()
            self.logger.error(f"❌ {step.description} failed with exception: {e}")
            return False

    def _handle_cleanup_step(self, step: PipelineStep) -> bool:
        """Handle the interactive cleanup step."""
        import subprocess

        # Run dry-run first
        result = subprocess.run([step.command] + step.args, capture_output=True, text=True)

        if result.returncode == 0 and result.stdout:
            self.logger.info(result.stdout)

            if not self.config.get("auto_cleanup", False):
                response = input("Proceed with cleanup? (y/n): ").strip().lower()
                if response != "y":
                    step.status = StepStatus.SKIPPED
                    step.end_time = datetime.now()
                    self.logger.info("⚠️  Database cleanup skipped by user")
                    return True

            # Run actual cleanup
            cleanup_args = [arg for arg in step.args if arg != "--dry-run"]
            result = subprocess.run([step.command] + cleanup_args, capture_output=True, text=True)

            if result.returncode == 0:
                step.status = StepStatus.COMPLETED
                step.end_time = datetime.now()
                self.logger.info("✅ Database cleanup completed")
                return True

        step.status = StepStatus.FAILED
        step.error_message = result.stderr
        step.end_time = datetime.now()
        return False

    def _has_nvd_api_key(self) -> bool:
        """Check if NVD API key is available."""
        import os

        from dotenv import load_dotenv

        load_dotenv(override=True)
        return bool(os.getenv("NVD_API_KEY"))

    def _retry_step(self, step: PipelineStep) -> bool:
        """Retry a failed step."""
        if step.retry_count >= step.max_retries:
            return False

        step.retry_count += 1
        self.logger.info(
            f"🔄 Retrying {step.description} (attempt {step.retry_count + 1}/{step.max_retries + 1})"
        )

        # Reset step state
        step.status = StepStatus.PENDING
        step.start_time = None
        step.end_time = None
        step.error_message = None

        return self._execute_step(step)

    def run(self) -> bool:
        """Execute the complete pipeline."""
        self.logger.info("🚀 Starting Neo4j Code Graph Analysis Pipeline")
        self.logger.info(f"📁 Repository: {self.repo_url}")

        self.start_time = datetime.now()
        completed_steps = 0
        failed_steps = 0

        for i, step in enumerate(self.steps, 1):
            # Skip optional steps if configured
            if not step.required and (
                (step.name == "cve_analysis" and self.skip_cve)
                or (step.name == "cleanup_prompt" and self.skip_cleanup)
            ):
                step.status = StepStatus.SKIPPED
                continue

            self.logger.info(f"📊 Progress: {i}/{len(self.steps)} - {step.description}")

            success = self._execute_step(step)

            # Retry logic
            while not success and step.retry_count < step.max_retries:
                success = self._retry_step(step)

            if success:
                completed_steps += 1
            else:
                failed_steps += 1

                if step.required and not self.continue_on_error:
                    self.logger.error(f"💥 Pipeline failed at required step: {step.description}")
                    break
                elif not step.required:
                    self.logger.warning(f"⚠️  Optional step failed: {step.description}")

        self.end_time = datetime.now()
        self._print_summary(completed_steps, failed_steps)

        return failed_steps == 0 or (failed_steps > 0 and self.continue_on_error)

    def _print_summary(self, completed: int, failed: int):
        """Print pipeline execution summary."""
        if self.start_time is not None and self.end_time is not None:
            duration = (self.end_time - self.start_time).total_seconds()
            duration_str = f"{duration:.2f} seconds"
        else:
            duration_str = "N/A"

        self.logger.info("\n" + "=" * 60)
        self.logger.info("🎉 Pipeline Execution Summary")
        self.logger.info("=" * 60)
        self.logger.info(f"📁 Repository: {self.repo_url}")
        self.logger.info(f"⏱️  Total Duration: {duration_str}")
        self.logger.info(f"✅ Completed Steps: {completed}")
        self.logger.info(f"❌ Failed Steps: {failed}")
        self.logger.info(
            f"⏭️  Skipped Steps: {len([s for s in self.steps if s.status == StepStatus.SKIPPED])}"
        )

        self.logger.info("\n📋 Step Details:")
        for step in self.steps:
            status_icon = {
                StepStatus.COMPLETED: "✅",
                StepStatus.FAILED: "❌",
                StepStatus.SKIPPED: "⏭️",
                StepStatus.PENDING: "⏸️",
            }[step.status]

            duration_str = f"({step.duration:.2f}s)" if step.duration else ""
            self.logger.info(f"  {status_icon} {step.description} {duration_str}")

            if step.status == StepStatus.FAILED and step.error_message:
                self.logger.error(f"      Error: {step.error_message}")

        if failed == 0:
            self.logger.info("\n🎉 Pipeline completed successfully!")
            self.logger.info("\n🔍 Next Steps:")
            self.logger.info("  1. Explore the graph via Neo4j Browser")
            self.logger.info("  2. Run example queries from examples/ directory")
            self.logger.info("  3. Run: python examples/cve_demo_queries.py")
        else:
            self.logger.warning(f"\n⚠️  Pipeline completed with {failed} failed steps")
            self.logger.warning("📊 Check the logs above for error details")

    def get_status(self) -> dict[str, Any]:
        """Get current pipeline status."""
        return {
            "repo_url": self.repo_url,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration": (
                (self.end_time - self.start_time).total_seconds()
                if self.start_time and self.end_time
                else None
            ),
            "steps": [
                {
                    "name": step.name,
                    "description": step.description,
                    "status": step.status.value,
                    "duration": step.duration,
                    "retry_count": step.retry_count,
                    "error_message": step.error_message,
                }
                for step in self.steps
            ],
        }


# Note: factory removed to reduce API surface; construct PipelineManager directly


def main():
    """Main entry point for the pipeline manager."""
    parser = argparse.ArgumentParser(
        description="Neo4j Code Graph Analysis Pipeline Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run complete pipeline
  python -m src.pipeline.manager https://github.com/user/repo.git

  # Run with options
  python -m src.pipeline.manager https://github.com/user/repo.git \\
    --skip-cleanup --continue-on-error --log-level DEBUG

  # Dry run (show what would be executed)
  python -m src.pipeline.manager https://github.com/user/repo.git --dry-run
        """,
    )

    parser.add_argument("repo_url", help="Git repository URL to analyze")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be executed without running",
    )
    parser.add_argument("--skip-cleanup", action="store_true", help="Skip database cleanup step")
    parser.add_argument("--skip-cve", action="store_true", help="Skip CVE analysis step")
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Continue pipeline even if non-critical steps fail",
    )
    parser.add_argument(
        "--auto-cleanup",
        action="store_true",
        help="Automatically proceed with database cleanup",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )
    parser.add_argument("--log-file", help="Optional log file")

    args = parser.parse_args()

    # Setup logging
    setup_logging(args.log_level, args.log_file)

    # Create and run pipeline
    config = {
        "dry_run": args.dry_run,
        "skip_cleanup": args.skip_cleanup,
        "skip_cve": args.skip_cve,
        "continue_on_error": args.continue_on_error,
        "auto_cleanup": args.auto_cleanup,
    }

    pipeline = PipelineManager(args.repo_url, config)

    try:
        success = pipeline.run()
        exit_code = 0 if success else 1
    except KeyboardInterrupt:
        logging.getLogger(__name__).error("❌ Pipeline interrupted by user")
        exit_code = 130
    except Exception as e:
        logging.getLogger(__name__).error(f"❌ Pipeline failed with unexpected error: {e}")
        exit_code = 1

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
