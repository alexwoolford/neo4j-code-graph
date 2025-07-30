#!/usr/bin/env python3
"""
Enhanced dependency extraction with proper GAV coordinate handling.

This module replaces the loose dependency extraction with precise
GAV (Group:Artifact:Version) coordinate management.
"""

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from src.security.gav_cve_matcher import GAVCoordinate

logger = logging.getLogger(__name__)


@dataclass
class DependencyInfo:
    """Complete dependency information with metadata."""

    gav: GAVCoordinate
    scope: str = "compile"  # compile, test, runtime, etc.
    source_file: str = ""
    dependency_management: bool = False

    def to_neo4j_node(self) -> Dict:
        """Convert to Neo4j node properties."""
        return {
            "package": self.gav.full_coordinate,
            "group_id": self.gav.group_id,
            "artifact_id": self.gav.artifact_id,
            "version": self.gav.version,
            "language": "java",
            "ecosystem": "maven",
            "scope": self.scope,
            "source_file": self.source_file,
            "dependency_management": self.dependency_management,
        }


class EnhancedDependencyExtractor:
    """Enhanced dependency extraction with proper GAV handling."""

    def __init__(self):
        self.property_resolver = PropertyResolver()

    def extract_all_dependencies(self, repo_root: Path) -> List[DependencyInfo]:
        """Extract all dependencies from repository with proper GAV coordinates."""
        logger.info("🔍 Enhanced dependency extraction starting...")

        all_dependencies = []

        # Extract from Maven pom.xml files
        for pom_file in repo_root.rglob("pom.xml"):
            try:
                logger.debug(f"Processing Maven file: {pom_file}")
                maven_deps = self._extract_maven_dependencies_enhanced(pom_file)
                all_dependencies.extend(maven_deps)
            except Exception as e:
                logger.debug(f"Error processing {pom_file}: {e}")

        # Extract from Gradle build files
        for gradle_file in repo_root.rglob("build.gradle*"):
            try:
                logger.debug(f"Processing Gradle file: {gradle_file}")
                gradle_deps = self._extract_gradle_dependencies_enhanced(gradle_file)
                all_dependencies.extend(gradle_deps)
            except Exception as e:
                logger.debug(f"Error processing {gradle_file}: {e}")

        # Remove duplicates while preserving highest scope
        unique_dependencies = self._deduplicate_dependencies(all_dependencies)

        logger.info(f"✅ Extracted {len(unique_dependencies)} unique dependencies")
        return unique_dependencies

    def _extract_maven_dependencies_enhanced(self, pom_file: Path) -> List[DependencyInfo]:
        """Extract dependencies from Maven pom.xml with full GAV coordinates."""
        dependencies = []

        try:
            tree = ET.parse(pom_file)
            root = tree.getroot()

            # Handle namespaces
            namespace = self._get_maven_namespace(root)

            # Resolve properties first
            properties = self._extract_maven_properties(root, namespace)

            # Extract regular dependencies
            for dependency in root.findall(".//maven:dependency", namespace):
                dep_info = self._parse_maven_dependency(
                    dependency, namespace, properties, str(pom_file), scope="compile"
                )
                if dep_info:
                    dependencies.append(dep_info)

            # Extract dependency management
            for dependency in root.findall(
                ".//maven:dependencyManagement//maven:dependency", namespace
            ):
                dep_info = self._parse_maven_dependency(
                    dependency,
                    namespace,
                    properties,
                    str(pom_file),
                    scope="dependencyManagement",
                    dependency_management=True,
                )
                if dep_info:
                    dependencies.append(dep_info)

        except ET.ParseError as e:
            logger.debug(f"XML parsing error in {pom_file}: {e}")
        except Exception as e:
            logger.debug(f"Error processing Maven file {pom_file}: {e}")

        return dependencies

    def _parse_maven_dependency(
        self,
        dependency,
        namespace: Dict,
        properties: Dict[str, str],
        source_file: str,
        scope: str = "compile",
        dependency_management: bool = False,
    ) -> Optional[DependencyInfo]:
        """Parse a single Maven dependency element."""
        group_id_elem = dependency.find("maven:groupId", namespace)
        artifact_id_elem = dependency.find("maven:artifactId", namespace)
        version_elem = dependency.find("maven:version", namespace)
        scope_elem = dependency.find("maven:scope", namespace)

        if not (group_id_elem is not None and artifact_id_elem is not None):
            return None

        group_id = group_id_elem.text
        artifact_id = artifact_id_elem.text
        version = version_elem.text if version_elem is not None else "UNKNOWN"
        actual_scope = scope_elem.text if scope_elem is not None else scope

        # Resolve properties in version
        if version.startswith("${") and version.endswith("}"):
            prop_name = version[2:-1]
            version = properties.get(prop_name, version)

        # Only include if we have a concrete version
        if version and not version.startswith("${") and version != "UNKNOWN":
            gav = GAVCoordinate(group_id, artifact_id, version)

            return DependencyInfo(
                gav=gav,
                scope=actual_scope,
                source_file=source_file,
                dependency_management=dependency_management,
            )

        return None

    def _extract_gradle_dependencies_enhanced(self, gradle_file: Path) -> List[DependencyInfo]:
        """Extract dependencies from Gradle build files with GAV coordinates."""
        dependencies = []

        try:
            with open(gradle_file, "r", encoding="utf-8") as f:
                content = f.read()

            # Pattern for standard Gradle dependencies: 'group:artifact:version'
            standard_pattern = (
                r"(?:implementation|api|compile|testImplementation|testCompile|runtime)\s+"
                r"['\"]([a-zA-Z0-9._-]+):([a-zA-Z0-9._-]+):([a-zA-Z0-9._-]+)['\"]"
            )  # noqa: E501

            # Pattern for map-style dependencies
            map_pattern = (
                r"(?:implementation|api|compile|testImplementation|testCompile|runtime)\s+"
                r"(?:group\s*:\s*['\"]([^'\"]+)['\"],?\s*)?name\s*:\s*['\"]([^'\"]+)['\"]"  # noqa: E501
                r",?\s*version\s*:\s*['\"]([^'\"]+)['\"]"
            )

            # Extract version properties
            version_props = {}
            version_pattern = r"(\w+)\s*=\s*['\"]([^'\"]+)['\"]"
            for match in re.finditer(version_pattern, content):
                prop_name, version = match.groups()
                if "version" in prop_name.lower():
                    version_props[prop_name] = version

            # Process standard format dependencies
            for match in re.finditer(standard_pattern, content):
                group_id, artifact_id, version = match.groups()

                # Resolve version variables
                if version.startswith("$"):
                    var_name = version[1:]
                    version = version_props.get(var_name, version)

                if not version.startswith("$"):
                    gav = GAVCoordinate(group_id, artifact_id, version)
                    dependencies.append(
                        DependencyInfo(
                            gav=gav,
                            scope=self._extract_gradle_scope(match.group(0)),
                            source_file=str(gradle_file),
                        )
                    )

            # Process map format dependencies
            for match in re.finditer(map_pattern, content):
                group_id, artifact_id, version = match.groups()

                if not version.startswith("$"):
                    gav = GAVCoordinate(group_id, artifact_id, version)
                    dependencies.append(
                        DependencyInfo(
                            gav=gav,
                            scope=self._extract_gradle_scope(match.group(0)),
                            source_file=str(gradle_file),
                        )
                    )

        except Exception as e:
            logger.debug(f"Error processing Gradle file {gradle_file}: {e}")

        return dependencies

    def _extract_gradle_scope(self, dependency_line: str) -> str:
        """Extract scope from Gradle dependency line."""
        if "testImplementation" in dependency_line or "testCompile" in dependency_line:
            return "test"
        elif "runtime" in dependency_line:
            return "runtime"
        else:
            return "compile"

    def _get_maven_namespace(self, root) -> Dict[str, str]:
        """Get Maven namespace from root element."""
        namespace = {"maven": "http://maven.apache.org/POM/4.0.0"}
        if root.tag.startswith("{"):
            ns = root.tag.split("}")[0][1:]
            namespace = {"maven": ns}
        return namespace

    def _extract_maven_properties(self, root, namespace: Dict[str, str]) -> Dict[str, str]:
        """Extract Maven properties for version resolution."""
        properties = {}

        # Extract from properties section
        props_elem = root.find(".//maven:properties", namespace)
        if props_elem is not None:
            for prop in props_elem:
                if prop.text:
                    # Remove namespace from tag name
                    prop_name = prop.tag.split("}")[-1] if "}" in prop.tag else prop.tag
                    properties[prop_name] = prop.text

        # Extract common Maven properties
        version_elem = root.find(".//maven:version", namespace)
        if version_elem is not None and version_elem.text:
            properties["project.version"] = version_elem.text
            properties["version"] = version_elem.text

        return properties

    def _deduplicate_dependencies(self, dependencies: List[DependencyInfo]) -> List[DependencyInfo]:
        """Remove duplicate dependencies, keeping the one with highest scope priority."""
        scope_priority = {"compile": 3, "runtime": 2, "test": 1, "dependencyManagement": 0}

        dependency_map = {}

        for dep in dependencies:
            key = dep.gav.package_key

            if key not in dependency_map:
                dependency_map[key] = dep
            else:
                existing = dependency_map[key]
                # Keep dependency with higher scope priority
                if scope_priority.get(dep.scope, 0) > scope_priority.get(existing.scope, 0):
                    dependency_map[key] = dep

        return list(dependency_map.values())

    def create_neo4j_nodes(self, dependencies: List[DependencyInfo]) -> List[Dict]:
        """Create Neo4j node data from dependencies."""
        return [dep.to_neo4j_node() for dep in dependencies]


class PropertyResolver:
    """Resolves Maven/Gradle property references."""

    def resolve_version(self, version: str, properties: Dict[str, str]) -> str:
        """Resolve version property references."""
        if not version or not version.startswith("${"):
            return version

        # Extract property name
        if version.startswith("${") and version.endswith("}"):
            prop_name = version[2:-1]
            return properties.get(prop_name, version)

        return version


# Integration function to replace old dependency extraction
def extract_enhanced_dependencies_for_neo4j(repo_root: Path) -> Dict[str, str]:
    """
    Extract dependencies and return in format compatible with existing Neo4j code.

    This maintains backward compatibility while using enhanced extraction.
    """
    extractor = EnhancedDependencyExtractor()
    dependencies = extractor.extract_all_dependencies(repo_root)

    # Convert to old format for compatibility
    dependency_versions = {}
    for dep in dependencies:
        # Store both full GAV and package key for backward compatibility
        dependency_versions[dep.gav.full_coordinate] = dep.gav.version
        dependency_versions[dep.gav.package_key] = dep.gav.version

        # Also store artifact-only key for some matching scenarios
        dependency_versions[dep.gav.artifact_id] = dep.gav.version

    logger.info(f"✅ Enhanced extraction found {len(dependencies)} dependencies")
    return dependency_versions


if __name__ == "__main__":
    # Test the enhanced extraction
    import sys

    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) > 1:
        repo_path = Path(sys.argv[1])
        extractor = EnhancedDependencyExtractor()
        deps = extractor.extract_all_dependencies(repo_path)

        print(f"\nFound {len(deps)} dependencies:")
        for dep in deps:
            print(f"  {dep.gav.full_coordinate} (scope: {dep.scope})")
    else:
        print("Usage: python dependency_extraction.py <repo_path>")
