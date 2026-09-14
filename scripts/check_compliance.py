#!/usr/bin/env python3
"""Validate the machine-readable technical claims behind ``COMPLIANCE.md``.

This is an evidence-model check, not a legal sufficiency or release gate.  It
keeps the human mapping readable while requiring every claim to have a typed,
inspectable evidence record.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

CLAIM_STATUSES = {
    "implemented",
    "partially_implemented",
    "documented",
    "planned",
    "not_applicable",
    "unverified",
}
EVIDENCE_STATES = {
    "current",
    "disabled",
    "manual-only",
    "never-run",
    "stale",
    "missing",
    "failing",
}
GREEN_STATUSES = {"implemented"}
GREEN_BLOCKERS = EVIDENCE_STATES - {"current"}
STATUS_MARKERS = {"✅", "🟡", "🟠", "⚪", "—"}
MARKER_STATUS = {
    "✅": "implemented",
    "🟡": "partially_implemented",
    "🟠": "planned",
    "⚪": "unverified",
    "—": "not_applicable",
}
STATUS_WORDS = {status: status for status in CLAIM_STATUSES}
CONTROL_ID_RE = re.compile(r"^[A-Z][A-Z0-9.-]+$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CITED_ARTIFACT_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])((?:packages/[^\s;`,)]+/tests/[^\s;`,)]+)|"
    r"(?:formal|tests)/[^\s;`,)]+)"
)


@dataclass(frozen=True)
class Finding:
    subject: str
    reason: str

    def __str__(self) -> str:
        return f"{self.subject}: {self.reason}"


def _parse_date(value: Any, field: str, subject: str) -> date:
    if not isinstance(value, str):
        raise ValueError(f"{subject}.{field} must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{subject}.{field} must be an ISO date") from exc


def _parse_datetime(value: Any, field: str, subject: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{subject}.{field} must be an ISO datetime")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{subject}.{field} must be an ISO datetime") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{subject}.{field} must include a timezone")
    return parsed.astimezone(UTC)


def _require_keys(item: dict[str, Any], keys: set[str], subject: str) -> list[str]:
    missing = sorted(keys - item.keys())
    return [f"{subject} is missing required field(s): {', '.join(missing)}"] if missing else []


def _relative_artifact(root: Path, value: Any, subject: str) -> tuple[Path | None, list[str]]:
    if not isinstance(value, str) or not value:
        return None, [f"{subject}.path must be a non-empty repository-relative path"]
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        return None, [f"{subject}.path must stay inside the repository"]
    resolved = (root / path).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        return None, [f"{subject}.path escapes the repository"]
    if not resolved.is_file():
        return None, [f"{subject}.path does not resolve to a file: {value}"]
    return resolved, []


def _validate_evidence(  # noqa: C901
    root: Path, evidence: Any, as_of: datetime
) -> tuple[list[Finding], dict[str, dict[str, Any]]]:
    findings: list[Finding] = []
    records: dict[str, dict[str, Any]] = {}
    if not isinstance(evidence, list) or not evidence:
        return [Finding("evidence", "must be a non-empty list")], records

    required = {"id", "kind", "state", "mode", "observed_at"}
    for index, raw in enumerate(evidence):
        subject = f"evidence[{index}]"
        if not isinstance(raw, dict):
            findings.append(Finding(subject, "must be an object"))
            continue
        findings.extend(
            Finding(subject, reason) for reason in _require_keys(raw, required, subject)
        )
        evidence_id = raw.get("id")
        if not isinstance(evidence_id, str) or not evidence_id:
            findings.append(Finding(subject, "id must be a non-empty string"))
        elif evidence_id in records:
            findings.append(Finding(subject, f"duplicate id {evidence_id!r}"))
        else:
            records[evidence_id] = raw

        kind = raw.get("kind")
        if kind not in {"repository_artifact", "immutable_execution"}:
            findings.append(
                Finding(subject, "kind must be repository_artifact or immutable_execution")
            )
        if kind == "repository_artifact" or "path" in raw or "sha256" in raw:
            findings.extend(
                Finding(subject, reason)
                for reason in _require_keys(raw, {"path", "sha256"}, subject)
            )
            path, path_findings = _relative_artifact(root, raw.get("path"), subject)
            findings.extend(Finding(subject, reason) for reason in path_findings)
            digest = raw.get("sha256")
            if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
                findings.append(Finding(subject, "sha256 must be a lowercase SHA-256 digest"))
            elif path is not None:
                actual = hashlib.sha256(path.read_bytes()).hexdigest()
                if actual != digest:
                    findings.append(
                        Finding(subject, "sha256 does not match the repository artifact")
                    )
        if raw.get("state") not in EVIDENCE_STATES:
            findings.append(Finding(subject, f"state must be one of {sorted(EVIDENCE_STATES)}"))
        if raw.get("mode") not in {"automated", "manual"}:
            findings.append(Finding(subject, "mode must be automated or manual"))
        try:
            observed = _parse_datetime(raw.get("observed_at"), "observed_at", subject)
            if observed > as_of:
                findings.append(Finding(subject, "observed_at cannot be in the future"))
        except ValueError as exc:
            findings.append(Finding(subject, str(exc)))
        if raw.get("kind") == "immutable_execution":
            execution_id = raw.get("execution_id")
            if not isinstance(execution_id, str) or not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9._:/-]{5,127}", execution_id
            ):
                findings.append(
                    Finding(subject, "immutable_execution requires a structured execution_id")
                )
        if "expires_at" in raw:
            try:
                expires = _parse_datetime(raw["expires_at"], "expires_at", subject)
                if expires < as_of and raw.get("state") == "current":
                    findings.append(
                        Finding(subject, "current evidence has expired; classify it as stale")
                    )
            except ValueError as exc:
                findings.append(Finding(subject, str(exc)))
    return findings, records


def _validate_claims(  # noqa: C901
    claims: Any, evidence: dict[str, dict[str, Any]], as_of: datetime
) -> list[Finding]:
    findings: list[Finding] = []
    if not isinstance(claims, list) or not claims:
        return [Finding("claims", "must be a non-empty list")]
    required = {
        "control_id",
        "status",
        "owner",
        "scope",
        "evidence_refs",
        "last_verified",
        "stale_after_days",
    }
    seen: set[str] = set()
    for index, raw in enumerate(claims):
        subject = f"claims[{index}]"
        if not isinstance(raw, dict):
            findings.append(Finding(subject, "must be an object"))
            continue
        findings.extend(
            Finding(subject, reason) for reason in _require_keys(raw, required, subject)
        )
        control_id = raw.get("control_id")
        if not isinstance(control_id, str) or not CONTROL_ID_RE.fullmatch(control_id):
            findings.append(Finding(subject, "control_id must be an uppercase stable identifier"))
        elif control_id in seen:
            findings.append(Finding(subject, f"duplicate control_id {control_id!r}"))
        else:
            seen.add(control_id)
        status = raw.get("status")
        if status not in CLAIM_STATUSES:
            findings.append(Finding(subject, f"status must be one of {sorted(CLAIM_STATUSES)}"))
        for field in ("owner", "scope"):
            if not isinstance(raw.get(field), str) or not raw[field].strip():
                findings.append(Finding(subject, f"{field} must be a non-empty string"))
        refs = raw.get("evidence_refs")
        if (
            not isinstance(refs, list)
            or not refs
            or not all(isinstance(ref, str) and ref for ref in refs)
        ):
            findings.append(Finding(subject, "evidence_refs must be a non-empty list of ids"))
            refs = []
        try:
            last_verified = _parse_date(raw.get("last_verified"), "last_verified", subject)
            if last_verified > as_of.date():
                findings.append(Finding(subject, "last_verified cannot be in the future"))
        except ValueError as exc:
            findings.append(Finding(subject, str(exc)))
        stale_after = raw.get("stale_after_days")
        if not isinstance(stale_after, int) or isinstance(stale_after, bool) or stale_after < 0:
            findings.append(Finding(subject, "stale_after_days must be a non-negative integer"))
        if "expires" in raw:
            try:
                expires = _parse_date(raw["expires"], "expires", subject)
                if expires < as_of.date():
                    findings.append(Finding(subject, "claim expiry has passed"))
            except ValueError as exc:
                findings.append(Finding(subject, str(exc)))
        resolved = []
        for ref in refs:
            if ref not in evidence:
                findings.append(Finding(subject, f"evidence reference does not resolve: {ref}"))
            else:
                resolved.append(evidence[ref])
        if isinstance(stale_after, int) and not isinstance(stale_after, bool) and stale_after >= 0:
            for record in resolved:
                if record.get("state") != "current":
                    continue
                try:
                    observed = _parse_datetime(record.get("observed_at"), "observed_at", subject)
                except ValueError:
                    continue
                if as_of - observed > timedelta(days=stale_after):
                    findings.append(
                        Finding(subject, f"evidence is stale for this claim: {record.get('id')}")
                    )
        if status in GREEN_STATUSES:
            for record in resolved:
                state = record.get("state")
                if state in GREEN_BLOCKERS:
                    findings.append(
                        Finding(
                            subject,
                            f"implemented claim cannot use {state} evidence: {record.get('id')}",
                        )
                    )
                if state == "current" and (
                    record.get("mode") != "automated" or record.get("result") != "passed"
                ):
                    findings.append(
                        Finding(
                            subject,
                            f"implemented claim requires automated passed evidence: {record.get('id')}",
                        )
                    )
    return findings


def _split_row(line: str) -> list[str]:
    if not line.startswith("|") or not line.rstrip().endswith("|"):
        return []
    return [cell.strip() for cell in line.strip()[1:-1].split("|")]


def _control_id(cell: str) -> str | None:
    value = re.sub(r"[*`]", "", cell).strip()
    match = re.match(r"(AT-\d+|GOVERN-\d+|MAP-\d+|MEASURE-\d+|MANAGE-\d+)", value)
    if match:
        return match.group(1)
    match = re.match(r"Art\.\s*(\d+)", value, re.IGNORECASE)
    if match:
        return f"EU-ART-{match.group(1)}"
    if value.startswith("Security "):
        return "SOC2-SECURITY"
    if value.startswith("Availability "):
        return "SOC2-AVAILABILITY"
    if value.startswith("Processing Integrity "):
        return "SOC2-PROCESSING-INTEGRITY"
    if value.startswith("Confidentiality "):
        return "SOC2-CONFIDENTIALITY"
    if value.startswith("Privacy "):
        return "SOC2-PRIVACY"
    generic = re.fullmatch(r"[A-Z][A-Z0-9.-]+", value)
    return generic.group(0) if generic else None


def _cited_artifact_paths(cells: list[str]) -> set[str]:
    paths: set[str] = set()
    for cell in cells[1:-1]:
        paths.update(match.group(1).rstrip(".") for match in CITED_ARTIFACT_RE.finditer(cell))
    return paths


def _looks_like_table_row(line: str, expected_cells: int) -> bool:
    stripped = line.strip()
    return bool(stripped) and (stripped.endswith("|") or stripped.count("|") >= expected_cells - 1)


def _parse_status_row(
    headers: list[str], row: str, label: str
) -> tuple[list[Finding], str | None, str | None, set[str]]:
    cells = _split_row(row)
    if len(cells) != len(headers):
        return (
            [
                Finding(
                    label,
                    f"malformed table row: expected {len(headers)} cells, got {len(cells)}",
                )
            ],
            None,
            None,
            set(),
        )
    findings: list[Finding] = []
    control_id = _control_id(cells[0])
    if control_id is None:
        findings.append(Finding(label, "missing control ID"))
    status_cell = cells[-1].strip()
    marker = next((candidate for candidate in STATUS_MARKERS if candidate in status_cell), None)
    status = MARKER_STATUS.get(marker) if marker else STATUS_WORDS.get(status_cell)
    if status is None:
        findings.append(Finding(label, "missing or invalid status cell"))
    return findings, control_id, status, _cited_artifact_paths(cells)


def _parse_compliance_document(  # noqa: C901
    path: Path,
) -> tuple[list[Finding], dict[str, str], dict[str, set[str]]]:
    """Parse status tables, retaining the inspectable paths cited by each claim."""
    lines = path.read_text(encoding="utf-8").splitlines()
    findings: list[Finding] = []
    statuses: dict[str, str] = {}
    cited_paths: dict[str, set[str]] = {}
    for index, line in enumerate(lines):
        headers = _split_row(line)
        if not headers or index + 1 >= len(lines) or not lines[index + 1].startswith("|---"):
            continue
        if headers[-1].lower() != "status":
            continue
        row_index = index + 2
        while row_index < len(lines):
            row = lines[row_index]
            if not row.strip():
                break
            label = f"COMPLIANCE.md:{row_index + 1}"
            if not row.startswith("|"):
                if _looks_like_table_row(row, len(headers)):
                    findings.append(
                        Finding(
                            label,
                            f"malformed table row: expected {len(headers)} cells and a leading pipe",
                        )
                    )
                    row_index += 1
                    continue
                break
            row_findings, control_id, status, paths = _parse_status_row(headers, row, label)
            findings.extend(row_findings)
            if status is not None and control_id is not None:
                if control_id in statuses:
                    findings.append(Finding(label, f"duplicate control ID: {control_id}"))
                statuses[control_id] = status
                cited_paths[control_id] = paths
            row_index += 1
    if not statuses:
        findings.append(Finding(str(path), "no status-bearing compliance tables found"))
    return findings, statuses, cited_paths


def parse_compliance_document(path: Path) -> tuple[list[Finding], dict[str, str]]:
    """Parse every status-bearing Markdown table and reject malformed rows."""
    findings, statuses, _ = _parse_compliance_document(path)
    return findings, statuses


def validate(
    root: Path,
    *,
    document: Path | None = None,
    registry: Path | None = None,
    as_of: datetime | None = None,
) -> list[Finding]:
    root = root.resolve()
    document = document or root / "COMPLIANCE.md"
    registry = registry or root / "docs" / "compliance" / "claims.json"
    as_of = as_of or datetime.now(UTC)
    findings: list[Finding] = []
    try:
        document_findings, document_statuses, cited_paths = _parse_compliance_document(document)
    except (OSError, UnicodeError) as exc:
        return [Finding(str(document), f"cannot read document: {exc}")]
    findings.extend(document_findings)
    try:
        payload = json.loads(registry.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        findings.append(Finding(str(registry), f"cannot read JSON registry: {exc}"))
        return findings
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        findings.append(Finding(str(registry), "schema_version must be 1"))
        return findings
    evidence_findings, evidence = _validate_evidence(root, payload.get("evidence"), as_of)
    findings.extend(evidence_findings)
    findings.extend(_validate_claims(payload.get("claims"), evidence, as_of))
    claim_items = {
        item.get("control_id"): item for item in payload.get("claims", []) if isinstance(item, dict)
    }
    claim_statuses = {control_id: item.get("status") for control_id, item in claim_items.items()}
    if set(document_statuses) != set(claim_statuses):
        findings.append(
            Finding("claim coverage", "COMPLIANCE.md controls and registry controls differ")
        )
    for control_id, marker_status in document_statuses.items():
        if claim_statuses.get(control_id) != marker_status:
            findings.append(
                Finding(
                    control_id,
                    f"document status {marker_status!r} disagrees with registry {claim_statuses.get(control_id)!r}",
                )
            )
        claim = claim_items.get(control_id)
        refs = set(claim.get("evidence_refs", [])) if claim else set()
        for path in cited_paths.get(control_id, set()):
            matching_refs = {
                evidence_id
                for evidence_id, record in evidence.items()
                if record.get("kind") == "repository_artifact" and record.get("path") == path
            }
            if not matching_refs:
                findings.append(
                    Finding(
                        f"{control_id} evidence",
                        f"cited path has no typed repository evidence record: {path}",
                    )
                )
            elif not matching_refs & refs:
                findings.append(
                    Finding(
                        f"{control_id} evidence",
                        f"cited path is not referenced by the claim: {path}",
                    )
                )
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--as-of", type=lambda value: datetime.fromisoformat(value.replace("Z", "+00:00"))
    )
    args = parser.parse_args(argv)
    findings = validate(args.root, as_of=args.as_of)
    if findings:
        for finding in findings:
            print(f"ERROR: {finding}")
        print(f"compliance evidence validation failed ({len(findings)} finding(s))")
        return 1
    print("OK: compliance claims have valid, inspectable evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
