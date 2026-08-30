#!/usr/bin/env python3
"""Inventory repository state surfaces that can serialize otherwise independent PRs.

The contract is intentionally representation-focused. A file can be perfectly valid
as a quality/security oracle and still be a bad collaboration primitive when every
branch has to rewrite the same aggregate after ``develop`` moves.

This checker does not migrate any surface. It makes the current state explicit and
prevents a new shared aggregate from being introduced silently. Legacy aggregates
are an exact-path frozen set; future work may only shrink that set or move a surface
to a branch-independent representation.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_REL = Path("quality/branch-independence.json")

ALLOWED_KINDS = frozenset(
    {
        "base_derived",
        "folded_notes",
        "generated",
        "legacy_shared_aggregate",
        "per_identity_policy",
        "retired_compat",
        "specification",
    }
)
MIGRATION_TARGET_KINDS = ALLOWED_KINDS - {"legacy_shared_aggregate", "retired_compat"}
GLOB_CHARS = frozenset("*?[")
BASE_ENV = "BRANCH_INDEPENDENCE_BASE_REV"
RATCHET_BASE_ENV = "RATCHET_BASE_REV"
DEFAULT_BASE_REV = "origin/develop"


class BranchIndependenceError(RuntimeError):
    """The branch-independence registry or repository state is invalid."""


def _json_object(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise BranchIndependenceError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise BranchIndependenceError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise BranchIndependenceError(f"{path} must contain a JSON object")
    return raw


def load_registry(path: Path) -> dict[str, Any]:
    """Load one registry object from disk."""
    return _json_object(path)


def _patterns(surface: dict[str, Any]) -> list[str]:
    raw = surface.get("paths")
    return list(raw) if isinstance(raw, list) else []


def _has_glob(pattern: str) -> bool:
    return any(char in pattern for char in GLOB_CHARS)


def _validate_roots(registry: dict[str, Any]) -> list[str]:
    roots = registry.get("quality_roots")
    valid = isinstance(roots, list) and bool(roots)
    if valid:
        valid = all(isinstance(item, str) and item for item in roots)
    return [] if valid else ["quality_roots must be a non-empty list of paths"]


def _validate_frozen(registry: dict[str, Any]) -> tuple[list[str], set[str]]:
    frozen = registry.get("frozen_legacy_paths")
    if not isinstance(frozen, list) or not all(isinstance(item, str) and item for item in frozen):
        return ["frozen_legacy_paths must be a list of exact paths"], set()

    errors: list[str] = []
    frozen_set = set(frozen)
    if len(frozen_set) != len(frozen):
        errors.append("frozen_legacy_paths contains duplicates")
    errors.extend(
        f"frozen legacy path must be exact, not a glob: {path}"
        for path in frozen
        if _has_glob(path)
    )
    return errors, frozen_set


def _surface_identity_errors(
    surface: dict[str, Any],
    index: int,
    seen_ids: set[str],
) -> tuple[list[str], str]:
    surface_id = surface.get("id")
    if not isinstance(surface_id, str) or not surface_id:
        return [f"surface[{index}] has no id"], f"surface[{index}]"
    if surface_id in seen_ids:
        return [f"duplicate surface id: {surface_id}"], surface_id
    seen_ids.add(surface_id)
    return [], surface_id


def _surface_path_errors(label: str, paths: list[str]) -> list[str]:
    if not paths or not all(isinstance(path, str) and path for path in paths):
        return [f"{label} must list at least one path or glob"]
    return [
        f"{label} path must be a quality JSON surface: {path}"
        for path in paths
        if not path.startswith("quality/") or not path.endswith(".json")
    ]


def _legacy_surface_errors(
    label: str,
    surface: dict[str, Any],
    paths: list[str],
) -> tuple[list[str], set[str]]:
    if surface.get("kind") != "legacy_shared_aggregate":
        return [], set()

    errors: list[str] = []
    if surface.get("target_kind") not in MIGRATION_TARGET_KINDS:
        errors.append(f"{label} legacy surface needs a non-legacy target_kind")
    errors.extend(
        f"{label} legacy path must be exact, not a glob: {path}"
        for path in paths
        if _has_glob(path)
    )
    return errors, set(paths)


def _surface_errors(
    surface: dict[str, Any],
    index: int,
    seen_ids: set[str],
) -> tuple[list[str], set[str]]:
    identity_errors, label = _surface_identity_errors(surface, index, seen_ids)
    errors = list(identity_errors)

    kind = surface.get("kind")
    if kind not in ALLOWED_KINDS:
        errors.append(f"{label} has unknown kind {kind!r}")
    reason = surface.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        errors.append(f"{label} must explain its representation")

    paths = _patterns(surface)
    errors.extend(_surface_path_errors(label, paths))
    legacy_errors, legacy_paths = _legacy_surface_errors(label, surface, paths)
    errors.extend(legacy_errors)
    return errors, legacy_paths


def registry_errors(registry: dict[str, Any]) -> list[str]:
    """Validate the registry schema and the frozen legacy set."""
    errors = [] if registry.get("version") == 1 else ["registry version must be 1"]
    errors.extend(_validate_roots(registry))
    frozen_errors, frozen_set = _validate_frozen(registry)
    errors.extend(frozen_errors)

    surfaces = registry.get("surfaces")
    if not isinstance(surfaces, list) or not surfaces:
        return [*errors, "surfaces must be a non-empty list"]

    seen_ids: set[str] = set()
    legacy_paths: set[str] = set()
    for index, surface in enumerate(surfaces):
        if not isinstance(surface, dict):
            errors.append(f"surface[{index}] must be an object")
            continue
        surface_errors, surface_legacy = _surface_errors(surface, index, seen_ids)
        errors.extend(surface_errors)
        legacy_paths.update(surface_legacy)

    extra_legacy = sorted(legacy_paths - frozen_set)
    missing_legacy = sorted(frozen_set - legacy_paths)
    if extra_legacy:
        errors.append("new legacy shared aggregate(s) are forbidden: " + ", ".join(extra_legacy))
    if missing_legacy:
        errors.append(
            "frozen legacy path(s) are no longer classified legacy; remove them from "
            "frozen_legacy_paths in the same migration: " + ", ".join(missing_legacy)
        )
    return errors


def discover_quality_json(root: Path, registry: dict[str, Any]) -> set[str]:
    """Find every committed-shaped JSON state path under the registered roots."""
    discovered: set[str] = set()
    for root_rel in registry.get("quality_roots", []):
        directory = root / root_rel
        if not directory.exists():
            continue
        for path in directory.rglob("*.json"):
            if path.is_file():
                discovered.add(path.relative_to(root).as_posix())
    return discovered


def coverage_errors(registry: dict[str, Any], paths: set[str]) -> list[str]:
    """Require each discovered state file to match exactly one surface."""
    surfaces = [surface for surface in registry.get("surfaces", []) if isinstance(surface, dict)]
    errors: list[str] = []
    for path in sorted(paths):
        matches = [
            str(surface.get("id", "<unnamed>"))
            for surface in surfaces
            if any(fnmatch.fnmatchcase(path, pattern) for pattern in _patterns(surface))
        ]
        if not matches:
            errors.append(f"unclassified quality state: {path}")
        elif len(matches) > 1:
            errors.append(f"quality state matches multiple surfaces: {path}: {', '.join(matches)}")

    for surface in surfaces:
        surface_id = str(surface.get("id", "<unnamed>"))
        for pattern in _patterns(surface):
            if _has_glob(pattern):
                continue
            if pattern not in paths:
                errors.append(f"registered exact path does not exist: {surface_id}: {pattern}")
    return errors


def _git(args: list[str], *, root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


def base_registry(root: Path, explicit_base: str | None = None) -> dict[str, Any] | None:
    """Read the registry at a named trusted base when available.

    The registry did not exist before this contract lands, so absence is the
    bootstrap case. After landing, CI may name the base through the dedicated
    variable or the repository-wide ratchet base variable. Expansion of the
    legacy set is then rejected even if a candidate edits its own frozen list.
    """
    explicit = (
        explicit_base
        or os.environ.get(BASE_ENV, "").strip()
        or os.environ.get(RATCHET_BASE_ENV, "").strip()
    )
    base = explicit or DEFAULT_BASE_REV
    resolved = _git(["rev-parse", "--verify", f"{base}^{{commit}}"], root=root)
    if resolved.returncode != 0:
        if not explicit:
            return None
        raise BranchIndependenceError(
            f"base revision {base!r} cannot be resolved: {resolved.stderr.strip()}"
        )
    merge_base = _git(["merge-base", resolved.stdout.strip(), "HEAD"], root=root)
    if merge_base.returncode != 0:
        raise BranchIndependenceError(
            f"cannot resolve merge base for {base!r}: {merge_base.stderr.strip()}"
        )
    commit = merge_base.stdout.strip()
    object_name = f"{commit}:{REGISTRY_REL.as_posix()}"
    exists = _git(["cat-file", "-e", object_name], root=root)
    if exists.returncode != 0:
        readable = _git(["cat-file", "-e", f"{commit}^{{tree}}"], root=root)
        if readable.returncode != 0:
            raise BranchIndependenceError(
                f"base commit {commit} cannot be read: {(readable.stderr or exists.stderr).strip()}"
            )
        return None
    shown = _git(["show", object_name], root=root)
    if shown.returncode != 0:
        raise BranchIndependenceError(
            f"registry exists at base {commit[:12]} but cannot be read: {shown.stderr.strip()}"
        )
    try:
        raw = json.loads(shown.stdout)
    except json.JSONDecodeError as exc:
        raise BranchIndependenceError(
            f"branch-independence registry at base {commit[:12]} is invalid JSON: {exc}"
        ) from exc
    if not isinstance(raw, dict):
        raise BranchIndependenceError(
            f"branch-independence registry at base {commit[:12]} is not an object"
        )
    return raw


def trusted_base_errors(registry: dict[str, Any], base: dict[str, Any] | None) -> list[str]:
    """Forbid growing the legacy set relative to a trusted base registry."""
    if base is None:
        return []
    candidate_legacy = set(registry.get("frozen_legacy_paths", []))
    base_legacy = set(base.get("frozen_legacy_paths", []))
    added = sorted(candidate_legacy - base_legacy)
    if not added:
        return []
    return ["candidate expands the trusted legacy freeze: " + ", ".join(added)]


def check_repository(
    root: Path = ROOT,
    *,
    registry_path: Path | None = None,
    base: dict[str, Any] | None = None,
) -> list[str]:
    """Return every contract violation without stopping at the first one."""
    registry_path = root / REGISTRY_REL if registry_path is None else registry_path
    registry = load_registry(registry_path)
    errors = registry_errors(registry)
    if errors:
        return errors
    paths = discover_quality_json(root, registry)
    errors.extend(coverage_errors(registry, paths))
    errors.extend(trusted_base_errors(registry, base))
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument(
        "--base",
        help="trusted base ref; defaults to CI base environment variables",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    registry_path = root / REGISTRY_REL
    try:
        base = base_registry(root, args.base)
        errors = check_repository(root, registry_path=registry_path, base=base)
    except (BranchIndependenceError, OSError, subprocess.SubprocessError) as exc:
        print(f"FAIL: branch-independence contract could not be evaluated: {exc}", file=sys.stderr)
        return 2
    if errors:
        print("FAIL: branch-independence contract", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print("PASS: every quality JSON state surface has one branch-independence representation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
