#!/usr/bin/env python3
"""Reject flat application modules under ``packages/*/backend``.

Backend applications are executable package surfaces, not import roots that
are made visible by putting their directories first on ``sys.path``.  The
approved package names are intentionally explicit and kept here as a small
fitness function while older deployment tooling is being cut over.
"""

from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_PACKAGES = {
    "hive-conductor": "hive_conductor",
    "maistro-turing": "maistro_turing_backend",
}
ALLOWED_TOP_LEVEL_DIRS = {"tests", "__pycache__"}


def _package_violations(root: Path, backend: Path, package: str) -> list[str]:
    """Check one approved backend without making path order authoritative."""
    package_root = backend / package
    if not (package_root / "__init__.py").is_file():
        return [f"{package_root.relative_to(root)} must contain __init__.py"]

    found: list[str] = []
    for child in sorted(backend.iterdir()):
        if (
            child.name in ALLOWED_TOP_LEVEL_DIRS
            or child.name == "__init__.py"
            or child == package_root
        ):
            continue
        if child.is_file() and child.suffix == ".py":
            found.append(
                f"{child.relative_to(root)} is a flat backend module; move it under {package}/"
            )
        elif child.is_dir() and any(child.rglob("*.py")):
            found.append(
                f"{child.relative_to(root)} contains Python outside the approved {package}/ package"
            )

    # A package can contain subpackages, but every Python-bearing directory must
    # be importable as part of the approved namespace.
    for path in sorted(package_root.rglob("*.py")):
        if not (path.parent / "__init__.py").is_file():
            found.append(f"{path.relative_to(root)} is not inside an __init__.py package")
    return found


def violations(root: Path = ROOT) -> list[str]:
    """Return stable, reviewable violations for every backend application."""
    found: list[str] = []
    for backend in sorted((root / "packages").glob("*/backend")):
        package = APP_PACKAGES.get(backend.parent.name)
        if package is None:
            if any(backend.rglob("*.py")):
                found.append(f"{backend.relative_to(root)} has no approved application package")
        else:
            found.extend(_package_violations(root, backend, package))
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    errors = violations()
    if errors:
        print("backend package namespace check failed:")
        print("\n".join(f"- {error}" for error in errors))
        return 1
    print("backend package namespace check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
