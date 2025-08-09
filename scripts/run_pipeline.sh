#!/bin/bash

# Neo4j Code Graph Analysis Pipeline
# Run this script to execute the complete analysis pipeline on any Git repository

set -e  # Exit on any error

# Fix OpenMP library conflict on macOS
export KMP_DUPLICATE_LIB_OK=TRUE

# Check if repository URL is provided
if [ $# -eq 0 ]; then
    echo "❌ Error: Repository URL required"
    echo ""
    echo "Usage: $0 <repository-url>"
    echo ""
    echo "Example:"
    echo "  $0 https://github.com/your-org/your-java-repo.git"
    echo ""
    exit 1
fi

REPO_URL=$1
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "🚀 Starting Neo4j Code Graph Analysis Pipeline"
echo "=============================================="
echo "📁 Repository: $REPO_URL"
echo ""

# Step 0: Setup database schema and cleanup
echo "🏗️  Step 0: Setting up database schema..."
python "$SCRIPT_DIR/schema_management.py"
echo "✅ Schema setup completed"

echo ""
echo "🧹 Cleaning up previous analysis (if any)..."
# Auto-confirm cleanup in CI/non-interactive mode
if [ -n "$CI" ] || [ ! -t 0 ]; then
  python "$SCRIPT_DIR/cleanup_graph.py"
  echo "✅ Cleanup completed (non-interactive)"
else
  python "$SCRIPT_DIR/cleanup_graph.py" --dry-run
  read -p "Proceed with cleanup? (y/n): " -n 1 -r
  echo
  if [[ $REPLY =~ ^[Yy]$ ]]; then
      python "$SCRIPT_DIR/cleanup_graph.py"
      echo "✅ Cleanup completed"
  else
      echo "⚠️  Skipping cleanup - you may have duplicate data"
  fi
fi

# Step 1: Clone Repository (once for efficiency)
echo ""
echo "📥 Step 1: Cloning repository for analysis..."
TEMP_REPO_DIR=$(mktemp -d)
git clone "$REPO_URL" "$TEMP_REPO_DIR"
echo "✅ Repository cloned to: $TEMP_REPO_DIR"

# Cleanup function for proper temp directory removal
cleanup_repo() {
    if [ -n "$TEMP_REPO_DIR" ] && [ -d "$TEMP_REPO_DIR" ]; then
        echo "🧹 Cleaning up temporary repository..."
        rm -rf "$TEMP_REPO_DIR"
        echo "✅ Cleanup completed"
    fi
}

# Ensure cleanup on exit
trap cleanup_repo EXIT

# Step 2: Load Code Structure (Java files and methods with embeddings)
echo ""
echo "📝 Step 2: Loading Java code structure with embeddings..."
echo "⏰ This step may take a while for large repositories..."
python "$SCRIPT_DIR/code_to_graph.py" "$TEMP_REPO_DIR"
echo "✅ Code structure loaded"

# Step 3: Load Git History (commits and developer data)
echo ""
echo "📚 Step 3: Loading Git commit history..."
python "$SCRIPT_DIR/git_history_to_graph.py" "$TEMP_REPO_DIR"
echo "✅ Git history loaded"

# Step 4: Create Method Similarities
echo ""
echo "🔗 Step 4: Creating method similarities using KNN..."
python "$SCRIPT_DIR/create_method_similarity.py" --top-k 5 --cutoff 0.8
echo "✅ Method similarities created"

# Step 5: Detect Communities
echo ""
echo "🏘️  Step 5: Detecting communities using Louvain..."
python "$SCRIPT_DIR/create_method_similarity.py" --no-knn --community-threshold 0.8
echo "✅ Communities detected"

# Step 6: Run Centrality Analysis
echo ""
echo "🎯 Step 6: Running centrality analysis to identify important methods..."
python "$SCRIPT_DIR/centrality_analysis.py" --algorithms pagerank betweenness degree --top-n 15 --write-back
echo "✅ Centrality analysis completed"

# Step 7: Advanced Analysis
echo ""
echo "🔥 Step 7: Running advanced analysis..."

echo "  📊 Analyzing file change coupling..."
python "$SCRIPT_DIR/analyze.py" coupling --min-support 5 --create-relationships
echo "  ✅ Change coupling analysis completed"

echo "  🔥 Analyzing code hotspots..."
python "$SCRIPT_DIR/analyze.py" hotspots --days 365 --min-changes 3 --top-n 15
echo "  ✅ Hotspot analysis completed"

# Step 8: Universal CVE Vulnerability Analysis
echo ""
echo "🛡️  Step 8: Universal vulnerability analysis..."
# Source .env if present for local runs
if [ -f ".env" ]; then
  set -o allexport
  # shellcheck disable=SC1091
  source .env
  set +o allexport
fi
if [ -n "${NVD_API_KEY}" ]; then
    echo "  🔍 Analyzing vulnerability impact using dynamic dependency extraction..."
    python "$SCRIPT_DIR/cve_analysis.py" --risk-threshold 7.0 --max-hops 4
    echo "  ✅ CVE analysis completed"
else
    echo "  ⚠️  NVD_API_KEY not found - skipping CVE analysis"
    echo "  💡 To enable CVE analysis:"
    echo "     1. Get API key: https://nvd.nist.gov/developers/request-an-api-key"
    echo "     2. Add to .env: NVD_API_KEY=your_key_here"
fi

echo ""
echo "🎉 Pipeline completed successfully!"
echo "Your Neo4j graph now contains:"
echo ""
echo "📁 Core Structure:"
echo "  - Comprehensive code structure (Files, Methods, Classes, Interfaces, Directories)"
echo "  - Object-oriented relationships (EXTENDS, IMPLEMENTS, CONTAINS_METHOD)"
echo "  - Method call graph (CALLS relationships with call types)"
echo "  - Rich metadata (LOC, modifiers, complexity metrics)"
echo ""
echo "📈 Temporal Analysis:"
echo "  - Complete Git history (Commits, Developers, File versions)"
echo "  - Change coupling analysis (CO_CHANGED relationships)"
echo "  - Multi-factor hotspot scoring (frequency × complexity)"
echo ""
echo "🧠 Semantic Analysis:"
echo "  - GraphCodeBERT embeddings (768-dimensional method similarity)"
echo "  - K-NN similarity networks with tunable similarity thresholds"
echo "  - Community detection via Louvain algorithm"
echo ""
echo "⭐ Graph-Theoretic Insights:"
echo "  - PageRank centrality (overall importance in call graph)"
echo "  - Betweenness centrality (critical connectors and bottlenecks)"
echo "  - Degree centrality (hub methods and high-activity components)"
echo ""
echo "🛡️  Security Analysis:"
echo "  - Universal CVE vulnerability impact analysis"
echo "  - Language-agnostic dependency tracking"
echo "  - Multi-hop vulnerability propagation analysis"
echo ""
echo "🔍 Next Steps:"
echo "  1. Explore the graph via Neo4j Browser"
echo "  2. Run example queries from examples/ directory"
echo "  3. Build custom analyses using the rich graph structure"
echo ""
echo "📊 For interactive CVE analysis, run:"
echo "     python examples/cve_demo_queries.py"
