#!/usr/bin/env python3
"""Gate the installed Python supply chain against reviewed vulnerability and usage state.

Single source of truth for both pip-audit jobs (ci.yml `security` and
security.yml `Supply chain (pip-audit)`). Those two used to disagree: ci.yml ran
bare `pip-audit --strict` with no allowlist while security.yml carried an inline
allowlist, so a CVE could be simultaneously "triaged and accepted" and "hard
failure" in the same run. One list, one verdict.

The same gate also rejects unreviewed unused direct runtime dependencies. Every
``packages/*/pyproject.toml`` production dependency must either be imported by
shipped Python or carry a reviewed disposition for a non-import runtime use or a
pre-existing cleanup owner. Local workspace distributions are mapped from their
checked-in source roots so editable-install metadata cannot misclassify shared
namespaces such as ``maistro-core`` -> ``maistro``.

Both ledgers are ratchets. A new advisory or unreviewed unused dependency fails;
a dependency disposition also fails once the dependency disappears or becomes
directly imported.

Usage:  pip-audit --strict --format=json -r deps.txt > audit.json || true
        python scripts/pip_audit_gate.py audit.json
"""

from __future__ import annotations

import ast
import json
import re
import sys
import tomllib
from collections import defaultdict
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEPENDENCY_LEDGER = ROOT / "quality" / "direct-dependency-exceptions.json"

_VALID_DEPENDENCY_CATEGORIES = frozenset(
    {
        "ENTRYPOINT_RUNTIME",
        "FRAMEWORK_RUNTIME",
        "DECLARATIVE_RUNTIME",
        "PLATFORM_RUNTIME",
        "PACKAGING_RUNTIME",
        "PENDING_CLEANUP",
    }
)
_EXCLUDED_PARTS = frozenset({"tests", "test", "mutants", "build", "dist", ".venv"})
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*")
# Some wheels do not expose distribution->top-level-module metadata consistently
# across uv sync shapes. These distribution/import spellings are stable package API,
# so keep the mapping deterministic rather than making the verdict environment-dependent.
_DISTRIBUTION_IMPORT_OVERRIDES: dict[str, frozenset[str]] = {
    "argon2-cffi": frozenset({"argon2"}),
    "pillow": frozenset({"PIL"}),
    "pyjwt": frozenset({"jwt"}),
    "pyyaml": frozenset({"yaml"}),
}

# (package, advisory id) -> why it is accepted. Keyed by the PAIR, not the
# package: exempting a whole package would silently pass every FUTURE advisory
# on it, including one with a fix or one reachable on a code path the triage
# below never considered. Each new advisory blocks until someone reads it and
# adds its ID here with reasoning specific enough to re-audit.
ALLOWED: dict[tuple[str, str], str] = {
    ("ecdsa", "PYSEC-2026-1325"): (
        "Minerva timing side channel on the P-256 curve via "
        "SigningKey.sign_digest(). Upstream considers side-channel attacks out "
        "of scope and has stated there is no planned fix, so there is no "
        "version to upgrade to. Transitive via bip-utils (the `identity` "
        "extra). maistro.identity derives on Ed25519 and secp256k1 only — it "
        "never touches P-256 — and the attack additionally requires local "
        "timing measurement of signing operations. Not reachable as used."
    ),
}


@dataclass(frozen=True)
class PackageUsage:
    """Runtime dependency/import evidence for one production package."""

    manifest: str
    dependencies: frozenset[str]
    imports: frozenset[str]
    import_names: dict[str, frozenset[str]]

    @property
    def unused(self) -> frozenset[str]:
        return frozenset(
            dependency
            for dependency in self.dependencies
            if not self.imports.intersection(self.import_names[dependency])
        )


def canonical_name(name: str) -> str:
    """Return a PEP 503-style normalized distribution name."""
    return re.sub(r"[-_.]+", "-", name).lower()


def requirement_name(requirement: str) -> str:
    """Extract and normalize the distribution name from a PEP 508 requirement."""
    match = _NAME_RE.match(requirement.strip())
    if match is None:
        raise ValueError(f"cannot parse dependency requirement: {requirement!r}")
    return canonical_name(match.group(0))


def runtime_dependencies(manifest: Path) -> frozenset[str]:
    """Read only ``project.dependencies``; test/optional groups are not shipped runtime."""
    data = tomllib.loads(manifest.read_text())
    project = data.get("project", {})
    raw = project.get("dependencies", [])
    return frozenset(requirement_name(item) for item in raw)


def _dotted_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _dotted_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _literal_dynamic_import(node: ast.Call) -> str | None:
    dotted = _dotted_name(node.func)
    if dotted not in {"importlib.import_module", "__import__"} or not node.args:
        return None
    first = node.args[0]
    if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
        return None
    return first.value.split(".", 1)[0]


def imports_from_source(source: str) -> frozenset[str]:
    """Return top-level modules imported by one Python source string."""
    tree = ast.parse(source)
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".", 1)[0])
        elif isinstance(node, ast.Call):
            dynamic = _literal_dynamic_import(node)
            if dynamic:
                found.add(dynamic)
    return frozenset(found)


def production_imports(package_dir: Path) -> frozenset[str]:
    """Collect imports from shipped Python while excluding tests/generated artifacts."""
    found: set[str] = set()
    for path in package_dir.rglob("*.py"):
        relative = path.relative_to(package_dir)
        if any(part in _EXCLUDED_PARTS for part in relative.parts):
            continue
        if path.name.startswith("test_"):
            continue
        try:
            found.update(imports_from_source(path.read_text(errors="replace")))
        except SyntaxError as exc:
            raise RuntimeError(f"cannot parse production Python {path}: {exc}") from exc
    return frozenset(found)


def installed_distribution_imports() -> dict[str, frozenset[str]]:
    """Invert installed package metadata to distribution -> top-level import names."""
    inverted: dict[str, set[str]] = defaultdict(set)
    for import_name, distributions in metadata.packages_distributions().items():
        for distribution in distributions:
            inverted[canonical_name(distribution)].add(import_name.split(".", 1)[0])
    return {name: frozenset(imports) for name, imports in inverted.items()}


def _local_import_roots(manifest: Path) -> frozenset[str]:
    """Derive import roots shipped by a local workspace package."""
    roots: set[str] = set()
    src = manifest.parent / "src"
    if src.is_dir():
        for child in src.iterdir():
            if child.name.startswith("."):
                continue
            if child.is_dir():
                roots.add(child.name)
            elif child.suffix == ".py":
                roots.add(child.stem)

    data = tomllib.loads(manifest.read_text())
    wheel = (
        data.get("tool", {}).get("hatch", {}).get("build", {}).get("targets", {}).get("wheel", {})
    )
    for package in wheel.get("packages", []):
        roots.add(Path(package).name)
    for target in wheel.get("sources", {}).values():
        if isinstance(target, str) and target:
            roots.add(target.split("/", 1)[0])
    return frozenset(roots)


def local_distribution_imports(root: Path = ROOT) -> dict[str, frozenset[str]]:
    """Map local distribution names to import roots from checked-in package layout."""
    result: dict[str, frozenset[str]] = {}
    for manifest in sorted((root / "packages").glob("*/pyproject.toml")):
        data = tomllib.loads(manifest.read_text())
        name = data.get("project", {}).get("name")
        if isinstance(name, str):
            roots = _local_import_roots(manifest)
            if roots:
                result[canonical_name(name)] = roots
    return result


def import_names_for(
    dependency: str,
    distributions: dict[str, frozenset[str]],
) -> frozenset[str]:
    """Resolve import names, using conventional underscore spelling as fallback."""
    mapped = distributions.get(dependency, frozenset())
    override = _DISTRIBUTION_IMPORT_OVERRIDES.get(dependency, frozenset())
    if mapped or override:
        return frozenset(mapped | override)
    return frozenset({dependency.replace("-", "_")})


def discover(
    root: Path = ROOT,
    installed: dict[str, frozenset[str]] | None = None,
) -> list[PackageUsage]:
    """Discover runtime dependency/import evidence for every package manifest."""
    distribution_imports = dict(installed or installed_distribution_imports())
    for name, imports in local_distribution_imports(root).items():
        distribution_imports[name] = frozenset(
            distribution_imports.get(name, frozenset()) | imports
        )

    usages: list[PackageUsage] = []
    for manifest in sorted((root / "packages").glob("*/pyproject.toml")):
        dependencies = runtime_dependencies(manifest)
        if not dependencies:
            continue
        imports = production_imports(manifest.parent)
        names = {
            dependency: import_names_for(dependency, distribution_imports)
            for dependency in dependencies
        }
        usages.append(
            PackageUsage(
                manifest=manifest.relative_to(root).as_posix(),
                dependencies=dependencies,
                imports=imports,
                import_names=names,
            )
        )
    return usages


def load_dependency_ledger(
    path: Path = DEPENDENCY_LEDGER,
) -> dict[str, dict[str, dict[str, Any]]]:
    """Load the reviewed unused-direct-dependency disposition ledger."""
    if not path.exists():
        raise FileNotFoundError(path)
    data = json.loads(path.read_text())
    if data.get("schema_version") != 1 or not isinstance(data.get("exceptions"), dict):
        raise ValueError(
            "direct-dependency ledger must have schema_version=1 and an exceptions object"
        )
    return data["exceptions"]


def _validate_dependency_disposition(
    manifest: str,
    dependency: str,
    entry: dict[str, Any],
) -> list[str]:
    failures: list[str] = []
    category = entry.get("category")
    owner = entry.get("owner")
    rationale = entry.get("rationale")
    prefix = f"{manifest}: {dependency}"
    if category not in _VALID_DEPENDENCY_CATEGORIES:
        failures.append(f"{prefix}: invalid/missing disposition category {category!r}")
    if not isinstance(owner, str) or not owner.strip():
        failures.append(f"{prefix}: disposition is missing an owner")
    if not isinstance(rationale, str) or len(rationale.strip()) < 20:
        failures.append(f"{prefix}: disposition rationale is missing or too vague")
    return failures


def audit(
    usages: list[PackageUsage],
    dispositions: dict[str, dict[str, dict[str, Any]]],
) -> list[str]:
    """Return two-way ratchet failures for unused dependencies and stale dispositions."""
    failures: list[str] = []
    by_manifest = {usage.manifest: usage for usage in usages}

    for usage in usages:
        recorded = dispositions.get(usage.manifest, {})
        for dependency in sorted(usage.unused):
            entry = recorded.get(dependency)
            if entry is None:
                failures.append(
                    f"{usage.manifest}: {dependency} is a direct runtime dependency with no "
                    "production import and no reviewed disposition"
                )
                continue
            failures.extend(_validate_dependency_disposition(usage.manifest, dependency, entry))

    for manifest, entries in sorted(dispositions.items()):
        usage = by_manifest.get(manifest)
        if usage is None:
            failures.append(
                f"{manifest}: disposition ledger names no discovered production package"
            )
            continue
        for dependency, entry in sorted(entries.items()):
            failures.extend(_validate_dependency_disposition(manifest, dependency, entry))
            if dependency not in usage.dependencies:
                failures.append(
                    f"{manifest}: {dependency} disposition is stale; dependency was removed"
                )
            elif dependency not in usage.unused:
                failures.append(
                    f"{manifest}: {dependency} disposition is stale; production code now imports it"
                )

    return failures


def audit_direct_dependencies() -> int:
    """Run the direct production dependency usage ratchet."""
    try:
        usages = discover()
        dispositions = load_dependency_ledger()
    except (FileNotFoundError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAIL: direct-dependency usage check could not run: {exc}", file=sys.stderr)
        return 1

    failures = audit(usages, dispositions)
    if failures:
        print("FAIL: direct runtime dependency inventory is not justified\n")
        for failure in failures:
            print(f"  - {failure}")
        print(
            "\nRemove unused dependencies. If a dependency is required without a direct Python "
            "import, add a narrowly reviewed runtime disposition. Baseline cleanup debt only with "
            "a concrete owner and rationale."
        )
        return 1

    dependency_count = sum(len(usage.dependencies) for usage in usages)
    disposition_count = sum(len(usage.unused) for usage in usages)
    print(
        f"direct-dependency usage OK: {len(usages)} packages, {dependency_count} runtime "
        f"dependencies, {disposition_count} reviewed dispositions"
    )
    return 0


def audit_pip_report(path: str) -> int:
    """Gate one pip-audit JSON report against the advisory allowlist."""
    with open(path) as fh:
        data = json.load(fh)

    vulnerable = [
        dependency for dependency in data.get("dependencies", []) if dependency.get("vulns")
    ]
    blocking: list[tuple[dict, dict]] = [
        (dependency, vulnerability)
        for dependency in vulnerable
        for vulnerability in dependency["vulns"]
        if (dependency["name"], vulnerability["id"]) not in ALLOWED
    ]

    if blocking:
        print("::error::pip-audit found advisories outside the triaged allowlist:")
        for dependency, vulnerability in blocking:
            fix = vulnerability.get("fix_versions") or []
            hint = f"upgrade to {fix[-1]}" if fix else "NO FIX AVAILABLE — needs triage"
            print(
                f"  {dependency['name']}=={dependency['version']} {vulnerability['id']} -> {hint}"
            )
        print(
            "\nFix by upgrading the dependency. Only add a (package, advisory) "
            "pair to ALLOWED in scripts/pip_audit_gate.py when no fixed version "
            "exists, and say why."
        )
        return 1

    for dependency in vulnerable:
        for vulnerability in dependency["vulns"]:
            print(f"allowed: {dependency['name']}=={dependency['version']} {vulnerability['id']}")
    print(f"pip-audit OK ({len(vulnerable)} known, all triaged in ALLOWED)")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {argv[0]} <pip-audit.json>", file=sys.stderr)
        return 2
    report_result = audit_pip_report(argv[1])
    if report_result:
        return report_result
    return audit_direct_dependencies()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
