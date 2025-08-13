#!/usr/bin/env python
"""
Development environment setup script for neo4j-code-graph.
"""

import logging
import os
import subprocess
import sys
from pathlib import Path

from src.utils.common import setup_logging

# Setup logging for the dev setup script
setup_logging("INFO")
logger = logging.getLogger(__name__)


def run_command(cmd, check=True, shell=False):
    """Run a command and return the result."""
    logger.info(f"🔧 Running: {cmd}")
    if isinstance(cmd, str) and not shell:
        cmd = cmd.split()

    result = subprocess.run(cmd, capture_output=True, text=True, shell=shell)

    if check and result.returncode != 0:
        logger.error(f"❌ Command failed: {cmd}")
        logger.error(f"stdout: {result.stdout}")
        logger.error(f"stderr: {result.stderr}")
        sys.exit(1)

    return result


def check_python_version():
    """Check if Python version is compatible."""
    logger.info("🐍 Checking Python version...")

    if sys.version_info < (3, 10):
        logger.error("❌ Python 3.10 or higher is required")
        sys.exit(1)

    logger.info("✅ Python %s.%s detected", sys.version_info.major, sys.version_info.minor)


def check_git():
    """Check if git is available."""
    logger.info("📡 Checking Git availability...")

    try:
        result = run_command("git --version")
        logger.info("✅ %s", result.stdout.strip())
    except FileNotFoundError:
        logger.error("❌ Git is not installed or not in PATH")
        sys.exit(1)


def setup_virtual_environment():
    """Create and activate virtual environment if needed."""
    logger.info("🏠 Setting up virtual environment...")

    venv_path = Path(".venv")

    if not venv_path.exists():
        logger.info("Creating virtual environment...")
        run_command([sys.executable, "-m", "venv", ".venv"])
        logger.info("✅ Virtual environment created")
    else:
        logger.info("✅ Virtual environment already exists")

    # Provide activation instructions
    if os.name == "nt":  # Windows
        activate_cmd = ".venv\\Scripts\\activate"
    else:  # Unix/Linux/MacOS
        activate_cmd = "source .venv/bin/activate"

    logger.info("💡 To activate: %s", activate_cmd)

    return venv_path


def install_dependencies():
    """Install project dependencies."""
    logger.info("📦 Installing dependencies...")

    # Install the package in development mode
    run_command([sys.executable, "-m", "pip", "install", "-e", ".[dev]"])

    # Install requirements
    if Path("config/requirements.txt").exists():
        run_command([sys.executable, "-m", "pip", "install", "-r", "config/requirements.txt"])

    logger.info("✅ Dependencies installed")


def setup_pre_commit():
    """Setup pre-commit hooks."""
    logger.info("🎣 Setting up pre-commit hooks...")

    try:
        run_command([sys.executable, "-m", "pre_commit", "install"])
        logger.info("✅ Pre-commit hooks installed")
    except subprocess.CalledProcessError:
        logger.warning("⚠️  Pre-commit setup failed (this is optional)")


def create_env_file():
    """Create .env file if it doesn't exist."""
    logger.info("⚙️  Setting up environment configuration...")

    env_file = Path(".env")
    env_example = Path(".env.example")

    if not env_file.exists():
        if env_example.exists():
            # Copy from example
            env_file.write_text(env_example.read_text())
            logger.info("✅ Created .env from .env.example")
        else:
            # Create basic .env
            env_content = """# Neo4j Connection Settings
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=neo4j
NEO4J_DATABASE=neo4j

# Optional: NVD API Key for CVE analysis
# Get from: https://nvd.nist.gov/developers/request-an-api-key
# NVD_API_KEY=your_api_key_here
"""
            env_file.write_text(env_content)
            logger.info("✅ Created basic .env file")

        logger.info("💡 Please update .env with your Neo4j credentials")
    else:
        logger.info("✅ .env file already exists")


def run_basic_tests():
    """Run a quick test to verify setup."""
    logger.info("🧪 Running basic tests...")

    try:
        result = run_command([sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short", "-x"])
        if "passed" in result.stdout:
            logger.info("✅ Basic tests passed")
        else:
            logger.warning("⚠️  Some tests failed (this might be expected without Neo4j)")
    except subprocess.CalledProcessError:
        logger.warning("⚠️  Tests failed (this might be expected without Neo4j)")


def print_next_steps():
    """Print helpful next steps."""
    logger.info("\n🎉 Development environment setup complete!")
    logger.info("\n📋 Next steps:")
    logger.info("  1. Update .env with your Neo4j credentials")
    logger.info("  2. Start Neo4j database")
    logger.info("  3. Run: make schema  (to setup database schema)")
    logger.info("  4. Run: make test    (to verify everything works)")
    logger.info("  5. Run: make pipeline REPO_URL=<your-repo>  (to analyze a repository)")
    logger.info("\n🔧 Available commands:")
    logger.info("  make help        - Show all available commands")
    logger.info("  make test        - Run tests with coverage")
    logger.info("  make lint        - Run code quality checks")
    logger.info("  make format      - Format code with black/isort")
    logger.info("  make pre-commit  - Run all pre-commit hooks")
    logger.info("\n📚 Documentation:")
    logger.info("  README.md        - Project overview and usage")
    logger.info("  docs/            - Additional documentation")


def main():
    """Main setup function."""
    logger.info("🚀 Setting up neo4j-code-graph development environment...\n")

    # Change to project root directory
    script_dir = Path(__file__).parent.parent
    os.chdir(script_dir)

    try:
        check_python_version()
        check_git()
        setup_virtual_environment()
        install_dependencies()
        setup_pre_commit()
        create_env_file()
        run_basic_tests()
        print_next_steps()

    except KeyboardInterrupt:
        logger.error("\n❌ Setup interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error("\n❌ Setup failed: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
