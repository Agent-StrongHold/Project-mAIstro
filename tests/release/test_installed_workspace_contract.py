"""Contract tests for the #86 (M3-A4) installed-workspace proof harness.

The harness (``scripts/prove-installed-workspace.py``) is the release
orchestrator for the finite installed proof the #86 clarification defines. Its
contract is the shipped schema plus the rules a schema cannot express, so
these tests drive the real script -- through its own module and its own CLI --
rather than re-describing it. A harness that is only exercised by prose is
exactly the "structural validity is never run occurrence" failure the issue
warns about.

What these tests protect, in the order the issue cares about:

* an invalid manifest is refused (the shipped schema is the enforced contract);
* the cross-field rules (independent headless review, two users, two
  workspaces, the four mandatory fail-closed cases) are enforced, not merely
  documented;
* a secret-shaped literal never reaches a manifest or a bundle;
* a stop-before command is BLOCKED and is never executed;
* an unmet clean-target contract BLOCKS the install instead of proceeding;
* an absent credential or an unauthorized provider budget is NOT_RUN -- never a
  licence to create one;
* a missing canonical id, a broken restart correlation, a leaky scope, or a
  fail-closed case that reports success is a FAIL, not a pass;
* the bundle carries every required file, hashes them, and ``--verify``
  detects a tampered payload.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "prove-installed-workspace.py"
SCHEMA_PATH = ROOT / "docs" / "testing" / "installed-workspace-proof-manifest.schema.json"
PROOF_DOC = ROOT / "docs" / "testing" / "installed-workspace-proof.md"

#: The four mandatory fail-closed cases the issue names.
MANDATORY_CASES = (
    "absent_credential",
    "unavailable_model",
    "inaccessible_runtime",
    "missing_sandbox_capability",
)


@pytest.fixture(scope="module")
def harness():
    """The shipped harness, loaded the way its filename allows."""
    spec = importlib.util.spec_from_file_location("prove_installed_workspace", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Manifest construction
# ---------------------------------------------------------------------------


def _json_command(payload: dict[str, Any]) -> list[str]:
    """A command whose stdout is one JSON object."""
    return [sys.executable, "-c", f"import json; print(json.dumps({payload!r}))"]


def _text_command(message: str) -> list[str]:
    """A command whose stdout is one plain line."""
    return [sys.executable, "-c", f"print({message!r})"]


def _clean_probe_payload() -> dict[str, Any]:
    return {
        "developer_checkout_absent": True,
        "inherited_credentials_absent": True,
        "inherited_python_uv_absent": True,
        "inherited_app_data_absent": True,
        "os": "linux",
        "arch": "x86_64",
        "uid": 1000,
    }


def build_manifest(tmp_path: Path) -> dict[str, Any]:
    """A reviewed, headless-free manifest whose every command succeeds.

    The commands are local, side-effect-free stand-ins for the public
    installer/lifecycle/product clients a real reviewed manifest names: the
    harness only ever launches what the manifest declares, so the stand-ins
    exercise the harness's own contract without touching a live installation.
    """
    workdir = tmp_path / "target"
    workdir.mkdir(parents=True, exist_ok=True)
    denied = {"denied": True, "leaked": [], "dispatched": False}
    cases = [
        {
            "name": name,
            "owner": "#1824",
            "recovery": "supply the prerequisite and retry",
            "expected_outcome": "blocked",
            "arrange": {"command": _text_command("arranged")},
            "client": {
                "command": _json_command(
                    {"outcome": "blocked", "recovery": "supply the prerequisite"}
                ),
                "payload": "fail-closed.json",
            },
        }
        for name in MANDATORY_CASES
    ]
    return {
        "schema": 1,
        "review": {
            "reviewed": True,
            "reviewer": "release-owner",
            "reviewed_at": "2026-10-20T00:00:00Z",
        },
        "artifacts": {
            "ref": "v1.2.0-rc1",
            "ref_immutable": True,
            "entrypoint": ["curl", "-fsSL", "https://example.invalid/get.sh"],
            "entrypoint_documentation": "docs/install/default-installer.md",
            "digests": {"engine": "sha256:" + "0" * 64},
        },
        "support_row": {
            "id": "linux-x86-docker-default",
            "browser": "ui",
            "owner": "#1820",
            "os": "linux",
            "arch": "x86_64",
            "runtime": "docker",
            "context": "default",
            "store_profile": "standalone-compose",
        },
        "target": {
            "host": "clean-vm-1",
            "account": "operator",
            "probe": _json_command(_clean_probe_payload()),
            "requirements": {
                "developer_checkout_absent": True,
                "inherited_credentials_absent": True,
                "inherited_python_uv_absent": True,
                "inherited_app_data_absent": True,
            },
            "env_path": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "home": str(workdir),
            "workdir": str(workdir),
        },
        "credentials": [
            {
                "name": "gateway",
                "reference": "vault://gateway/provider",
                "scope": "gateway",
                "present": True,
            }
        ],
        "provider": {
            "gateway": "https://gateway.example/v1",
            "model_default": "default-model",
            "budget": {"authorized": True, "max_model_calls": 5, "authorization_ref": "REL-86"},
        },
        "scenarios": {
            "install": {
                "installer": {"command": _text_command("installed"), "name": "FIRST_RUN"},
                "post_checks": [
                    {
                        "command": _json_command({"healthy": True}),
                        "name": "HEALTH_0",
                        "expect_json": {"healthy": True},
                    }
                ],
                "login": {
                    "mode": "browser",
                    "command": {
                        "command": _json_command({"signed_in_as": "operator"}),
                        "expect_json": {"signed_in_as": "operator"},
                    },
                },
                "workspace": {"command": _json_command({"workspace": "ws-1"})},
                "effective_config": {
                    "command": _json_command(
                        {"gateway": "https://gateway.example/v1", "model": "default-model"}
                    ),
                    "payload": "effective-config.json",
                },
            },
            "execute": {
                "client": {
                    "command": _json_command(
                        {
                            "run_id": "run-1",
                            "node_run_id": "node-1",
                            "attempt_id": "attempt-1",
                            "gateway": "https://gateway.example/v1",
                            "model": "default-model",
                            "response_digest": "sha256:" + "a" * 64,
                            "provider_calls": 1,
                        }
                    ),
                    "payload": "execution.json",
                },
                "correlation": {"user": "operator", "workspace": "ws-1"},
            },
            "restart": {
                "stop": {"command": _json_command({"drained": True, "sandboxes_remaining": 0})},
                "start": {"command": _text_command("started")},
                "persistence": {
                    "command": _json_command(
                        {"correlated_run_id": "run-1", "user": "operator", "workspace": "ws-1"}
                    ),
                    "payload": "restart.json",
                },
                "new_request": {"command": _json_command({"accepted": True, "provider_calls": 1})},
            },
            "isolate": {
                "users": ["operator", "other-operator"],
                "workspaces": ["ws-1", "ws-2"],
                "positive_control": {"command": _json_command({"accessible": True})},
                "probes": [
                    {
                        "name": f"probe-{index}",
                        "kind": kind,
                        "command": {"command": _json_command(denied)},
                    }
                    for index, kind in enumerate(
                        (
                            "foreign_session",
                            "foreign_run_detail",
                            "foreign_events",
                            "foreign_artifact",
                        )
                    )
                ],
            },
            "fail_closed": {"cases": cases},
        },
    }


def write_manifest(tmp_path: Path, manifest: dict[str, Any], name: str = "manifest.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path


def prove(harness, manifest_path: Path, output: Path) -> int:
    """Run the harness in prove mode; returns the process exit code."""
    return harness.main(["--manifest", str(manifest_path), "--output", str(output)])


def family_outcomes(results: dict[str, Any]) -> dict[str, str]:
    return {family: results["scenarios"][family]["outcome"] for family in harness_families(results)}


def harness_families(results: dict[str, Any]) -> list[str]:
    return list(results["scenarios"])


def subchecks(results: dict[str, Any], family: str) -> dict[str, dict[str, Any]]:
    return {sub["name"]: sub for sub in results["scenarios"][family]["subchecks"]}


# ---------------------------------------------------------------------------
# The shipped contract
# ---------------------------------------------------------------------------


def test_schema_file_ships_and_declares_the_mandatory_sections() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    required = schema["required"]
    assert set(required) == {
        "schema",
        "review",
        "artifacts",
        "support_row",
        "target",
        "credentials",
        "provider",
        "scenarios",
    }
    assert schema["properties"]["scenarios"]["required"] == [
        "install",
        "execute",
        "restart",
        "isolate",
        "fail_closed",
    ]


def test_proof_document_ships_and_names_the_entrypoint(harness) -> None:
    text = PROOF_DOC.read_text(encoding="utf-8")
    assert "scripts/prove-installed-workspace.py" in text
    assert "--manifest" in text and "--output" in text
    assert harness.REQUIRED_FILES, "the harness must declare its required bundle files"


def test_reference_manifest_validates_against_the_shipped_schema(harness, tmp_path: Path) -> None:
    manifest = build_manifest(tmp_path)
    schema = harness.load_contract()
    harness.validate_manifest(manifest, schema)
    harness.check_cross_rules(manifest)


def test_schema_refuses_a_manifest_missing_a_required_section(harness, tmp_path: Path) -> None:
    manifest = build_manifest(tmp_path)
    del manifest["provider"]
    schema = harness.load_contract()
    with pytest.raises(harness.SchemaError):
        harness.validate_manifest(manifest, schema)


def test_schema_refuses_an_unexpected_key(harness, tmp_path: Path) -> None:
    manifest = build_manifest(tmp_path)
    manifest["artifacts"]["unreviewed_artifact"] = "v9.9.9"
    schema = harness.load_contract()
    with pytest.raises(harness.SchemaError):
        harness.validate_manifest(manifest, schema)


def test_schema_subset_refuses_a_keyword_it_does_not_implement(harness) -> None:
    """The schema file must never claim a validation it cannot perform."""
    schema = harness.load_contract()
    schema["properties"]["artifacts"]["oneOf"] = [{"type": "string"}]
    with pytest.raises(harness.SchemaError):
        harness.validate_manifest({"schema": 1}, schema)


def test_schema_refuses_a_moving_branch_artifact(harness, tmp_path: Path) -> None:
    manifest = build_manifest(tmp_path)
    manifest["artifacts"]["ref"] = "develop"
    schema = harness.load_contract()
    with pytest.raises(harness.SchemaError):
        harness.validate_manifest(manifest, schema)


def test_headless_row_requires_independent_review(harness, tmp_path: Path) -> None:
    manifest = build_manifest(tmp_path)
    manifest["support_row"]["browser"] = "headless"
    manifest["scenarios"]["install"]["login"]["mode"] = "authenticated_equivalent"
    manifest["support_row"]["headless_review"] = {
        "independently_reviewed": False,
        "reviewer": "release-owner",
    }
    with pytest.raises(harness.ProofError):
        harness.check_cross_rules(manifest)


def test_headless_row_requires_a_reviewed_profile(harness, tmp_path: Path) -> None:
    manifest = build_manifest(tmp_path)
    manifest["support_row"]["browser"] = "headless"
    manifest["scenarios"]["install"]["login"]["mode"] = "authenticated_equivalent"
    manifest["support_row"]["headless_review"] = {
        "independently_reviewed": True,
        "reviewer": "release-owner",
    }
    with pytest.raises(harness.ProofError):
        harness.check_cross_rules(manifest)


def test_ui_row_must_use_the_browser_login(harness, tmp_path: Path) -> None:
    manifest = build_manifest(tmp_path)
    manifest["scenarios"]["install"]["login"]["mode"] = "authenticated_equivalent"
    with pytest.raises(harness.ProofError):
        harness.check_cross_rules(manifest)


def test_every_mandatory_fail_closed_case_is_required(harness, tmp_path: Path) -> None:
    manifest = build_manifest(tmp_path)
    manifest["scenarios"]["fail_closed"]["cases"] = [
        case
        for case in manifest["scenarios"]["fail_closed"]["cases"]
        if case["name"] != "missing_sandbox_capability"
    ]
    with pytest.raises(harness.ProofError):
        harness.check_cross_rules(manifest)


def test_isolation_requires_two_distinct_users_and_workspaces(harness, tmp_path: Path) -> None:
    manifest = build_manifest(tmp_path)
    manifest["scenarios"]["isolate"]["users"] = ["operator", "operator"]
    with pytest.raises(harness.ProofError):
        harness.check_cross_rules(manifest)


def test_manifest_must_name_at_least_one_artifact_digest(harness, tmp_path: Path) -> None:
    manifest = build_manifest(tmp_path)
    manifest["artifacts"]["digests"] = {}
    with pytest.raises(harness.ProofError):
        harness.check_cross_rules(manifest)


def test_a_secret_shaped_literal_is_refused_in_a_manifest(harness, tmp_path: Path) -> None:
    manifest = build_manifest(tmp_path)
    manifest["credentials"][0]["reference"] = "sk-abcdefghijklmnopqrstuvwxyz012345"
    path = write_manifest(tmp_path, manifest)
    schema = harness.load_contract()
    with pytest.raises(harness.ProofError):
        harness.load_manifest(path, schema)


# ---------------------------------------------------------------------------
# Stop-before policy
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("argv", "category"),
    [
        (["sudo", "install.sh"], "elevation"),
        (["docker", "login", "registry.example"], "credential-generation-or-import"),
        (["ssh-keygen", "-t", "ed25519"], "credential-generation-or-import"),
        (["maestro", "grant", "create", "--role", "admin"], "new-grants"),
        (["usermod", "-aG", "docker", "operator"], "socket-or-group-permission-change"),
    ],
)
def test_a_stop_before_command_blocks_its_family_without_executing(
    harness, tmp_path: Path, argv: list[str], category: str
) -> None:
    sentinel = tmp_path / "executed.marker"
    manifest = build_manifest(tmp_path)
    manifest["scenarios"]["install"]["installer"]["command"] = [
        sys.executable,
        "-c",
        f"open({str(sentinel)!r}, 'w').write('ran')",
    ]
    manifest["scenarios"]["execute"]["client"]["command"] = list(argv)
    path = write_manifest(tmp_path, manifest)
    output = tmp_path / "bundle"
    exit_code = prove(harness, path, output)
    results = json.loads((output / "results.json").read_text(encoding="utf-8"))
    assert results["scenarios"]["EXECUTE"]["outcome"] == harness.BLOCKED
    assert any(stop["category"] == category for stop in results["stop_befores"])
    assert exit_code == harness.EXIT_EVIDENCE


def test_a_stop_before_install_command_is_never_executed(harness, tmp_path: Path) -> None:
    sentinel = tmp_path / "installer-ran.marker"
    manifest = build_manifest(tmp_path)
    manifest["scenarios"]["install"]["installer"]["command"] = [
        "sudo",
        "-n",
        sys.executable,
        "-c",
        f"import pathlib; pathlib.Path({str(sentinel)!r}).write_text('ran')",
    ]
    path = write_manifest(tmp_path, manifest)
    output = tmp_path / "bundle"
    exit_code = prove(harness, path, output)
    results = json.loads((output / "results.json").read_text(encoding="utf-8"))
    assert results["scenarios"]["INSTALL"]["outcome"] == harness.BLOCKED
    assert not sentinel.exists(), "a stop-before command must not be executed"
    assert exit_code == harness.EXIT_EVIDENCE


# ---------------------------------------------------------------------------
# Clean-target contract
# ---------------------------------------------------------------------------


def test_an_unmet_clean_target_contract_blocks_the_install(harness, tmp_path: Path) -> None:
    sentinel = tmp_path / "installer-ran.marker"
    payload = _clean_probe_payload()
    payload["developer_checkout_absent"] = False
    manifest = build_manifest(tmp_path)
    manifest["target"]["probe"] = _json_command(payload)
    manifest["scenarios"]["install"]["installer"]["command"] = [
        sys.executable,
        "-c",
        f"import pathlib; pathlib.Path({str(sentinel)!r}).write_text('ran')",
    ]
    path = write_manifest(tmp_path, manifest)
    output = tmp_path / "bundle"
    exit_code = prove(harness, path, output)
    results = json.loads((output / "results.json").read_text(encoding="utf-8"))
    checks = subchecks(results, "INSTALL")
    assert results["scenarios"]["INSTALL"]["outcome"] == harness.BLOCKED
    assert "CLEAN_TARGET_CONTRACT" in checks
    assert checks["CLEAN_TARGET_CONTRACT"]["missing_prerequisite"] == "developer_checkout_absent"
    assert not sentinel.exists(), "the install must not run on a target that failed the contract"
    assert exit_code == harness.EXIT_EVIDENCE


# ---------------------------------------------------------------------------
# Provider gate and budget
# ---------------------------------------------------------------------------


def test_an_absent_credential_makes_execute_not_run(harness, tmp_path: Path) -> None:
    manifest = build_manifest(tmp_path)
    manifest["credentials"][0]["present"] = False
    path = write_manifest(tmp_path, manifest)
    output = tmp_path / "bundle"
    exit_code = prove(harness, path, output)
    results = json.loads((output / "results.json").read_text(encoding="utf-8"))
    checks = subchecks(results, "EXECUTE")
    assert results["scenarios"]["EXECUTE"]["outcome"] == harness.NOT_RUN
    assert checks["PROVIDER_RESPONSE"]["missing_prerequisite"]
    assert results["budget"]["observed_provider_calls"] == 0
    assert exit_code == harness.EXIT_EVIDENCE


def test_an_unauthorized_provider_budget_makes_execute_not_run(harness, tmp_path: Path) -> None:
    manifest = build_manifest(tmp_path)
    manifest["provider"]["budget"]["authorized"] = False
    path = write_manifest(tmp_path, manifest)
    output = tmp_path / "bundle"
    exit_code = prove(harness, path, output)
    results = json.loads((output / "results.json").read_text(encoding="utf-8"))
    assert results["scenarios"]["EXECUTE"]["outcome"] == harness.NOT_RUN
    assert results["budget"]["authorized"] is False
    assert exit_code == harness.EXIT_EVIDENCE


def test_the_provider_budget_ceiling_blocks_the_release_proof(harness, tmp_path: Path) -> None:
    manifest = build_manifest(tmp_path)
    manifest["provider"]["budget"]["max_model_calls"] = 1
    path = write_manifest(tmp_path, manifest)
    output = tmp_path / "bundle"
    exit_code = prove(harness, path, output)
    results = json.loads((output / "results.json").read_text(encoding="utf-8"))
    assert results["scenarios"]["RESTART"]["outcome"] == harness.NOT_RUN
    assert results["budget"]["remaining_model_calls"] == 0
    assert results["closeout"]["all_families_pass"] is False
    assert exit_code == harness.EXIT_EVIDENCE


def test_execution_without_canonical_ids_fails(harness, tmp_path: Path) -> None:
    manifest = build_manifest(tmp_path)
    manifest["scenarios"]["execute"]["client"]["command"] = _json_command(
        {"run_id": "run-1", "provider_calls": 1}
    )
    path = write_manifest(tmp_path, manifest)
    output = tmp_path / "bundle"
    exit_code = prove(harness, path, output)
    results = json.loads((output / "results.json").read_text(encoding="utf-8"))
    checks = subchecks(results, "EXECUTE")
    assert checks["CANONICAL_IDS_PRESENT"]["outcome"] == harness.FAIL
    assert "node_run_id" in checks["CANONICAL_IDS_PRESENT"]["detail"]
    assert exit_code == harness.EXIT_EVIDENCE


def test_execution_reporting_a_different_effective_model_fails(harness, tmp_path: Path) -> None:
    """The issue requires the effective runtime values, not the plan metadata."""
    manifest = build_manifest(tmp_path)
    manifest["scenarios"]["execute"]["client"]["command"] = _json_command(
        {
            "run_id": "run-1",
            "node_run_id": "node-1",
            "attempt_id": "attempt-1",
            "gateway": "https://gateway.example/v1",
            "model": "some-other-model",
            "response_digest": "sha256:" + "b" * 64,
            "provider_calls": 1,
        }
    )
    path = write_manifest(tmp_path, manifest)
    output = tmp_path / "bundle"
    exit_code = prove(harness, path, output)
    results = json.loads((output / "results.json").read_text(encoding="utf-8"))
    checks = subchecks(results, "EXECUTE")
    assert checks["EFFECTIVE_MATCHES_DECLARED"]["outcome"] == harness.FAIL
    assert "some-other-model" in checks["EFFECTIVE_MATCHES_DECLARED"]["detail"]
    assert exit_code == harness.EXIT_EVIDENCE


def test_execution_reporting_a_different_effective_gateway_fails(harness, tmp_path: Path) -> None:
    manifest = build_manifest(tmp_path)
    manifest["scenarios"]["execute"]["client"]["command"] = _json_command(
        {
            "run_id": "run-1",
            "node_run_id": "node-1",
            "attempt_id": "attempt-1",
            "gateway": "https://elsewhere.example/v1",
            "model": "default-model",
            "response_digest": "sha256:" + "b" * 64,
            "provider_calls": 1,
        }
    )
    path = write_manifest(tmp_path, manifest)
    output = tmp_path / "bundle"
    exit_code = prove(harness, path, output)
    results = json.loads((output / "results.json").read_text(encoding="utf-8"))
    checks = subchecks(results, "EXECUTE")
    assert checks["EFFECTIVE_MATCHES_DECLARED"]["outcome"] == harness.FAIL
    assert "elsewhere.example" in checks["EFFECTIVE_MATCHES_DECLARED"]["detail"]
    assert exit_code == harness.EXIT_EVIDENCE


def test_execution_without_a_response_digest_fails(harness, tmp_path: Path) -> None:
    manifest = build_manifest(tmp_path)
    manifest["scenarios"]["execute"]["client"]["command"] = _json_command(
        {
            "run_id": "run-1",
            "node_run_id": "node-1",
            "attempt_id": "attempt-1",
            "gateway": "https://gateway.example/v1",
            "model": "default-model",
            "provider_calls": 1,
        }
    )
    path = write_manifest(tmp_path, manifest)
    output = tmp_path / "bundle"
    exit_code = prove(harness, path, output)
    results = json.loads((output / "results.json").read_text(encoding="utf-8"))
    checks = subchecks(results, "EXECUTE")
    assert checks["RESPONSE_DIGEST_PRESENT"]["outcome"] == harness.FAIL
    assert exit_code == harness.EXIT_EVIDENCE


def test_execution_without_a_provider_call_count_fails(harness, tmp_path: Path) -> None:
    """An unreported provider-call count leaves the budget unbounded."""
    manifest = build_manifest(tmp_path)
    manifest["scenarios"]["execute"]["client"]["command"] = _json_command(
        {
            "run_id": "run-1",
            "node_run_id": "node-1",
            "attempt_id": "attempt-1",
            "gateway": "https://gateway.example/v1",
            "model": "default-model",
            "response_digest": "sha256:" + "c" * 64,
        }
    )
    path = write_manifest(tmp_path, manifest)
    output = tmp_path / "bundle"
    exit_code = prove(harness, path, output)
    results = json.loads((output / "results.json").read_text(encoding="utf-8"))
    checks = subchecks(results, "EXECUTE")
    assert checks["PROVIDER_CALLS_REPORTED"]["outcome"] == harness.FAIL
    assert exit_code == harness.EXIT_EVIDENCE


def test_the_results_record_the_principal_and_the_canonical_execution_ids(
    harness, tmp_path: Path
) -> None:
    manifest = build_manifest(tmp_path)
    path = write_manifest(tmp_path, manifest)
    output = tmp_path / "bundle"
    prove(harness, path, output)
    results = json.loads((output / "results.json").read_text(encoding="utf-8"))
    execute = results["scenarios"]["EXECUTE"]
    assert execute["principal"] == {"user": "operator", "workspace": "ws-1"}
    assert execute["canonical_ids"] == {
        "run_id": "run-1",
        "node_run_id": "node-1",
        "attempt_id": "attempt-1",
    }
    assert execute["effective"]["model"] == "default-model"
    assert results["scenarios"]["RESTART"]["principal"] == {
        "user": "operator",
        "workspace": "ws-1",
    }


def test_the_results_record_the_support_row_and_the_controller_provenance(
    harness, tmp_path: Path
) -> None:
    manifest = build_manifest(tmp_path)
    path = write_manifest(tmp_path, manifest)
    output = tmp_path / "bundle"
    prove(harness, path, output)
    results = json.loads((output / "results.json").read_text(encoding="utf-8"))
    echo = results["profile_echo"]
    assert echo["support_row"] == "linux-x86-docker-default"
    assert echo["os"] == "linux"
    assert echo["arch"] == "x86_64"
    assert echo["runtime"] == "docker"
    assert echo["context"] == "default"
    assert echo["store_profile"] == "standalone-compose"
    assert results["harness"]["script_sha256"].startswith("sha256:")
    assert results["harness"]["controller_commit"]
    assert results["generated_at"].endswith("Z")


# ---------------------------------------------------------------------------
# Restart, isolation, fail-closed truthfulness
# ---------------------------------------------------------------------------


def test_restart_without_correlation_fails(harness, tmp_path: Path) -> None:
    manifest = build_manifest(tmp_path)
    manifest["scenarios"]["restart"]["persistence"]["command"] = _json_command(
        {"correlated_run_id": "run-other", "user": "operator", "workspace": "ws-1"}
    )
    path = write_manifest(tmp_path, manifest)
    output = tmp_path / "bundle"
    exit_code = prove(harness, path, output)
    results = json.loads((output / "results.json").read_text(encoding="utf-8"))
    checks = subchecks(results, "RESTART")
    assert checks["CORRELATION"]["outcome"] == harness.FAIL
    assert "run-other" in checks["CORRELATION"]["detail"]
    assert exit_code == harness.EXIT_EVIDENCE


def test_a_stop_that_leaves_sandboxes_behind_fails(harness, tmp_path: Path) -> None:
    manifest = build_manifest(tmp_path)
    manifest["scenarios"]["restart"]["stop"]["command"] = _json_command(
        {"drained": True, "sandboxes_remaining": 2}
    )
    path = write_manifest(tmp_path, manifest)
    output = tmp_path / "bundle"
    exit_code = prove(harness, path, output)
    results = json.loads((output / "results.json").read_text(encoding="utf-8"))
    checks = subchecks(results, "RESTART")
    assert checks["NO_ORPHANED_SANDBOXES"]["outcome"] == harness.FAIL
    assert exit_code == harness.EXIT_EVIDENCE


def test_an_isolation_probe_that_is_not_denied_fails(harness, tmp_path: Path) -> None:
    manifest = build_manifest(tmp_path)
    manifest["scenarios"]["isolate"]["probes"][0]["command"]["command"] = _json_command(
        {"denied": False, "leaked": ["other user's message"], "dispatched": True}
    )
    path = write_manifest(tmp_path, manifest)
    output = tmp_path / "bundle"
    exit_code = prove(harness, path, output)
    results = json.loads((output / "results.json").read_text(encoding="utf-8"))
    checks = subchecks(results, "ISOLATE")
    assert checks["ISOLATION_PROBE-0"]["outcome"] == harness.FAIL
    assert exit_code == harness.EXIT_EVIDENCE


def test_the_isolation_positive_control_must_be_accessible(harness, tmp_path: Path) -> None:
    manifest = build_manifest(tmp_path)
    manifest["scenarios"]["isolate"]["positive_control"]["command"] = _json_command(
        {"accessible": False}
    )
    path = write_manifest(tmp_path, manifest)
    output = tmp_path / "bundle"
    exit_code = prove(harness, path, output)
    results = json.loads((output / "results.json").read_text(encoding="utf-8"))
    checks = subchecks(results, "ISOLATE")
    assert checks["POSITIVE_CONTROL_ACCESSIBLE"]["outcome"] == harness.FAIL
    assert exit_code == harness.EXIT_EVIDENCE


def test_a_fail_closed_case_reporting_success_fails(harness, tmp_path: Path) -> None:
    manifest = build_manifest(tmp_path)
    manifest["scenarios"]["fail_closed"]["cases"][0]["client"]["command"] = _json_command(
        {"outcome": "succeeded", "recovery": "none needed"}
    )
    path = write_manifest(tmp_path, manifest)
    output = tmp_path / "bundle"
    exit_code = prove(harness, path, output)
    results = json.loads((output / "results.json").read_text(encoding="utf-8"))
    checks = subchecks(results, "FAIL_CLOSED")
    assert checks["TRUTHFUL_ABSENT_CREDENTIAL"]["outcome"] == harness.FAIL
    assert exit_code == harness.EXIT_EVIDENCE


def test_a_fail_closed_case_without_a_recovery_pointer_fails(harness, tmp_path: Path) -> None:
    manifest = build_manifest(tmp_path)
    manifest["scenarios"]["fail_closed"]["cases"][1]["client"]["command"] = _json_command(
        {"outcome": "blocked"}
    )
    path = write_manifest(tmp_path, manifest)
    output = tmp_path / "bundle"
    exit_code = prove(harness, path, output)
    results = json.loads((output / "results.json").read_text(encoding="utf-8"))
    checks = subchecks(results, "FAIL_CLOSED")
    assert checks["TRUTHFUL_UNAVAILABLE_MODEL"]["outcome"] == harness.FAIL
    assert exit_code == harness.EXIT_EVIDENCE


def test_effective_configuration_must_match_the_declared_provider(harness, tmp_path: Path) -> None:
    manifest = build_manifest(tmp_path)
    manifest["scenarios"]["install"]["effective_config"]["command"] = _json_command(
        {"gateway": "https://other.example/v1", "model": "default-model"}
    )
    path = write_manifest(tmp_path, manifest)
    output = tmp_path / "bundle"
    exit_code = prove(harness, path, output)
    results = json.loads((output / "results.json").read_text(encoding="utf-8"))
    checks = subchecks(results, "INSTALL")
    assert checks["EFFECTIVE_MATCHES_DECLARED"]["outcome"] == harness.FAIL
    assert exit_code == harness.EXIT_EVIDENCE


# ---------------------------------------------------------------------------
# The evidence bundle
# ---------------------------------------------------------------------------


def test_a_complete_run_passes_every_family_and_writes_the_bundle(harness, tmp_path: Path) -> None:
    manifest = build_manifest(tmp_path)
    path = write_manifest(tmp_path, manifest)
    output = tmp_path / "bundle"
    exit_code = prove(harness, path, output)
    results = json.loads((output / "results.json").read_text(encoding="utf-8"))
    assert exit_code == harness.EXIT_OK
    assert results["closeout"]["all_families_pass"] is True
    assert set(family_outcomes(results).values()) == {harness.PASS}
    for name in harness.REQUIRED_FILES:
        assert (output / name).is_file(), f"{name} must be in the bundle"
    index = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert set(harness.REQUIRED_FILES) <= set(index["files"])
    for excluded in harness.EXCLUDED_FROM_HASH:
        assert excluded not in index["files"]
    assert results["closeout"]["bundle_verified"] is True


@pytest.mark.parametrize(
    ("family", "slot"),
    [
        ("INSTALL", "probe"),
        ("INSTALL", "login"),
        ("INSTALL", "workspace"),
        ("INSTALL", "effective_config"),
        ("EXECUTE", "client"),
        ("RESTART", "stop"),
        ("RESTART", "persistence"),
        ("RESTART", "new_request"),
        ("ISOLATE", "positive_control"),
        ("FAIL_CLOSED", "client"),
    ],
)
@pytest.mark.parametrize("stdout", ["not JSON", "[]"])
def test_required_observations_cannot_pass_without_a_json_object(
    harness, tmp_path: Path, family: str, slot: str, stdout: str
) -> None:
    manifest = build_manifest(tmp_path)
    command = _text_command(stdout)
    if slot == "probe":
        manifest["target"]["probe"] = command
    else:
        scenario = manifest["scenarios"][family.lower()]
        if family == "FAIL_CLOSED":
            step = scenario["cases"][0][slot]
        elif slot == "login":
            step = scenario[slot]["command"]
        else:
            step = scenario[slot]
        step["command"] = command
        # These optional manifest expectations must not be the only thing
        # enforcing the harness's mandatory observation contract.
        step.pop("expect_json", None)
        step.pop("payload", None)
    output = tmp_path / "bundle"
    exit_code = prove(harness, write_manifest(tmp_path, manifest), output)
    results = json.loads((output / "results.json").read_text(encoding="utf-8"))
    assert exit_code == harness.EXIT_EVIDENCE
    assert results["scenarios"][family]["outcome"] == harness.FAIL
    assert results["closeout"]["all_families_pass"] is False
    assert any(
        check["detail"] == "stdout was not a JSON object"
        for check in results["scenarios"][family]["subchecks"]
    )
    assert harness.verify_bundle(output) == []
    if slot == "probe":
        install = json.loads((output / "effective-config.json").read_text(encoding="utf-8"))
        assert [step["name"] for step in install["steps"]] == ["TARGET_CLEAN"]


@pytest.mark.parametrize(
    "observation",
    [
        {"sandboxes_remaining": 0},
        {"drained": False, "sandboxes_remaining": 0},
        {"drained": 1, "sandboxes_remaining": 0},
        {"drained": True, "sandboxes_remaining": False},
        {"drained": True, "sandboxes_remaining": 0.0},
        {"drained": True},
    ],
)
def test_restart_requires_observed_lifespan_drain_and_integer_zero_sandboxes(
    harness, tmp_path: Path, observation: dict[str, Any]
) -> None:
    manifest = build_manifest(tmp_path)
    manifest["scenarios"]["restart"]["stop"]["command"] = _json_command(observation)
    output = tmp_path / "bundle"
    exit_code = prove(harness, write_manifest(tmp_path, manifest), output)
    results = json.loads((output / "results.json").read_text(encoding="utf-8"))
    checks = subchecks(results, "RESTART")
    expected = (
        "LIFESPAN_DRAINED" if observation.get("drained") is not True else "NO_ORPHANED_SANDBOXES"
    )
    assert checks[expected]["outcome"] == harness.FAIL
    assert results["scenarios"]["RESTART"]["outcome"] == harness.FAIL
    assert exit_code == harness.EXIT_EVIDENCE


def test_the_bundle_records_the_effective_environment_and_the_target_probe(
    harness, tmp_path: Path
) -> None:
    manifest = build_manifest(tmp_path)
    path = write_manifest(tmp_path, manifest)
    output = tmp_path / "bundle"
    prove(harness, path, output)
    results = json.loads((output / "results.json").read_text(encoding="utf-8"))
    assert results["environment"]["target_probe"]["os"] == "linux"
    assert results["environment"]["declared"]["account"] == "operator"
    assert results["artifacts"]["ref"] == "v1.2.0-rc1"
    assert results["profile_echo"]["support_row"] == "linux-x86-docker-default"


def test_the_bundle_hashes_its_payloads_and_detects_a_tampered_file(
    harness, tmp_path: Path
) -> None:
    manifest = build_manifest(tmp_path)
    path = write_manifest(tmp_path, manifest)
    output = tmp_path / "bundle"
    prove(harness, path, output)
    assert harness.verify_bundle(output) == []
    (output / "execution.json").write_text('{"tampered": true}\n', encoding="utf-8")
    problems = harness.verify_bundle(output)
    assert any("execution.json" in problem and "hash mismatch" in problem for problem in problems)


def test_the_bundle_refuses_a_manifest_listed_evidence_that_names_results(
    harness, tmp_path: Path
) -> None:
    manifest = build_manifest(tmp_path)
    path = write_manifest(tmp_path, manifest)
    output = tmp_path / "bundle"
    prove(harness, path, output)
    results = json.loads((output / "results.json").read_text(encoding="utf-8"))
    results["scenarios"]["EXECUTE"]["evidence"] = ["results.json"]
    (output / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    problems = harness.verify_bundle(output)
    assert any("results.json" in problem for problem in problems)


def test_not_applicable_is_refused_outside_the_browser_login_subcheck(
    harness, tmp_path: Path
) -> None:
    manifest = build_manifest(tmp_path)
    path = write_manifest(tmp_path, manifest)
    output = tmp_path / "bundle"
    prove(harness, path, output)
    results = json.loads((output / "results.json").read_text(encoding="utf-8"))
    results["scenarios"]["INSTALL"]["subchecks"].append(
        {"name": "WORKSPACE", "outcome": harness.NOT_APPLICABLE, "detail": None, "evidence": []}
    )
    (output / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    problems = harness.verify_bundle(output)
    assert any("NOT_APPLICABLE" in problem for problem in problems)


def test_a_headless_row_records_browser_login_as_not_applicable(harness, tmp_path: Path) -> None:
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps({"support_row": "linux-x86-headless"}), encoding="utf-8")
    manifest = build_manifest(tmp_path)
    manifest["support_row"]["browser"] = "headless"
    manifest["support_row"]["profile_path"] = str(profile)
    manifest["support_row"]["headless_review"] = {
        "independently_reviewed": True,
        "reviewer": "release-owner",
    }
    manifest["scenarios"]["install"]["login"]["mode"] = "authenticated_equivalent"
    path = write_manifest(tmp_path, manifest)
    output = tmp_path / "bundle"
    exit_code = prove(harness, path, output)
    results = json.loads((output / "results.json").read_text(encoding="utf-8"))
    checks = subchecks(results, "INSTALL")
    assert checks["BROWSER_LOGIN"]["outcome"] == harness.NOT_APPLICABLE
    assert "AUTH_EQUIVALENT" in checks
    assert exit_code == harness.EXIT_OK


def test_the_install_log_redacts_secret_shaped_output(harness, tmp_path: Path) -> None:
    manifest = build_manifest(tmp_path)
    manifest["scenarios"]["install"]["installer"]["command"] = [
        sys.executable,
        "-c",
        "print('API_KEY=supersecretvalue123')",
    ]
    path = write_manifest(tmp_path, manifest)
    output = tmp_path / "bundle"
    prove(harness, path, output)
    log = (output / "install.log").read_text(encoding="utf-8")
    assert "supersecretvalue123" not in log
    assert harness.REDACTED in log


def test_the_harness_does_not_inherit_the_controller_environment(harness) -> None:
    env = harness.build_env({"env_path": "/opt/bin", "home": "/home/operator"})
    assert env == {"PATH": "/opt/bin", "HOME": "/home/operator", "LC_ALL": "C.UTF-8"}
    assert "VIRTUAL_ENV" not in env
    assert "PYTHONPATH" not in env


def test_a_manifest_naming_the_developer_checkout_is_refused(harness, tmp_path: Path) -> None:
    """The issue forbids substituting the checkout for the published artifact."""
    manifest = build_manifest(tmp_path)
    manifest["scenarios"]["install"]["installer"]["command"] = ["bash", str(ROOT / "install.sh")]
    path = write_manifest(tmp_path, manifest)
    output = tmp_path / "bundle"
    with pytest.raises(harness.ProofError) as refusal:
        prove(harness, path, output)
    assert "checkout" in str(refusal.value)
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--manifest", str(path), "--output", str(output)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 2
    assert "checkout" in completed.stderr
    assert not output.exists() or not any(output.iterdir())


def test_a_manifest_naming_a_secret_shaped_literal_never_reaches_the_bundle(
    harness, tmp_path: Path
) -> None:
    manifest = build_manifest(tmp_path)
    manifest["scenarios"]["install"]["installer"]["command"] = _text_command("nothing to see")
    path = write_manifest(tmp_path, manifest)
    output = tmp_path / "bundle"
    prove(harness, path, output)
    copied = json.loads((output / "reviewed-manifest.json").read_text(encoding="utf-8"))
    assert copied["credentials"][0]["reference"] == "vault://gateway/provider"
    index = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert "reviewed-manifest.json" not in index["files"]


# ---------------------------------------------------------------------------
# CLI contract
# ---------------------------------------------------------------------------


def test_the_cli_exits_two_on_an_invalid_manifest(tmp_path: Path) -> None:
    manifest = build_manifest(tmp_path)
    del manifest["provider"]
    path = write_manifest(tmp_path, manifest)
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--manifest",
            str(path),
            "--output",
            str(tmp_path / "bundle"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 2
    assert "error:" in completed.stderr


def test_the_cli_exits_one_when_a_family_does_not_pass(tmp_path: Path) -> None:
    manifest = build_manifest(tmp_path)
    manifest["credentials"][0]["present"] = False
    path = write_manifest(tmp_path, manifest)
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--manifest",
            str(path),
            "--output",
            str(tmp_path / "bundle"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 1


def test_the_cli_verifies_a_shipped_bundle(tmp_path: Path) -> None:
    manifest = build_manifest(tmp_path)
    path = write_manifest(tmp_path, manifest)
    bundle = tmp_path / "bundle"
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--manifest", str(path), "--output", str(bundle)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0
    verified = subprocess.run(
        [sys.executable, str(SCRIPT), "--verify", str(bundle)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert verified.returncode == 0
    assert "never run occurrence" in verified.stdout


def test_the_cli_refuses_to_overwrite_a_non_empty_bundle(harness, tmp_path: Path) -> None:
    manifest = build_manifest(tmp_path)
    path = write_manifest(tmp_path, manifest)
    output = tmp_path / "bundle"
    output.mkdir()
    (output / "existing.txt").write_text("previous evidence\n", encoding="utf-8")
    with pytest.raises(harness.ProofError):
        prove(harness, path, output)


def test_the_manifest_is_validated_before_anything_is_executed(harness, tmp_path: Path) -> None:
    """A manifest that fails the schema must not launch a single command."""
    sentinel = tmp_path / "probe-ran.marker"
    manifest = build_manifest(tmp_path)
    manifest["target"]["probe"] = [
        sys.executable,
        "-c",
        f"import pathlib; pathlib.Path({str(sentinel)!r}).write_text('ran')",
    ]
    manifest["artifacts"]["ref"] = "not-a-tag"
    path = write_manifest(tmp_path, manifest)
    output = tmp_path / "bundle"
    with pytest.raises(harness.SchemaError):
        prove(harness, path, output)
    assert not sentinel.exists()


# ---------------------------------------------------------------------------
# Harness internals: the pure logic a manifest cannot reach directly, driven
# through the harness's own module so the contract is exercised, not re-described
# ---------------------------------------------------------------------------


def test_schema_subset_rejects_every_unsupported_shape(harness) -> None:
    """Each validator error path fires on the input that names it."""
    cases = [
        (1, {"type": "string"}, "expected string, got integer"),
        (None, {"type": "object"}, "expected object, got null"),
        (1.5, {"type": "string"}, "expected string, got number"),
        ({1, 2}, {"type": "string"}, "got set"),
        (2, {"const": 1}, "expected const"),
        ("b", {"enum": ["a"]}, "not in enum"),
        (-1, {"type": "integer", "minimum": 0}, "minimum"),
        ("ab", {"type": "string", "minLength": 3}, "minLength"),
        ("abcd", {"type": "string", "maxLength": 3}, "maxLength"),
        ([1], {"minItems": 2}, "minItems"),
        ([1, 2, 3], {"maxItems": 2}, "maxItems"),
        ({"a": 1}, {"$ref": "http://example.invalid/schema"}, "only local"),
        ({"a": 1}, {"$ref": "#/$defs/absent"}, "not defined"),
        (1, {"unsupported_keyword": True}, "unsupported keyword"),
        # A nested False schema forbids its value; a nested non-object schema is
        # refused as a contract error. The top-level validator only accepts
        # object schemas, so both shapes are exercised through allOf.
        ([1], {"allOf": [False]}, "forbids any value"),
        (1, {"allOf": ["not-a-schema"]}, "must be an object or boolean"),
    ]
    for instance, schema, fragment in cases:
        with pytest.raises(harness.SchemaError, match=fragment):
            harness.validate_manifest(instance, schema)


def test_validate_manifest_refuses_a_non_object_defs_table(harness) -> None:
    with pytest.raises(harness.SchemaError, match="defs must be an object"):
        harness.validate_manifest(1, {"$defs": ["not-a-table"]})


def test_load_contract_refuses_an_unreadable_or_malformed_schema(
    harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "absent-schema.json"
    monkeypatch.setattr(harness, "SCHEMA_PATH", missing)
    with pytest.raises(harness.ProofError, match="cannot read contract schema"):
        harness.load_contract()

    malformed = tmp_path / "malformed-schema.json"
    malformed.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(harness, "SCHEMA_PATH", malformed)
    with pytest.raises(harness.ProofError, match="not valid JSON"):
        harness.load_contract()

    scalar = tmp_path / "scalar-schema.json"
    scalar.write_text("42", encoding="utf-8")
    monkeypatch.setattr(harness, "SCHEMA_PATH", scalar)
    with pytest.raises(harness.ProofError, match="must be a JSON object"):
        harness.load_contract()


def test_a_headless_row_must_declare_the_authenticated_equivalent_login(
    harness, tmp_path: Path
) -> None:
    manifest = build_manifest(tmp_path)
    manifest["support_row"]["browser"] = "headless"
    manifest["support_row"]["profile_path"] = str(tmp_path / "profile.json")
    manifest["support_row"]["headless_review"] = {"independently_reviewed": True}
    # login.mode stays "browser": the one combination the cross-rule refuses.
    with pytest.raises(harness.ProofError, match="authenticated_equivalent"):
        harness.check_cross_rules(manifest)


def test_isolation_requires_two_distinct_workspaces(harness, tmp_path: Path) -> None:
    manifest = build_manifest(tmp_path)
    manifest["scenarios"]["isolate"]["workspaces"] = ["ws-1", "ws-1"]
    with pytest.raises(harness.ProofError, match="two distinct workspaces"):
        harness.check_cross_rules(manifest)


def test_commands_outside_the_checkout_are_not_checkout_artifacts(harness, tmp_path: Path) -> None:
    """The refusal targets this repository's tree, not any absolute path."""
    manifest = build_manifest(tmp_path)
    manifest["scenarios"]["install"]["installer"]["command"] = ["/bin/echo", "installed"]
    harness.check_no_checkout_artifacts(manifest)


def test_iter_commands_skips_a_non_object_fail_closed_case(harness) -> None:
    commands = list(
        harness.iter_commands(
            {"scenarios": {"fail_closed": {"cases": ["not-a-step", {"name": "case"}]}}}
        )
    )
    assert commands == []


def test_build_step_enforces_its_step_contract(harness) -> None:
    with pytest.raises(harness.ProofError, match="must be an object"):
        harness.build_step(["not", "a", "dict"], "STEP")
    with pytest.raises(harness.ProofError, match="non-empty argv of strings"):
        harness.build_step({"command": []}, "STEP")
    with pytest.raises(harness.ProofError, match="expect_exit must be a non-empty list"):
        harness.build_step({"command": ["true"], "expect_exit": []}, "STEP")


def test_build_cwd_refuses_a_missing_workdir(harness) -> None:
    with pytest.raises(harness.ProofError, match="does not exist"):
        harness.build_cwd({"workdir": str(Path("/nonexistent-proof-target"))})


def test_elapsed_ms_survives_an_unusable_stamp(harness) -> None:
    assert harness._elapsed_ms("not-a-timestamp") == 0


def test_the_harness_digest_records_itself_as_unavailable_when_unreadable(
    harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    class UnreadablePath:
        def __init__(self, *args: object) -> None:
            pass

        def resolve(self) -> UnreadablePath:
            return self

        def read_bytes(self) -> bytes:
            raise OSError("unreadable")

    monkeypatch.setattr(harness, "Path", UnreadablePath)
    assert harness._harness_script_digest() == "unavailable"


def test_the_controller_commit_is_unavailable_when_git_is(harness, monkeypatch):
    def raise_os_error(*args, **kwargs):
        raise OSError("no git")

    monkeypatch.setattr(harness.subprocess, "run", raise_os_error)
    assert harness._harness_controller_commit() == "unavailable"

    class FailedProc:
        returncode = 1
        stdout = ""

    monkeypatch.setattr(harness.subprocess, "run", lambda *a, **k: FailedProc())
    assert harness._harness_controller_commit() == "unavailable"


def test_the_install_log_newline_terminates_each_chunk_and_truncates_at_the_cap(
    harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log_path = tmp_path / "install.log"
    log = harness.InstallLog(log_path)
    log.append("no trailing newline", ["chunk-without-newline"])
    assert log_path.read_text(encoding="utf-8").endswith("chunk-without-newline\n")

    monkeypatch.setattr(harness, "INSTALL_LOG_CAP_BYTES", log._bytes + 8)
    log.append("over the cap", ["0123456789abcdef"])
    assert log.truncated is True
    assert "TRUNCATED" in log_path.read_text(encoding="utf-8")
    assert log._bytes == harness.INSTALL_LOG_CAP_BYTES


def test_a_step_that_times_out_or_misses_its_binary_is_a_recorded_failure(
    harness, tmp_path: Path
) -> None:
    log_path = tmp_path / "install.log"
    log = harness.InstallLog(log_path)
    env = harness.build_env({})
    cwd = harness.build_cwd({"workdir": str(tmp_path)})

    slow = harness.build_step(
        {"command": [sys.executable, "-c", "import time; time.sleep(30)"], "timeout_s": 1},
        "SLOW",
    )
    timed_out = harness.run_step(slow, env, cwd, log)
    assert timed_out.timed_out is True
    assert harness.step_outcome(timed_out) == (harness.FAIL, "timed out after 1s")

    absent = harness.build_step({"command": ["definitely-not-a-real-binary-xyz"]}, "ABSENT")
    missing = harness.run_step(absent, env, cwd, log)
    assert missing.exit_code is None
    outcome, detail = harness.step_outcome(missing)
    assert outcome == harness.FAIL
    assert "command not found" in detail
    assert "ABSENT" in log_path.read_text(encoding="utf-8")


def test_log_result_without_a_log_is_a_no_op(harness) -> None:
    step = harness.build_step({"command": ["true"]}, "STEP")
    result = harness.StepResult(step=step, executed=True, exit_code=0)
    harness._log_result(None, result, True)


def test_expect_json_enforces_every_expectation_shape(harness) -> None:
    def step(expect_json: dict[str, Any], payload: str | None = None) -> harness.Step:
        raw: dict[str, Any] = {"command": ["true"], "expect_json": expect_json}
        if payload is not None:
            raw["payload"] = payload
        return harness.build_step(raw, "STEP")

    # A payload-bearing step whose stdout is not JSON fails even unchecked.
    assert (
        harness.check_expect_json(step({}, payload="out.json"), None)
        == "stdout was not a JSON object"
    )
    # With expectations, a non-JSON stdout fails the same way.
    assert harness.check_expect_json(step({"a": 1}), None) == "stdout was not a JSON object"
    assert harness.check_expect_json(step({"a": 1}), {}) == "stdout JSON missing key 'a'"
    assert "nonempty_string" in harness.check_expect_json(
        step({"a": "nonempty_string"}), {"a": "   "}
    )
    assert "positive_integer" in harness.check_expect_json(
        step({"a": "positive_integer"}), {"a": 0}
    )
    # A boolean is not a positive integer even though bool is an int subtype.
    assert harness.check_expect_json(step({"a": "positive_integer"}), {"a": True}) == (
        "a: expected positive_integer, got True"
    )
    assert harness.check_expect_json(step({"a": "integer"}), {"a": True}) == (
        "a: expected integer, got bool"
    )
    assert "expected string" in harness.check_expect_json(step({"a": "string"}), {"a": 1})
    assert "expected 1" in harness.check_expect_json(step({"a": 1}), {"a": 2})
    assert harness.check_expect_json(step({"a": 1}), {"a": 1}) is None


def test_step_outcome_reports_the_expectation_failure_detail(harness) -> None:
    good = harness.build_step({"command": ["true"], "expect_json": {"a": 1}}, "STEP")
    result = harness.StepResult(step=good, executed=True, exit_code=0, stdout_json={"a": 2})
    outcome, detail = harness.step_outcome(result)
    assert outcome == harness.FAIL
    assert "expected 1" in detail


def test_a_family_with_no_outcome_is_not_run(harness) -> None:
    """No subchecks means nothing ran; NOT_RUN is the honest verdict."""
    family = harness.FamilyResult("INSTALL", "install.log")
    assert family.outcome == harness.NOT_RUN


def test_the_budget_state_is_unbounded_without_an_integer_ceiling(harness, tmp_path: Path) -> None:
    manifest = build_manifest(tmp_path)
    del manifest["provider"]["budget"]["max_model_calls"]
    output = tmp_path / "bundle"
    output.mkdir()
    run = harness.ProofRun(manifest, write_manifest(tmp_path, manifest), output)
    assert run._budget_state() == (True, None)


def test_a_profile_path_that_does_not_exist_is_refused_before_any_run(
    harness, tmp_path: Path
) -> None:
    manifest = build_manifest(tmp_path)
    manifest["support_row"]["browser"] = "headless"
    manifest["support_row"]["profile_path"] = str(tmp_path / "absent-profile.json")
    manifest["support_row"]["headless_review"] = {
        "independently_reviewed": True,
        "reviewer": "release-owner",
    }
    manifest["scenarios"]["install"]["login"]["mode"] = "authenticated_equivalent"
    path = write_manifest(tmp_path, manifest)
    with pytest.raises(harness.ProofError, match="does not exist"):
        prove(harness, path, tmp_path / "bundle")


def test_a_manifest_that_is_not_json_is_refused_with_proof_error(harness, tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text("{truncated", encoding="utf-8")
    schema = harness.load_contract()
    with pytest.raises(harness.ProofError, match="not valid JSON"):
        harness.load_manifest(path, schema)
    with pytest.raises(harness.ProofError, match="cannot read manifest"):
        harness.load_manifest(tmp_path / "absent-manifest.json", schema)


# ---------------------------------------------------------------------------
# Stop-before policy across every remaining family
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("slot_path", "argv"),
    [
        ("restart.stop", ["sudo", "systemctl", "stop", "maistro-engine"]),
        ("isolate.positive_control", ["chgrp", "docker", "/var/run/docker.sock"]),
        ("fail_closed.case0.arrange", ["ssh-keygen", "-t", "ed25519"]),
    ],
)
def test_a_stop_before_command_in_any_family_blocks_that_family(
    harness, tmp_path: Path, slot_path: str, argv: list[str]
) -> None:
    family, _, rest = slot_path.partition(".")
    manifest = build_manifest(tmp_path)
    target = manifest["scenarios"][family.lower()]
    if family == "fail_closed":
        target["cases"][0]["arrange"]["command"] = list(argv)
    elif rest == "positive_control":
        target["positive_control"]["command"] = list(argv)
    else:
        target[rest]["command"] = list(argv)
    path = write_manifest(tmp_path, manifest)
    output = tmp_path / "bundle"
    exit_code = prove(harness, path, output)
    results = json.loads((output / "results.json").read_text(encoding="utf-8"))
    assert results["scenarios"][family.upper()]["outcome"] == harness.BLOCKED
    assert any(
        sub["outcome"] == harness.BLOCKED and sub["name"].startswith("STOP_BEFORE_")
        for sub in results["scenarios"][family.upper()]["subchecks"]
    )
    assert exit_code == harness.EXIT_EVIDENCE


# ---------------------------------------------------------------------------
# Family observations the first repair round did not reach
# ---------------------------------------------------------------------------


def test_the_install_effective_config_must_match_the_declared_model(
    harness, tmp_path: Path
) -> None:
    manifest = build_manifest(tmp_path)
    manifest["scenarios"]["install"]["effective_config"]["command"] = _json_command(
        {"gateway": "https://gateway.example/v1", "model": "a-different-model"}
    )
    path = write_manifest(tmp_path, manifest)
    output = tmp_path / "bundle"
    exit_code = prove(harness, path, output)
    results = json.loads((output / "results.json").read_text(encoding="utf-8"))
    checks = subchecks(results, "INSTALL")
    assert checks["EFFECTIVE_MATCHES_DECLARED"]["outcome"] == harness.FAIL
    assert "a-different-model" in checks["EFFECTIVE_MATCHES_DECLARED"]["detail"]
    assert results["scenarios"]["INSTALL"]["outcome"] == harness.FAIL
    assert exit_code == harness.EXIT_EVIDENCE


def test_the_install_effective_config_must_match_a_declared_model_tier(
    harness, tmp_path: Path
) -> None:
    manifest = build_manifest(tmp_path)
    manifest["provider"]["model_tier"] = "tier-reviewed"
    manifest["scenarios"]["install"]["effective_config"]["command"] = _json_command(
        {
            "gateway": "https://gateway.example/v1",
            "model": "default-model",
            "model_tier": "tier-unreviewed",
        }
    )
    path = write_manifest(tmp_path, manifest)
    output = tmp_path / "bundle"
    exit_code = prove(harness, path, output)
    results = json.loads((output / "results.json").read_text(encoding="utf-8"))
    checks = subchecks(results, "INSTALL")
    assert checks["EFFECTIVE_MATCHES_DECLARED"]["outcome"] == harness.FAIL
    assert "tier-unreviewed" in checks["EFFECTIVE_MATCHES_DECLARED"]["detail"]
    assert exit_code == harness.EXIT_EVIDENCE


def test_the_login_subcheck_keeps_its_canonical_name(harness, tmp_path: Path) -> None:
    """A manifest-chosen step label must not rename the canonical subcheck."""
    manifest = build_manifest(tmp_path)
    manifest["scenarios"]["install"]["login"]["command"]["name"] = "SIGNIN"
    path = write_manifest(tmp_path, manifest)
    output = tmp_path / "bundle"
    exit_code = prove(harness, path, output)
    results = json.loads((output / "results.json").read_text(encoding="utf-8"))
    checks = subchecks(results, "INSTALL")
    assert "BROWSER_LOGIN" in checks
    assert checks["BROWSER_LOGIN"]["outcome"] == harness.PASS
    assert "SIGNIN" not in checks
    assert exit_code == harness.EXIT_OK


@pytest.mark.parametrize(
    ("field", "observed"),
    [
        ("user", "someone-else"),
        ("workspace", "other-workspace"),
    ],
)
def test_restart_correlation_reports_a_scope_mismatch_as_a_failure(
    harness, tmp_path: Path, field: str, observed: str
) -> None:
    manifest = build_manifest(tmp_path)
    persistence = {"correlated_run_id": "run-1", "user": "operator", "workspace": "ws-1"}
    persistence[field] = observed
    manifest["scenarios"]["restart"]["persistence"]["command"] = _json_command(persistence)
    path = write_manifest(tmp_path, manifest)
    output = tmp_path / "bundle"
    exit_code = prove(harness, path, output)
    results = json.loads((output / "results.json").read_text(encoding="utf-8"))
    checks = subchecks(results, "RESTART")
    assert checks["CORRELATION"]["outcome"] == harness.FAIL
    assert field in checks["CORRELATION"]["detail"]
    assert exit_code == harness.EXIT_EVIDENCE


@pytest.mark.parametrize(
    "observed",
    [{"accepted": True}, {"provider_calls": True}, {"provider_calls": -1}],
)
def test_a_restart_request_must_report_a_non_negative_call_count(
    harness, tmp_path: Path, observed: dict[str, Any]
) -> None:
    manifest = build_manifest(tmp_path)
    manifest["scenarios"]["restart"]["new_request"]["command"] = _json_command(observed)
    path = write_manifest(tmp_path, manifest)
    output = tmp_path / "bundle"
    exit_code = prove(harness, path, output)
    results = json.loads((output / "results.json").read_text(encoding="utf-8"))
    checks = subchecks(results, "RESTART")
    assert checks["PROVIDER_CALLS_REPORTED"]["outcome"] == harness.FAIL
    assert exit_code == harness.EXIT_EVIDENCE


# ---------------------------------------------------------------------------
# Bundle assembly and --verify: structural integrity is the contract
# ---------------------------------------------------------------------------


def test_write_bundle_refuses_to_ship_a_bundle_missing_a_required_file(
    harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = build_manifest(tmp_path)
    path = write_manifest(tmp_path, manifest)
    output = tmp_path / "bundle"
    prove(harness, path, output)
    results = json.loads((output / "results.json").read_text(encoding="utf-8"))
    payloads = {
        family: json.loads((output / harness.payload_name(family)).read_text(encoding="utf-8"))
        for family in harness.FAMILIES
    }
    other = tmp_path / "incomplete"
    other.mkdir()
    (other / "a-subdir").mkdir()  # directories are skipped, not hashed
    monkeypatch.setattr(harness, "REQUIRED_FILES", (*harness.REQUIRED_FILES, "ghost.bin"))
    with pytest.raises(harness.ProofError, match=r"ghost\.bin"):
        harness.write_bundle(other, results, payloads, b"{}", None)


def _shipped_bundle(harness, tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    manifest = build_manifest(tmp_path)
    path = write_manifest(tmp_path, manifest)
    bundle = tmp_path / "bundle"
    prove(harness, path, bundle)
    results = json.loads((bundle / "results.json").read_text(encoding="utf-8"))
    return bundle, results


def _rewrite_index(bundle: Path, mutate) -> None:
    index = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    mutate(index)
    (bundle / "manifest.json").write_text(json.dumps(index, indent=2), encoding="utf-8")


def _rewrite_results(bundle: Path, mutate) -> None:
    results = json.loads((bundle / "results.json").read_text(encoding="utf-8"))
    mutate(results)
    (bundle / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")


def test_verify_names_a_missing_or_malformed_index(harness, tmp_path: Path) -> None:
    bundle, _results = _shipped_bundle(harness, tmp_path)
    (bundle / "manifest.json").unlink()
    assert any("missing manifest.json" in p for p in harness.verify_bundle(bundle))

    (bundle / "manifest.json").write_text("{broken", encoding="utf-8")
    assert any("not valid JSON" in p for p in harness.verify_bundle(bundle))

    (bundle / "manifest.json").write_text(json.dumps({"schema": 99}), encoding="utf-8")
    assert any("unsupported schema" in p for p in harness.verify_bundle(bundle))

    (bundle / "manifest.json").write_text(json.dumps({"schema": 1}), encoding="utf-8")
    assert any("no files map" in p for p in harness.verify_bundle(bundle))


def test_verify_enforces_the_index_file_map(harness, tmp_path: Path) -> None:
    bundle, _results = _shipped_bundle(harness, tmp_path)

    _rewrite_index(bundle, lambda index: index["files"].pop("restart.json"))
    assert any("does not list required file" in p for p in harness.verify_bundle(bundle))

    _rewrite_index(bundle, lambda index: index["files"].update({"manifest.json": "sha256:x"}))
    assert any("excluded file" in p for p in harness.verify_bundle(bundle))

    _rewrite_index(bundle, lambda index: index["files"].pop("manifest.json"))
    _rewrite_index(bundle, lambda index: index["files"].update({"restart.json": "sha256:x"}))
    (bundle / "restart.json").unlink()
    assert any("restart.json" in p and "is missing" in p for p in harness.verify_bundle(bundle))


def test_verify_refuses_a_results_file_it_cannot_read_or_trust(harness, tmp_path: Path) -> None:
    bundle, _results = _shipped_bundle(harness, tmp_path)

    (bundle / "results.json").write_text("{broken", encoding="utf-8")
    assert any("results.json unreadable" in p for p in harness.verify_bundle(bundle))

    (bundle / "results.json").write_text(json.dumps({"schema": 99}), encoding="utf-8")
    assert any("unsupported schema" in p for p in harness.verify_bundle(bundle))

    (bundle / "results.json").write_text(
        json.dumps({"schema": 1, "scenarios": []}), encoding="utf-8"
    )
    assert any("must be exactly" in p for p in harness.verify_bundle(bundle))


def test_verify_scores_each_scenario_entry_shape(harness, tmp_path: Path) -> None:
    bundle, _results = _shipped_bundle(harness, tmp_path)

    def not_an_object(candidate: dict[str, Any]) -> None:
        candidate["scenarios"]["EXECUTE"] = "pass-shaped text"

    _rewrite_results(bundle, not_an_object)
    _rehash_bundle(harness, bundle)
    assert any("scenario entry must be an object" in p for p in harness.verify_bundle(bundle))

    _rewrite_results(
        bundle,
        lambda candidate: candidate["scenarios"].update(
            {"EXECUTE": {"outcome": "PASSISH", "subchecks": [], "evidence": []}}
        ),
    )
    _rehash_bundle(harness, bundle)
    assert any("invalid outcome" in p for p in harness.verify_bundle(bundle))

    _rewrite_results(
        bundle,
        lambda candidate: candidate["scenarios"].update(
            {
                "EXECUTE": {
                    "outcome": harness.PASS,
                    "subchecks": ["not-an-object"],
                    "evidence": [],
                }
            }
        ),
    )
    _rehash_bundle(harness, bundle)
    assert any("subcheck must be an object" in p for p in harness.verify_bundle(bundle))

    _rewrite_results(
        bundle,
        lambda candidate: candidate["scenarios"].update(
            {
                "EXECUTE": {
                    "outcome": harness.PASS,
                    "subchecks": [{"name": "X", "outcome": "MAYBE", "evidence": []}],
                    "evidence": [],
                }
            }
        ),
    )
    _rehash_bundle(harness, bundle)
    problems = harness.verify_bundle(bundle)
    assert any("EXECUTE/X: invalid outcome" in p for p in problems)


def test_verify_restricts_not_applicable_to_reviewed_headless_browser_login(
    harness, tmp_path: Path
) -> None:
    bundle, _results = _shipped_bundle(harness, tmp_path)

    def smuggle(candidate: dict[str, Any]) -> None:
        candidate["scenarios"]["INSTALL"]["subchecks"].append(
            {"name": "WORKSPACE", "outcome": harness.NOT_APPLICABLE, "evidence": []}
        )

    _rewrite_results(bundle, smuggle)
    _rehash_bundle(harness, bundle)
    assert any(
        "NOT_APPLICABLE is only valid for BROWSER_LOGIN" in p for p in harness.verify_bundle(bundle)
    )


def test_verify_requires_evidence_references_to_name_listed_payloads(
    harness, tmp_path: Path
) -> None:
    bundle, _results = _shipped_bundle(harness, tmp_path)

    _rewrite_results(
        bundle,
        lambda candidate: candidate["scenarios"]["EXECUTE"].update(
            {"evidence": [1234, "side-channel.txt"]}
        ),
    )
    _rehash_bundle(harness, bundle)
    problems = harness.verify_bundle(bundle)
    assert any("evidence reference must be a string" in p for p in problems)
    assert any("names an unlisted file" in p for p in problems)


def test_verify_requires_the_junit_report_to_name_exactly_the_families(
    harness, tmp_path: Path
) -> None:
    bundle, _results = _shipped_bundle(harness, tmp_path)

    junit = (bundle / "junit.xml").read_text(encoding="utf-8")
    (bundle / "junit.xml").write_text(junit.replace("RESTART", "EXTRA"), encoding="utf-8")
    _rehash_bundle(harness, bundle)
    problems = harness.verify_bundle(bundle)
    assert any("junit.xml testcases" in p for p in problems)

    (bundle / "junit.xml").write_text("<broken", encoding="utf-8")
    assert any("junit.xml unreadable" in p for p in harness.verify_bundle(bundle))


def _rehash_bundle(harness, bundle: Path) -> None:
    """Recompute the index hashes so a mutation's own problem is scorable."""
    index = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    files = {
        name: f"sha256:{harness._sha256_bytes((bundle / name).read_bytes())}"
        for name in index["files"]
        if name != "results.json" or (bundle / "results.json").exists()
    }
    index["files"] = files
    index["bundle_digest"] = harness._canonical_digest(files)
    (bundle / "manifest.json").write_text(json.dumps(index, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI surface, driven in-process so the dispatch itself is the thing under test
# ---------------------------------------------------------------------------


def test_the_cli_validates_a_manifest_without_running_anything(
    harness, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = build_manifest(tmp_path)
    path = write_manifest(tmp_path, manifest)
    assert harness.main(["--validate-manifest", "--manifest", str(path)]) == harness.EXIT_OK
    assert "structurally valid" in capsys.readouterr().out


def test_the_cli_verify_mode_reports_each_bundle_verdict(
    harness, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bundle, _results = _shipped_bundle(harness, tmp_path)
    assert harness.main(["--verify", str(bundle)]) == harness.EXIT_OK
    assert "structurally valid" in capsys.readouterr().out

    (bundle / "execution.json").write_text('{"tampered": true}\n', encoding="utf-8")
    assert harness.main(["--verify", str(bundle)]) == harness.EXIT_EVIDENCE
    assert "hash mismatch" in capsys.readouterr().err

    assert harness.main(["--verify", str(tmp_path / "absent-bundle")]) == harness.EXIT_MISUSE
    assert "does not exist" in capsys.readouterr().err


def test_the_cli_requires_its_mode_arguments(harness, tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as misuse:
        harness.main(["--validate-manifest"])
    assert misuse.value.code == 2


def test_a_bundle_that_fails_self_verification_never_exits_zero(
    harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """The closeout records the verification failure; the run does not pass."""
    manifest = build_manifest(tmp_path)
    path = write_manifest(tmp_path, manifest)
    output = tmp_path / "bundle"
    problem = "injected: index does not match the bundle"

    monkeypatch.setattr(
        harness,
        "verify_bundle",
        lambda _bundle: [problem],  # first and final check
    )
    exit_code = prove(harness, path, output)
    assert exit_code == harness.EXIT_EVIDENCE
    assert problem in capsys.readouterr().err
    results = json.loads((output / "results.json").read_text(encoding="utf-8"))
    assert results["closeout"]["bundle_verified"] is False


def test_a_first_check_failure_is_rewritten_before_the_final_verdict(
    harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """First check fails, final check passes: the bundle is re-hashed and honest."""
    manifest = build_manifest(tmp_path)
    path = write_manifest(tmp_path, manifest)
    output = tmp_path / "bundle"
    problem = "injected: transient verification failure"
    responses = iter([[problem], []])
    monkeypatch.setattr(harness, "verify_bundle", lambda _bundle: next(responses))
    exit_code = prove(harness, path, output)
    assert exit_code == harness.EXIT_EVIDENCE
    results = json.loads((output / "results.json").read_text(encoding="utf-8"))
    # The closeout keeps the recorded failure; the closeout is evidence, not
    # something the harness overwrites after the fact.
    assert results["closeout"]["bundle_verified"] is False
    # The rewritten index itself verifies cleanly with the real verifier.
    monkeypatch.undo()
    assert harness.verify_bundle(output) == []


def test_a_reference_manifest_is_reproducible_from_the_shipped_builder() -> None:
    """The fixture builder must not drift from the schema's required shape."""
    reference = build_manifest(Path("/tmp"))
    assert reference["schema"] == 1
    assert set(reference["scenarios"]) == {
        "install",
        "execute",
        "restart",
        "isolate",
        "fail_closed",
    }
    assert len(reference["scenarios"]["isolate"]["probes"]) >= 4
    assert {case["name"] for case in reference["scenarios"]["fail_closed"]["cases"]} == set(
        MANDATORY_CASES
    )
    assert copy.deepcopy(reference) == reference
