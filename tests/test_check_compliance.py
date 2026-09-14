"""Regression tests for the fail-closed compliance registry gate."""

from __future__ import annotations

import copy
import datetime as dt
import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-compliance.py"


@pytest.fixture(scope="module")
def checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_compliance", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def registry(checker: ModuleType) -> dict:
    return copy.deepcopy(checker.load_registry())


def test_real_registry_and_document_are_consistent(checker: ModuleType) -> None:
    assert checker.check(today=dt.date(2026, 8, 25)) == []


def test_registry_exposes_the_six_explicit_statuses(checker: ModuleType) -> None:
    statuses = {control["status"] for control in checker.load_registry()["controls"]}
    assert statuses == checker.STATUSES - {"implemented"}
    assert "implemented" in checker.STATUSES


def test_missing_required_field_fails_schema(checker: ModuleType, registry: dict) -> None:
    del registry["controls"][0]["owner"]
    errors = checker.validate_registry(registry, today=dt.date(2026, 8, 25))
    assert any("missing fields: owner" in error for error in errors)


def test_implemented_without_evidence_is_not_green(checker: ModuleType, registry: dict) -> None:
    control = registry["controls"][0]
    control["status"] = "implemented"
    control["last_verified"] = "2026-08-25"
    errors = checker.validate_registry(registry, today=dt.date(2026, 8, 25))
    assert any("implemented but has no immutable evidence" in error for error in errors)


def test_implemented_requires_an_executable_control_reference(
    checker: ModuleType, registry: dict
) -> None:
    control = registry["controls"][0]
    control["status"] = "implemented"
    control["control_refs"] = ["docs/adr/ADR-032-contracts-as-acceptance-criteria.md"]
    errors = checker.validate_registry(registry, today=dt.date(2026, 8, 25))
    assert any("no executable control reference" in error for error in errors)


def test_failing_evidence_cannot_support_implemented(checker: ModuleType, registry: dict) -> None:
    control = registry["controls"][0]
    control["status"] = "implemented"
    control["evidence"] = [
        {
            "url": "https://example.invalid/evidence/1",
            "sha256": "a" * 64,
            "release_digest": "b" * 40,
            "observed_at": "2026-08-25",
            "result": "failed",
            "workflow_ref": ".github/workflows/ci.yml",
            "workflow_enabled": True,
            "manual_only": False,
            "ran": True,
        }
    ]
    registry["release_digest"] = "b" * 40
    errors = checker.validate_registry(registry, today=dt.date(2026, 8, 25))
    assert any("non-passing evidence" in error for error in errors)


def test_implemented_requires_a_release_digest(checker: ModuleType, registry: dict) -> None:
    control = registry["controls"][0]
    control["status"] = "implemented"
    errors = checker.validate_registry(registry, today=dt.date(2026, 8, 25))
    assert any("has no release digest" in error for error in errors)


def test_disabled_workflow_evidence_cannot_be_green(checker: ModuleType, registry: dict) -> None:
    control = registry["controls"][0]
    digest = "b" * 40
    control["status"] = "implemented"
    control["evidence"] = [
        {
            "url": "https://example.invalid/evidence/1",
            "sha256": "a" * 64,
            "release_digest": digest,
            "observed_at": "2026-08-25",
            "result": "passed",
            "workflow_ref": ".github/workflows/ci.yml",
            "workflow_enabled": False,
            "manual_only": False,
            "ran": True,
        }
    ]
    registry["release_digest"] = digest
    errors = checker.validate_registry(registry, today=dt.date(2026, 8, 25))
    assert any("disabled workflow evidence" in error for error in errors)


def test_expired_implemented_evidence_fails(checker: ModuleType, registry: dict) -> None:
    control = registry["controls"][0]
    digest = "b" * 40
    control["status"] = "implemented"
    control["expires"] = "2026-08-24"
    control["evidence"] = [
        {
            "url": "https://example.invalid/evidence/1",
            "sha256": "a" * 64,
            "release_digest": digest,
            "observed_at": "2026-08-20",
            "result": "passed",
            "workflow_ref": ".github/workflows/ci.yml",
            "workflow_enabled": True,
            "manual_only": False,
            "ran": True,
        }
    ]
    registry["release_digest"] = digest
    errors = checker.validate_registry(registry, today=dt.date(2026, 8, 25))
    assert any("expired evidence" in error for error in errors)


def test_release_mode_requires_exact_digest_and_evidence(checker: ModuleType) -> None:
    errors = checker.check(
        release_digest="b" * 40,
        require_release_evidence=True,
        today=dt.date(2026, 8, 25),
    )
    assert any("release evidence is missing" in error for error in errors)
    assert any("registry has no release_digest" in error for error in errors)


def test_malformed_table_row_fails_closed(checker: ModuleType) -> None:
    document = (ROOT / "COMPLIANCE.md").read_text(encoding="utf-8")
    first_row = next(line for line in document.splitlines() if line.startswith("| OWASP-AT-01 |"))
    malformed = document.replace(first_row, first_row.rsplit(" |", 2)[0] + " |")
    errors = checker.validate_document(malformed, checker.load_registry())
    assert any("has 8 cells; expected 9" in error for error in errors)


def test_document_unknown_id_is_rejected(checker: ModuleType) -> None:
    document = (ROOT / "COMPLIANCE.md").read_text(encoding="utf-8")
    document = document.replace("| OWASP-AT-01 |", "| UNKNOWN-CONTROL |", 1)
    errors = checker.validate_document(document, checker.load_registry())
    assert any("unknown control ID UNKNOWN-CONTROL" in error for error in errors)


def test_forged_disabled_stale_evidence_fails_closed(checker: ModuleType, registry: dict) -> None:
    control = registry["controls"][0]
    control["status"] = "implemented"
    control["last_verified"] = "2000-01-01"
    digest = "1e264a7a39e9f87bdbd165c4f35510b4a72de7f4"
    control["evidence"] = [
        {
            "url": "https://example.invalid/evidence/1",
            "sha256": "a" * 64,
            "release_digest": digest,
            "observed_at": "2000-01-01",
            "result": "passed",
            "workflow_ref": ".github/workflows/mutation.yml",
            "workflow_enabled": True,
            "manual_only": False,
            "ran": True,
        }
    ]
    registry["release_digest"] = digest
    errors = checker.validate_registry(registry, today=dt.date(2026, 8, 25))
    assert any("immutable GitHub Actions" in error for error in errors)
    assert any("stale evidence" in error for error in errors)
    assert any("workflow_enabled does not match" in error for error in errors)
    assert any("manual_only does not match" in error for error in errors)


def test_evidence_schema_requires_immutable_http_link(checker: ModuleType, registry: dict) -> None:
    control = registry["controls"][0]
    control["evidence"] = [
        {
            "url": "./mutable-log.txt",
            "sha256": "a" * 64,
            "release_digest": "b" * 40,
            "observed_at": "2026-08-25",
            "result": "passed",
            "workflow_ref": ".github/workflows/ci.yml",
            "workflow_enabled": True,
            "manual_only": False,
            "ran": True,
        }
    ]
    registry["release_digest"] = "b" * 40
    errors = checker.validate_registry(registry, today=dt.date(2026, 8, 25))
    assert any(
        "url must be an immutable GitHub Actions run or artifact link" in error for error in errors
    )


def test_duplicate_control_ids_are_rejected(checker: ModuleType, registry: dict) -> None:
    registry["controls"].append(copy.deepcopy(registry["controls"][0]))
    errors = checker.validate_registry(registry, today=dt.date(2026, 8, 25))
    assert any("duplicate control ID OWASP-AT-01" in error for error in errors)


def test_json_is_human_readable_and_has_no_unknown_top_level_claims() -> None:
    data = json.loads((ROOT / "quality" / "compliance-registry.json").read_text(encoding="utf-8"))
    assert set(data) == {"schema_version", "release_digest", "controls"}
