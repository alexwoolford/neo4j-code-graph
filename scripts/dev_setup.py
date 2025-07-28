#!/usr/bin/env python
"""
Development environment setup script for neo4j-code-graph.
"""

import logging
import os
import subprocess
import sys
from pathlib import Path

# Setup logging for the dev setup script
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
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
    print("🐍 Checking Python version...")

    if sys.version_info < (3, 10):
        print("❌ Python 3.10 or higher is required")
        sys.exit(1)

    print(f"✅ Python {sys.version_info.major}.{sys.version_info.minor} detected")


def check_git():
    """Check if git is available."""
    print("📡 Checking Git availability...")

    try:
        result = run_command("git --version")
        print(f"✅ {result.stdout.strip()}")
    except FileNotFoundError:
        print("❌ Git is not installed or not in PATH")
        sys.exit(1)


def setup_virtual_environment():
    """Create and activate virtual environment if needed."""
    print("🏠 Setting up virtual environment...")

    venv_path = Path(".venv")

    if not venv_path.exists():
        print("Creating virtual environment...")
        run_command([sys.executable, "-m", "venv", ".venv"])
        print("✅ Virtual environment created")
    else:
        print("✅ Virtual environment already exists")

    # Provide activation instructions
    if os.name == "nt":  # Windows
        activate_cmd = ".venv\\Scripts\\activate"
    else:  # Unix/Linux/MacOS
        activate_cmd = "source .venv/bin/activate"

    print(f"💡 To activate: {activate_cmd}")

    return venv_path


def install_dependencies():
    """Install project dependencies."""
    print("📦 Installing dependencies...")

    # Install the package in development mode
    run_command([sys.executable, "-m", "pip", "install", "-e", ".[dev]"])

    # Install requirements
    if Path("config/requirements.txt").exists():
        run_command([sys.executable, "-m", "pip", "install", "-r", "config/requirements.txt"])

    print("✅ Dependencies installed")


def setup_pre_commit():
    """Setup pre-commit hooks."""
    print("🎣 Setting up pre-commit hooks...")

    try:
        run_command([sys.executable, "-m", "pre_commit", "install"])
        print("✅ Pre-commit hooks installed")
    except subprocess.CalledProcessError:
        print("⚠️  Pre-commit setup failed (this is optional)")


def create_env_file():
    """Create .env file if it doesn't exist."""
    print("⚙️  Setting up environment configuration...")

    env_file = Path(".env")
    env_example = Path(".env.example")

    if not env_file.exists():
        if env_example.exists():
            # Copy from example
            env_file.write_text(env_example.read_text())
            print("✅ Created .env from .env.example")
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
            print("✅ Created basic .env file")

        print("💡 Please update .env with your Neo4j credentials")
    else:
        print("✅ .env file already exists")


def run_basic_tests():
    """Run a quick test to verify setup."""
    print("🧪 Running basic tests...")

    try:
        result = run_command([sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short", "-x"])
        if "passed" in result.stdout:
            print("✅ Basic tests passed")
        else:
            print("⚠️  Some tests failed (this might be expected without Neo4j)")
    except subprocess.CalledProcessError:
        print("⚠️  Tests failed (this might be expected without Neo4j)")


def print_next_steps():
    """Print helpful next steps."""
    print("\n🎉 Development environment setup complete!")
    print("\n📋 Next steps:")
    print("  1. Update .env with your Neo4j credentials")
    print("  2. Start Neo4j database")
    print("  3. Run: make schema  (to setup database schema)")
    print("  4. Run: make test    (to verify everything works)")
    print("  5. Run: make pipeline REPO_URL=<your-repo>  (to analyze a repository)")
    print("\n🔧 Available commands:")
    print("  make help        - Show all available commands")
    print("  make test        - Run tests with coverage")
    print("  make lint        - Run code quality checks")
    print("  make format      - Format code with black/isort")
    print("  make pre-commit  - Run all pre-commit hooks")
    print("\n📚 Documentation:")
    print("  README.md        - Project overview and usage")
    print("  docs/            - Additional documentation")


def main():
    """Main setup function."""
    print("🚀 Setting up neo4j-code-graph development environment...\n")

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
        print("\n❌ Setup interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Setup failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
