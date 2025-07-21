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

echo "🚀 Starting Neo4j Code Graph Analysis Pipeline"
echo "=============================================="
echo "📁 Repository: $REPO_URL"
echo ""

# Step 0: Clean up previous analysis (if any)
echo "🧹 Step 0: Cleaning up previous analysis..."
python cleanup_graph.py --dry-run
read -p "Proceed with cleanup? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    python cleanup_graph.py
    echo "✅ Cleanup completed"
else
    echo "⚠️  Skipping cleanup - you may have duplicate data"
fi

# Step 1: Load Code Structure (Java files and methods with embeddings)
echo ""
echo "📝 Step 1: Loading Java code structure with embeddings..."
echo "⏰ This step may take a while for large repositories..."
python code_to_graph.py "$REPO_URL"
echo "✅ Code structure loaded"

# Step 2: Load Git History (commits and developer data)
echo ""
echo "📚 Step 2: Loading Git commit history..."
python git_history_to_graph.py "$REPO_URL"
echo "✅ Git history loaded"

# Step 3: Create Method Similarities  
echo ""
echo "🔗 Step 3: Creating method similarities using KNN..."
python create_method_similarity.py --top-k 5 --cutoff 0.8
echo "✅ Method similarities created"

# Step 4: Detect Communities
echo ""
echo "🏘️  Step 4: Detecting communities using Louvain..."
python create_method_similarity.py --no-knn --community-threshold 0.8
echo "✅ Communities detected"

echo ""
echo "🎉 Pipeline completed successfully!"
echo "Your Neo4j graph now contains:"
echo "  - Code structure (Files, Methods, Directories) with embeddings"
echo "  - Git history (Commits, Developers, File versions)"  
echo "  - Method similarities (SIMILAR relationships with scores)"
echo "  - Community detection results (similarityCommunity property)"
echo ""
echo "💡 You can now explore the graph using Neo4j Browser or run Cypher queries!"
echo ""
echo "Example queries:"
echo "  // Find most similar methods"
echo "  MATCH (m1:Method)-[s:SIMILAR]->(m2:Method)"
echo "  RETURN m1.name, m2.name, s.score ORDER BY s.score DESC LIMIT 10"
echo ""
echo "  // Find prolific developers"  
echo "  MATCH (d:Developer)-[:AUTHORED]->(c:Commit)"
echo "  RETURN d.name, count(c) as commits ORDER BY commits DESC LIMIT 10" 