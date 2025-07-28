#!/usr/bin/env python3
"""
Environment validation script for neo4j-code-graph.

Validates that all prerequisites, dependencies, and configurations
are properly set up before running the analysis pipeline.
"""

import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import List

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from constants import ENV_VARS, STATUS_ICONS

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


class EnvironmentValidator:
    """Validates the development and runtime environment."""

    def __init__(self):
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.checks_passed = 0
        self.checks_total = 0

    def validate_all(self) -> bool:
        """Run all validation checks.

        Returns:
            True if all critical checks pass, False otherwise
        """
        logger.info(f"{STATUS_ICONS['progress']} Starting environment validation...")

        # Core system checks
        self._check_python_version()
        self._check_git_installed()

        # Dependency checks
        self._check_python_dependencies()
        self._check_neo4j_connection()

        # Configuration checks
        self._check_environment_variables()
        self._check_project_structure()

        # Optional checks
        self._check_gpu_availability()
        self._check_disk_space()

        # Print results
        self._print_summary()

        return len(self.errors) == 0

    def _check_python_version(self) -> None:
        """Validate Python version is 3.10+."""
        self.checks_total += 1

        if sys.version_info >= (3, 10):
            logger.info(
                f"{STATUS_ICONS['success']} Python {sys.version_info.major}.{sys.version_info.minor} detected"
            )
            self.checks_passed += 1
        else:
            self.errors.append(
                f"Python 3.10+ required, found {sys.version_info.major}.{sys.version_info.minor}"
            )
            logger.error(f"{STATUS_ICONS['error']} Python version check failed")

    def _check_git_installed(self) -> None:
        """Check if Git is available."""
        self.checks_total += 1

        try:
            result = subprocess.run(
                ["git", "--version"], capture_output=True, text=True, check=True
            )
            logger.info(f"{STATUS_ICONS['success']} {result.stdout.strip()}")
            self.checks_passed += 1
        except (subprocess.CalledProcessError, FileNotFoundError):
            self.errors.append("Git is not installed or not in PATH")
            logger.error(f"{STATUS_ICONS['error']} Git not found")

    def _check_python_dependencies(self) -> None:
        """Check critical Python dependencies."""
        critical_deps = [
            "neo4j",
            "torch",
            "transformers",
            "pandas",
            "tqdm",
            "gitpython",
            "python-dotenv",
        ]

        for dep in critical_deps:
            self.checks_total += 1
            try:
                __import__(dep.replace("-", "_"))
                logger.info(f"{STATUS_ICONS['success']} {dep} installed")
                self.checks_passed += 1
            except ImportError:
                self.errors.append(f"Missing critical dependency: {dep}")
                logger.error(f"{STATUS_ICONS['error']} {dep} not found")

    def _check_neo4j_connection(self) -> None:
        """Test Neo4j database connection."""
        self.checks_total += 1

        try:
            from neo4j import GraphDatabase

            from utils.neo4j_utils import get_neo4j_config

            uri, username, password, database = get_neo4j_config()

            with GraphDatabase.driver(uri, auth=(username, password)) as driver:
                with driver.session(database=database) as session:
                    result = session.run("RETURN 1 as test")
                    result.single()

            logger.info(f"{STATUS_ICONS['success']} Neo4j connection successful")
            self.checks_passed += 1

        except Exception as e:
            self.warnings.append(f"Neo4j connection failed: {e}")
            logger.warning(f"{STATUS_ICONS['warning']} Neo4j connection test failed")

    def _check_environment_variables(self) -> None:
        """Validate environment variables."""
        from dotenv import load_dotenv

        load_dotenv()

        for env_var, default in ENV_VARS.items():
            self.checks_total += 1
            value = os.getenv(env_var, default)

            if value:
                logger.info(f"{STATUS_ICONS['success']} {env_var} configured")
                self.checks_passed += 1
            else:
                if env_var == "NVD_API_KEY":
                    self.warnings.append(
                        f"Optional: {env_var} not set (CVE analysis will be slower)"
                    )
                    logger.warning(f"{STATUS_ICONS['warning']} {env_var} not set (optional)")
                else:
                    self.errors.append(f"Required environment variable not set: {env_var}")
                    logger.error(f"{STATUS_ICONS['error']} {env_var} not configured")

    def _check_project_structure(self) -> None:
        """Validate project directory structure."""
        required_dirs = ["src", "scripts", "tests", "config"]

        required_files = ["pyproject.toml", "requirements.txt", "README.md"]

        for directory in required_dirs:
            self.checks_total += 1
            if Path(directory).exists():
                logger.info(f"{STATUS_ICONS['success']} Directory {directory}/ exists")
                self.checks_passed += 1
            else:
                self.errors.append(f"Missing required directory: {directory}/")
                logger.error(f"{STATUS_ICONS['error']} Directory {directory}/ missing")

        for file_path in required_files:
            self.checks_total += 1
            if Path(file_path).exists():
                logger.info(f"{STATUS_ICONS['success']} File {file_path} exists")
                self.checks_passed += 1
            else:
                self.errors.append(f"Missing required file: {file_path}")
                logger.error(f"{STATUS_ICONS['error']} File {file_path} missing")

    def _check_gpu_availability(self) -> None:
        """Check GPU availability for ML workloads."""
        self.checks_total += 1

        try:
            import torch

            if torch.cuda.is_available():
                gpu_count = torch.cuda.device_count()
                logger.info(f"{STATUS_ICONS['success']} CUDA available with {gpu_count} GPU(s)")
                self.checks_passed += 1
            else:
                logger.info(f"{STATUS_ICONS['info']} No CUDA GPUs available (CPU mode)")
                self.checks_passed += 1
        except ImportError:
            self.warnings.append("PyTorch not available for GPU check")
            logger.warning(f"{STATUS_ICONS['warning']} Cannot check GPU availability")

    def _check_disk_space(self) -> None:
        """Check available disk space."""
        self.checks_total += 1

        try:
            import shutil

            total, used, free = shutil.disk_usage(".")
            free_gb = free // (1024**3)

            if free_gb >= 5:
                logger.info(
                    f"{STATUS_ICONS['success']} Sufficient disk space: {free_gb}GB available"
                )
                self.checks_passed += 1
            else:
                self.warnings.append(f"Low disk space: {free_gb}GB available (5GB+ recommended)")
                logger.warning(f"{STATUS_ICONS['warning']} Low disk space: {free_gb}GB")
        except Exception as e:
            logger.warning(f"{STATUS_ICONS['warning']} Could not check disk space: {e}")

    def _print_summary(self) -> None:
        """Print validation summary."""
        logger.info("\n" + "=" * 60)
        logger.info("🎯 Environment Validation Summary")
        logger.info("=" * 60)
        logger.info(f"✅ Checks passed: {self.checks_passed}/{self.checks_total}")

        if self.errors:
            logger.error(f"❌ Critical errors: {len(self.errors)}")
            for error in self.errors:
                logger.error(f"   • {error}")

        if self.warnings:
            logger.warning(f"⚠️  Warnings: {len(self.warnings)}")
            for warning in self.warnings:
                logger.warning(f"   • {warning}")

        if not self.errors:
            logger.info(f"\n{STATUS_ICONS['success']} Environment validation passed!")
            logger.info("🚀 Ready to run neo4j-code-graph analysis!")
        else:
            logger.error(f"\n{STATUS_ICONS['error']} Environment validation failed!")
            logger.error("🔧 Please fix the errors above before proceeding.")

        # Helpful next steps
        if not self.errors:
            logger.info("\n📋 Next steps:")
            logger.info("  1. Run: make schema")
            logger.info("  2. Run: make pipeline REPO_URL=<your-repo>")
        else:
            logger.info("\n🔧 Fix issues with:")
            logger.info("  • pip install -r requirements.txt")
            logger.info("  • Update .env file with Neo4j credentials")
            logger.info("  • Ensure Neo4j is running")


def main():
    """Main entry point."""
    try:
        validator = EnvironmentValidator()
        success = validator.validate_all()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        logger.error("❌ Validation interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"❌ Validation failed with unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
