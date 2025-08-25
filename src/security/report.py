from __future__ import annotations

from typing import Any


def generate_impact_report(vulnerabilities: list[dict[str, Any]]) -> None:
    if not vulnerabilities:
        print("\n🎉 **EXCELLENT NEWS!**")
        print("No high-risk vulnerabilities found in your codebase!")
        print("This could mean:")
        print("  • Your dependencies are up-to-date and secure")
        print("  • The components you're using don't have known critical vulnerabilities")
        print("  • Your dependency versions are newer than vulnerable ranges")
        return

    print("\n🚨 **VULNERABILITY IMPACT REPORT**")
    print(f"Found {len(vulnerabilities)} potential security issues")
    print("=" * 80)

    for vuln in vulnerabilities[:10]:
        print(f"\n🔴 {vuln['cve_id']} (CVSS: {vuln['cvss_score']:.1f})")
        print(f"   Severity: {vuln['severity']}")
        print(f"   Description: {vuln['description'][:100]}...")
        if vuln.get("affected_dependencies"):
            print(f"   Potentially affects: {len(vuln['affected_dependencies'])} dependencies")
