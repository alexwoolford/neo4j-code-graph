#!/usr/bin/env python3
"""
Unified analysis tool for neo4j-code-graph.
Consolidates all analysis functions into a single CLI with subcommands.
"""

import argparse
import logging
import sys
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict, Counter
from itertools import combinations

import javalang
from neo4j import GraphDatabase
from common import setup_logging, create_neo4j_driver, add_common_args

logger = logging.getLogger(__name__)


# === CHANGE COUPLING ANALYSIS ===
def analyze_change_coupling(session, args):
    """Analyze file change co-occurrence and create relationships."""
    logger.info("Analyzing file change co-occurrence...")
    
    # Extract commit-file data
    query = """
    MATCH (c:Commit)-[:CHANGED]->(fv:FileVer)-[:OF_FILE]->(f:File)
    RETURN c.sha as commit_sha, f.path as file_path
    ORDER BY c.sha
    """
    
    result = session.run(query)
    commits_to_files = defaultdict(set)
    for record in result:
        commits_to_files[record["commit_sha"]].add(record["file_path"])
    
    if not commits_to_files:
        logger.error("No commit-file data found. Run git_history_to_graph.py first.")
        return
    
    logger.info(f"Found {len(commits_to_files)} commits affecting files")
    
    # Calculate co-occurrences
    pair_counts = Counter()
    file_counts = Counter()
    
    for commit_sha, files in commits_to_files.items():
        for file_path in files:
            file_counts[file_path] += 1
        
        if len(files) > 1:
            for file_pair in combinations(sorted(files), 2):
                pair_counts[file_pair] += 1
    
    # Filter and calculate confidence
    frequent_pairs = {
        pair: count for pair, count in pair_counts.items() 
        if count >= args.min_support
    }
    
    logger.info(f"Found {len(frequent_pairs)} file pairs with co-occurrence >= {args.min_support}")
    
    # Create relationships if requested
    if args.create_relationships:
        logger.info("Creating CO_CHANGED relationships...")
        relationships_created = 0
        batch_size = 100
        batch = []
        
        for (file_a, file_b), support in frequent_pairs.items():
            count_a = file_counts[file_a]
            count_b = file_counts[file_b]
            confidence = max(support / count_a, support / count_b)
            
            if confidence >= args.min_confidence:
                batch.append({
                    'file_a': file_a,
                    'file_b': file_b,
                    'support': support,
                    'confidence': confidence
                })
                
                if len(batch) >= batch_size:
                    _create_coupling_batch(session, batch)
                    relationships_created += len(batch)
                    batch = []
        
        if batch:
            _create_coupling_batch(session, batch)
            relationships_created += len(batch)
        
        logger.info(f"Created {relationships_created} CO_CHANGED relationships")
    
    # Print top results
    _print_coupling_results(frequent_pairs, file_counts, args.min_confidence)


def _create_coupling_batch(session, batch):
    """Create a batch of CO_CHANGED relationships."""
    query = """
    UNWIND $relationships as rel
    MATCH (a:File {path: rel.file_a})
    MATCH (b:File {path: rel.file_b})
    MERGE (a)-[r:CO_CHANGED]->(b)
    SET r.support = rel.support, r.confidence = rel.confidence
    MERGE (b)-[r2:CO_CHANGED]->(a)
    SET r2.support = rel.support, r2.confidence = rel.confidence
    """
    session.run(query, relationships=batch)


def _print_coupling_results(frequent_pairs, file_counts, min_confidence, top_n=20):
    """Print top coupling results."""
    co_occurrences = []
    for (file_a, file_b), support in frequent_pairs.items():
        count_a = file_counts[file_a]
        count_b = file_counts[file_b]
        confidence = max(support / count_a, support / count_b)
        
        if confidence >= min_confidence:
            co_occurrences.append({
                'file_a': file_a,
                'file_b': file_b,
                'support': support,
                'confidence': confidence
            })
    
    co_occurrences.sort(key=lambda x: x['support'], reverse=True)
    
    print("\n" + "="*100)
    print(f"TOP {min(top_n, len(co_occurrences))} FILE CO-OCCURRENCES")
    print("="*100)
    print(f"{'File A':<40} {'File B':<40} {'Support':<8} {'Confidence':<10}")
    print("-"*100)
    
    for co_occ in co_occurrences[:top_n]:
        print(f"{co_occ['file_a'][:39]:<40} {co_occ['file_b'][:39]:<40} "
              f"{co_occ['support']:<8} {co_occ['confidence']:<10.3f}")


# === CODE METRICS ===
def add_code_metrics(session, args):
    """Add code metrics to File and Method nodes."""
    if not Path(args.repo_path).exists():
        logger.error(f"Repository path does not exist: {args.repo_path}")
        return
    
    # Update file metrics
    files = _get_files_needing_metrics(session)
    logger.info(f"Found {len(files)} files needing metrics")
    
    updated = 0
    batch = []
    batch_size = 50
    
    for file_path in files:
        full_path = Path(args.repo_path) / file_path
        
        if not full_path.exists():
            continue
        
        metrics = _calculate_file_metrics(full_path)
        if not metrics:
            continue
        
        batch.append({
            'path': file_path,
            'total_lines': metrics['total_lines'],
            'code_lines': metrics['code_lines'],
            'comment_lines': metrics['comment_lines'],
            'class_count': metrics['class_count'],
            'interface_count': metrics['interface_count'],
            'method_count': metrics['method_count'],
            'file_size_bytes': metrics['file_size_bytes']
        })
        
        if len(batch) >= batch_size:
            if not args.dry_run:
                _update_file_batch(session, batch)
            updated += len(batch)
            logger.info(f"Updated metrics for {updated} files...")
            batch = []
    
    if batch:
        if not args.dry_run:
            _update_file_batch(session, batch)
        updated += len(batch)
    
    logger.info(f"{'Would update' if args.dry_run else 'Updated'} metrics for {updated} files")
    
    if not args.dry_run:
        _print_metrics_summary(session)


def _get_files_needing_metrics(session):
    """Get files that don't have metrics yet."""
    query = """
    MATCH (f:File)
    WHERE f.total_lines IS NULL
    RETURN f.path as path
    ORDER BY f.path
    """
    result = session.run(query)
    return [record["path"] for record in result]


def _calculate_file_metrics(file_path):
    """Calculate metrics for a Java file."""
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        lines = content.split('\n')
        total_lines = len(lines)
        code_lines = len([line for line in lines if line.strip() and not line.strip().startswith('//')])
        comment_lines = len([line for line in lines if line.strip().startswith('//')])
        
        # Count classes and methods
        try:
            tree = javalang.parse.parse(content)
            classes = len(list(tree.filter(javalang.tree.ClassDeclaration)))
            interfaces = len(list(tree.filter(javalang.tree.InterfaceDeclaration)))
            methods = len(list(tree.filter(javalang.tree.MethodDeclaration)))
        except:
            classes = interfaces = methods = 0
        
        return {
            'total_lines': total_lines,
            'code_lines': code_lines,
            'comment_lines': comment_lines,
            'class_count': classes,
            'interface_count': interfaces,
            'method_count': methods,
            'file_size_bytes': len(content.encode('utf-8'))
        }
    except Exception as e:
        logger.warning(f"Could not calculate metrics for {file_path}: {e}")
        return None


def _update_file_batch(session, batch):
    """Update a batch of file metrics."""
    query = """
    UNWIND $files as file
    MATCH (f:File {path: file.path})
    SET f.total_lines = file.total_lines,
        f.code_lines = file.code_lines,
        f.comment_lines = file.comment_lines,
        f.class_count = file.class_count,
        f.interface_count = file.interface_count,
        f.method_count = file.method_count,
        f.file_size_bytes = file.file_size_bytes
    """
    session.run(query, files=batch)


def _print_metrics_summary(session):
    """Print a summary of the metrics added."""
    print("\n" + "="*80)
    print("CODE METRICS SUMMARY")
    print("="*80)
    
    # File metrics summary
    file_query = """
    MATCH (f:File)
    WHERE f.total_lines IS NOT NULL
    RETURN 
        count(f) as file_count,
        avg(f.total_lines) as avg_total_lines,
        max(f.total_lines) as max_total_lines,
        avg(f.method_count) as avg_methods_per_file,
        max(f.method_count) as max_methods_per_file
    """
    result = session.run(file_query).single()
    
    print(f"Files with metrics: {result['file_count']}")
    print(f"Average file size: {result['avg_total_lines']:.1f} lines")
    print(f"Largest file: {result['max_total_lines']} lines")
    print(f"Average methods per file: {result['avg_methods_per_file']:.1f}")
    print(f"File with most methods: {result['max_methods_per_file']}")


# === HOTSPOT ANALYSIS ===
def analyze_hotspots(session, args):
    """Analyze code hotspots combining change frequency with complexity."""
    logger.info(f"Analyzing hotspots for last {args.days} days...")
    
    # Calculate cutoff date - handle both string and datetime
    cutoff_date = datetime.now() - timedelta(days=args.days)
    
    file_hotspots = _calculate_file_hotspots(session, cutoff_date, args.min_changes, args.min_size)
    
    if not file_hotspots:
        logger.warning("No file hotspots found. Ensure git history and code metrics are loaded.")
        return
    
    method_hotspots = _calculate_method_hotspots(session, cutoff_date, args.min_changes)
    coupling_hotspots = _find_coupling_hotspots(session)
    
    _print_hotspot_summary(file_hotspots, method_hotspots, coupling_hotspots, args.top_n)


def _calculate_file_hotspots(session, cutoff_date, min_changes, min_size):
    """Calculate hotspot scores for files."""
    # Use datetime comparison directly since dates are now datetime objects
    query = """
    MATCH (f:File)
    OPTIONAL MATCH (f)<-[:OF_FILE]-(fv:FileVer)<-[:CHANGED]-(c:Commit)
    WHERE c.date >= $cutoff_date
    WITH f, count(DISTINCT c) as change_count
    WHERE f.total_lines >= $min_size 
      AND change_count >= $min_changes
    RETURN 
        f.path as file_path,
        f.total_lines as total_lines,
        f.code_lines as code_lines,
        f.method_count as method_count,
        change_count,
        (change_count * f.total_lines) as hotspot_score
    ORDER BY hotspot_score DESC
    """
    
    result = session.run(query, 
                        cutoff_date=cutoff_date,  # Pass datetime directly
                        min_size=min_size, 
                        min_changes=min_changes)
    
    hotspots = []
    for record in result:
        hotspots.append({
            'file_path': record['file_path'],
            'total_lines': record['total_lines'] or 0,
            'code_lines': record['code_lines'] or 0,
            'method_count': record['method_count'] or 0,
            'change_count': record['change_count'],
            'hotspot_score': record['hotspot_score'],
            'changes_per_100_lines': (record['change_count'] * 100.0 / record['total_lines']) if record['total_lines'] else 0
        })
    
    logger.info(f"Found {len(hotspots)} file hotspots")
    return hotspots


def _calculate_method_hotspots(session, cutoff_date, min_changes):
    """Calculate method hotspots based on file changes."""
    query = """
    MATCH (m:Method)-[:DECLARED_BY]->(f:File)
    OPTIONAL MATCH (f)<-[:OF_FILE]-(fv:FileVer)<-[:CHANGED]-(c:Commit)
    WHERE c.date >= $cutoff_date
    WITH m, f, count(DISTINCT c) as file_change_count
    WHERE file_change_count >= $min_changes
    RETURN 
        m.name as method_name,
        m.file as file_path,
        m.line as line_number,
        m.class as class_name,
        m.estimated_lines as estimated_lines,
        file_change_count,
        (file_change_count * COALESCE(m.estimated_lines, 20)) as method_hotspot_score
    ORDER BY method_hotspot_score DESC
    LIMIT 50
    """
    
    result = session.run(query, cutoff_date=cutoff_date, min_changes=min_changes)
    
    method_hotspots = []
    for record in result:
        method_hotspots.append({
            'method_name': record['method_name'],
            'file_path': record['file_path'],
            'line_number': record['line_number'],
            'class_name': record['class_name'] or 'N/A',
            'estimated_lines': record['estimated_lines'] or 20,
            'file_change_count': record['file_change_count'],
            'method_hotspot_score': record['method_hotspot_score']
        })
    
    return method_hotspots


def _find_coupling_hotspots(session, min_support=5):
    """Find files that are both hotspots AND highly coupled."""
    query = """
    MATCH (f:File)
    WHERE f.total_lines IS NOT NULL
    OPTIONAL MATCH (f)-[co:CO_CHANGED]->(other:File)
    WHERE co.support >= $min_support
    WITH f, count(co) as coupling_count, sum(co.support) as total_coupling_strength
    WHERE coupling_count > 0
    OPTIONAL MATCH (f)<-[:OF_FILE]-(fv:FileVer)<-[:CHANGED]-(c:Commit)
    WITH f, coupling_count, total_coupling_strength, count(DISTINCT c) as change_count
    WHERE change_count >= 3
    RETURN 
        f.path as file_path,
        f.total_lines as total_lines,
        change_count,
        coupling_count,
        total_coupling_strength,
        (change_count * coupling_count * f.total_lines) as complexity_hotspot_score
    ORDER BY complexity_hotspot_score DESC
    LIMIT 20
    """
    
    result = session.run(query, min_support=min_support)
    
    coupling_hotspots = []
    for record in result:
        coupling_hotspots.append({
            'file_path': record['file_path'],
            'total_lines': record['total_lines'],
            'change_count': record['change_count'],
            'coupling_count': record['coupling_count'],
            'total_coupling_strength': record['total_coupling_strength'],
            'complexity_hotspot_score': record['complexity_hotspot_score']
        })
    
    return coupling_hotspots


def _print_hotspot_summary(file_hotspots, method_hotspots, coupling_hotspots, top_n=20):
    """Print comprehensive hotspot analysis."""
    print("\n" + "="*100)
    print("🔥 CODE HOTSPOT ANALYSIS")
    print("="*100)
    
    # File hotspots
    print(f"\n📁 TOP {min(top_n, len(file_hotspots))} FILE HOTSPOTS")
    print("(Files with high change frequency × size)")
    print("-" * 100)
    print(f"{'File':<50} {'Lines':<8} {'Changes':<8} {'Score':<10} {'Chg/100L':<8}")
    print("-" * 100)
    
    for hotspot in file_hotspots[:top_n]:
        print(f"{hotspot['file_path'][:49]:<50} "
              f"{hotspot['total_lines']:<8} "
              f"{hotspot['change_count']:<8} "
              f"{hotspot['hotspot_score']:<10} "
              f"{hotspot['changes_per_100_lines']:<8.1f}")
    
    # Method hotspots
    if method_hotspots:
        print(f"\n🔧 TOP 10 METHOD HOTSPOTS")
        print("-" * 100)
        print(f"{'Method':<30} {'Class':<25} {'File':<30} {'Score':<10}")
        print("-" * 100)
        
        for hotspot in method_hotspots[:10]:
            method_display = hotspot['method_name'][:29]
            class_display = hotspot['class_name'][:24]
            file_display = hotspot['file_path'].split('/')[-1][:29]
            
            print(f"{method_display:<30} "
                  f"{class_display:<25} "
                  f"{file_display:<30} "
                  f"{hotspot['method_hotspot_score']:<10}")
    
    # Coupling hotspots
    if coupling_hotspots:
        print(f"\n🔗 TOP 10 HIGH-COUPLING HOTSPOTS")
        print("-" * 100)
        print(f"{'File':<50} {'Changes':<8} {'Coupled':<8} {'Score':<10}")
        print("-" * 100)
        
        for hotspot in coupling_hotspots[:10]:
            print(f"{hotspot['file_path'][:49]:<50} "
                  f"{hotspot['change_count']:<8} "
                  f"{hotspot['coupling_count']:<8} "
                  f"{hotspot['complexity_hotspot_score']:<10}")


# === MAIN CLI ===
def create_parser():
    """Create the main argument parser with subcommands."""
    parser = argparse.ArgumentParser(
        description="Unified analysis tool for neo4j-code-graph",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Analyze file change coupling
  python analyze.py coupling --min-support 3 --create-relationships
  
  # Add code metrics  
  python analyze.py metrics --repo-path /path/to/repo
  
  # Find hotspots
  python analyze.py hotspots --days 180 --min-changes 5
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Analysis commands')
    
    # Coupling analysis
    coupling_parser = subparsers.add_parser('coupling', help='Analyze file change coupling')
    add_common_args(coupling_parser)
    coupling_parser.add_argument('--min-support', type=int, default=3,
                                help='Minimum co-occurrence count (default: 3)')
    coupling_parser.add_argument('--min-confidence', type=float, default=0.5,
                                help='Minimum confidence score (default: 0.5)')
    coupling_parser.add_argument('--create-relationships', action='store_true',
                                help='Create CO_CHANGED relationships in Neo4j')
    
    # Code metrics
    metrics_parser = subparsers.add_parser('metrics', help='Add code metrics to graph')
    add_common_args(metrics_parser)
    metrics_parser.add_argument('--repo-path', required=True,
                               help='Path to local repository')
    metrics_parser.add_argument('--dry-run', action='store_true',
                               help='Preview changes without updating')
    
    # Hotspot analysis
    hotspots_parser = subparsers.add_parser('hotspots', help='Analyze code hotspots')
    add_common_args(hotspots_parser)
    hotspots_parser.add_argument('--days', type=int, default=365,
                                help='Analyze last N days (default: 365)')
    hotspots_parser.add_argument('--min-changes', type=int, default=3,
                                help='Minimum changes for hotspot (default: 3)')
    hotspots_parser.add_argument('--min-size', type=int, default=50,
                                help='Minimum file size for hotspot (default: 50)')
    hotspots_parser.add_argument('--top-n', type=int, default=20,
                                help='Show top N results (default: 20)')
    
    return parser


def main():
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    setup_logging(args.log_level, args.log_file)
    driver = create_neo4j_driver(args.uri, args.username, args.password)
    
    try:
        with driver.session(database=args.database) as session:
            if args.command == 'coupling':
                analyze_change_coupling(session, args)
            elif args.command == 'metrics':
                add_code_metrics(session, args)
            elif args.command == 'hotspots':
                analyze_hotspots(session, args)
            else:
                logger.error(f"Unknown command: {args.command}")
                
    finally:
        driver.close()


if __name__ == "__main__":
    main() 