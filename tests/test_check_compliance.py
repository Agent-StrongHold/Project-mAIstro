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
                "evidence_refs": ["run-1", "execution-1"],
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
    receipt = {
        "execution_id": "https://github.com/Agent-StrongHold/Project-mAIstro/actions/runs/123456",
        "repository": "Agent-StrongHold/Project-mAIstro",
        "run_id": 123456,
        "head_sha": "a" * 40,
        "workflow": ".github/workflows/ci.yml",
        "result": "passed",
        "conclusion": "success",
        "observed_at": "2026-09-14T11:00:00Z",
    }
    receipt_path = tmp_path / "execution-receipt.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    payload["evidence"].append(
        {
            "id": "execution-1",
            "kind": "immutable_execution",
            "path": receipt_path.name,
            "sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            "execution_id": receipt["execution_id"],
            "state": "current",
            "mode": "automated",
            "result": "passed",
            "observed_at": receipt["observed_at"],
        }
    )
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
        "Y-1 | malformed row with no status and no closing pipe\n",
        "AT-99 missing separators and status\n",
    ],
)
def test_malformed_table_row_fails_instead_of_disappearing(tmp_path: Path, row: str) -> None:
    _write_repository(tmp_path)
    (tmp_path / "COMPLIANCE.md").write_text(
        f"| ID | Engine control | Status |\n|---|---|---|\n| X-1 | control | implemented |\n{row}",
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


def test_implemented_claim_requires_immutable_execution_evidence(tmp_path: Path) -> None:
    _write_repository(tmp_path)
    payload = json.loads((tmp_path / "registry.json").read_text())
    payload["claims"][0]["evidence_refs"] = ["run-1"]
    payload["evidence"] = [payload["evidence"][0]]
    (tmp_path / "registry.json").write_text(json.dumps(payload))

    assert any(
        "at least one immutable execution record" in str(finding) for finding in _findings(tmp_path)
    )


def test_forged_execution_id_is_rejected_even_with_matching_receipt(tmp_path: Path) -> None:
    _write_repository(tmp_path)
    payload = json.loads((tmp_path / "registry.json").read_text())
    record = payload["evidence"][1]
    receipt_path = tmp_path / record["path"]
    receipt = json.loads(receipt_path.read_text())
    receipt["execution_id"] = "forged:run/123456"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    record["execution_id"] = receipt["execution_id"]
    record["sha256"] = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    (tmp_path / "registry.json").write_text(json.dumps(payload))

    assert any(
        "canonical GitHub Actions run URL" in str(finding) for finding in _findings(tmp_path)
    )


def test_current_failing_execution_cannot_support_implemented(tmp_path: Path) -> None:
    _write_repository(tmp_path)
    payload = json.loads((tmp_path / "registry.json").read_text())
    record = payload["evidence"][1]
    record["result"] = "failed"
    receipt_path = tmp_path / record["path"]
    receipt = json.loads(receipt_path.read_text())
    receipt["result"] = "failed"
    receipt["conclusion"] = "failure"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    record["sha256"] = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    (tmp_path / "registry.json").write_text(json.dumps(payload))

    assert any(
        "requires automated passed evidence" in str(finding) for finding in _findings(tmp_path)
    )


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


def test_immutable_execution_requires_an_inspectable_receipt(tmp_path: Path) -> None:
    _write_repository(tmp_path)
    payload = json.loads((tmp_path / "registry.json").read_text())
    record = payload["evidence"][0]
    record["kind"] = "immutable_execution"
    record["execution_id"] = (
        "https://github.com/Agent-StrongHold/Project-mAIstro/actions/runs/123457"
    )
    receipt = {
        "execution_id": record["execution_id"],
        "repository": "Agent-StrongHold/Project-mAIstro",
        "run_id": 123457,
        "head_sha": "a" * 40,
        "workflow": ".github/workflows/ci.yml",
        "result": record["result"],
        "conclusion": "success",
        "observed_at": record["observed_at"],
    }
    receipt_path = tmp_path / "execution-receipt-2.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    record["path"] = receipt_path.name
    record["sha256"] = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    (tmp_path / "registry.json").write_text(json.dumps(payload))

    assert _findings(tmp_path) == []


def test_immutable_execution_id_without_a_receipt_fails_closed(tmp_path: Path) -> None:
    _write_repository(tmp_path)
    payload = json.loads((tmp_path / "registry.json").read_text())
    record = payload["evidence"][0]
    record["kind"] = "immutable_execution"
    record["execution_id"] = "forged:run/123456"
    record.pop("path")
    record.pop("sha256")
    (tmp_path / "registry.json").write_text(json.dumps(payload))

    assert any(
        "missing required field(s): path, sha256" in str(finding) for finding in _findings(tmp_path)
    )


def test_last_verified_staleness_is_reported(tmp_path: Path) -> None:
    _write_repository(tmp_path)
    payload = json.loads((tmp_path / "registry.json").read_text())
    payload["claims"][0]["last_verified"] = "1900-01-01"
    payload["claims"][0]["stale_after_days"] = 0
    (tmp_path / "registry.json").write_text(json.dumps(payload))

    assert any("claim verification is stale" in str(finding) for finding in _findings(tmp_path))


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
