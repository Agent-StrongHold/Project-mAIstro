"""Golden-style tests for install plan builder (no Docker required)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from maistro_bootstrap.materialize import materialize_install_artifacts
from maistro_bootstrap.plan import DEFAULT_CURL_INSTALL_URL, build_install_plan
from maistro_bootstrap.schema import parse_answers_dict


def test_plan_includes_compose_profile_hints() -> None:
    raw = {
        "schema_version": "1",
        "features": ["llm_proxy", "observability"],
        "stack_bringup": "none",
    }
    answers = parse_answers_dict(raw)
    plan = build_install_plan(answers, repo_root=Path("/tmp/x"))
    hints = plan.get("compose_profile_hints", [])
    assert any("llm_proxy" in h for h in hints)
    assert any("observability" in h for h in hints)


@pytest.mark.ac("SPEC-180/AC-1")
def test_golden_plan_shape() -> None:
    raw = {
        "schema_version": "1",
        "features": ["core_lib"],
        "stack_bringup": "none",
        "deployment_tier": "proxmox",
    }
    plan = build_install_plan(parse_answers_dict(raw), repo_root=None)
    assert plan["kind"] == "maistro_install_plan"
    assert "compose_profile_hints" in plan
    assert any("Proxmox" in n for n in plan["preview_notes"])


def test_plan_includes_uv_sync_for_core_lib() -> None:
    raw = {
        "schema_version": "1",
        "features": ["core_lib"],
        "stack_bringup": "none",
    }
    answers = parse_answers_dict(raw)
    plan = build_install_plan(answers, repo_root=Path("/tmp/fake-root"))
    lines = "\n".join(plan["shell_commands"])
    assert "uv sync" in lines


def test_plan_uses_updateable_root_copier_dispatcher() -> None:
    answers = parse_answers_dict(
        {
            "schema_version": "1",
            "product": "autonoetic",
            "stack_bringup": "none",
        }
    )

    plan = build_install_plan(
        answers,
        repo_root=Path("/tmp/maistro-root"),
        copier_dest="../my product",
    )

    assert plan["copier_command"] == (
        "uv run copier copy --data product_template=autonoetic "
        "https://github.com/Agent-StrongHold/Project-mAIstro.git '../my product'"
    )


def test_apply_spec_when_root_full_and_repo_root() -> None:
    raw = {
        "schema_version": "1",
        "features": [],
        "stack_bringup": "root_full",
        "container_runtime": "docker",
    }
    answers = parse_answers_dict(raw)
    fake = Path("/tmp/maistro-fake-root")
    plan = build_install_plan(answers, repo_root=fake)
    spec = plan["apply_spec"]
    assert spec is not None
    assert spec["cwd"] == str(fake)
    assert spec["argv"] == ["docker", "compose", "build", "--pull", "never"]


def test_apply_spec_podman_runtime() -> None:
    raw = {
        "schema_version": "1",
        "features": [],
        "stack_bringup": "root_full",
        "container_runtime": "podman",
    }
    answers = parse_answers_dict(raw)
    plan = build_install_plan(answers, repo_root=Path("/tmp/x"))
    assert plan["apply_spec"]["argv"][0] == "podman"


def test_stub_manifest_preview_for_llm_proxy() -> None:
    raw = {
        "schema_version": "1",
        "features": ["llm_proxy"],
        "stack_bringup": "none",
    }
    answers = parse_answers_dict(raw)
    plan = build_install_plan(answers, repo_root=None)
    joined = " ".join(plan["preview_notes"])
    assert "litellm" in joined.lower() or "preview" in joined.lower()


def test_golden_plan_root_full_without_repo_root_has_no_apply_spec(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("maistro_bootstrap.plan.find_maistro_engine_root", lambda: None)
    plan = build_install_plan(
        parse_answers_dict({"schema_version": "1", "stack_bringup": "root_full"})
    )

    assert plan["repo_root"] is None
    assert plan["apply_spec"] is None
    missing_root_note = (
        "stack_bringup=root_full: [preview] Repo root not found — set MAISTRO_REPO_ROOT "
        "or run from inside maistro-engine; apply will not run."
    )
    assert plan["shell_commands"][0] == "# === maistro-install plan (default: print only) ==="
    assert f"# {missing_root_note}" in plan["shell_commands"]
    assert missing_root_note in plan["preview_notes"]


def test_golden_plan_observability_and_gateway_preview_notes() -> None:
    plan = build_install_plan(
        parse_answers_dict(
            {
                "schema_version": "1",
                "features": ["observability"],
                "llm_gateway": "other",
                "observability_backend": "langfuse_v3",
                "stack_bringup": "none",
            }
        ),
        repo_root=Path("/tmp/maistro-root"),
    )

    assert [
        note for note in plan["preview_notes"] if "langfuse" in note or "llm_gateway=other" in note
    ] == [
        "[preview] Root compose includes `langfuse`; choosing Arize or Langfuse v2/v3 in answers "
        "is a manifest hint until matching services are added to compose.",
        "observability=langfuse_v3: [preview] Stack includes `langfuse` service; "
        "image major version pinning is a separate compose change.",
        "llm_gateway=other: [preview] No alternate gateway merged in Tier 0; "
        "use direct SDK calls or add a compose profile later.",
    ]
    assert plan["compose_profile_hints"] == [
        "# Compose profile stub (root docker-compose.yml is always-on today):",
        "# When profiles land: COMPOSE_PROFILES=llm,observability docker compose up -d",
        "# See docs/install/compose-slices.example.yml",
        "# [preview] feature observability → future profile `observability` toggles Langfuse slice.",
    ]


def test_plan_includes_environment_and_generated_artifacts() -> None:
    raw = {
        "schema_version": "1",
        "sandbox_profile": "safe",
        "admin_user": "root-admin",
        "daily_driver_user": "alice",
        "additional_users": ["bob"],
        "first_agents": ["guide", "builder"],
        "delivery_mode": "image_pull",
        "crypto_profile": "distributed_identity_root",
    }
    plan = build_install_plan(parse_answers_dict(raw), repo_root=Path("/tmp/x"))
    assert "admin_available" in plan["environment"]
    artifacts = plan["generated_artifacts"]
    assert artifacts["bootstrap_users"] == ["root-admin", "alice", "bob"]
    assert artifacts["curl_entrypoint_url"] == DEFAULT_CURL_INSTALL_URL
    assert "gist.githubusercontent.com" in artifacts["curl_entrypoint"]
    assert artifacts["reactor"]["first_agents"] == ["guide", "builder"]
    assert artifacts["delivery"]["mode"] == "image_pull"
    assert artifacts["delivery"]["images"]["enabled"] is True
    assert artifacts["identity_root"]["default"] is True
    assert artifacts["identity_root"]["materialize"] is True
    assert "build from source" in artifacts["unsupported_options"]["handoff"]
    assert artifacts["sandbox_policy"]["docker_socket_mount"] is False
    service = artifacts["compose_override_preview"]["services"]["maistro-reactor"]
    assert service["read_only"] is True
    assert service["cap_drop"] == ["ALL"]
    # A service with neither image: nor build: fails `docker compose config`
    # when the override is merged by install.sh.
    assert "image" in service or "build" in service
    assert service["profiles"] == ["reactor"]
    assert any("sandbox_profile=safe" in note for note in plan["preview_notes"])


def test_developer_sandbox_points_unsupported_options_to_source_build() -> None:
    raw = {"schema_version": "1", "sandbox_profile": "developer"}
    plan = build_install_plan(parse_answers_dict(raw), repo_root=Path("/tmp/x"))
    assert any("no privileged containers" in note for note in plan["preview_notes"])
    artifacts = plan["generated_artifacts"]
    assert artifacts["sandbox_policy"]["host_privileged"] is False
    assert artifacts["sandbox_policy"]["docker_socket_mount"] is False
    service = artifacts["compose_override_preview"]["services"]["maistro-reactor"]
    assert service["security_opt"] == ["no-new-privileges:true"]
    assert service["cap_drop"] == ["ALL"]


def test_unsafe_host_profile_is_rejected_by_schema() -> None:
    raw = {"schema_version": "1", "sandbox_profile": "unsafe_host"}
    with pytest.raises(ValueError):
        parse_answers_dict(raw)


def test_no_crypto_profile_removes_identity_root_materialization() -> None:
    raw = {"schema_version": "1", "crypto_profile": "no_crypto"}
    plan = build_install_plan(parse_answers_dict(raw), repo_root=Path("/tmp/x"))
    identity_root = plan["generated_artifacts"]["identity_root"]
    assert identity_root["default"] is False
    assert identity_root["materialize"] is False
    assert any("crypto_profile=no_crypto" in note for note in plan["preview_notes"])


def test_full_all_crypto_profile_is_explicit() -> None:
    raw = {"schema_version": "1", "crypto_profile": "full_all_crypto"}
    plan = build_install_plan(parse_answers_dict(raw), repo_root=Path("/tmp/x"))
    assert plan["generated_artifacts"]["identity_root"]["profile"] == "full_all_crypto"
    assert any("full_all_crypto" in note for note in plan["preview_notes"])


def test_materialize_install_artifacts_writes_reviewable_files(tmp_path: Path) -> None:
    raw = {
        "schema_version": "1",
        "admin_user": "admin",
        "daily_driver_user": "driver",
        "first_agents": ["guide"],
    }
    plan = build_install_plan(parse_answers_dict(raw), repo_root=Path("/tmp/x"))

    written = materialize_install_artifacts(plan, tmp_path)

    names = {path.name for path in written}
    assert "install-plan.json" in names
    assert "install-answers.yaml" in names
    assert "compose.override.yml" in names
    assert "sandbox-policy.json" in names
    assert "bootstrap-users.json" in names
    assert "first-agents.json" in names
    assert "delivery.json" in names
    assert "identity-root.json" in names
    assert "unsupported-options.json" in names
    assert "tutorial-todo.md" in names
    assert "install.sh" in names
    assert "install.ps1" in names
    assert "driver" in (tmp_path / "bootstrap-users.json").read_text(encoding="utf-8")
    assert "image_pull" in (tmp_path / "delivery.json").read_text(encoding="utf-8")
    assert "MAISTRO_CRYPTO_PROFILE" in (tmp_path / "compose.override.yml").read_text(
        encoding="utf-8"
    )
    assert "Maistro first-run setup" in (tmp_path / "tutorial-todo.md").read_text(encoding="utf-8")
    assert "Set-Location $PSScriptRoot" in (tmp_path / "install.ps1").read_text(encoding="utf-8")
    if os.name != "nt":
        assert (tmp_path / "install.sh").stat().st_mode & 0o100


def test_source_build_delivery_has_same_behavior_contract() -> None:
    raw = {"schema_version": "1", "delivery_mode": "source_build"}
    plan = build_install_plan(parse_answers_dict(raw), repo_root=Path("/tmp/x"))
    delivery = plan["generated_artifacts"]["delivery"]
    assert delivery["mode"] == "source_build"
    assert delivery["source"]["enabled"] is True
    assert delivery["images"]["enabled"] is False
    assert "same answers" in delivery["behavior_contract"]
    assert any("takes longer" in note for note in plan["preview_notes"])
    service = plan["generated_artifacts"]["compose_override_preview"]["services"]["maistro-reactor"]
    assert service["environment"]["MAISTRO_DELIVERY_MODE"] == "source_build"
