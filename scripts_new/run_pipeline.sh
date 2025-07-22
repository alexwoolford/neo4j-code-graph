#!/bin/bash

# Neo4j Code Graph Analysis Pipeline
# Run this script to execute the complete analysis pipeline on any Git repository

set -e  # Exit on any error

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
python "$SCRIPT_DIR/cleanup_graph.py" --dry-run
read -p "Proceed with cleanup? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    python "$SCRIPT_DIR/cleanup_graph.py"
    echo "✅ Cleanup completed"
else
    echo "⚠️  Skipping cleanup - you may have duplicate data"
fi

# Step 1: Load Code Structure (Java files and methods with embeddings)
echo ""
echo "📝 Step 1: Loading Java code structure with embeddings..."
echo "⏰ This step may take a while for large repositories..."
python "$SCRIPT_DIR/code_to_graph.py" "$REPO_URL"
echo "✅ Code structure loaded"

# Step 2: Load Git History (commits and developer data)
echo ""
echo "📚 Step 2: Loading Git commit history..."
python "$SCRIPT_DIR/git_history_to_graph.py" "$REPO_URL"
echo "✅ Git history loaded"

# Step 3: Create Method Similarities  
echo ""
echo "🔗 Step 3: Creating method similarities using KNN..."
python "$SCRIPT_DIR/create_method_similarity.py" --top-k 5 --cutoff 0.8
echo "✅ Method similarities created"

# Step 4: Detect Communities
echo ""
echo "🏘️  Step 4: Detecting communities using Louvain..."
python "$SCRIPT_DIR/create_method_similarity.py" --no-knn --community-threshold 0.8
echo "✅ Communities detected"

# Step 5: Run Centrality Analysis
echo ""
echo "🎯 Step 5: Running centrality analysis to identify important methods..."
python "$SCRIPT_DIR/centrality_analysis.py" --algorithms pagerank betweenness degree --top-n 15 --write-back
echo "✅ Centrality analysis completed"

# Step 6: Enhanced Analysis
echo ""
echo "🔥 Step 6: Running enhanced analysis..."

echo "  📊 Analyzing file change coupling..."
python "$SCRIPT_DIR/analyze.py" coupling --min-support 5 --create-relationships
echo "  ✅ Change coupling analysis completed"

echo "  🔥 Analyzing code hotspots..."
python "$SCRIPT_DIR/analyze.py" hotspots --days 365 --min-changes 3 --top-n 15
echo "  ✅ Hotspot analysis completed"

# Step 7: Universal CVE Vulnerability Analysis
echo ""
echo "🛡️  Step 7: Universal vulnerability analysis..."
if [ -n "${NVD_API_KEY}" ] || [ -f ".env" ]; then
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
echo "🎉 Enhanced Pipeline completed successfully!"
echo "Your Neo4j graph now contains:"
echo ""
echo "📁 Core Structure:"
echo "  - Enhanced code structure (Files, Methods, Classes, Interfaces, Directories)"
echo "  - Object-oriented relationships (EXTENDS, IMPLEMENTS, CONTAINS_METHOD)"
echo "  - Method call graph (CALLS relationships with call types)"
echo "  - Rich metadata (LOC, modifiers, complexity metrics)"
echo ""
echo "📈 Temporal Analysis:"
echo "  - Complete Git history (Commits, Developers, File versions)"
echo "  - Change coupling analysis (CO_CHANGED relationships)"
echo "  - Enhanced hotspot scoring (frequency × complexity)"
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