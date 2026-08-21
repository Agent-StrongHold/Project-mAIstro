#!/usr/bin/env python3
"""Filter mutation targets using validated checkpoints from the same sweep."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

_RUNTIME_CACHE_DIRS = {"__pycache__", ".pytest_cache", ".hypothesis"}
_RUNTIME_CACHE_FILES = {".coverage"}
_RUNTIME_CACHE_SUFFIXES = {".pyc", ".pyo"}


def _is_runtime_cache(path: Path) -> bool:
    return (
        any(part in _RUNTIME_CACHE_DIRS for part in path.parts)
        or path.name in _RUNTIME_CACHE_FILES
        or path.suffix in _RUNTIME_CACHE_SUFFIXES
    )


def tree_hash(path_text: str) -> str:
    path = Path(path_text)
    if not path.exists():
        raise ValueError(f"checkpoint path does not exist: {path_text}")
    digest = hashlib.sha256()
    files = (
        [path]
        if path.is_file()
        else sorted(
            item for item in path.rglob("*") if item.is_file() and not _is_runtime_cache(item)
        )
    )
    for item in files:
        digest.update(item.as_posix().encode())
        digest.update(item.read_bytes())
    return digest.hexdigest()


def read_targets(path: Path) -> list[tuple[str, str]]:
    targets: list[tuple[str, str]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        try:
            source, tests = raw.split("\t", 1)
        except ValueError as exc:
            raise ValueError(f"invalid mutation target row: {raw!r}") from exc
        targets.append((source, tests))
    return targets


def read_checkpoints(root: Path) -> dict[str, list[dict[str, Any]]]:
    checkpoints: dict[str, list[dict[str, Any]]] = {}
    if not root.exists():
        return checkpoints
    for path in sorted(root.rglob("*.checkpoint.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            continue
        source = payload.get("source")
        if isinstance(source, str) and source:
            checkpoints.setdefault(source, []).append(payload)
    return checkpoints


def reusable_checkpoint(
    source: str,
    tests: str,
    candidates: list[dict[str, Any]],
    *,
    commit: str,
    tool_fingerprint: str,
) -> dict[str, Any] | None:
    source_hash = tree_hash(source)
    test_scope_hash = tree_hash(tests)
    for candidate in reversed(candidates):
        if candidate.get("complete") is not True:
            continue
        if candidate.get("verified_commit") != commit:
            continue
        if candidate.get("tool_fingerprint") != tool_fingerprint:
            continue
        if candidate.get("source_hash") != source_hash:
            continue
        if candidate.get("test_scope_hash") != test_scope_hash:
            continue
        return candidate
    return None


def filter_targets(
    targets: list[tuple[str, str]],
    checkpoints: dict[str, list[dict[str, Any]]],
    *,
    commit: str,
    tool_fingerprint: str,
) -> tuple[list[tuple[str, str]], list[dict[str, Any]]]:
    pending: list[tuple[str, str]] = []
    reused: list[dict[str, Any]] = []
    for source, tests in targets:
        checkpoint = reusable_checkpoint(
            source,
            tests,
            checkpoints.get(source, []),
            commit=commit,
            tool_fingerprint=tool_fingerprint,
        )
        if checkpoint is None:
            pending.append((source, tests))
        else:
            reused.append(checkpoint)
    return pending, reused


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("targets", type=Path)
    parser.add_argument("--checkpoints", type=Path, required=True)
    parser.add_argument("--environment", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reused-output", type=Path, required=True)
    args = parser.parse_args(argv)

    environment = json.loads(args.environment.read_text(encoding="utf-8"))
    fingerprint = environment.get("tool_fingerprint")
    if not isinstance(fingerprint, str) or not fingerprint:
        raise ValueError("mutation environment has no tool_fingerprint")

    pending, reused = filter_targets(
        read_targets(args.targets),
        read_checkpoints(args.checkpoints),
        commit=args.commit,
        tool_fingerprint=fingerprint,
    )
    args.output.write_text(
        "".join(f"{source}\t{tests}\n" for source, tests in pending), encoding="utf-8"
    )
    args.reused_output.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in reused), encoding="utf-8"
    )
    print(f"mutation continuation: reused={len(reused)} pending={len(pending)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
