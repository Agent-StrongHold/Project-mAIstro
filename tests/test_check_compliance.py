"""Regression tests for the fail-closed compliance registry gate."""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import importlib.util
import io
import json
import zipfile
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-compliance.py"
PRODUCER_SCRIPT = ROOT / "scripts" / "produce-compliance-evidence.py"


@pytest.fixture(scope="module")
def checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_compliance", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def producer() -> ModuleType:
    spec = importlib.util.spec_from_file_location("produce_compliance_evidence", PRODUCER_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def registry(checker: ModuleType) -> dict:
    return copy.deepcopy(checker.load_registry())


def attestation_for(control: dict, digest: str) -> tuple[dict, bytes]:
    payload = {
        "schema_version": 1,
        "control_id": control["id"],
        "control_refs": control["control_refs"],
        "test_refs": control["test_refs"],
        "release_digest": digest,
        "result": "passed",
        "tests": [{"ref": ref, "result": "passed", "exit_code": 0} for ref in control["test_refs"]],
    }
    content = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("compliance-attestation.json", content)
    return (
        {
            "file": "compliance-attestation.json",
            "sha256": hashlib.sha256(content).hexdigest(),
        },
        archive.getvalue(),
    )


def test_evidence_producer_binds_each_executed_test(
    producer: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    control = {
        "id": "TEST-CONTROL",
        "status": "implemented",
        "control_refs": ["scripts/check-compliance.py"],
        "test_refs": ["tests/test_check_compliance.py"],
    }

    class Completed:
        returncode = 0
        stdout = "1 passed"
        stderr = ""

    monkeypatch.setattr(producer.subprocess, "run", lambda *args, **kwargs: Completed())
    assert (
        producer.produce(
            {"controls": [control]},
            release_digest="a" * 40,
            output=tmp_path,
            today=dt.date(2026, 8, 25),
            runner="python",
        )
        == 0
    )
    manifest = json.loads((tmp_path / "TEST-CONTROL.json").read_text())
    assert manifest["control_id"] == "TEST-CONTROL"
    assert manifest["test_refs"] == control["test_refs"]
    assert manifest["tests"][0]["result"] == "passed"
    assert manifest["tests"][0]["exit_code"] == 0


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


def test_test_refs_must_identify_test_modules(checker: ModuleType, registry: dict) -> None:
    control = registry["controls"][0]
    control["test_refs"] = ["scripts/release_guard.py"]
    errors = checker.validate_registry(registry, today=dt.date(2026, 8, 25))
    assert any("non-test executable reference" in error for error in errors)


def test_evidence_scope_must_match_control_id(checker: ModuleType, registry: dict) -> None:
    control = registry["controls"][0]
    control["evidence"] = [
        {
            "url": "https://example.invalid/evidence/1",
            "control_id": "OTHER-CONTROL",
            "control_refs": control["control_refs"],
            "test_refs": control["test_refs"],
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
    errors = checker.validate_registry(registry, today=dt.date(2026, 8, 25))
    assert any("control_id does not match control ID" in error for error in errors)


def test_failing_evidence_cannot_support_implemented(checker: ModuleType, registry: dict) -> None:
    control = registry["controls"][0]
    control["status"] = "implemented"
    control["evidence"] = [
        {
            "url": "https://example.invalid/evidence/1",
            "control_id": control["id"],
            "control_refs": control["control_refs"],
            "test_refs": control["test_refs"],
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
            "control_id": control["id"],
            "control_refs": control["control_refs"],
            "test_refs": control["test_refs"],
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
            "control_id": control["id"],
            "control_refs": control["control_refs"],
            "test_refs": control["test_refs"],
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


def test_release_mode_requires_exact_digest_and_evidence(
    checker: ModuleType, registry: dict
) -> None:
    registry["controls"][0]["status"] = "implemented"
    errors = checker.validate_registry(
        registry,
        root=ROOT,
        release_digest="b" * 40,
        require_release_evidence=True,
        today=dt.date(2026, 8, 25),
    )
    assert any("release evidence is missing" in error for error in errors)
    assert any("registry has no release_digest" in error for error in errors)


def test_release_mode_rejects_unverified_release_required_controls(
    checker: ModuleType, registry: dict
) -> None:
    errors = checker.validate_registry(
        registry,
        root=ROOT,
        release_digest="b" * 40,
        require_release_evidence=True,
        today=dt.date(2026, 8, 25),
    )
    assert any("EU-AI-ACT-ART-15 is unverified, not implemented" in error for error in errors)
    assert any(
        "release evidence is missing: EU-AI-ACT-ART-15 has no evidence" in error for error in errors
    )


def test_release_mode_requires_digest_without_green_claims(
    checker: ModuleType, registry: dict
) -> None:
    errors = checker.validate_registry(
        registry,
        root=ROOT,
        require_release_evidence=True,
        today=dt.date(2026, 8, 25),
    )
    assert "--release-digest is required when release evidence is required" in errors


def test_evidence_workflow_does_not_run_after_release_tags(checker: ModuleType) -> None:
    workflow_path = ROOT / ".github" / "workflows" / "compliance-evidence.yml"
    source = workflow_path.read_text(encoding="utf-8")
    workflow = checker.yaml.safe_load(source)
    trigger_config = workflow.get("on", workflow.get(True))
    assert isinstance(trigger_config, dict)
    push = trigger_config["push"]
    assert isinstance(push, dict)
    assert "tags" not in push


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
            "control_id": control["id"],
            "control_refs": control["control_refs"],
            "test_refs": control["test_refs"],
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
            "control_id": control["id"],
            "control_refs": control["control_refs"],
            "test_refs": control["test_refs"],
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


def test_green_artifact_must_match_github_provenance(
    checker: ModuleType, registry: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    control = registry["controls"][0]
    digest = "b" * 40
    control["status"] = "implemented"
    control["last_verified"] = "2026-08-25"
    attestation, archive = attestation_for(control, digest)
    control["evidence"] = [
        {
            "url": "https://github.com/Agent-StrongHold/Project-mAIstro/actions/runs/123/artifacts/456",
            "control_id": control["id"],
            "control_refs": control["control_refs"],
            "test_refs": control["test_refs"],
            "sha256": "a" * 64,
            "release_digest": digest,
            "observed_at": "2026-08-25",
            "result": "passed",
            "workflow_ref": ".github/workflows/ci.yml",
            "workflow_enabled": True,
            "manual_only": False,
            "ran": True,
            "attestation": attestation,
        }
    ]
    registry["release_digest"] = digest
    monkeypatch.setattr(checker, "_git_commit_exists", lambda _digest, _root: True)
    monkeypatch.setattr(checker, "_github_bytes", lambda _url: (archive, None))

    def github_json(url: str) -> tuple[dict, None]:
        if "/artifacts/" in url:
            return {
                "workflow_run": {"id": 123},
                "expired": False,
                "digest": "sha256:" + "a" * 64,
            }, None
        if "/workflows/" in url:
            return {"state": "active"}, None
        return {
            "head_sha": digest,
            "path": ".github/workflows/ci.yml",
            "status": "completed",
            "conclusion": "success",
        }, None

    monkeypatch.setattr(checker, "_github_json", github_json)
    assert checker.validate_registry(registry, today=dt.date(2026, 8, 25)) == []

    control["evidence"][0].pop("attestation")
    errors = checker.validate_registry(registry, today=dt.date(2026, 8, 25))
    assert any("missing its executed-test attestation" in error for error in errors)


def test_commit_bound_locator_resolves_exact_release_artifact(
    checker: ModuleType,
    producer: ModuleType,
    registry: dict,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    control = registry["controls"][0]
    digest = "b" * 40
    control["status"] = "implemented"
    control["last_verified"] = "2026-08-25"

    class Completed:
        returncode = 0
        stdout = "1 passed"
        stderr = ""

    monkeypatch.setattr(producer.subprocess, "run", lambda *args, **kwargs: Completed())
    assert (
        producer.produce(
            {"controls": [control]},
            release_digest=digest,
            output=tmp_path,
            today=dt.date(2026, 8, 25),
            runner="python",
        )
        == 0
    )
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as bundle:
        bundle.write(tmp_path / f"{control['id']}.json", f"{control['id']}.json")
    archive = archive_buffer.getvalue()
    control["evidence"] = [
        {
            "url": (
                "https://github.com/Agent-StrongHold/Project-mAIstro/blob/"
                f"{digest}/.github/workflows/compliance-evidence.yml"
            ),
            "control_id": control["id"],
            "control_refs": control["control_refs"],
            "test_refs": control["test_refs"],
            "sha256": None,
            "release_digest": digest,
            "observed_at": "2026-08-25",
            "result": "passed",
            "workflow_ref": ".github/workflows/compliance-evidence.yml",
            "workflow_enabled": True,
            "manual_only": False,
            "ran": True,
            "attestation": {"file": f"{control['id']}.json", "sha256": None},
        }
    ]
    registry["release_digest"] = digest
    monkeypatch.setattr(checker, "_git_commit_exists", lambda _digest, _root: True)
    artifact_name = f"compliance-evidence-{digest}"

    def github_json(url: str) -> tuple[dict, None]:
        if "/runs?" in url:
            return {
                "workflow_runs": [
                    {
                        "id": 123,
                        "head_sha": digest,
                        "path": ".github/workflows/compliance-evidence.yml",
                        "status": "completed",
                        "conclusion": "success",
                    }
                ]
            }, None
        if "/runs/123/artifacts?" in url:
            return {
                "artifacts": [
                    {
                        "id": 456,
                        "name": artifact_name,
                        "expired": False,
                        "digest": "sha256:" + "a" * 64,
                    }
                ]
            }, None
        return {"state": "active"}, None

    monkeypatch.setattr(checker, "_github_json", github_json)
    monkeypatch.setattr(checker, "_github_bytes", lambda _url: (archive, None))
    assert checker.validate_registry(registry, today=dt.date(2026, 8, 25)) == []


def test_commit_bound_locator_fails_when_exact_artifact_is_missing(
    checker: ModuleType, registry: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    control = registry["controls"][0]
    digest = "c" * 40
    control["status"] = "implemented"
    control["last_verified"] = "2026-08-25"
    control["evidence"] = [
        {
            "url": (
                "https://github.com/Agent-StrongHold/Project-mAIstro/blob/"
                f"{digest}/.github/workflows/compliance-evidence.yml"
            ),
            "control_id": control["id"],
            "control_refs": control["control_refs"],
            "test_refs": control["test_refs"],
            "sha256": None,
            "release_digest": digest,
            "observed_at": "2026-08-25",
            "result": "passed",
            "workflow_ref": ".github/workflows/compliance-evidence.yml",
            "workflow_enabled": True,
            "manual_only": False,
            "ran": True,
            "attestation": {"file": f"{control['id']}.json", "sha256": None},
        }
    ]
    registry["release_digest"] = digest
    monkeypatch.setattr(checker, "_git_commit_exists", lambda _digest, _root: True)

    def github_json(url: str) -> tuple[dict, None]:
        if "/runs?" in url:
            return {
                "workflow_runs": [
                    {
                        "id": 123,
                        "head_sha": digest,
                        "path": ".github/workflows/compliance-evidence.yml",
                        "status": "completed",
                        "conclusion": "success",
                    }
                ]
            }, None
        if "/runs/123/artifacts?" in url:
            return {"artifacts": []}, None
        return {"state": "active"}, None

    monkeypatch.setattr(checker, "_github_json", github_json)
    errors = checker.validate_registry(registry, today=dt.date(2026, 8, 25))
    assert any("has no artifact named compliance-evidence-" in error for error in errors)


def test_live_disabled_workflow_cannot_support_green(
    checker: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = {
        "url": "https://github.com/Agent-StrongHold/Project-mAIstro/actions/runs/123/artifacts/456",
        "control_id": "OWASP-AT-01",
        "control_refs": ["packages/maistro-core/src/maistro/security/warden/detector.py"],
        "test_refs": ["packages/maistro-core/tests/security/warden/test_detector.py"],
        "sha256": "a" * 64,
        "release_digest": "b" * 40,
        "attestation": {"file": "manifest.json", "sha256": "c" * 64},
    }

    def github_json(url: str) -> tuple[dict, None]:
        if "/artifacts/" in url:
            return {
                "workflow_run": {"id": 123},
                "expired": False,
                "digest": "sha256:" + "a" * 64,
            }, None
        if "/workflows/" in url:
            return {"state": "disabled_manually"}, None
        return {
            "head_sha": item["release_digest"],
            "path": ".github/workflows/ci.yml",
            "status": "completed",
            "conclusion": "success",
        }, None

    monkeypatch.setattr(checker, "_github_json", github_json)
    errors = checker._verify_artifact_evidence(
        item, evidence_where="controls[0].evidence[0]", workflow_ref=".github/workflows/ci.yml"
    )
    assert any("not active in GitHub Actions" in error for error in errors)


def test_forged_artifact_digest_cannot_support_green(
    checker: ModuleType, registry: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    control = registry["controls"][0]
    digest = "b" * 40
    control["status"] = "implemented"
    control["last_verified"] = "2026-08-25"
    control["evidence"] = [
        {
            "url": "https://github.com/Agent-StrongHold/Project-mAIstro/actions/runs/123/artifacts/456",
            "control_id": control["id"],
            "control_refs": control["control_refs"],
            "test_refs": control["test_refs"],
            "sha256": "a" * 64,
            "release_digest": digest,
            "observed_at": "2026-08-25",
            "result": "passed",
            "workflow_ref": ".github/workflows/ci.yml",
            "workflow_enabled": True,
            "manual_only": False,
            "ran": True,
        }
    ]
    registry["release_digest"] = digest
    monkeypatch.setattr(checker, "_git_commit_exists", lambda _digest, _root: True)

    def github_json(url: str) -> tuple[dict, None]:
        if "/artifacts/" in url:
            return {
                "workflow_run": {"id": 123},
                "expired": False,
                "digest": "sha256:" + "c" * 64,
            }, None
        return {
            "head_sha": digest,
            "path": ".github/workflows/ci.yml",
            "status": "completed",
            "conclusion": "success",
        }, None

    monkeypatch.setattr(checker, "_github_json", github_json)
    errors = checker.validate_registry(registry, today=dt.date(2026, 8, 25))
    assert any("does not match the GitHub artifact digest" in error for error in errors)


def test_green_run_link_is_not_artifact_evidence(checker: ModuleType, registry: dict) -> None:
    control = registry["controls"][0]
    digest = "b" * 40
    control["status"] = "implemented"
    control["last_verified"] = "2026-08-25"
    control["evidence"] = [
        {
            "url": "https://github.com/Agent-StrongHold/Project-mAIstro/actions/runs/123",
            "control_id": control["id"],
            "control_refs": control["control_refs"],
            "test_refs": control["test_refs"],
            "sha256": "a" * 64,
            "release_digest": digest,
            "observed_at": "2026-08-25",
            "result": "passed",
            "workflow_ref": ".github/workflows/ci.yml",
            "workflow_enabled": True,
            "manual_only": False,
            "ran": True,
        }
    ]
    registry["release_digest"] = digest
    errors = checker.validate_registry(registry, today=dt.date(2026, 8, 25))
    assert any("must identify an immutable GitHub Actions artifact" in error for error in errors)


def test_duplicate_control_ids_are_rejected(checker: ModuleType, registry: dict) -> None:
    registry["controls"].append(copy.deepcopy(registry["controls"][0]))
    errors = checker.validate_registry(registry, today=dt.date(2026, 8, 25))
    assert any("duplicate control ID OWASP-AT-01" in error for error in errors)


def test_json_is_human_readable_and_has_no_unknown_top_level_claims() -> None:
    data = json.loads((ROOT / "quality" / "compliance-registry.json").read_text(encoding="utf-8"))
    assert set(data) == {"schema_version", "release_digest", "controls"}
