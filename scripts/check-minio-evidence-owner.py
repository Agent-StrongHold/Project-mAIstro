#!/usr/bin/env python3
"""Keep MinIO archive evidence single-produced and fail closed.

`coverage (MinIO)` is the canonical runtime producer because it already runs the
archive conformance suite against a real MinIO server while collecting coverage.
The legacy required `object storage (MinIO)` context may delegate to that proof,
but only while the repository still requires the canonical producer and no
second workflow starts executing the same archive pytest target again.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CI_WORKFLOW = Path(".github/workflows/ci.yml")
QUALITY_WORKFLOW = Path(".github/workflows/quality.yml")
BRANCH_PROTECTION = Path(".github/branch-protection.json")
ARCHIVE_TARGET = "pytest packages/maistro-core/tests/archive"
MINIO_IMAGE = "minio/minio:RELEASE.2025-04-22T22-12-26Z"


class MinioEvidenceContractError(RuntimeError):
    """Raised when the canonical MinIO evidence ownership cannot be proven."""


def _job_block(text: str, job_id: str) -> str:
    lines = text.splitlines()
    marker = f"  {job_id}:"
    try:
        start = lines.index(marker)
    except ValueError as exc:
        raise MinioEvidenceContractError(f"workflow job {job_id!r} is missing") from exc

    end = len(lines)
    for index in range(start + 1, len(lines)):
        if re.fullmatch(r"  [A-Za-z0-9_-]+:\s*", lines[index]):
            end = index
            break
    return "\n".join(lines[start:end])


def _all_strings(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, dict):
        found: set[str] = set()
        for key, item in value.items():
            found.update(_all_strings(key))
            found.update(_all_strings(item))
        return found
    if isinstance(value, list):
        found = set()
        for item in value:
            found.update(_all_strings(item))
        return found
    return set()


def _archive_executions(root: Path) -> list[str]:
    executions: list[str] = []
    for workflow in sorted((root / ".github/workflows").glob("*.yml")):
        for lineno, line in enumerate(workflow.read_text(encoding="utf-8").splitlines(), start=1):
            if line.lstrip().startswith("#"):
                continue
            if ARCHIVE_TARGET in line:
                executions.append(f"{workflow.relative_to(root)}:{lineno}")
    return executions


def validate(root: Path = ROOT) -> list[str]:
    """Return contract violations; an empty list is the only passing state."""
    errors: list[str] = []
    ci = (root / CI_WORKFLOW).read_text(encoding="utf-8")
    quality = (root / QUALITY_WORKFLOW).read_text(encoding="utf-8")

    try:
        canonical = _job_block(quality, "coverage-archive")
    except MinioEvidenceContractError as exc:
        errors.append(str(exc))
        canonical = ""

    for needle, message in (
        ("name: coverage (MinIO)", "coverage-archive lost its required check name"),
        (MINIO_IMAGE, "coverage-archive no longer uses the reviewed pinned MinIO image"),
        ("server /data", "coverage-archive no longer starts the MinIO server"),
        (
            'MAISTRO_REQUIRE_S3_LEGS: "1"',
            "coverage-archive no longer makes skipped S3 legs fatal",
        ),
        ("coverage run --branch", "coverage-archive no longer records branch coverage"),
        (ARCHIVE_TARGET, "coverage-archive no longer executes archive conformance"),
    ):
        if needle not in canonical:
            errors.append(message)

    executions = _archive_executions(root)
    if len(executions) != 1:
        errors.append(
            "archive conformance must have exactly one workflow execution; found "
            + (", ".join(executions) if executions else "none")
        )
    elif not executions[0].startswith(str(QUALITY_WORKFLOW)):
        errors.append(f"archive conformance execution is not owned by {QUALITY_WORKFLOW}")

    try:
        compatibility = _job_block(ci, "object-storage")
    except MinioEvidenceContractError as exc:
        errors.append(str(exc))
        compatibility = ""
    if "name: object storage (MinIO)" not in compatibility:
        errors.append("legacy object-storage context lost its required check name")
    if "python3 scripts/check-minio-evidence-owner.py" not in compatibility:
        errors.append("legacy object-storage context no longer validates canonical ownership")
    if ARCHIVE_TARGET in compatibility or "minio/minio:" in compatibility:
        errors.append("legacy object-storage context started producing MinIO evidence again")

    try:
        protection = json.loads((root / BRANCH_PROTECTION).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"cannot read checked-in branch protection: {exc}")
    else:
        required = _all_strings(protection)
        for check in ("coverage (MinIO)", "object storage (MinIO)"):
            if check not in required:
                errors.append(f"checked-in branch protection no longer requires {check!r}")

    return errors


def main() -> int:
    try:
        errors = validate()
    except OSError as exc:
        print(f"FAIL: MinIO evidence ownership could not be established: {exc}")
        return 1
    if errors:
        print("FAIL: MinIO evidence ownership is not single-producer and fail-closed")
        for error in errors:
            print(f"  - {error}")
        return 1
    print(
        "OK: coverage (MinIO) is the sole archive/MinIO runtime producer; "
        "object storage (MinIO) is a compatibility contract only."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
