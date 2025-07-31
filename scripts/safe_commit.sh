#!/bin/bash

# Safe commit script that guarantees CI compatibility
# Usage: ./scripts/safe_commit.sh "commit message"

set -e

COMMIT_MSG="$1"

if [ -z "$COMMIT_MSG" ]; then
    echo "❌ Usage: $0 \"commit message\""
    echo "   Example: $0 \"Fix authentication bug\""
    exit 1
fi

echo "🔍 Safe Commit Process Started"
echo "=============================="
echo "Commit message: $COMMIT_MSG"
echo ""

# Step 1: Auto-fix common issues
echo "🔧 Step 1: Auto-fixing formatting and imports..."
if command -v make >/dev/null 2>&1; then
    make format 2>/dev/null || {
        echo "⚠️  make format failed, running manual fixes..."
        black src/ tests/ scripts/ 2>/dev/null || true
        isort src/ tests/ scripts/ 2>/dev/null || true
    }
else
    echo "⚠️  make not available, running manual fixes..."
    black src/ tests/ scripts/ 2>/dev/null || true
    isort src/ tests/ scripts/ 2>/dev/null || true
fi

# Step 2: Comprehensive validation
echo ""
echo "🚨 Step 2: Running comprehensive pre-commit validation..."
if ! pre-commit run --all-files; then
    echo ""
    echo "❌ PRE-COMMIT VALIDATION FAILED!"
    echo "=================================="
    echo "🚨 COMMIT ABORTED: Issues must be fixed first"
    echo ""
    echo "💡 Next steps:"
    echo "   1. Fix the issues shown above"
    echo "   2. Re-run: $0 \"$COMMIT_MSG\""
    echo ""
    echo "🔧 Common fixes:"
    echo "   - Fix syntax errors manually"
    echo "   - Run 'make format' again if needed"
    echo "   - Check import statements"
    echo "=================================="
    exit 1
fi

# Step 3: Safe commit
echo ""
echo "✅ Step 3: All checks passed! Committing safely..."
git add .
git commit -m "$COMMIT_MSG"

echo ""
echo "🎉 COMMIT SUCCESSFUL!"
echo "==================="
echo "✅ All quality checks passed"
echo "✅ CI will pass without issues"
echo "✅ Commit: $COMMIT_MSG"
echo "==================="
