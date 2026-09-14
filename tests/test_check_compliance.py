"""Regression tests for the standalone technical compliance evidence validator."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_compliance.py"
spec = importlib.util.spec_from_file_location("check_compliance", SCRIPT)
assert spec and spec.loader
check_compliance = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = check_compliance
spec.loader.exec_module(check_compliance)


AS_OF = datetime(2026, 9, 14, 12, tzinfo=UTC)


def _write_repository(
    tmp_path: Path,
    *,
    evidence_state: str = "current",
    mode: str = "automated",
    result: str = "passed",
) -> None:
    artifact = tmp_path / "evidence.txt"
    artifact.write_text("repository-owned evidence\n", encoding="utf-8")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    (tmp_path / "COMPLIANCE.md").write_text(
        "| ID | Engine control | Status |\n|---|---|---|\n| X-1 | control | implemented |\n",
        encoding="utf-8",
    )
    payload = {
        "schema_version": 1,
        "claims": [
            {
                "control_id": "X-1",
                "status": "implemented",
                "owner": "test owner",
                "scope": "test scope",
                "evidence_refs": ["run-1"],
                "last_verified": "2026-09-14",
                "stale_after_days": 30,
            }
        ],
        "evidence": [
            {
                "id": "run-1",
                "kind": "repository_artifact",
                "path": "evidence.txt",
                "sha256": digest,
                "state": evidence_state,
                "mode": mode,
                "result": result,
                "observed_at": "2026-09-14T11:00:00Z",
            }
        ],
    }
    (tmp_path / "registry.json").write_text(json.dumps(payload), encoding="utf-8")


def _findings(tmp_path: Path) -> list[check_compliance.Finding]:
    return check_compliance.validate(
        tmp_path,
        document=tmp_path / "COMPLIANCE.md",
        registry=tmp_path / "registry.json",
        as_of=AS_OF,
    )


@pytest.mark.parametrize(
    "row",
    [
        "| X-1 | control |\n",
        "X-1 | control | implemented |\n",
    ],
)
def test_malformed_table_row_fails_instead_of_disappearing(tmp_path: Path, row: str) -> None:
    _write_repository(tmp_path)
    (tmp_path / "COMPLIANCE.md").write_text(
        f"| ID | Engine control | Status |\n|---|---|---|\n{row}",
        encoding="utf-8",
    )

    assert any("malformed table row" in str(finding) for finding in _findings(tmp_path))


def test_missing_status_cell_fails_closed(tmp_path: Path) -> None:
    _write_repository(tmp_path)
    (tmp_path / "COMPLIANCE.md").write_text(
        "| ID | Engine control | Status |\n|---|---|---|\n| X-1 | control | |\n",
        encoding="utf-8",
    )

    assert any("missing or invalid status cell" in str(finding) for finding in _findings(tmp_path))


@pytest.mark.parametrize(
    "field",
    ["owner", "control_id"],
)
def test_required_claim_identity_fields_fail_when_missing(tmp_path: Path, field: str) -> None:
    _write_repository(tmp_path)
    payload = json.loads((tmp_path / "registry.json").read_text())
    payload["claims"][0].pop(field)
    (tmp_path / "registry.json").write_text(json.dumps(payload))

    findings = _findings(tmp_path)

    assert any(
        f"claims[0] is missing required field(s): {field}" in str(finding) for finding in findings
    )


def test_missing_evidence_reference_fails(tmp_path: Path) -> None:
    _write_repository(tmp_path)
    payload = json.loads((tmp_path / "registry.json").read_text())
    payload["claims"][0]["evidence_refs"] = ["does-not-exist"]
    (tmp_path / "registry.json").write_text(json.dumps(payload))

    assert any("does not resolve" in str(finding) for finding in _findings(tmp_path))


@pytest.mark.parametrize(
    ("state", "mode", "result"),
    [
        ("disabled", "automated", "passed"),
        ("manual-only", "manual", "observed"),
        ("stale", "automated", "passed"),
        ("never-run", "automated", "not-run"),
        ("missing", "automated", "not-found"),
        ("failing", "automated", "failed"),
    ],
)
def test_non_current_evidence_cannot_support_implemented(
    tmp_path: Path, state: str, mode: str, result: str
) -> None:
    _write_repository(tmp_path, evidence_state=state, mode=mode, result=result)

    findings = _findings(tmp_path)

    assert any("implemented claim" in str(finding) for finding in findings)


def test_valid_current_evidence_record_passes(tmp_path: Path) -> None:
    _write_repository(tmp_path)

    assert _findings(tmp_path) == []


def test_cited_test_path_requires_a_typed_record_in_the_claim(tmp_path: Path) -> None:
    _write_repository(tmp_path)
    cited = tmp_path / "tests" / "test_evidence.py"
    cited.parent.mkdir()
    cited.write_text("def test_evidence(): pass\n", encoding="utf-8")
    (tmp_path / "COMPLIANCE.md").write_text(
        "| ID | Engine control | Test path | Status |\n"
        "|---|---|---|---|\n"
        "| X-1 | control | `tests/test_evidence.py` | implemented |\n",
        encoding="utf-8",
    )

    findings = _findings(tmp_path)

    assert any("no typed repository evidence record" in str(finding) for finding in findings)


def test_immutable_execution_evidence_is_structured_without_free_form_prose(
    tmp_path: Path,
) -> None:
    _write_repository(tmp_path)
    payload = json.loads((tmp_path / "registry.json").read_text())
    record = payload["evidence"][0]
    record.pop("path")
    record.pop("sha256")
    record["kind"] = "immutable_execution"
    record["execution_id"] = "github:run/123456"
    (tmp_path / "registry.json").write_text(json.dumps(payload))

    assert _findings(tmp_path) == []


def test_all_claim_statuses_are_distinct_schema_values() -> None:
    expected = {
        "implemented",
        "partially_implemented",
        "documented",
        "planned",
        "not_applicable",
        "unverified",
    }
    assert expected == check_compliance.CLAIM_STATUSES


def test_claim_status_schema_does_not_collapse_to_a_boolean() -> None:
    assert len(check_compliance.CLAIM_STATUSES) == 6
