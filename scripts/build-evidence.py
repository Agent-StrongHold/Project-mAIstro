#!/usr/bin/env python3
"""Create deterministic build-evidence identities from explicit input closures.

A build result is reusable only when every declared input, the command, and the
execution/toolchain identity match. Missing inputs fail closed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

SCHEMA_VERSION = 1


class EvidenceError(RuntimeError):
    """Raised when a trustworthy evidence identity cannot be produced."""


@dataclass(frozen=True)
class InputDigest:
    path: str
    sha256: str


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_digest(path: Path) -> str:
    if path.is_symlink():
        return _sha256_bytes(b"symlink\0" + os.readlink(path).encode())
    if not path.is_file():
        raise EvidenceError(f"input is neither a file nor directory: {path}")
    return _sha256_bytes(path.read_bytes())


def _walk_input(path: Path, root: Path) -> Iterable[tuple[str, str]]:
    if path.is_symlink() or path.is_file():
        yield path.relative_to(root).as_posix(), _file_digest(path)
        return
    if not path.is_dir():
        raise EvidenceError(f"missing input: {path}")

    files = sorted(
        (
            candidate
            for candidate in path.rglob("*")
            if candidate.is_file() or candidate.is_symlink()
        ),
        key=lambda candidate: candidate.as_posix(),
    )
    for candidate in files:
        yield candidate.relative_to(root).as_posix(), _file_digest(candidate)


def _normalize_input(raw: str, root: Path) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = root / path
    path = path.resolve(strict=False) if not path.is_symlink() else path.absolute()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise EvidenceError(f"input escapes repository root: {raw}") from exc
    if not path.exists() and not path.is_symlink():
        raise EvidenceError(f"missing input: {raw}")
    return path


def digest_inputs(raw_inputs: Iterable[str], root: Path) -> list[InputDigest]:
    """Hash an explicit, repository-relative input closure deterministically."""
    root = root.resolve()
    by_path: dict[str, str] = {}
    for raw in raw_inputs:
        path = _normalize_input(raw, root)
        for relative, digest in _walk_input(path, root):
            prior = by_path.get(relative)
            if prior is not None and prior != digest:
                raise EvidenceError(f"input changed while hashing: {relative}")
            by_path[relative] = digest
    if not by_path:
        raise EvidenceError("evidence requires at least one concrete input file")
    return [InputDigest(path=path, sha256=by_path[path]) for path in sorted(by_path)]


def build_manifest(
    *,
    inputs: Iterable[str],
    command: str,
    root: Path,
    tools: Iterable[str] = (),
) -> dict[str, object]:
    """Return a deterministic manifest and evidence key for one build node."""
    if not command.strip():
        raise EvidenceError("command must not be empty")

    input_digests = digest_inputs(inputs, root)
    identity = {
        "schema": SCHEMA_VERSION,
        "command": command,
        "runtime": {
            "implementation": platform.python_implementation(),
            "python": platform.python_version(),
        },
        "tools": sorted(set(tools)),
        "inputs": [asdict(item) for item in input_digests],
    }
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    return {**identity, "evidence_key": f"sha256:{_sha256_bytes(canonical)}"}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", action="append", required=True, dest="inputs")
    parser.add_argument("--command", required=True)
    parser.add_argument("--tool", action="append", default=[], dest="tools")
    parser.add_argument("--root", default=".")
    parser.add_argument("--out")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        manifest = build_manifest(
            inputs=args.inputs,
            command=args.command,
            root=Path(args.root),
            tools=args.tools,
        )
    except EvidenceError as exc:
        print(f"build evidence unavailable: {exc}", file=sys.stderr)
        return 2

    rendered = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    if args.out:
        Path(args.out).write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
