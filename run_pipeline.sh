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

# Step 5: Run Centrality Analysis
echo ""
echo "🎯 Step 5: Running centrality analysis to identify important methods..."
python centrality_analysis.py --algorithms pagerank betweenness degree --top-n 15 --write-back
echo "✅ Centrality analysis completed"

# Step 6: Enhanced Analysis
echo ""
echo "🔥 Step 6: Running enhanced analysis..."

echo "  📊 Analyzing file change coupling..."
python analyze.py coupling --min-support 3 --create-relationships
echo "  ✅ Change coupling analysis completed"

echo "  🔥 Analyzing code hotspots..."
python analyze.py hotspots --days 365 --min-changes 3 --top-n 15
echo "  ✅ Hotspot analysis completed"

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
echo "  - Method similarities (SIMILAR relationships with scores)"
echo "  - Community detection (similarityCommunity properties)"
echo "  - Centrality scores (PageRank, Betweenness, Degree on methods)"
echo ""
echo "💡 You can now perform advanced code analysis queries!"
echo ""
echo "🔍 Example Advanced Queries:"
echo ""
echo "  // Find architecturally most important methods (PageRank)"
echo "  MATCH (m:Method) WHERE m.pagerank_score IS NOT NULL"
echo "  RETURN m.class + '.' + m.name as method, m.pagerank_score, m.file"
echo "  ORDER BY m.pagerank_score DESC LIMIT 10"
echo ""
echo "  // Find inheritance hierarchies"
echo "  MATCH path = (leaf:Class)-[:EXTENDS*]->(root:Class)"
echo "  WHERE NOT (root)-[:EXTENDS]->()"
echo "  RETURN leaf.name, root.name, length(path) as depth ORDER BY depth DESC"
echo ""
echo "  // Find code hotspots (high complexity + frequent changes)"
echo "  MATCH (f:File) WHERE f.total_lines > 100"
echo "  OPTIONAL MATCH (f)<-[:OF_FILE]-(fv)<-[:CHANGED]-(c:Commit)"
echo "  WHERE c.date >= datetime() - duration('P180D')"
echo "  WITH f, count(c) as changes"
echo "  RETURN f.path, changes, f.total_lines, f.class_count"
echo "  ORDER BY (changes * f.total_lines) DESC LIMIT 10"
echo ""
echo "  // Find files that change together (coupling)"
echo "  MATCH (f1:File)-[co:CO_CHANGED]->(f2:File) WHERE co.support > 5"
echo "  RETURN f1.path, f2.path, co.support ORDER BY co.support DESC LIMIT 10" 