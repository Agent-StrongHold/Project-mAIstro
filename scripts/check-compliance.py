#!/usr/bin/env python3
"""Validate the compliance control registry and its rendered Markdown view.

The registry is deliberately evidence-first.  A control may describe an
implementation without claiming that a release has proved it.  Only an
``implemented`` control with passing, non-expired evidence bound to the exact
release digest can be green.  Legal sufficiency is outside this checker.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "quality" / "compliance-registry.json"
DOCUMENT = ROOT / "COMPLIANCE.md"
SCHEMA_VERSION = 1
STATUSES = frozenset(
    {
        "implemented",
        "partially_implemented",
        "documented",
        "planned",
        "not_applicable",
        "unverified",
    }
)
ID_RE = re.compile(r"^[A-Z][A-Z0-9-]+$")
HEX_DIGEST_RE = re.compile(r"^[0-9a-f]{40,64}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
REQUIRED_CONTROL_FIELDS = frozenset(
    {
        "id",
        "framework",
        "requirement",
        "status",
        "owner",
        "scope",
        "control_refs",
        "test_refs",
        "evidence",
        "last_verified",
        "expires",
        "release_required",
    }
)
REQUIRED_EVIDENCE_FIELDS = frozenset(
    {
        "url",
        "sha256",
        "release_digest",
        "observed_at",
        "result",
        "workflow_ref",
        "workflow_enabled",
        "manual_only",
        "ran",
    }
)
TABLE_HEADER = (
    "ID",
    "Framework",
    "Claim",
    "Status",
    "Owner",
    "Scope",
    "Last verification",
    "Expires",
    "Evidence",
)
BEGIN_MARKER = "<!-- compliance-registry:begin -->"
END_MARKER = "<!-- compliance-registry:end -->"


def _date(value: Any, field: str, where: str, errors: list[str]) -> dt.date | None:
    if value is None:
        return None
    if not isinstance(value, str) or not DATE_RE.fullmatch(value):
        errors.append(f"{where}.{field} must be an ISO date or null")
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        errors.append(f"{where}.{field} is not a real calendar date")
        return None


def _is_link(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _local_ref_exists(value: str, root: Path) -> bool:
    if _is_link(value):
        return True
    return (root / value).is_file()


def _is_executable_ref(value: str) -> bool:
    return value.startswith(("packages/", "scripts/", "formal/", "tests/", ".github/workflows/"))


def validate_registry(  # noqa: C901 - this is the single fail-closed schema/evidence gate
    registry: Any,
    *,
    root: Path = ROOT,
    today: dt.date | None = None,
    release_digest: str | None = None,
    require_release_evidence: bool = False,
) -> list[str]:
    """Return schema and evidence errors without making any network requests."""
    errors: list[str] = []
    today = today or dt.date.today()
    if not isinstance(registry, dict):
        return ["registry must be a JSON object"]
    if registry.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"registry schema_version must be {SCHEMA_VERSION}")
    registry_digest = registry.get("release_digest")
    if registry_digest is not None and (
        not isinstance(registry_digest, str) or not HEX_DIGEST_RE.fullmatch(registry_digest)
    ):
        errors.append("registry.release_digest must be null or a 40-64 character git digest")
    controls = registry.get("controls")
    if not isinstance(controls, list) or not controls:
        errors.append("registry.controls must be a non-empty list")
        return errors

    seen: set[str] = set()
    for index, control in enumerate(controls):
        where = f"controls[{index}]"
        if not isinstance(control, dict):
            errors.append(f"{where} must be an object")
            continue
        unknown = set(control) - REQUIRED_CONTROL_FIELDS
        missing = REQUIRED_CONTROL_FIELDS - set(control)
        if unknown:
            errors.append(f"{where} has unknown fields: {', '.join(sorted(unknown))}")
        if missing:
            errors.append(f"{where} is missing fields: {', '.join(sorted(missing))}")
            continue
        ident = control["id"]
        if not isinstance(ident, str) or not ID_RE.fullmatch(ident):
            errors.append(f"{where}.id must be an uppercase control ID")
        elif ident in seen:
            errors.append(f"duplicate control ID {ident}")
        else:
            seen.add(ident)
        for field in ("framework", "requirement", "owner", "scope"):
            if not isinstance(control[field], str) or not control[field].strip():
                errors.append(f"{where}.{field} must be a non-empty string")
        status = control["status"]
        if status not in STATUSES:
            errors.append(f"{where}.status {status!r} is not a supported status")
        if not isinstance(control["release_required"], bool):
            errors.append(f"{where}.release_required must be boolean")
        for field in ("control_refs", "test_refs", "evidence"):
            if not isinstance(control[field], list):
                errors.append(f"{where}.{field} must be a list")
        refs = control["control_refs"]
        if isinstance(refs, list):
            if not refs:
                errors.append(f"{where}.control_refs must not be empty")
            for ref in refs:
                if not isinstance(ref, str) or not _local_ref_exists(ref, root):
                    errors.append(f"{where}.control_refs contains a missing reference: {ref!r}")
        test_refs = control["test_refs"]
        if isinstance(test_refs, list):
            for ref in test_refs:
                if not isinstance(ref, str) or not _local_ref_exists(ref, root):
                    errors.append(f"{where}.test_refs contains a missing reference: {ref!r}")
        last_verified = _date(control["last_verified"], "last_verified", where, errors)
        expires = _date(control["expires"], "expires", where, errors)
        if expires is not None and expires < today and status == "implemented":
            errors.append(f"{ident} has expired evidence ({control['expires']})")
        if (
            status in {"implemented", "partially_implemented", "documented"}
            and last_verified is None
        ):
            errors.append(f"{ident} requires last_verified for status {status}")
        evidence = control["evidence"]
        if isinstance(evidence, list):
            for evidence_index, item in enumerate(evidence):
                evidence_where = f"{where}.evidence[{evidence_index}]"
                if not isinstance(item, dict):
                    errors.append(f"{evidence_where} must be an object")
                    continue
                evidence_missing = REQUIRED_EVIDENCE_FIELDS - set(item)
                evidence_unknown = set(item) - REQUIRED_EVIDENCE_FIELDS
                if evidence_unknown:
                    errors.append(
                        f"{evidence_where} has unknown fields: {', '.join(sorted(evidence_unknown))}"
                    )
                if evidence_missing:
                    errors.append(
                        f"{evidence_where} is missing fields: {', '.join(sorted(evidence_missing))}"
                    )
                    continue
                if not isinstance(item["url"], str) or not _is_link(item["url"]):
                    errors.append(f"{evidence_where}.url must be an absolute HTTP(S) link")
                if (
                    not isinstance(item["workflow_ref"], str)
                    or not item["workflow_ref"].startswith(".github/workflows/")
                    or not _local_ref_exists(item["workflow_ref"], root)
                ):
                    errors.append(f"{evidence_where}.workflow_ref must name an existing workflow")
                for field in ("workflow_enabled", "manual_only", "ran"):
                    if not isinstance(item[field], bool):
                        errors.append(f"{evidence_where}.{field} must be boolean")
                if not isinstance(item["sha256"], str) or not SHA256_RE.fullmatch(item["sha256"]):
                    errors.append(f"{evidence_where}.sha256 must be a 64 character SHA-256 digest")
                evidence_digest = item["release_digest"]
                if not isinstance(evidence_digest, str) or not HEX_DIGEST_RE.fullmatch(
                    evidence_digest
                ):
                    errors.append(f"{evidence_where}.release_digest must be a git digest")
                _date(item["observed_at"], "observed_at", evidence_where, errors)
                if item["result"] not in {"passed", "failed"}:
                    errors.append(f"{evidence_where}.result must be 'passed' or 'failed'")
                if status == "implemented":
                    if item.get("result") != "passed":
                        errors.append(
                            f"{ident} has non-passing evidence supporting implemented status"
                        )
                    if not item.get("workflow_enabled"):
                        errors.append(
                            f"{ident} has disabled workflow evidence supporting implemented status"
                        )
                    if item.get("manual_only"):
                        errors.append(
                            f"{ident} has manual-only evidence supporting implemented status"
                        )
                    if not item.get("ran"):
                        errors.append(
                            f"{ident} has never-run evidence supporting implemented status"
                        )
                if registry_digest and evidence_digest != registry_digest:
                    errors.append(f"{ident} evidence is not bound to registry.release_digest")
        if status == "implemented":
            if not registry_digest:
                errors.append(f"{ident} is implemented but has no release digest")
            if not control["evidence"]:
                errors.append(f"{ident} is implemented but has no immutable evidence")
            if not control["test_refs"]:
                errors.append(f"{ident} is implemented but has no executable test reference")
            if not any(_is_executable_ref(ref) for ref in control["control_refs"]):
                errors.append(f"{ident} is implemented but has no executable control reference")
            if expires is not None and expires < today:
                errors.append(f"{ident} is implemented but its evidence expiry has passed")
        if require_release_evidence and control["release_required"]:
            if not registry_digest:
                errors.append(
                    f"release evidence is missing: registry has no release_digest for {ident}"
                )
            if not control["evidence"]:
                errors.append(f"release evidence is missing: {ident} has no evidence")
            if status != "implemented":
                errors.append(
                    f"release evidence is incomplete: {ident} is {status}, not implemented"
                )

    if require_release_evidence:
        if not release_digest:
            errors.append("--release-digest is required when release evidence is required")
        elif not HEX_DIGEST_RE.fullmatch(release_digest):
            errors.append("--release-digest must be a 40-64 character git digest")
        elif registry_digest != release_digest:
            errors.append("registry.release_digest does not match --release-digest")
    return errors


def _table_rows(document: str) -> tuple[list[tuple[str, ...]], list[str]]:
    errors: list[str] = []
    if BEGIN_MARKER not in document or END_MARKER not in document:
        return [], ["COMPLIANCE.md is missing the compliance registry markers"]
    body = document.split(BEGIN_MARKER, 1)[1].split(END_MARKER, 1)[0]
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    if len(lines) < 3:
        return [], ["compliance registry table is incomplete"]
    if not (lines[0].startswith("|") and lines[0].endswith("|")):
        errors.append("compliance registry table has no header row")
        return [], errors
    header = tuple(cell.strip() for cell in lines[0][1:-1].split("|"))
    if header != TABLE_HEADER:
        errors.append(f"compliance registry header must be {TABLE_HEADER!r}")
    separator = (
        tuple(cell.strip() for cell in lines[1][1:-1].split("|"))
        if lines[1].startswith("|")
        else ()
    )
    if len(separator) != len(TABLE_HEADER) or any(
        not set(cell) <= {"-", ":"} for cell in separator
    ):
        errors.append("compliance registry has a malformed separator row")
    rows: list[tuple[str, ...]] = []
    for line_number, line in enumerate(lines[2:], start=3):
        if not (line.startswith("|") and line.endswith("|")):
            errors.append(f"compliance registry line {line_number} is not a table row")
            continue
        cells = tuple(cell.strip() for cell in line[1:-1].split("|"))
        if len(cells) != len(TABLE_HEADER):
            errors.append(
                f"compliance registry line {line_number} has {len(cells)} cells; expected {len(TABLE_HEADER)}"
            )
            continue
        rows.append(cells)
    return rows, errors


def validate_document(document: str, registry: Any) -> list[str]:
    rows, errors = _table_rows(document)
    controls = registry.get("controls", []) if isinstance(registry, dict) else []
    by_id = {control.get("id"): control for control in controls if isinstance(control, dict)}
    row_ids: set[str] = set()
    for row in rows:
        ident, framework, claim, status, owner, scope, last_verified, expires, evidence = row
        if ident in row_ids:
            errors.append(f"COMPLIANCE.md repeats control ID {ident}")
        row_ids.add(ident)
        control = by_id.get(ident)
        if control is None:
            errors.append(f"COMPLIANCE.md names unknown control ID {ident}")
            continue
        expected = (
            control["framework"],
            control["requirement"],
            control["status"],
            control["owner"],
            control["scope"],
            control["last_verified"] or "not recorded",
            control["expires"],
            _evidence_cell(control["evidence"]),
        )
        if (framework, claim, status, owner, scope, last_verified, expires, evidence) != expected:
            errors.append(f"COMPLIANCE.md row for {ident} does not match the registry")
        if status == "implemented" and evidence == "none":
            errors.append(f"COMPLIANCE.md marks {ident} implemented without evidence")
    missing = set(by_id) - row_ids
    if missing:
        errors.append(f"COMPLIANCE.md is missing control IDs: {', '.join(sorted(missing))}")
    return errors


def _evidence_cell(evidence: Any) -> str:
    if not evidence:
        return "none"
    return "; ".join(f"[{item['sha256'][:12]}]({item['url']})" for item in evidence)


def load_registry(path: Path = REGISTRY) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def check(
    *,
    registry_path: Path = REGISTRY,
    document_path: Path = DOCUMENT,
    release_digest: str | None = None,
    require_release_evidence: bool = False,
    today: dt.date | None = None,
) -> list[str]:
    try:
        registry = load_registry(registry_path)
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot load {registry_path}: {exc}"]
    errors = validate_registry(
        registry,
        root=registry_path.parents[1],
        today=today,
        release_digest=release_digest,
        require_release_evidence=require_release_evidence,
    )
    try:
        document = document_path.read_text(encoding="utf-8")
    except OSError as exc:
        return [*errors, f"cannot load {document_path}: {exc}"]
    return [*errors, *validate_document(document, registry)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=REGISTRY)
    parser.add_argument("--document", type=Path, default=DOCUMENT)
    parser.add_argument("--release-digest", help="exact commit digest being released")
    parser.add_argument(
        "--require-release-evidence",
        action="store_true",
        help="require every release-required control to have current passing evidence",
    )
    args = parser.parse_args(argv)
    errors = check(
        registry_path=args.registry,
        document_path=args.document,
        release_digest=args.release_digest,
        require_release_evidence=args.require_release_evidence,
    )
    if errors:
        print(f"compliance check FAILED ({len(errors)} problem(s))", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("compliance registry and COMPLIANCE.md are valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
