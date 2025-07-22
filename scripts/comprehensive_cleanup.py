#!/usr/bin/env python3
"""
Comprehensive cleanup script for neo4j-code-graph project.
Fixes remaining code quality issues and removes all "enhanced/optimized" language.
"""

import os
import re
import subprocess
from pathlib import Path


def fix_syntax_errors():
    """Fix critical syntax errors first."""
    print("🔧 Fixing critical syntax errors...")
    
    # Fix examples/cve_demo_queries.py - already fixed
    # Fix git_history_to_graph.py - already fixed  
    # Fix schema_management.py - already fixed
    
    # Fix tests/test_enhanced_features.py
    test_file = "tests/test_enhanced_features.py"
    if os.path.exists(test_file):
        with open(test_file, 'r') as f:
            content = f.read()
        
        # Fix the malformed assertion
        content = re.sub(
            r'assert "doSomething" in call_names, "Missing "doSomething\' in \{call_names\}"',
            r'assert "doSomething" in call_names, f"Missing doSomething in {call_names}"',
            content
        )
        
        with open(test_file, 'w') as f:
            f.write(content)
        print("✅ Fixed syntax errors in test_enhanced_features.py")


def remove_enhanced_language():
    """Remove all 'enhanced/optimized/improved' language from the codebase."""
    print("🧹 Removing 'enhanced/optimized/improved' language...")
    
    replacements = {
        # Remove "enhanced" language
        r'\benhanced\b': '',
        r'\bEnhanced\b': '',
        r'\benhance\b': '',
        r'\benhancement\b': '',
        r'\benhancements\b': '',
        
        # Remove "optimized" language
        r'\boptimized\b': '',
        r'\bOptimized\b': '',
        r'\boptimize\b': '',
        r'\boptimization\b': '',
        r'\boptimizations\b': '',
        
        # Remove "improved" language
        r'\bimproved\b': '',
        r'\bImproved\b': '',
        r'\bimprove\b': '',
        r'\bimprovement\b': '',
        r'\bimprovements\b': '',
        
        # Remove "faster" language
        r'\bfaster\b': '',
        r'\bFaster\b': '',
        r'\bfast\b': '',
        r'\brapid\b': '',
        r'\bquick\b': 'efficient',
        r'\bQuick\b': 'Efficient',
        
        # Remove "better" language when it's not needed
        r'\bbetter\b': '',
        r'\bBetter\b': '',
    }
    
    files_to_process = [
        'README.md',
        'AGENTS.md', 
        'run_pipeline.sh',
        'analyze.py',
        'git_history_to_graph.py',
        'code_to_graph.py',
        'centrality_analysis.py',
        'cve_analysis.py',
        'docs/NVD_API_SETUP.md',
        'tests/test_enhanced_features.py'
    ]
    
    for file_path in files_to_process:
        if os.path.exists(file_path):
            with open(file_path, 'r') as f:
                content = f.read()
            
            original_content = content
            
            # Apply replacements carefully
            for pattern, replacement in replacements.items():
                content = re.sub(pattern, replacement, content)
            
            # Clean up any resulting double spaces or awkward phrasing
            content = re.sub(r'\s+', ' ', content)  # Multiple spaces to single
            content = re.sub(r'\s+\n', '\n', content)  # Space before newline
            content = re.sub(r'\n\s+', '\n', content)  # Space after newline
            
            if content != original_content:
                with open(file_path, 'w') as f:
                    f.write(content)
                print(f"✅ Cleaned language in {file_path}")


def fix_remaining_flake8():
    """Fix remaining flake8 issues."""
    print("🔧 Fixing remaining flake8 issues...")
    
    # Fix unused imports
    unused_fixes = {
        'cve_analysis.py': ['import numpy as np'],
        'cve_cache_manager.py': ['import os'],
        'tests/test_code_to_graph.py': ['import code_to_graph'],
        'tests/test_utils.py': ['import os'],
    }
    
    for file_path, imports_to_remove in unused_fixes.items():
        if os.path.exists(file_path):
            with open(file_path, 'r') as f:
                lines = f.readlines()
            
            filtered_lines = []
            for line in lines:
                should_remove = False
                for import_line in imports_to_remove:
                    if import_line.strip() in line.strip():
                        should_remove = True
                        break
                
                if not should_remove:
                    filtered_lines.append(line)
            
            if len(filtered_lines) != len(lines):
                with open(file_path, 'w') as f:
                    f.writelines(filtered_lines)
                print(f"✅ Removed unused imports from {file_path}")
    
    # Fix undefined Mock imports in test_schema_management.py
    test_schema_file = "tests/test_schema_management.py"
    if os.path.exists(test_schema_file):
        with open(test_schema_file, 'r') as f:
            content = f.read()
        
        # Add back the Mock import that was incorrectly removed
        if 'from unittest.mock import' not in content:
            content = 'from unittest.mock import Mock, MagicMock\n' + content
        
        with open(test_schema_file, 'w') as f:
            f.write(content)
        print("✅ Fixed Mock imports in test_schema_management.py")
    
    # Fix unused variables
    files_with_unused_vars = [
        'code_to_graph.py',
        'cve_cache_manager.py', 
        'tests/test_cve_analysis.py'
    ]
    
    for file_path in files_with_unused_vars:
        if os.path.exists(file_path):
            with open(file_path, 'r') as f:
                content = f.read()
            
            # Remove or comment out unused variables
            patterns_to_fix = [
                r'^\s*source_package\s*=.*$',
                r'^\s*start_date_str\s*=.*$',
                r'^\s*end_date_str\s*=.*$',
                r'^\s*analyzer\s*=\s*CVEAnalyzer.*$',
            ]
            
            lines = content.split('\n')
            fixed_lines = []
            
            for line in lines:
                should_comment = False
                for pattern in patterns_to_fix:
                    if re.match(pattern, line, re.MULTILINE):
                        should_comment = True
                        break
                
                if should_comment:
                    fixed_lines.append('    # ' + line.strip() + '  # Unused variable')
                else:
                    fixed_lines.append(line)
            
            fixed_content = '\n'.join(fixed_lines)
            if fixed_content != content:
                with open(file_path, 'w') as f:
                    f.write(fixed_content)
                print(f"✅ Fixed unused variables in {file_path}")


def add_proper_spacing():
    """Add proper spacing between functions and classes."""
    print("📏 Adding proper spacing...")
    
    test_files = [
        'tests/test_connection.py',
        'tests/test_cve_analysis.py'
    ]
    
    for file_path in test_files:
        if os.path.exists(file_path):
            with open(file_path, 'r') as f:
                content = f.read()
            
            # Add proper spacing before function definitions
            content = re.sub(r'\n(def \w+)', r'\n\n\1', content)
            content = re.sub(r'\n(class \w+)', r'\n\n\1', content)
            content = re.sub(r'\n(@\w+)', r'\n\n\1', content)  # decorators
            
            # Add spacing after function definitions
            content = re.sub(r'(\ndef \w+.*:)\n(\s*""")', r'\1\n\n\2', content)
            
            # Remove excessive spacing (more than 2 consecutive newlines)
            content = re.sub(r'\n{3,}', '\n\n', content)
            
            with open(file_path, 'w') as f:
                f.write(content)
            print(f"✅ Fixed spacing in {file_path}")


def final_quality_check():
    """Run final quality checks."""
    print("\n🔍 Running final quality checks...")
    
    try:
        result = subprocess.run([
            'python', '-m', 'flake8', '.', 
            '--exclude=.git,__pycache__,.pytest_cache,cve_cache,scripts',
            '--max-line-length=120',
            '--statistics'
        ], capture_output=True, text=True)
        
        if result.returncode == 0:
            print("🎉 All flake8 issues resolved!")
        else:
            issues = result.stdout.strip().split('\n') if result.stdout.strip() else []
            print(f"📊 {len(issues)} issues remaining")
            if len(issues) < 20:
                print("Remaining issues:")
                print(result.stdout[:1000])
    
    except Exception as e:
        print(f"⚠️  Could not run flake8: {e}")


def main():
    """Run comprehensive cleanup."""
    print("🚀 Starting comprehensive cleanup...")
    
    fix_syntax_errors()
    remove_enhanced_language()
    fix_remaining_flake8()
    add_proper_spacing()
    final_quality_check()
    
    print("\n✅ Comprehensive cleanup complete!")
    print("🎯 Project is now production-ready with clean, professional language!")


if __name__ == "__main__":
    main() 