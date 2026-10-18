"""Regression tests for the fail-closed compliance registry gate."""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import importlib.util
import io
import json
import subprocess
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
        "observed_at": "2026-08-25",
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


# ---------------------------------------------------------------------------
# Helpers for the fail-closed path tests below
# ---------------------------------------------------------------------------


def evidence_item(control: dict, digest: str, **overrides: object) -> dict:
    item = {
        "url": "https://example.invalid/evidence/1",
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
    item.update(overrides)
    return item


def manifest_payload(control: dict, digest: str, **overrides: object) -> dict:
    payload = {
        "schema_version": 1,
        "observed_at": "2026-08-25",
        "control_id": control["id"],
        "control_refs": control["control_refs"],
        "test_refs": control["test_refs"],
        "release_digest": digest,
        "result": "passed",
        "tests": [{"ref": ref, "result": "passed", "exit_code": 0} for ref in control["test_refs"]],
    }
    payload.update(overrides)
    return payload


def zip_bytes(**files: bytes) -> bytes:
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as bundle:
        for name, content in files.items():
            bundle.writestr(name, content)
    return archive.getvalue()


# ---------------------------------------------------------------------------
# Verification claims must be time-bounded (#362): a missing expiry can never
# go stale, so the checker fails closed instead of trusting it forever.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["implemented", "partially_implemented", "documented"])
def test_verified_statuses_require_an_expiry_date(
    checker: ModuleType, registry: dict, status: str
) -> None:
    control = registry["controls"][0]
    control["status"] = status
    control["expires"] = None
    errors = checker.validate_registry(registry, today=dt.date(2026, 8, 25))
    assert any("requires an expires date" in error for error in errors)


def test_unverified_statuses_may_omit_expiry(checker: ModuleType, registry: dict) -> None:
    control = registry["controls"][0]
    control["status"] = "planned"
    control["last_verified"] = None
    control["expires"] = None
    errors = [
        error
        for error in checker.validate_registry(registry, today=dt.date(2026, 8, 25))
        if control["id"] in error
    ]
    assert errors == []


def test_implemented_requires_last_verified(checker: ModuleType, registry: dict) -> None:
    control = registry["controls"][0]
    control["status"] = "implemented"
    control["last_verified"] = None
    errors = checker.validate_registry(registry, today=dt.date(2026, 8, 25))
    assert any("requires last_verified" in error for error in errors)


def test_malformed_and_impossible_dates_fail_closed(checker: ModuleType, registry: dict) -> None:
    control = registry["controls"][0]
    control["last_verified"] = "26th of August"
    errors = checker.validate_registry(registry, today=dt.date(2026, 8, 25))
    assert any("must be an ISO date or null" in error for error in errors)
    control["last_verified"] = "2026-02-30"
    errors = checker.validate_registry(registry, today=dt.date(2026, 8, 25))
    assert any("not a real calendar date" in error for error in errors)


def test_link_and_reference_helpers_fail_closed(checker: ModuleType, tmp_path: Path) -> None:
    assert checker._is_link(None) is False
    assert checker._local_ref_exists("https://example.com/control.md", tmp_path) is True
    assert checker._local_ref_exists("docs/adr/ADR-001.md", tmp_path) is False
    assert checker._is_test_ref("scripts/release_guard.py") is False
    assert checker._is_test_ref("docs/adr/x.md") is False
    assert checker._is_test_ref("packages/maistro-core/tests/test_x.py") is True


def test_git_probe_fails_closed_when_git_is_unavailable(
    checker: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: object, **kwargs: object) -> object:
        raise OSError("git missing")

    monkeypatch.setattr(checker.subprocess, "run", boom)
    assert checker._git_commit_exists("b" * 40, tmp_path) is False


def test_workflow_locator_accepts_only_commit_bound_workflow_links(
    checker: ModuleType,
) -> None:
    base = f"https://github.com/{checker.GITHUB_REPOSITORY}/blob"
    assert checker._workflow_locator(None) is None
    assert checker._workflow_locator(f"http://github.com/x/blob/{'b' * 40}/w.yml") is None
    assert checker._workflow_locator(f"https://gitlab.com/x/blob/{'b' * 40}/w.yml") is None
    assert checker._workflow_locator(f"{base}/nothex/.github/workflows/ci.yml") is None
    assert checker._workflow_locator(f"{base}/{'b' * 40}/docs/notes.md") is None
    assert checker._workflow_locator(f"{base}/{'b' * 40}/.github/workflows/ci.yml") == (
        "b" * 40,
        ".github/workflows/ci.yml",
    )


def test_immutable_link_accepts_only_github_actions_urls(checker: ModuleType) -> None:
    base = f"https://github.com/{checker.GITHUB_REPOSITORY}/actions/runs"
    assert checker._is_immutable_evidence_link(None) is False
    assert checker._is_immutable_evidence_link("http://github.com/x") is False
    assert checker._is_immutable_evidence_link("https://example.com/actions/runs/1") is False
    assert (
        checker._is_immutable_evidence_link(
            f"https://github.com/{checker.GITHUB_REPOSITORY}/wiki/x"
        )
        is False
    )
    assert checker._is_immutable_evidence_link(f"{base}/123") is True
    assert checker._is_immutable_evidence_link(f"{base}/123/artifacts/456") is True


def test_evidence_artifact_ids_require_run_and_artifact_numbers(
    checker: ModuleType,
) -> None:
    base = f"https://github.com/{checker.GITHUB_REPOSITORY}/actions/runs"
    assert checker._evidence_artifact_ids("http://github.com/x") is None
    assert checker._evidence_artifact_ids(f"{base}/123") is None
    assert checker._evidence_artifact_ids(f"{base}/abc/artifacts/def") is None
    assert checker._evidence_artifact_ids(f"{base}/0/artifacts/456") is None
    assert checker._evidence_artifact_ids(f"{base}/123/artifacts/456") == (123, 456)


def test_github_json_reports_failures_as_evidence_failures(
    checker: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)

    def boom(request: object, timeout: int) -> None:
        raise OSError("network down")

    monkeypatch.setattr(checker.urllib.request, "urlopen", boom)
    payload, failure = checker._github_json("https://api.github.com/x")
    assert payload is None
    assert "network down" in (failure or "")

    class FakeResponse:
        def read(self) -> bytes:
            return b"[1, 2]"

        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *exc: object) -> bool:
            return False

    monkeypatch.setattr(checker.urllib.request, "urlopen", lambda request, timeout: FakeResponse())
    payload, failure = checker._github_json("https://api.github.com/x")
    assert payload is None
    assert failure == "GitHub returned a non-object response"


def test_github_requests_carry_the_token_header(
    checker: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "token-123")
    seen: dict[str, str] = {}

    class FakeResponse:
        def read(self) -> bytes:
            return b"{}"

        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *exc: object) -> bool:
            return False

    def fake_urlopen(request: object, timeout: int) -> FakeResponse:
        seen.update(request.headers)  # type: ignore[attr-defined]
        return FakeResponse()

    monkeypatch.setattr(checker.urllib.request, "urlopen", fake_urlopen)
    payload, failure = checker._github_json("https://api.github.com/x")
    assert (payload, failure) == ({}, None)
    assert seen["Authorization"] == "Bearer token-123"


def test_github_bytes_downloads_artifacts_and_fails_closed(
    checker: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GH_TOKEN", "tok-456")
    seen: dict[str, str] = {}

    class FakeResponse:
        def __init__(self, body: bytes) -> None:
            self.body = body

        def read(self) -> bytes:
            return self.body

        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *exc: object) -> bool:
            return False

    def fake_urlopen(request: object, timeout: int) -> FakeResponse:
        seen.update(request.headers)  # type: ignore[attr-defined]
        return FakeResponse(b"artifact-bytes")

    monkeypatch.setattr(checker.urllib.request, "urlopen", fake_urlopen)
    body, failure = checker._github_bytes("https://api.github.com/x/zip")
    assert (body, failure) == (b"artifact-bytes", None)
    assert seen["Authorization"] == "Bearer tok-456"

    def boom(request: object, timeout: int) -> None:
        raise OSError("no route to host")

    monkeypatch.setattr(checker.urllib.request, "urlopen", boom)
    body, failure = checker._github_bytes("https://api.github.com/x/zip")
    assert body is None
    assert "no route to host" in (failure or "")


# ---------------------------------------------------------------------------
# Attestation verification must fail closed on every unprovable shape
# ---------------------------------------------------------------------------


def test_attestation_metadata_must_be_well_formed(checker: ModuleType) -> None:
    bad_path = {"attestation": {"file": "../escape.json", "sha256": "a" * 64}}
    errors = checker._verify_attestation(bad_path, evidence_where="e", artifact_id=1)
    assert any("attestation must name a file" in error for error in errors)
    bad_digest = {"attestation": {"file": "manifest.json", "sha256": "nope"}}
    errors = checker._verify_attestation(bad_digest, evidence_where="e", artifact_id=1)
    assert any("attestation must name a file" in error for error in errors)
    assert any(
        "is missing its executed-test attestation" in error
        for error in checker._verify_attestation({}, evidence_where="e", artifact_id=1)
    )


def test_unreadable_artifacts_fail_closed(
    checker: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = {"attestation": {"file": "manifest.json", "sha256": None}}

    monkeypatch.setattr(checker, "_github_bytes", lambda _url: (None, "artifact gone"))
    errors = checker._verify_attestation(item, evidence_where="e", artifact_id=1)
    assert any("could not download artifact 1" in error for error in errors)

    monkeypatch.setattr(checker, "_github_bytes", lambda _url: (b"not a zip", None))
    errors = checker._verify_attestation(item, evidence_where="e", artifact_id=1)
    assert any("artifact has no readable" in error for error in errors)

    monkeypatch.setattr(
        checker, "_github_bytes", lambda _url: (zip_bytes(**{"other.txt": b"x"}), None)
    )
    errors = checker._verify_attestation(item, evidence_where="e", artifact_id=1)
    assert any("artifact has no readable" in error for error in errors)


def test_attestation_digest_must_match_its_manifest(
    checker: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = b'{"result": "passed"}\n'
    archive = zip_bytes(**{"manifest.json": content})
    monkeypatch.setattr(checker, "_github_bytes", lambda _url: (archive, None))
    item = {"attestation": {"file": "manifest.json", "sha256": "b" * 64}}
    errors = checker._verify_attestation(item, evidence_where="e", artifact_id=1)
    assert any("attestation.sha256 does not match its artifact file" in error for error in errors)


def test_attestation_must_prove_the_claimed_execution(
    checker: ModuleType,
    registry: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    control = registry["controls"][0]
    digest = "b" * 40
    item = {
        "control_id": control["id"],
        "control_refs": control["control_refs"],
        "test_refs": control["test_refs"],
        "release_digest": digest,
        "attestation": {"file": "manifest.json", "sha256": None},
    }

    item["observed_at"] = "2026-08-25"

    def verify_with(payload: object) -> list[str]:
        raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        monkeypatch.setattr(
            checker, "_github_bytes", lambda _url: (zip_bytes(**{"manifest.json": raw}), None)
        )
        return checker._verify_attestation(item, evidence_where="e", artifact_id=1)

    assert any(
        "observation date does not match" in e
        for e in verify_with(manifest_payload(control, digest, observed_at="2000-01-01"))
    )
    assert any("not valid JSON" in e for e in verify_with(b"{nope"))
    assert any("must be a JSON object" in e for e in verify_with(b"[1]"))
    assert any(
        "names the wrong control" in e
        for e in verify_with(manifest_payload(control, digest, control_id="OTHER"))
    )
    assert any(
        "not bound to the evidence release digest" in e
        for e in verify_with(manifest_payload(control, digest, release_digest="c" * 40))
    )
    assert any(
        "control_refs do not match the claim" in e
        for e in verify_with(manifest_payload(control, digest, control_refs=["other.py"]))
    )
    assert any(
        "test_refs do not match the claim" in e
        for e in verify_with(manifest_payload(control, digest, test_refs=["other.py"]))
    )
    assert any(
        "does not enumerate every claimed test" in e
        for e in verify_with(
            manifest_payload(
                control, digest, tests=[{"ref": "other.py", "result": "passed", "exit_code": 0}]
            )
        )
    )
    assert any(
        "does not prove passing test execution" in e
        for e in verify_with(manifest_payload(control, digest, result="failed"))
    )


# ---------------------------------------------------------------------------
# Commit-bound workflow locator resolution fails closed
# ---------------------------------------------------------------------------


def test_commit_bound_locator_must_bind_to_the_claim(checker: ModuleType) -> None:
    digest = "b" * 40
    other_digest = "c" * 40
    base = f"https://github.com/{checker.GITHUB_REPOSITORY}/blob"
    item = {
        "url": f"{base}/{other_digest}/.github/workflows/ci.yml",
        "release_digest": digest,
    }
    artifact, run_id, artifact_id, errors = checker._resolve_workflow_artifact(
        item, evidence_where="e", workflow_ref=".github/workflows/ci.yml"
    )
    assert (artifact, run_id, artifact_id) == (None, None, None)
    assert any("url is not bound to the evidence release digest" in e for e in errors)

    item["url"] = f"{base}/{digest}/.github/workflows/other.yml"
    _, _, _, errors = checker._resolve_workflow_artifact(
        item, evidence_where="e", workflow_ref=".github/workflows/ci.yml"
    )
    assert any("url does not identify workflow_ref" in e for e in errors)


def test_commit_bound_locator_ignores_non_locator_urls(checker: ModuleType) -> None:
    item = {"url": "https://example.invalid/x", "release_digest": "b" * 40}
    assert checker._resolve_workflow_artifact(item, evidence_where="e", workflow_ref="w") == (
        None,
        None,
        None,
        [],
    )


def test_commit_bound_run_resolution_fails_closed(
    checker: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    digest = "b" * 40
    item = {
        "url": (
            f"https://github.com/{checker.GITHUB_REPOSITORY}/blob/{digest}/.github/workflows/ci.yml"
        ),
        "release_digest": digest,
    }

    def resolve() -> list[str]:
        return checker._resolve_workflow_artifact(
            item, evidence_where="e", workflow_ref=".github/workflows/ci.yml"
        )[3]

    monkeypatch.setattr(checker, "_github_json", lambda _url: (None, "api down"))
    assert any("could not list workflow runs" in e for e in resolve())

    monkeypatch.setattr(checker, "_github_json", lambda _url: ({"unexpected": 1}, None))
    assert any("workflow run listing is malformed" in e for e in resolve())

    monkeypatch.setattr(checker, "_github_json", lambda _url: ({"workflow_runs": []}, None))
    assert any("has no workflow run for the evidence release digest" in e for e in resolve())

    failed = {
        "workflow_runs": [
            {
                "id": 7,
                "head_sha": digest,
                "path": ".github/workflows/ci.yml",
                "status": "completed",
                "conclusion": "failure",
            }
        ]
    }
    monkeypatch.setattr(checker, "_github_json", lambda _url: (failed, None))
    assert any("workflow run did not complete successfully" in e for e in resolve())


def test_commit_bound_artifact_resolution_fails_closed(
    checker: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    digest = "b" * 40
    item = {
        "url": (
            f"https://github.com/{checker.GITHUB_REPOSITORY}/blob/{digest}/.github/workflows/ci.yml"
        ),
        "release_digest": digest,
    }
    good_run = {
        "id": 7,
        "head_sha": digest,
        "path": ".github/workflows/ci.yml",
        "status": "completed",
        "conclusion": "success",
    }

    def resolve() -> list[str]:
        return checker._resolve_workflow_artifact(
            item, evidence_where="e", workflow_ref=".github/workflows/ci.yml"
        )[3]

    # A run whose id is not a usable positive integer cannot be probed.
    monkeypatch.setattr(
        checker,
        "_github_json",
        lambda _url: ({"workflow_runs": [dict(good_run, id="seven")]}, None),
    )
    assert any("has no artifact named" in e for e in resolve())

    monkeypatch.setattr(
        checker,
        "_github_json",
        lambda url: (
            ({"workflow_runs": [good_run]}, None)
            if "/runs?" in url
            else (None, "artifact api down")
        ),
    )
    assert any("could not list artifacts for workflow run 7" in e for e in resolve())

    monkeypatch.setattr(
        checker,
        "_github_json",
        lambda url: (
            ({"workflow_runs": [good_run]}, None)
            if "/runs?" in url
            else ({"artifacts": "nope"}, None)
        ),
    )
    assert any("artifact listing is malformed" in e for e in resolve())

    monkeypatch.setattr(
        checker,
        "_github_json",
        lambda url: (
            ({"workflow_runs": [good_run]}, None)
            if "/runs?" in url
            else ({"artifacts": [{"id": 5, "name": "something-else"}]}, None)
        ),
    )
    assert any("has no artifact named" in e for e in resolve())


# ---------------------------------------------------------------------------
# Artifact provenance failures for artifact-URL evidence
# ---------------------------------------------------------------------------


def artifact_evidence_item(checker: ModuleType, control: dict, digest: str) -> dict:
    return {
        "url": (f"https://github.com/{checker.GITHUB_REPOSITORY}/actions/runs/123/artifacts/456"),
        "control_id": control["id"],
        "control_refs": control["control_refs"],
        "test_refs": control["test_refs"],
        "sha256": "a" * 64,
        "release_digest": digest,
        "attestation": {"file": "manifest.json", "sha256": None},
    }


def test_artifact_fetch_failure_fails_closed(
    checker: ModuleType, registry: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    control = registry["controls"][0]
    item = artifact_evidence_item(checker, control, "b" * 40)
    monkeypatch.setattr(checker, "_github_json", lambda _url: (None, "api down"))
    errors = checker._verify_artifact_evidence(
        item, evidence_where="e", workflow_ref=".github/workflows/ci.yml"
    )
    assert errors == ["e could not verify GitHub artifact 456: api down"]


def test_artifact_and_run_provenance_mismatches_fail_closed(
    checker: ModuleType, registry: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    control = registry["controls"][0]
    digest = "b" * 40
    item = artifact_evidence_item(checker, control, digest)
    archive = zip_bytes(**{"manifest.json": json.dumps(manifest_payload(control, digest)).encode()})

    def json_by_url(url: str) -> tuple[dict | None, str | None]:
        if url.endswith("/artifacts/456"):
            return {
                "workflow_run": {"id": 999},
                "expired": True,
                "digest": "not-a-digest",
            }, None
        if url.endswith("/runs/123"):
            return {
                "head_sha": "c" * 40,
                "path": ".github/workflows/other.yml",
                "status": "in_progress",
                "conclusion": None,
            }, None
        return {"state": "active"}, None

    monkeypatch.setattr(checker, "_github_bytes", lambda _url: (archive, None))
    monkeypatch.setattr(checker, "_github_json", json_by_url)
    errors = checker._verify_artifact_evidence(
        item, evidence_where="e", workflow_ref=".github/workflows/ci.yml"
    )
    assert any("does not belong to the URL's workflow run" in e for e in errors)
    assert any("not for the evidence release digest" in e for e in errors)
    assert any("does not match workflow_ref" in e for e in errors)
    assert any("workflow run did not complete successfully" in e for e in errors)
    assert any("artifact is expired or has no expiry state" in e for e in errors)
    assert any("artifact has no GitHub SHA-256 digest" in e for e in errors)


def test_run_and_workflow_fetch_failures_fail_closed(
    checker: ModuleType, registry: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    control = registry["controls"][0]
    digest = "b" * 40
    item = artifact_evidence_item(checker, control, digest)
    archive = zip_bytes(**{"manifest.json": json.dumps(manifest_payload(control, digest)).encode()})

    def json_by_url(url: str) -> tuple[dict | None, str | None]:
        if url.endswith("/artifacts/456"):
            return {
                "workflow_run": {"id": 123},
                "expired": False,
                "digest": "sha256:" + "a" * 64,
            }, None
        if url.endswith("/runs/123"):
            return None, "run api down"
        return None, "workflow api down"

    monkeypatch.setattr(checker, "_github_bytes", lambda _url: (archive, None))
    monkeypatch.setattr(checker, "_github_json", json_by_url)
    errors = checker._verify_artifact_evidence(
        item, evidence_where="e", workflow_ref=".github/workflows/ci.yml"
    )
    assert any("could not verify workflow run 123" in e for e in errors)
    assert any("could not verify live workflow state" in e for e in errors)


# ---------------------------------------------------------------------------
# Workflow-state derivation and registry-level schema failures
# ---------------------------------------------------------------------------


def test_workflow_state_derivation_fails_closed(checker: ModuleType, tmp_path: Path) -> None:
    assert checker._workflow_state(".github/workflows/missing.yml", tmp_path) is None
    (tmp_path / "broken.yml").write_text("a: [::", encoding="utf-8")
    assert checker._workflow_state("broken.yml", tmp_path) is None
    (tmp_path / "scalar.yml").write_text("just-a-string\n", encoding="utf-8")
    assert checker._workflow_state("scalar.yml", tmp_path) is None
    (tmp_path / "no-on.yml").write_text("name: x\njobs: {}\n", encoding="utf-8")
    assert checker._workflow_state("no-on.yml", tmp_path) is None


def test_workflow_state_reads_string_triggers(checker: ModuleType, tmp_path: Path) -> None:
    (tmp_path / "push.yml").write_text("on: push\njobs: {}\n", encoding="utf-8")
    assert checker._workflow_state("push.yml", tmp_path) == (True, False)


def test_registry_top_level_schema_failures(checker: ModuleType, registry: dict) -> None:
    assert checker.validate_registry(["nope"], today=dt.date(2026, 8, 25)) == [
        "registry must be a JSON object"
    ]
    registry["extra"] = 1
    del registry["schema_version"]
    registry["release_digest"] = "nope"
    errors = checker.validate_registry(registry, today=dt.date(2026, 8, 25))
    assert any("unknown fields: extra" in error for error in errors)
    assert any("missing fields: schema_version" in error for error in errors)
    assert any(f"schema_version must be {checker.SCHEMA_VERSION}" in error for error in errors)
    assert any(
        "release_digest must be null or a 40-64 character git digest" in error for error in errors
    )
    registry["controls"] = []
    errors = checker.validate_registry(registry, today=dt.date(2026, 8, 25))
    assert any("registry.controls must be a non-empty list" in error for error in errors)


def test_control_schema_failures(checker: ModuleType, registry: dict) -> None:
    bare = {"schema_version": 1, "release_digest": None, "controls": [1]}
    errors = checker.validate_registry(bare, today=dt.date(2026, 8, 25))
    assert any("controls[0] must be an object" in error for error in errors)

    cases: list[tuple[str, object, str]] = [
        ("unexpected", 1, "has unknown fields: unexpected"),
        ("id", "lower-id", "must be an uppercase control ID"),
        ("owner", "   ", "must be a non-empty string"),
        ("status", "green", "is not a supported status"),
        ("release_required", "yes", "release_required must be boolean"),
        ("verification_requested", "yes", "verification_requested must be boolean"),
        ("control_refs", "main.py", "control_refs must be a list"),
        ("control_refs", [], "control_refs must not be empty"),
        ("control_refs", ["docs/missing-control.md"], "contains a missing reference"),
        ("test_refs", ["docs/missing-test.md"], "contains a missing reference"),
    ]
    for field, value, expected in cases:
        current = copy.deepcopy(registry)
        current["controls"][0][field] = value
        errors = checker.validate_registry(current, today=dt.date(2026, 8, 25))
        assert any(expected in error for error in errors), field


def test_evidence_schema_failures(checker: ModuleType, registry: dict) -> None:
    digest = "b" * 40

    def errors_for(**overrides: object) -> list[str]:
        current = copy.deepcopy(registry)
        current["controls"][0]["evidence"] = [
            evidence_item(current["controls"][0], digest, **overrides)
        ]
        return checker.validate_registry(current, today=dt.date(2026, 8, 25))

    not_an_object = copy.deepcopy(registry)
    not_an_object["controls"][0]["evidence"] = [1]
    errors = checker.validate_registry(not_an_object, today=dt.date(2026, 8, 25))
    assert any("evidence[0] must be an object" in e for e in errors)

    no_url = copy.deepcopy(registry)
    missing = evidence_item(no_url["controls"][0], digest)
    del missing["url"]
    missing["bogus"] = 1
    no_url["controls"][0]["evidence"] = [missing]
    errors = checker.validate_registry(no_url, today=dt.date(2026, 8, 25))
    assert any("has unknown fields: bogus" in e for e in errors)
    assert any("is missing fields: url" in e for e in errors)

    assert any("must be a list of strings" in e for e in errors_for(control_refs="main.py"))
    assert any("is not bound to control" in e for e in errors_for(control_refs=["other.py"]))
    assert any(
        "workflow_ref must name an existing workflow" in e
        for e in errors_for(workflow_ref="no.yml")
    )
    assert any("workflow_enabled must be boolean" in e for e in errors_for(workflow_enabled="yes"))
    assert any("must be a 64 character SHA-256 digest" in e for e in errors_for(sha256="short"))
    assert any(
        "release_digest must be a git digest" in e for e in errors_for(release_digest="nope")
    )
    assert any(
        "observed_at cannot be in the future" in e for e in errors_for(observed_at="2027-01-01")
    )
    assert any("result must be 'passed' or 'failed'" in e for e in errors_for(result="green"))


def test_manual_only_and_never_run_evidence_cannot_be_green(
    checker: ModuleType, registry: dict
) -> None:
    control = registry["controls"][0]
    digest = "b" * 40
    control["status"] = "implemented"
    registry["release_digest"] = digest
    control["evidence"] = [
        evidence_item(control, digest, manual_only=True, ran=False, observed_at=None)
    ]
    errors = checker.validate_registry(registry, today=dt.date(2026, 8, 25))
    assert any("manual-only evidence supporting implemented status" in e for e in errors)
    assert any("never-run evidence supporting implemented status" in e for e in errors)
    assert any("implemented evidence requires observed_at" in e for e in errors)


def test_evidence_must_be_bound_to_the_registry_release_digest(
    checker: ModuleType, registry: dict
) -> None:
    control = registry["controls"][0]
    control["status"] = "implemented"
    registry["release_digest"] = "b" * 40
    control["evidence"] = [evidence_item(control, "c" * 40)]
    errors = checker.validate_registry(registry, today=dt.date(2026, 8, 25))
    assert any("evidence is not bound to registry.release_digest" in e for e in errors)


def test_implemented_requires_executable_test_references(
    checker: ModuleType, registry: dict
) -> None:
    control = registry["controls"][0]
    control["status"] = "implemented"
    control["last_verified"] = "2026-08-25"
    control["test_refs"] = []
    errors = checker.validate_registry(registry, today=dt.date(2026, 8, 25))
    assert any("implemented but has no executable test reference" in e for e in errors)
    control["test_refs"] = ["scripts/check-compliance.py"]
    errors = checker.validate_registry(registry, today=dt.date(2026, 8, 25))
    assert any("implemented but has no executable test reference" in e for e in errors)


def test_release_mode_rejects_malformed_release_digest(checker: ModuleType, registry: dict) -> None:
    errors = checker.validate_registry(
        registry,
        root=ROOT,
        release_digest="nope",
        require_release_evidence=True,
        today=dt.date(2026, 8, 25),
    )
    assert "--release-digest must be a 40-64 character git digest" in errors


# ---------------------------------------------------------------------------
# COMPLIANCE.md shape and consistency failures
# ---------------------------------------------------------------------------


def document_body(checker: ModuleType, *lines: str) -> str:
    return "\n".join([checker.BEGIN_MARKER, *lines, checker.END_MARKER])


def test_document_structure_failures(checker: ModuleType) -> None:
    registry = checker.load_registry()
    errors = checker.validate_document("no markers here", registry)
    assert any("missing the compliance registry markers" in e for e in errors)

    errors = checker.validate_document(document_body(checker), registry)
    assert any("compliance registry table is incomplete" in e for e in errors)

    errors = checker.validate_document(
        document_body(checker, "prose line", "| - | - |", "tail"), registry
    )
    assert any("has no header row" in e for e in errors)

    errors = checker.validate_document(
        document_body(checker, "| ID | Framework |", "| - | - |", "| A | b |"), registry
    )
    assert any("header must be" in e for e in errors)
    assert any("malformed separator row" in e for e in errors)


def test_document_rejects_non_table_rows(checker: ModuleType) -> None:
    document = (ROOT / "COMPLIANCE.md").read_text(encoding="utf-8")
    lines = document.splitlines()
    header_index = next(i for i, line in enumerate(lines) if line.startswith("| ID |"))
    separator_index = header_index + 1
    broken = "\n".join(
        [*lines[: separator_index + 1], "Prose line.", *lines[separator_index + 1 :]]
    )
    errors = checker.validate_document(broken, checker.load_registry())
    assert any("is not a table row" in e for e in errors)


def test_document_rejects_duplicate_control_rows(checker: ModuleType) -> None:
    document = (ROOT / "COMPLIANCE.md").read_text(encoding="utf-8")
    first_row = next(line for line in document.splitlines() if line.startswith("| OWASP-AT-01 |"))
    duplicated = document.replace(first_row, f"{first_row}\n{first_row}", 1)
    errors = checker.validate_document(duplicated, checker.load_registry())
    assert any("repeats control ID OWASP-AT-01" in e for e in errors)


def test_document_skips_incomplete_registry_controls(checker: ModuleType) -> None:
    document = (ROOT / "COMPLIANCE.md").read_text(encoding="utf-8")
    registry = checker.load_registry()
    del registry["controls"][0]["owner"]
    errors = checker.validate_document(document, registry)
    assert any("OWASP-AT-01 is incomplete; document comparison skipped" in e for e in errors)


def test_document_rejects_registry_drift(checker: ModuleType) -> None:
    document = (ROOT / "COMPLIANCE.md").read_text(encoding="utf-8")
    drifted = document.replace("| 2026-08-25 |", "| 2026-08-24 |", 1)
    errors = checker.validate_document(drifted, checker.load_registry())
    assert any("does not match the registry" in e for e in errors)


def test_document_rejects_implemented_without_evidence(checker: ModuleType) -> None:
    document = (ROOT / "COMPLIANCE.md").read_text(encoding="utf-8")
    registry = checker.load_registry()
    registry["controls"][0]["status"] = "implemented"
    registry["controls"][0]["evidence"] = []
    claimed = document.replace("| partially_implemented |", "| implemented |", 1)
    errors = checker.validate_document(claimed, registry)
    assert any("marks OWASP-AT-01 implemented without evidence" in e for e in errors)


def test_evidence_cell_rendering(checker: ModuleType) -> None:
    assert checker._evidence_cell([]) == "none"
    run_url = f"https://github.com/{checker.GITHUB_REPOSITORY}/actions/runs/1/artifacts/2"
    assert checker._evidence_cell([{"url": run_url, "sha256": "a" * 64}]) == (
        f"[{'a' * 12}]({run_url})"
    )
    locator = {
        "url": (
            f"https://github.com/{checker.GITHUB_REPOSITORY}/blob/"
            f"{'b' * 40}/.github/workflows/ci.yml"
        ),
        "sha256": None,
    }
    assert checker._evidence_cell([locator]) == f"[artifact via workflow]({locator['url']})"
    assert checker._evidence_cell([{"url": "not-a-link"}]) == "invalid"


def test_check_reports_unloadable_inputs(checker: ModuleType, tmp_path: Path) -> None:
    errors = checker.check(registry_path=tmp_path / "missing.json")
    assert any("cannot load" in error and "missing.json" in error for error in errors)
    errors = checker.check(document_path=tmp_path / "missing.md")
    assert any("cannot load" in error and "missing.md" in error for error in errors)


def test_main_exit_codes(
    checker: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    assert checker.main([]) == 0
    assert "valid" in capsys.readouterr().out

    broken = tmp_path / "registry.json"
    broken.write_text("{}", encoding="utf-8")
    assert checker.main(["--registry", str(broken)]) == 1
    assert "compliance check FAILED" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# The evidence producer fails closed too
# ---------------------------------------------------------------------------


def test_producer_skips_non_implemented_controls(producer: ModuleType, tmp_path: Path) -> None:
    registry = {"controls": [{"id": "P-1", "status": "planned", "test_refs": []}]}
    assert (
        producer.produce(
            registry,
            release_digest="a" * 40,
            output=tmp_path,
            today=dt.date(2026, 8, 25),
            runner="python",
        )
        == 0
    )
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["controls"] == []


def test_producer_rejects_implemented_control_with_invalid_test_refs(
    producer: ModuleType, tmp_path: Path
) -> None:
    registry = {
        "controls": [
            {"id": "P-1", "status": "implemented", "test_refs": "nope", "control_refs": []}
        ]
    }
    with pytest.raises(ValueError, match="invalid test_refs"):
        producer.produce(
            registry,
            release_digest="a" * 40,
            output=tmp_path,
            today=dt.date(2026, 8, 25),
            runner="python",
        )


def test_producer_records_subprocess_failures(
    producer: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = {
        "controls": [
            {
                "id": "P-1",
                "status": "implemented",
                "test_refs": ["tests/test_missing.py"],
                "control_refs": ["scripts/check-compliance.py"],
            }
        ]
    }

    def timeout(*args: object, **kwargs: object) -> object:
        raise producer.subprocess.TimeoutExpired(cmd="pytest", timeout=900)

    monkeypatch.setattr(producer.subprocess, "run", timeout)
    assert (
        producer.produce(
            registry,
            release_digest="a" * 40,
            output=tmp_path,
            today=dt.date(2026, 8, 25),
            runner="python",
        )
        == 1
    )
    manifest = json.loads((tmp_path / "P-1.json").read_text())
    assert manifest["result"] == "failed"
    assert manifest["tests"][0]["exit_code"] == 1


def test_producer_fails_implemented_control_without_tests(
    producer: ModuleType, tmp_path: Path
) -> None:
    registry = {
        "controls": [{"id": "P-1", "status": "implemented", "test_refs": [], "control_refs": []}]
    }
    assert (
        producer.produce(
            registry,
            release_digest="a" * 40,
            output=tmp_path,
            today=dt.date(2026, 8, 25),
            runner="python",
        )
        == 1
    )
    manifest = json.loads((tmp_path / "P-1.json").read_text())
    assert manifest["result"] == "failed"


def test_producer_main_loads_registry_and_fails_closed(
    producer: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        json.dumps({"controls": [{"id": "P-1", "status": "planned", "test_refs": []}]}),
        encoding="utf-8",
    )
    argv = [
        "--registry",
        str(registry_path),
        "--release-digest",
        "a" * 40,
        "--output",
        str(tmp_path / "out"),
    ]
    assert producer.main(argv) == 0

    broken = tmp_path / "broken.json"
    broken.write_text('{"nope": true}', encoding="utf-8")
    assert (
        producer.main(
            [
                "--registry",
                str(broken),
                "--release-digest",
                "a" * 40,
                "--output",
                str(tmp_path / "out2"),
            ]
        )
        == 1
    )
    assert "compliance evidence production failed" in capsys.readouterr().err


@pytest.fixture
def release_candidate(
    checker: ModuleType,
    producer: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict:
    """Real committed source, annotated tag and pytest execution; fake only GitHub I/O."""
    root = tmp_path / "checkout"
    root.mkdir()
    for directory in ("quality", "tests", "scripts", ".github/workflows"):
        (root / directory).mkdir(parents=True)
    (root / "scripts/control.py").write_text("ENABLED = True\n")
    (root / "tests/test_control.py").write_text(
        "from scripts.control import ENABLED\ndef test_enabled():\n    assert ENABLED\n"
    )
    workflow = root / checker.EVIDENCE_WORKFLOW
    workflow.write_text((ROOT / checker.EVIDENCE_WORKFLOW).read_text())
    control = {
        "id": "TEST-RELEASE",
        "framework": "Technical fixture",
        "requirement": "Control is enabled",
        "scope": "Test fixture only",
        "owner": "@control-owner",
        "status": "unverified",
        "control_refs": ["scripts/control.py"],
        "test_refs": ["tests/test_control.py"],
        "evidence": [],
        "last_verified": None,
        "expires": "2026-09-30",
        "release_required": True,
        "verification_requested": True,
    }
    source = {"schema_version": 1, "release_digest": None, "controls": [control]}
    registry_path = root / "quality/compliance-registry.json"
    registry_path.write_text(json.dumps(source))
    doc_path = root / "COMPLIANCE.md"
    doc_path.write_text(
        document_body(
            checker,
            "| " + " | ".join(checker.TABLE_HEADER) + " |",
            "|" + "---|" * len(checker.TABLE_HEADER),
            "| TEST-RELEASE | Technical fixture | Control is enabled | unverified | "
            "@control-owner | Test fixture only | not recorded | 2026-09-30 | none |",
        )
    )

    def git(*args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=root, text=True).strip()

    git("init", "-q")
    git("config", "user.name", "Compliance test")
    git("config", "user.email", "compliance-test@example.invalid")
    git("add", ".")
    git("commit", "-qm", "Reviewed technical verification request")
    digest = git("rev-parse", "HEAD")
    git("tag", "-a", "v1.0.0", "-m", "Test release")
    assert git("rev-parse", "v1.0.0^{commit}") == digest
    monkeypatch.setattr(producer, "ROOT", root)
    output = tmp_path / "artifact"
    assert (
        producer.produce(
            source,
            release_digest=digest,
            output=output,
            today=dt.date(2026, 8, 25),
        )
        == 0
    )
    # This is a real pytest subprocess, not a manufactured successful exit.
    manifest = json.loads((output / "TEST-RELEASE.json").read_text())
    assert "1 passed" in manifest["tests"][0]["output_tail"]
    archive = zip_bytes(**{path.name: path.read_bytes() for path in output.iterdir()})
    state = {
        "root": root,
        "registry": registry_path,
        "document": doc_path,
        "digest": digest,
        "archive": archive,
        "manifest": manifest,
        "artifact": {
            "id": 456,
            "name": f"compliance-evidence-{digest}",
            "expired": False,
            "workflow_run": {"id": 123},
            "digest": "sha256:" + hashlib.sha256(archive).hexdigest(),
        },
        "run": {
            "id": 123,
            "head_sha": digest,
            "path": checker.EVIDENCE_WORKFLOW,
            "status": "completed",
            "conclusion": "success",
            "event": "push",
        },
        "workflow": {"state": "active"},
    }

    def github_json(url: str) -> tuple[dict, None]:
        if "/runs?" in url:
            assert f"head_sha={digest}" in url
            return {"workflow_runs": [state["run"]]}, None
        if "/runs/123/artifacts?" in url:
            return {"artifacts": [state["artifact"]]}, None
        if url.endswith("/artifacts/456"):
            return state["artifact"], None
        if url.endswith("/runs/123"):
            return state["run"], None
        assert url.endswith("/workflows/compliance-evidence.yml")
        return state["workflow"], None

    monkeypatch.setattr(checker, "_github_json", github_json)
    monkeypatch.setattr(checker, "_github_bytes", lambda _url: (state["archive"], None))
    return state


def resolved_check(checker: ModuleType, state: dict, **kwargs: object) -> list[str]:
    return checker.check(
        registry_path=state["registry"],
        document_path=state["document"],
        release_digest=state["digest"],
        require_release_evidence=True,
        resolve_release_evidence=True,
        today=dt.date(2026, 8, 25),
        **kwargs,
    )


def test_real_tag_can_resolve_post_commit_evidence_without_source_edit(
    checker: ModuleType,
    release_candidate: dict,
    tmp_path: Path,
) -> None:
    state = release_candidate
    before = state["registry"].read_bytes()
    output = tmp_path / "release-compliance.json"
    assert resolved_check(checker, state, resolved_output=output) == []
    result = json.loads(output.read_text())
    assert result["release_digest"] == state["digest"]
    control = result["controls"][0]
    assert control["status"] == "implemented"
    assert control["expires"] == "2026-09-30"  # owner's shorter expiry is preserved
    assert control["evidence"][0]["url"].endswith("/runs/123/artifacts/456")
    assert state["registry"].read_bytes() == before
    assert (
        checker.check(
            registry_path=state["registry"],
            document_path=state["document"],
            today=dt.date(2026, 8, 25),
        )
        == []
    )


@pytest.mark.parametrize(
    ("target", "field", "value", "message"),
    [
        ("run", "head_sha", "b" * 40, "no workflow run"),
        ("run", "event", "workflow_dispatch", "did not complete successfully"),
        ("run", "conclusion", "failure", "did not complete successfully"),
        ("run", "status", "in_progress", "did not complete successfully"),
        ("artifact", "expired", True, "artifact is expired"),
        ("artifact", "digest", "sha256:" + "0" * 64, "SHA-256 does not match"),
        ("artifact", "name", "other-commit", "has no artifact"),
        ("workflow", "state", "disabled_manually", "not active"),
    ],
)
def test_release_resolution_rejects_invalid_provenance(
    checker: ModuleType,
    release_candidate: dict,
    tmp_path: Path,
    target: str,
    field: str,
    value: object,
    message: str,
) -> None:
    release_candidate[target][field] = value
    output = tmp_path / "release.json"
    errors = resolved_check(checker, release_candidate, resolved_output=output)
    assert any(message in error for error in errors), errors
    assert not output.exists()


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("release_digest", "b" * 40, "not bound to the evidence release digest"),
        ("observed_at", "2026-01-01", "stale evidence"),
        ("observed_at", None, "no valid executed manifest"),
        ("result", "failed", "non-passing evidence"),
        ("tests", [], "does not enumerate every claimed test"),
    ],
)
def test_release_resolution_rejects_invalid_execution(
    checker: ModuleType,
    release_candidate: dict,
    field: str,
    value: object,
    message: str,
) -> None:
    state = release_candidate
    state["manifest"][field] = value
    state["archive"] = zip_bytes(**{"TEST-RELEASE.json": json.dumps(state["manifest"]).encode()})
    state["artifact"]["digest"] = "sha256:" + hashlib.sha256(state["archive"]).hexdigest()
    errors = resolved_check(checker, state)
    assert any(message in error for error in errors), errors


def test_resolution_refuses_uncommitted_claim_edits(
    checker: ModuleType,
    release_candidate: dict,
) -> None:
    release_candidate["registry"].write_text(release_candidate["registry"].read_text() + "\n")
    errors = resolved_check(checker, release_candidate)
    assert any("differs from the committed source" in error for error in errors)


def test_resolution_refuses_another_checkout_digest(
    checker: ModuleType,
    release_candidate: dict,
) -> None:
    release_candidate["digest"] = "b" * 40
    assert "release digest must equal checkout HEAD" in resolved_check(checker, release_candidate)


def test_resolution_never_promotes_without_reviewed_request(
    checker: ModuleType,
    registry: dict,
) -> None:
    resolved, errors = checker.resolve_registry(registry, "b" * 40)
    assert errors == []
    assert [c["status"] for c in resolved["controls"]] == [
        c["status"] for c in registry["controls"]
    ]
    errors = checker.validate_registry(
        resolved,
        release_digest="b" * 40,
        require_release_evidence=True,
        today=dt.date(2026, 8, 25),
    )
    assert any("EU-AI-ACT-ART-15 is unverified" in error for error in errors)


@pytest.mark.parametrize("status", ["planned", "documented", "not_applicable"])
def test_requests_cannot_promote_non_candidate_statuses(
    checker: ModuleType,
    registry: dict,
    status: str,
) -> None:
    registry["controls"][0].update(status=status, verification_requested=True)
    errors = checker.validate_registry(registry, today=dt.date(2026, 8, 25))
    assert any("requires a technical candidate status" in error for error in errors)


def test_release_workflow_resolves_and_preserves_evidence_before_build(checker: ModuleType) -> None:
    workflow = checker.yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())
    jobs = workflow["jobs"]
    steps = jobs["guard"]["steps"]
    gate = next(step for step in steps if "--require-release-evidence" in step.get("run", ""))
    assert "--resolve-release-evidence" in gate["run"]
    assert "--resolved-output release-compliance.json" in gate["run"]
    assert jobs["wheels"]["needs"] == "guard"
    assert "guard" in jobs["pypi"]["needs"]
    assert "guard" in jobs["images"]["needs"]
    assert any(step.get("with", {}).get("name") == "release-compliance" for step in steps)
    publisher = jobs["github-release"]["steps"]
    assert any(step.get("with", {}).get("name") == "release-compliance" for step in publisher)
    assert any(
        "cp compliance/release-compliance.json release/" in step.get("run", "")
        for step in publisher
    )
    producer_workflow = checker.yaml.safe_load((ROOT / checker.EVIDENCE_WORKFLOW).read_text())
    assert "integration" in producer_workflow[True]["push"]["branches"]
    producer_steps = producer_workflow["jobs"]["produce"]["steps"]
    assert not any(
        "--release-digest" in step.get("run", "") and "check-compliance.py" in step.get("run", "")
        for step in producer_steps
    )
