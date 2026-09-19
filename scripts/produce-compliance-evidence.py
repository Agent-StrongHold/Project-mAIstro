#!/usr/bin/env python3
"""Run registry-declared tests and emit control-bound evidence manifests.

The output is intended to be uploaded as an immutable GitHub Actions artifact.
It is deliberately not a status updater: a human-reviewed registry change is
still required before a claim can become ``implemented``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "quality" / "compliance-registry.json"


def _load_registry(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("controls"), list):
        raise ValueError("registry must contain a controls list")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> bytes:
    content = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return content


def produce(
    registry: dict[str, Any],
    *,
    release_digest: str,
    output: Path,
    today: dt.date | None = None,
    runner: str | None = None,
) -> int:
    """Run every test behind an implemented claim and write its manifest."""
    today = today or dt.date.today()
    output.mkdir(parents=True, exist_ok=True)
    runner = runner or sys.executable
    failures = 0
    summary: list[dict[str, Any]] = []

    for control in registry["controls"]:
        if not isinstance(control, dict) or control.get("status") != "implemented":
            continue
        control_id = control.get("id")
        test_refs = control.get("test_refs")
        if (
            not isinstance(control_id, str)
            or not isinstance(test_refs, list)
            or not all(isinstance(ref, str) for ref in test_refs)
        ):
            raise ValueError(f"implemented control {control_id!r} has invalid test_refs")

        tests: list[dict[str, Any]] = []
        for ref in test_refs:
            command = [runner, "-m", "pytest", ref, "-q"]
            try:
                completed = subprocess.run(
                    command,
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=900,
                )
                exit_code = completed.returncode
                output_text = (completed.stdout + completed.stderr)[-4000:]
            except (OSError, subprocess.SubprocessError) as exc:
                exit_code = 1
                output_text = str(exc)
            result = "passed" if exit_code == 0 else "failed"
            tests.append(
                {
                    "command": command,
                    "exit_code": exit_code,
                    "ref": ref,
                    "result": result,
                    "output_tail": output_text,
                }
            )
            failures += exit_code != 0

        result = (
            "passed" if tests and all(test["result"] == "passed" for test in tests) else "failed"
        )
        if not tests:
            failures += 1
        payload = {
            "schema_version": 1,
            "control_id": control_id,
            "control_refs": control["control_refs"],
            "test_refs": test_refs,
            "release_digest": release_digest,
            "result": result,
            "observed_at": today.isoformat(),
            "tests": tests,
        }
        file_name = f"{control_id}.json"
        content = _write_json(output / file_name, payload)
        summary.append(
            {
                "control_id": control_id,
                "file": file_name,
                "sha256": hashlib.sha256(content).hexdigest(),
                "result": result,
            }
        )

    _write_json(
        output / "manifest.json",
        {
            "schema_version": 1,
            "release_digest": release_digest,
            "observed_at": today.isoformat(),
            "controls": summary,
        },
    )
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=REGISTRY)
    parser.add_argument("--release-digest", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        registry = _load_registry(args.registry)
        return produce(registry, release_digest=args.release_digest, output=args.output)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"compliance evidence production failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
