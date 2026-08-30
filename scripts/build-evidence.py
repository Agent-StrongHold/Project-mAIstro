#!/usr/bin/env python3
"""Create and verify fail-closed content-addressed build evidence.

A build result is reusable only when every declared input, the command, and the
execution/toolchain identity match. The identity manifest is deterministic. A
completed result envelope binds an observed exit code and duration to that
identity so a consumer can independently recompute the expected identity and
refuse missing, stale, tampered, or failed evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import sys
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
RESULT_SCHEMA_VERSION = 1


class EvidenceError(RuntimeError):
    """Raised when trustworthy evidence cannot be produced or verified."""


@dataclass(frozen=True)
class InputDigest:
    path: str
    sha256: str


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_hash(payload: Mapping[str, object]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{_sha256_bytes(canonical)}"


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
    """Return a deterministic identity manifest and key for one build node."""
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
    return {**identity, "evidence_key": _canonical_hash(identity)}


def _validated_identity(manifest: Mapping[str, Any]) -> dict[str, object]:
    expected_fields = {"schema", "command", "runtime", "tools", "inputs", "evidence_key"}
    if set(manifest) != expected_fields:
        raise EvidenceError("identity manifest fields do not match schema")
    if manifest.get("schema") != SCHEMA_VERSION:
        raise EvidenceError(f"unsupported identity schema: {manifest.get('schema')!r}")

    command = manifest.get("command")
    runtime = manifest.get("runtime")
    tools = manifest.get("tools")
    inputs = manifest.get("inputs")
    evidence_key = manifest.get("evidence_key")
    if not isinstance(command, str) or not command.strip():
        raise EvidenceError("identity command must be a non-empty string")
    if not isinstance(runtime, dict) or set(runtime) != {"implementation", "python"}:
        raise EvidenceError("identity runtime is malformed")
    if not all(isinstance(runtime.get(key), str) and runtime[key] for key in runtime):
        raise EvidenceError("identity runtime values must be non-empty strings")
    if not isinstance(tools, list) or not all(isinstance(tool, str) for tool in tools):
        raise EvidenceError("identity tools must be a list of strings")
    if tools != sorted(set(tools)):
        raise EvidenceError("identity tools are not canonical")
    if not isinstance(inputs, list) or not inputs:
        raise EvidenceError("identity inputs must be a non-empty list")

    normalized_inputs: list[dict[str, str]] = []
    previous_path = ""
    for item in inputs:
        if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
            raise EvidenceError("identity input entry is malformed")
        path = item.get("path")
        digest = item.get("sha256")
        if not isinstance(path, str) or not path:
            raise EvidenceError("identity input path must be non-empty")
        if path <= previous_path:
            raise EvidenceError("identity inputs are not in canonical path order")
        if not isinstance(digest, str) or len(digest) != 64:
            raise EvidenceError(f"identity input digest is malformed: {path}")
        try:
            int(digest, 16)
        except ValueError as exc:
            raise EvidenceError(f"identity input digest is malformed: {path}") from exc
        previous_path = path
        normalized_inputs.append({"path": path, "sha256": digest})

    identity: dict[str, object] = {
        "schema": SCHEMA_VERSION,
        "command": command,
        "runtime": dict(runtime),
        "tools": list(tools),
        "inputs": normalized_inputs,
    }
    expected_key = _canonical_hash(identity)
    if not isinstance(evidence_key, str) or evidence_key != expected_key:
        raise EvidenceError("identity evidence_key does not match manifest content")
    return {**identity, "evidence_key": evidence_key}


def complete_manifest(
    identity_manifest: Mapping[str, Any],
    *,
    exit_code: int,
    duration_seconds: float,
) -> dict[str, object]:
    """Bind one observed command result to a validated evidence identity."""
    identity = _validated_identity(identity_manifest)
    if isinstance(exit_code, bool) or not isinstance(exit_code, int) or exit_code < 0:
        raise EvidenceError("exit_code must be a non-negative integer")
    if not math.isfinite(duration_seconds) or duration_seconds < 0:
        raise EvidenceError("duration_seconds must be finite and non-negative")

    result = "success" if exit_code == 0 else "failure"
    attestation: dict[str, object] = {
        "schema": RESULT_SCHEMA_VERSION,
        "evidence_key": identity["evidence_key"],
        "result": result,
        "exit_code": exit_code,
        "duration_seconds": duration_seconds,
    }
    return {
        **attestation,
        "result_key": _canonical_hash(attestation),
        "identity": identity,
    }


def verify_completed_manifest(
    completed_manifest: Mapping[str, Any],
    *,
    expected_identity: Mapping[str, Any],
) -> dict[str, object]:
    """Verify that successful completed evidence exactly matches this consumer."""
    expected = _validated_identity(expected_identity)
    expected_fields = {
        "schema",
        "evidence_key",
        "result",
        "exit_code",
        "duration_seconds",
        "result_key",
        "identity",
    }
    if set(completed_manifest) != expected_fields:
        raise EvidenceError("completed evidence fields do not match schema")
    if completed_manifest.get("schema") != RESULT_SCHEMA_VERSION:
        raise EvidenceError(
            f"unsupported completed-evidence schema: {completed_manifest.get('schema')!r}"
        )

    embedded_raw = completed_manifest.get("identity")
    if not isinstance(embedded_raw, dict):
        raise EvidenceError("completed evidence identity is malformed")
    embedded = _validated_identity(embedded_raw)
    if embedded != expected:
        raise EvidenceError("completed evidence identity does not match expected inputs")
    if completed_manifest.get("evidence_key") != expected["evidence_key"]:
        raise EvidenceError("completed evidence_key does not match expected identity")

    exit_code = completed_manifest.get("exit_code")
    duration_seconds = completed_manifest.get("duration_seconds")
    result = completed_manifest.get("result")
    if isinstance(exit_code, bool) or not isinstance(exit_code, int) or exit_code < 0:
        raise EvidenceError("completed exit_code is malformed")
    if not isinstance(duration_seconds, (int, float)) or isinstance(duration_seconds, bool):
        raise EvidenceError("completed duration_seconds is malformed")
    duration = float(duration_seconds)
    if not math.isfinite(duration) or duration < 0:
        raise EvidenceError("completed duration_seconds is malformed")
    expected_result = "success" if exit_code == 0 else "failure"
    if result != expected_result:
        raise EvidenceError("completed result contradicts exit_code")

    attestation: dict[str, object] = {
        "schema": RESULT_SCHEMA_VERSION,
        "evidence_key": expected["evidence_key"],
        "result": expected_result,
        "exit_code": exit_code,
        "duration_seconds": duration_seconds,
    }
    if completed_manifest.get("result_key") != _canonical_hash(attestation):
        raise EvidenceError("completed result_key does not match evidence content")
    if exit_code != 0:
        raise EvidenceError(f"completed evidence records failed command exit code {exit_code}")

    return dict(completed_manifest)


def _read_json(path: str) -> dict[str, Any]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"cannot read evidence JSON {path!r}: {exc}") from exc
    if not isinstance(raw, dict):
        raise EvidenceError(f"evidence JSON {path!r} must contain an object")
    return raw


def _write_manifest(manifest: Mapping[str, object], out: str | None) -> None:
    rendered = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    if out:
        Path(out).write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--complete-from",
        metavar="IDENTITY_JSON",
        help="record exit/duration against a previously generated identity manifest",
    )
    mode.add_argument(
        "--verify-result",
        metavar="COMPLETED_JSON",
        help="verify completed evidence against the identity recomputed from --input/--command",
    )
    parser.add_argument("--input", action="append", default=[], dest="inputs")
    parser.add_argument("--command")
    parser.add_argument("--tool", action="append", default=[], dest="tools")
    parser.add_argument("--root", default=".")
    parser.add_argument("--out")
    parser.add_argument("--exit-code", type=int)
    parser.add_argument("--duration-seconds", type=float)
    return parser


def _identity_from_args(args: argparse.Namespace) -> dict[str, object]:
    if not args.inputs:
        raise EvidenceError("identity generation requires at least one --input")
    if args.command is None:
        raise EvidenceError("identity generation requires --command")
    return build_manifest(
        inputs=args.inputs,
        command=args.command,
        root=Path(args.root),
        tools=args.tools,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.complete_from:
            if args.exit_code is None or args.duration_seconds is None:
                raise EvidenceError(
                    "--complete-from requires --exit-code and --duration-seconds"
                )
            if args.inputs or args.command is not None or args.tools:
                raise EvidenceError(
                    "--complete-from consumes an existing identity; do not pass --input/--command/--tool"
                )
            manifest = complete_manifest(
                _read_json(args.complete_from),
                exit_code=args.exit_code,
                duration_seconds=args.duration_seconds,
            )
            _write_manifest(manifest, args.out)
            return 0

        identity = _identity_from_args(args)
        if args.exit_code is not None or args.duration_seconds is not None:
            raise EvidenceError(
                "--exit-code/--duration-seconds are only valid with --complete-from"
            )
        if args.verify_result:
            verify_completed_manifest(
                _read_json(args.verify_result),
                expected_identity=identity,
            )
            sys.stdout.write(f"verified build evidence {identity['evidence_key']}\n")
            return 0

        _write_manifest(identity, args.out)
        return 0
    except EvidenceError as exc:
        print(f"build evidence unavailable: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
