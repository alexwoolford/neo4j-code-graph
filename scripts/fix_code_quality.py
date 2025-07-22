#!/usr/bin/env python3
"""
Comprehensive code quality fixes for the neo4j-code-graph project.
"""

import os
import re
import subprocess
import sys
from pathlib import Path


def fix_whitespace_issues(file_path):
    """Fix trailing whitespace and blank lines with whitespace."""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Fix trailing whitespace
    lines = content.split('\n')
    fixed_lines = []

    for line in lines:
        # Remove trailing whitespace
        fixed_line = line.rstrip()
        fixed_lines.append(fixed_line)

    # Ensure file ends with newline
    if fixed_lines and fixed_lines[-1] != '':
        fixed_lines.append('')

    fixed_content = '\n'.join(fixed_lines)

    # Don't write if no changes
    if fixed_content != content:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(fixed_content)
        print(f"✅ Fixed whitespace in {file_path}")


def fix_boolean_comparisons(file_path):
    """Fix is True/False comparisons."""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    original_content = content

    # Fix is True comparisons
    content = re.sub(r'(\w+(?:\[.*?\])?(?:\..*?)?)\s*==\s*True\b', r'\1 is True', content)

    # Fix is False comparisons
    content = re.sub(r'(\w+(?:\[.*?\])?(?:\..*?)?)\s*==\s*False\b', r'\1 is False', content)

    if content != original_content:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"✅ Fixed boolean comparisons in {file_path}")


def remove_unused_imports(file_path):
    """Remove obvious unused imports."""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    lines = content.split('\n')
    fixed_lines = []
    imports_to_remove = []

    # Simple unused import detection
    unused_patterns = [
        (r'^import importlib$', 'importlib'),
        (r'^from unittest\.mock import.*patch.*', 'patch'),
        (r'^from unittest\.mock import.*MagicMock.*', 'MagicMock'),
        (r'^from neo4j import GraphDatabase$', 'GraphDatabase'),
        (r'^import os$', 'os'),
    ]

    for line in lines:
        should_remove = False

        for pattern, import_name in unused_patterns:
            if re.match(pattern, line.strip()):
                # Check if the import is actually used
                if import_name not in content or content.count(import_name) <= 1:
                    should_remove = True
                    imports_to_remove.append(line.strip())
                    break

        if not should_remove:
            fixed_lines.append(line)

    if imports_to_remove:
        fixed_content = '\n'.join(fixed_lines)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(fixed_content)
        print(f"✅ Removed unused imports in {file_path}: {imports_to_remove}")


def fix_line_length(file_path):
    """Fix basic line length issues."""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    lines = content.split('\n')
    fixed_lines = []

    for line in lines:
        if len(line) > 120 and 'CREATE CONSTRAINT' in line:
            # Break long constraint lines
            if 'IF NOT EXISTS FOR' in line:
                parts = line.split('IF NOT EXISTS FOR')
                if len(parts) == 2:
                    fixed_line = (parts[0].rstrip() + '\n' +
                                 '         "CREATE CONSTRAINT ' +
                                 parts[1].strip().replace('"CREATE CONSTRAINT ', ''))
                    fixed_lines.extend(fixed_line.split('\n'))
                    continue

        fixed_lines.append(line)

    fixed_content = '\n'.join(fixed_lines)
    if fixed_content != content:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(fixed_content)
        print(f"✅ Fixed line length issues in {file_path}")


def remove_unused_variables(file_path):
    """Remove obvious unused variables."""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Simple patterns for unused variables
    unused_patterns = [
        r'^\s*(\w+)\s*=\s*inspect\.signature\(.*\).*# F841',
        r'^\s*call_names\s*=\s*\[.*\].*# F841',
        r'^\s*source_package\s*=.*# F841',
    ]

    lines = content.split('\n')
    fixed_lines = []

    for line in lines:
        should_remove = False
        for pattern in unused_patterns:
            if re.search(pattern, line):
                should_remove = True
                break

        if not should_remove:
            fixed_lines.append(line)

    fixed_content = '\n'.join(fixed_lines)
    if fixed_content != content:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(fixed_content)
        print(f"✅ Removed unused variables in {file_path}")


def fix_f_string_placeholders(file_path):
    """Fix f-strings without placeholders."""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Find f-strings that don't actually need to be f-strings
    f_string_pattern = r'f["\']([^"\'{}]*)["\']'

    def replace_unnecessary_fstring(match):
        inner_content = match.group(1)
        if '{' not in inner_content and '}' not in inner_content:
            return ""{inner_content}"'
        return match.group(0)

    fixed_content = re.sub(f_string_pattern, replace_unnecessary_fstring, content)

    if fixed_content != content:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(fixed_content)
        print(f"✅ Fixed f-string placeholders in {file_path}")


def fix_python_file(file_path):
    """Apply all fixes to a Python file."""
    print(f"🔧 Processing {file_path}")

    try:
        fix_whitespace_issues(file_path)
        fix_boolean_comparisons(file_path)
        remove_unused_imports(file_path)
        fix_line_length(file_path)
        remove_unused_variables(file_path)
        fix_f_string_placeholders(file_path)
    except Exception as e:
        print(f"❌ Error processing {file_path}: {e}")


def main():
    """Main function to fix all Python files."""
    print("🚀 Starting comprehensive code quality fixes...")

    # Find all Python files
    python_files = []
    for root, dirs, files in os.walk('.'):
        # Skip certain directories
        dirs[:] = [d for d in dirs if d not in {'.git', '__pycache__', '.pytest_cache', 'cve_cache'}]

        for file in files:
            if file.endswith('.py'):
                python_files.append(os.path.join(root, file))

    print(f"📝 Found {len(python_files)} Python files to process")

    for file_path in sorted(python_files):
        fix_python_file(file_path)

    print("\n✅ Code quality fixes complete!")
    print("🔍 Running flake8 to check remaining issues...")

    # Run flake8 to see what's left
    try:
        result = subprocess.run([
            'python', '-m', 'flake8', '.',
            '--exclude=.git,__pycache__,.pytest_cache,cve_cache',
            '--max-line-length=120',
            '--statistics'
        ], capture_output=True, text=True)

        if result.returncode == 0:
            print("🎉 All flake8 issues resolved!")
        else:
            remaining_issues = len(result.stdout.strip().split('\n')) if result.stdout.strip() else 0
            print(f"📊 {remaining_issues} issues remaining - manual review needed")
            if remaining_issues < 50:
                print("Sample remaining issues:")
                print(result.stdout[:500])

    except Exception as e:
        print(f"⚠️  Could not run flake8: {e}")


if __name__ == "__main__":
    main()
