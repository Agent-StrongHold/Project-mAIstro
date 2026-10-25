"""Build a structured install plan (JSON-serializable) from validated answers."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import yaml

from maistro_bootstrap.platform_detect import deployment_tier_gate_message, environment_report
from maistro_bootstrap.repo_root import find_maistro_engine_root
from maistro_bootstrap.resolver import (
    commands_for,
    commands_for_compose_addons_run_podman,
    commands_for_compose_addons_validate,
    copier_command,
    podman_install_preface_lines,
    should_print_podman_preface,
)
from maistro_bootstrap.schema import InstallAnswersV1

DEFAULT_CURL_INSTALL_URL = (
    "https://gist.githubusercontent.com/maistro-ai/maistro-install/main/install.sh"
)


def effective_runtime(answers: InstallAnswersV1) -> str:
    if answers.container_runtime != "auto":
        return answers.container_runtime
    if answers.deployment_tier == "local_podman":
        return "podman"
    return "docker"


def _stub_preview_lines(answers: InstallAnswersV1) -> list[str]:
    manifest = Path(__file__).resolve().parent / "stub_manifest.yaml"
    if not manifest.is_file():
        return []
    data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
    fp = data.get("feature_preview") or {}
    ca = data.get("compose_addons") or {}
    out: list[str] = []
    for f in answers.features:
        if f in fp:
            out.append(str(fp[f]))
    for a in answers.compose_addons:
        if a in ca:
            out.append(str(ca[a]))
    return out


def _preview_for_observability(answers: InstallAnswersV1) -> list[str]:
    notes: list[str] = []
    ob = answers.observability_backend
    if ob == "arize":
        notes.append(
            "observability=arize: [preview] Root compose ships Langfuse today, not Arize; "
            "add a compose fragment or product override when ready."
        )
    elif ob in ("langfuse_v2", "langfuse_v3"):
        notes.append(
            f"observability={ob}: [preview] Stack includes `langfuse` service; "
            "image major version pinning is a separate compose change."
        )
    return notes


def _preview_for_gateway(answers: InstallAnswersV1) -> list[str]:
    if answers.llm_gateway == "other":
        return [
            "llm_gateway=other: [preview] No alternate gateway merged in Tier 0; "
            "use direct SDK calls or add a compose profile later."
        ]
    return []


def _compose_profile_hints(answers: InstallAnswersV1) -> list[str]:
    """Stub-phase lines until root compose uses profiles (see compose-slices.example.yml)."""
    lines = [
        "# Compose profile stub (root docker-compose.yml is always-on today):",
        "# When profiles land: COMPOSE_PROFILES=llm,observability docker compose up -d",
        "# See docs/install/compose-slices.example.yml",
    ]
    if "llm_proxy" in answers.features:
        lines.append("# [preview] feature llm_proxy → future profile `llm` toggles LiteLLM slice.")
    if "observability" in answers.features:
        lines.append(
            "# [preview] feature observability → future profile `observability` toggles Langfuse slice."
        )
    return lines


def _safety_notes(answers: InstallAnswersV1) -> list[str]:
    notes: list[str] = []
    if answers.install_surface == "curl":
        notes.append(
            "install_surface=curl: fetcher should only identify the environment, verify prerequisites, "
            "then run the pinned maistro-install payload; keep secrets out of shell history."
        )
    if answers.delivery_mode == "image_pull":
        notes.append(
            "delivery_mode=image_pull: default fast path pulls signed/pinned images and passes the same "
            "answers as runtime parameters."
        )
    else:
        notes.append(
            "delivery_mode=source_build: pulls source and builds locally with the same answers; expected "
            "runtime behavior should match image_pull, but install takes longer."
        )
    if answers.sandbox_profile == "safe":
        notes.append(
            "sandbox_profile=safe: default denies docker.sock mounts and host-privileged containers; "
            "use explicit warnings before enabling broader agent execution."
        )
    else:
        notes.append(
            "sandbox_profile=developer: allows local iteration while retaining installer security posture: "
            "no privileged containers, no docker.sock, no-new-privileges, and dropped capabilities. "
            "Build from source if you need unsupported options."
        )
    if answers.crypto_profile == "distributed_identity_root":
        notes.append(
            "crypto_profile=distributed_identity_root: default installs a distributed identity/trust root "
            "for agent specs, audit logs, approvals, and federation; wallet/spending plugins stay disabled."
        )
    elif answers.crypto_profile == "no_crypto":
        notes.append(
            "crypto_profile=no_crypto: removes the distributed identity root and crypto-backed signing; "
            "use only for offline demos or environments that provide identity externally."
        )
    else:
        notes.append(
            "crypto_profile=full_all_crypto: enables the full crypto intent surface for downstream "
            "installers, including DID/VC and wallet-capable components with explicit policy gates."
        )
    return notes


def _generated_artifacts(answers: InstallAnswersV1) -> dict[str, Any]:
    users = [answers.admin_user, answers.daily_driver_user, *answers.additional_users]
    compose = {
        "services": {
            "maistro-reactor": {
                # Profiles-gated: never starts unless COMPOSE_PROFILES=reactor is
                # set explicitly. The image reference makes the override pass
                # `docker compose config` when merged with the root compose file;
                # the real reactor image is published by the release workflow
                # (SPEC-072726-3439 Phase 5).
                "image": "ghcr.io/agent-stronghold/maistro-engine:reactor-preview",
                "profiles": ["reactor"],
                "environment": {
                    "MAISTRO_DELIVERY_MODE": answers.delivery_mode,
                    "MAISTRO_SANDBOX_PROFILE": answers.sandbox_profile,
                    "MAISTRO_CRYPTO_PROFILE": answers.crypto_profile,
                    "MAISTRO_FIRST_AGENTS": ",".join(answers.first_agents),
                },
                "security_opt": ["no-new-privileges:true"],
                "cap_drop": ["ALL"],
                "pids_limit": 512,
                "tmpfs": ["/tmp:rw,noexec,nosuid,size=256m"],
                "read_only": answers.sandbox_profile == "safe",
            }
        }
    }
    return {
        "curl_entrypoint_url": DEFAULT_CURL_INSTALL_URL,
        "curl_entrypoint": f"curl -fsSL {DEFAULT_CURL_INSTALL_URL} | bash -s -- --answers-file install-answers.yaml",
        "install_script_phases": [
            "preflight: detect OS/arch, admin ability, Docker/Podman, Hyper-V/WSL, KVM, LXC/VM hints",
            "answers: walk operator through safe defaults and warnings for incompatible choices",
            "render: write answers, compose override, sandbox policy, users, first agents, tutorial todo",
            "apply: install prerequisites only with confirmation, build/pull selected compose, start reactor",
        ],
        "compose_override_preview": compose,
        "bootstrap_users": users,
        "delivery": {
            "mode": answers.delivery_mode,
            "behavior_contract": "image_pull and source_build consume the same answers and runtime parameters",
            "expected_difference": "source_build takes longer; image_pull is faster",
            "source": {
                "enabled": answers.delivery_mode == "source_build",
                "commands": ["git clone <maistro-engine-url>", "uv sync --extra bootstrap"],
            },
            "images": {
                "enabled": answers.delivery_mode == "image_pull",
                "parameters": answers.model_dump(mode="json"),
            },
        },
        "sandbox_policy": {
            "profile": answers.sandbox_profile,
            "host_privileged": False,
            "docker_socket_mount": False,
            "no_new_privileges": True,
            "capabilities_dropped": "ALL",
        },
        "unsupported_options": {
            "installer_policy": "unsupported options are intentionally omitted from the installer",
            "handoff": "build from source for unsupported host-privileged or experimental options",
        },
        "identity_root": {
            "default": answers.crypto_profile == "distributed_identity_root",
            "profile": answers.crypto_profile,
            "materialize": answers.crypto_profile != "no_crypto",
        },
        "reactor": {"enabled": answers.reactor_enabled, "first_agents": answers.first_agents},
        "tutorial_todo": [
            f"Confirm admin profile for {answers.admin_user} and store recovery codes",
            f"Complete daily-driver onboarding for {answers.daily_driver_user}",
            "Choose provider accounts and add API keys through the secrets UI/env, not answers YAML",
            "Run first safe sandbox task, review audit log, then unlock developer profile if needed",
            "Record enough setup decisions to level up admin and user profiles from tutorial to operator",
        ],
    }


def build_install_plan(
    answers: InstallAnswersV1,
    *,
    repo_root: Path | None = None,
    copier_dest: str = "../my-product",
) -> dict[str, Any]:
    """Single JSON shape for CLI `--json` and Hive `POST /v1/install/plan`."""
    rr = repo_root if repo_root is not None else find_maistro_engine_root()
    features = set(answers.features)
    compose_addons = set(answers.compose_addons)

    shell_lines: list[str] = ["# === maistro-install plan (default: print only) ==="]
    shell_lines.extend(commands_for(features))
    shell_lines.extend(commands_for_compose_addons_validate(compose_addons))
    if should_print_podman_preface(compose_addons):
        shell_lines.extend([*podman_install_preface_lines(), ""])
    shell_lines.extend(commands_for_compose_addons_run_podman(compose_addons))

    preview_notes = [
        *_safety_notes(answers),
        *_stub_preview_lines(answers),
        *_preview_for_observability(answers),
        *_preview_for_gateway(answers),
    ]
    if answers.stack_bringup == "root_full" and rr is None:
        preview_notes.append(
            "stack_bringup=root_full: [preview] Repo root not found — set MAISTRO_REPO_ROOT "
            "or run from inside maistro-engine; apply will not run."
        )
    elif answers.stack_bringup == "root_full" and rr is not None:
        preview_notes.append(
            "stack_bringup=root_full: --apply runs `compose build --pull never` (images with "
            "`build:` only; no `up` / no pulls for compose `image:` services). "
            "When ready, run `docker compose up -d` (or podman) yourself to start dependencies."
        )

    gate = deployment_tier_gate_message(answers.deployment_tier)
    if gate:
        preview_notes.append(gate)

    for n in preview_notes:
        shell_lines.append(f"# {n}")

    apply_spec: dict[str, Any] | None = None
    if answers.stack_bringup == "root_full" and rr is not None:
        rt = effective_runtime(answers)
        binary = "podman" if rt == "podman" else "docker"
        apply_spec = {
            "cwd": str(rr),
            "argv": [binary, "compose", "build", "--pull", "never"],
            "description": (
                f"Build compose images with a Dockerfile from {rr} ({binary}); "
                "does not start containers or pull `image:`-only services"
            ),
        }

    copier_line: str | None = None
    if answers.product:
        copier_line = copier_command(answers.product, copier_dest)

    return {
        "kind": "maistro_install_plan",
        "plan_version": 1,
        "answers": answers.model_dump(mode="json"),
        "repo_root": str(rr) if rr else None,
        "shell_commands": shell_lines,
        "compose_profile_hints": _compose_profile_hints(answers),
        "preview_notes": preview_notes,
        "apply_spec": apply_spec,
        "copier_command": copier_line,
        "environment": environment_report(),
        "generated_artifacts": _generated_artifacts(answers),
    }


def shell_script_from_plan(plan: dict[str, Any]) -> str:
    """Flatten shell_commands for human copy-paste."""
    return "\n".join(plan.get("shell_commands", [])) + "\n"


def run_apply_spec(spec: dict[str, Any]) -> int:
    """Run compose build argv with cwd (no shell). Returns process exit code."""
    argv = [str(x) for x in spec["argv"]]
    cwd = str(spec["cwd"])
    proc = subprocess.run(list(argv), cwd=cwd, check=False)
    return int(proc.returncode)
