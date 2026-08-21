# Default Installer Context Dump

Purpose: hand this single file to another agent/human to continue the default installer work without needing prior chat history.

## User intent

Build a default installer that can eventually take a bare machine with no Python, Docker/Podman, Hyper-V/WSL/KVM readiness, or project checkout and end with a working Hive Conductor chat that can create an agent DAG autonomously.

Important product constraints from the conversation:

- The installer must be curl-first for normal users.
- The temporary curl URL should be a GitHub Gist raw URL for now, with a single constant to swap later when the production domain exists.
- Users must be able to choose either pulling signed/pinned images or pulling source and building locally; this should only affect install time, not runtime behavior.
- Unsafe/host-privileged options are not supported by the installer. If someone needs unsupported options, they can build from source.
- The developer profile must still satisfy the installer security posture: no privileged containers, no docker.sock mount, no-new-privileges, and dropped capabilities.
- The default crypto/identity posture is `distributed_identity_root`.
- `no_crypto` should remove identity-root materialization.
- `full_all_crypto` should be explicit and policy-gated downstream.
- Secrets must not be written into answers YAML.
- Do not create PRs for answer-only turns; only create PR metadata when code changes require it by repo automation.

## Current implementation state

The latest commit on this branch is the installer-plan/materialization/preflight/schema/wizard update. It does not make the installer fully end-to-end yet. It currently:

- Adds installer answer schema fields for install surface, delivery mode, sandbox profile, crypto profile, bootstrap users, first agents, and provider account intent.
- Adds preflight environment reporting for OS/distro/arch, admin availability, Docker/Podman probes, KVM, and Hyper-V/WSL hints.
- Adds generated artifacts to the resolved install plan.
- Adds local artifact materialization via `maistro-install --materialize-dir`.
- Adds a wizard flow for delivery mode, sandbox profile, crypto profile, and user names.
- Adds docs for what remains.

## What remains to get to a working bare-machine installer

Implement in this order:

1. Native no-Python bootstrap scripts:
   - POSIX shell for Linux/macOS.
   - PowerShell for Windows.
   - Detect OS/arch and unsupported platforms.
   - Install or locate `uv`.
   - Download a pinned installer payload.
   - Verify checksum/signature before execution.
2. Runtime and privilege setup:
   - Detect elevation/admin ability before mutation.
   - Linux: install/guide Docker Engine or Podman.
   - Windows: guide/install Docker Desktop plus WSL2/Hyper-V readiness.
   - macOS: guide/install Docker Desktop/Colima-compatible runtime.
   - Verify daemon health before compose actions.
3. Delivery paths:
   - `image_pull`: pull pinned/signed images and pass generated parameters.
   - `source_build`: clone pinned source revision, build locally, pass the same parameters.
   - Keep user-visible runtime behavior equivalent except for install duration.
4. Secure config and identity:
   - Collect provider/API secrets only via secure prompt/env/secrets file, never answers YAML.
   - Implement default distributed identity root materializer.
   - Ensure `no_crypto` skips identity root.
   - Keep `full_all_crypto` explicit and downstream policy gated.
5. Runtime wiring:
   - Wire admin user, daily-driver user, additional users, first agents, and reactor settings into core/server bootstrap APIs.
6. Stack startup:
   - Generate final compose files.
   - Start Postgres/LiteLLM/Langfuse/Hive Conductor/reactor.
   - Run migrations.
   - Wait for health checks.
   - Print/write status, logs, restart, backup, rollback, teardown commands.
7. Hive Conductor smoke test:
   - Print/open Hive Conductor URL.
   - Verify session/login/chat backend.
   - Run a smoke prompt that creates and completes a small autonomous agent DAG.
8. Persist tutorial/setup progress:
   - Track admin and daily-driver setup decisions.
   - Level profiles only after required decisions are complete.

## Commands used for this context dump

```bash
git show --stat --patch --find-renames --find-copies --binary HEAD
```

## Full diff of latest installer commit

commit 6fef583153adce47776cccc78899fb416145e103
Author: Codex <codex@openai.com>
Date:   Sun Jun 28 15:39:38 2026 +0000

    Add installer plan materialization, preflight environment report, schema and wizard updates
    
    ### Motivation
    
    - Model the curl-first default installer as a safe, inspectable plan and expose materialized artifacts for downstream fetchers and operators.
    - Provide a best-effort preflight `environment` report so the interactive wizard and remote fetcher can make informed safe-default decisions without mutating the host.
    - Add explicit safe defaults and schema fields to capture installer delivery, sandbox, and crypto intents so generated plans are actionable and reviewable.
    
    ### Description
    
    - Add `docs/install/default-installer.md` documenting the default installer flow, safe defaults, generated artifacts, and rollout checklist.
    - Introduce `materialize_install_artifacts` in `materialize.py` and wire a `--materialize-dir` CLI option in `cli.py` to write reviewable install artifacts without starting services.
    - Extend `plan.py` to include `environment` from `platform_detect.environment_report`, a `generated_artifacts` structure, and a `DEFAULT_CURL_INSTALL_URL` plus curl entrypoint text and delivery/sandbox/identity intents.
    - Enhance `platform_detect.py` with robust runtime probes (`_run_probe`), `environment_report`, and use `shutil.which` in `has_command`.
    - Expand the answers schema in `schema.py` with `install_surface`, `delivery_mode`, `sandbox_profile`, `crypto_profile`, user and agent fields, and additional validators.
    - Update the interactive wizard in `wizard.py` to show the preflight environment and prompt for the new fields (`delivery_mode`, `sandbox`, `crypto_profile`, admin/daily user names), while keeping safe defaults.
    - Add tests and a new test to exercise plan shape, generated artifacts, and the `materialize_install_artifacts` writer in `tests/test_plan.py`.
    
    ### Testing
    
    - Ran the package test file with `pytest packages/maistro-bootstrap/tests/test_plan.py` and all tests passed.
    - Unit tests verify plan contains `environment` and `generated_artifacts`, validate schema rejections (e.g. `unsafe_host`), and confirm `materialize_install_artifacts` writes the expected reviewable files and sets the entrypoint executable bit.
---
 docs/install/default-installer.md                  |  69 +++++++++++
 .../maistro-bootstrap/src/maistro_bootstrap/cli.py |  16 +++
 .../src/maistro_bootstrap/materialize.py           |  85 ++++++++++++++
 .../src/maistro_bootstrap/plan.py                  | 126 ++++++++++++++++++++-
 .../src/maistro_bootstrap/platform_detect.py       |  63 ++++++++++-
 .../src/maistro_bootstrap/schema.py                |  17 ++-
 .../src/maistro_bootstrap/wizard.py                |  29 ++++-
 packages/maistro-bootstrap/tests/test_plan.py      | 112 +++++++++++++++++-
 8 files changed, 507 insertions(+), 10 deletions(-)

diff --git a/docs/install/default-installer.md b/docs/install/default-installer.md
new file mode 100644
index 0000000..9aebc61
--- /dev/null
+++ b/docs/install/default-installer.md
@@ -0,0 +1,69 @@
+# Default installer flow
+
+`maistro-install` now models the curl-first default installer as a safe, functional plan rather than an opaque shell script. The intended remote entrypoint is a small fetcher that performs preflight checks, verifies the pinned installer payload, and hands off to the shared `InstallAnswersV1` resolver.
+
+## Preflight
+
+The plan includes a best-effort `environment` report with:
+
+- OS, distro, WSL status, and architecture.
+- Admin/root availability and a user-scoped fallback hint.
+- Docker and Podman command/daemon probes.
+- KVM device and Hyper-V/WSL hints for sandbox and VM choices.
+
+## Safe defaults
+
+Defaults are intentionally conservative:
+
+- `install_surface: curl` documents the curl bootstrap path.
+- `delivery_mode: image_pull` is the fast default; `source_build` pulls source and builds locally with the same answers/runtime parameters, so the user-visible behavior should only differ by install time.
+- `sandbox_profile: safe` denies docker socket mounts and marks the reactor preview read-only. The `developer` profile still keeps the installer security posture: no privileged containers, no docker.sock, no-new-privileges, and dropped Linux capabilities. Host-privileged unsafe installs are not supported by the installer; users who need unsupported options should build from source.
+- `crypto_profile: distributed_identity_root` creates the default distributed identity/trust root for signing, auditability, approvals, and federation without enabling wallet/spending plugins.
+- `reactor_enabled: true` seeds the first guide/operator/builder agents.
+- `admin_user` and `daily_driver_user` are rendered into the generated bootstrap user list.
+- Secrets stay out of answers YAML; provider selections are intent flags only.
+
+Operators may select the `developer` sandbox profile for local iteration, but `unsafe_host` is intentionally not in the schema or wizard; users who want unsupported options can build from source instead of using the default installer. Crypto choices are explicit: `distributed_identity_root` is default, `no_crypto` removes the identity root for constrained demos, and `full_all_crypto` is reserved for downstream installers that enable the complete DID/VC and wallet-capable surface behind policy gates.
+
+## Generated outputs
+
+The install plan exposes `generated_artifacts` for downstream curl/web installers to materialize:
+
+- curl entrypoint text,
+- install script phases,
+- compose override preview for the reactor,
+- delivery intent for image-pull vs source-build installation,
+- sandbox policy showing host-privileged access and docker.sock mounts are disabled,
+- identity-root materialization intent,
+- unsupported-option handoff guidance that points source builders away from the default installer,
+- bootstrap users,
+- first agents,
+- tutorial/setup todo list that advances the admin and daily-driver profiles once setup decisions are complete.
+
+## What remains to make this actually work
+
+The implementation now resolves a plan and can materialize local install artifacts. To ship the remote curl installer end to end, finish these pieces in order:
+
+1. **Publish a real curl entrypoint.** The temporary curl URL is the GitHub Gist raw URL encoded in `DEFAULT_CURL_INSTALL_URL`; swap that constant to the production domain when DNS is ready. The hosted script must detect OS/arch, refuse unsupported platforms clearly, download a pinned release artifact, verify its checksum/signature, and then invoke `maistro-install`.
+2. **Materialize plan artifacts.** Use `maistro-install --materialize-dir ./maistro-install-out` to write the selected answers file, delivery manifest, compose override, sandbox policy, first-users manifest, first-agents manifest, identity-root manifest, unsupported-option handoff, tutorial todo list, and local review script to the install target directory.
+3. **Bootstrap distributed identity root.** Implement the default `distributed_identity_root` materializer so it creates or imports the local instance identity/trust root without enabling wallet or spending components. `no_crypto` must skip this materializer, while `full_all_crypto` must stay behind explicit downstream policy gates.
+4. **Wire users and first agents to runtime code.** Connect `admin_user`, `daily_driver_user`, `additional_users`, `first_agents`, and `reactor_enabled` to the server/core bootstrap APIs instead of leaving them as plan metadata.
+5. **Start the stack, not just build it.** Keep the safe default preview/build behavior, but add an explicit confirmed install mode that runs compose validation, builds/pulls required services, starts the selected profiles, and prints recovery/rollback commands.
+6. **Persist setup progress.** Store the tutorial/setup todo list and profile-level decisions so the admin and daily-driver profiles can level up only after required setup choices are complete.
+7. **Package and test release artifacts.** Add CI that builds the installer payload, signs/checksums it, runs curl-style smoke tests on Linux/macOS/WSL targets, and exercises Docker and Podman paths without requiring secrets.
+8. **Document source-build escape hatch.** Keep unsupported host-privileged or experimental options out of the installer; document source-build steps for operators who intentionally need unsupported settings.
+
+## Bare-machine to Hive Conductor chat checklist
+
+To go from a machine with no Python, no container runtime, and no virtualization setup to a running Hive Conductor chat that can create an agent DAG autonomously, the installer still needs these executable pieces:
+
+1. **Native bootstrapper with no Python dependency.** Provide POSIX shell and PowerShell entrypoints that run on a bare host, detect OS/arch, install or locate `uv`, and then fetch the pinned `maistro-install` payload.
+2. **Privilege and runtime installer.** Detect whether elevation is available, then install or guide installation of Docker Engine/Podman on Linux, Docker Desktop/WSL2/Hyper-V on Windows, and Docker Desktop/Colima-compatible tooling on macOS. The script must verify the daemon is running before proceeding.
+3. **Virtualization readiness.** On Windows, verify WSL2/Hyper-V prerequisites and reboot requirements; on Linux, verify KVM/cgroups where needed; on macOS, verify the selected container VM is started.
+4. **Delivery implementation.** For `image_pull`, pull pinned Hive Conductor and dependency images and pass the generated parameters. For `source_build`, clone the pinned source revision, run `uv sync --extra bootstrap`, build compose services locally, and pass the same generated parameters.
+5. **Secrets and provider setup.** Prompt for provider/account intent, then collect actual API keys only through a secrets file or secure prompt that is never committed or written into answers YAML.
+6. **Compose stack startup.** Generate final compose files, start Postgres/LiteLLM/Langfuse/Hive Conductor services, run migrations, and wait for health checks instead of stopping at compose validation/build.
+7. **Identity and bootstrap users.** Materialize or import the distributed identity root, create the admin profile, create daily-driver user 1 and any additional users, and record recovery/setup actions.
+8. **Reactor and first agents.** Start the reactor service with the chosen sandbox and crypto profiles, seed the first guide/operator/builder agents, and verify they can enqueue and complete a minimal DAG task.
+9. **Hive Conductor chat readiness.** Open or print the Hive Conductor URL, verify login/session creation, verify chat can call the backend, and run a smoke prompt that creates a small agent DAG autonomously.
+10. **Recovery, rollback, and logs.** Print exact commands for status, logs, restart, backup, teardown, and source-build escape hatch, and write them into the materialized install directory.
diff --git a/packages/maistro-bootstrap/src/maistro_bootstrap/cli.py b/packages/maistro-bootstrap/src/maistro_bootstrap/cli.py
index 49f6e02..8dcd09b 100644
--- a/packages/maistro-bootstrap/src/maistro_bootstrap/cli.py
+++ b/packages/maistro-bootstrap/src/maistro_bootstrap/cli.py
@@ -10,6 +10,7 @@ import typer
 import yaml
 from rich.console import Console
 
+from maistro_bootstrap.materialize import materialize_install_artifacts
 from maistro_bootstrap.plan import build_install_plan, run_apply_spec
 from maistro_bootstrap.repo_root import find_maistro_engine_root
 from maistro_bootstrap.schema import InstallAnswersV1, parse_answers_dict
@@ -128,12 +129,25 @@ def main(
             help="Destination path for printed copier copy command.",
         ),
     ] = "../my-product",
+    materialize_dir: Annotated[
+        Path | None,
+        typer.Option(
+            "--materialize-dir",
+            help="Write install artifacts to this directory without starting services.",
+            file_okay=False,
+            dir_okay=True,
+        ),
+    ] = None,
 ) -> None:
     """Resolve install answers into a plan; optionally run compose build (apply)."""
     answers = _resolve_answers(answers_file)
     rr = maistro_root if maistro_root is not None else find_maistro_engine_root()
     plan = build_install_plan(answers, repo_root=rr, copier_dest=copier_dest)
 
+    if materialize_dir is not None:
+        written = materialize_install_artifacts(plan, materialize_dir)
+        console.print(f"[green]Wrote {len(written)} install artifacts to {materialize_dir}[/green]")
+
     if json_out:
         console.print_json(data=plan)
         if apply_flag and not dry_run:
@@ -143,6 +157,8 @@ def main(
         return
 
     _print_human_plan(plan, answers, plan.get("repo_root"))
+    if materialize_dir is not None:
+        console.print(f"\n[bold]Materialized artifacts[/bold]: {materialize_dir}")
 
     if apply_flag:
         if dry_run:
diff --git a/packages/maistro-bootstrap/src/maistro_bootstrap/materialize.py b/packages/maistro-bootstrap/src/maistro_bootstrap/materialize.py
new file mode 100644
index 0000000..798a2b1
--- /dev/null
+++ b/packages/maistro-bootstrap/src/maistro_bootstrap/materialize.py
@@ -0,0 +1,85 @@
+"""Write a resolved maistro-install plan to an install target directory."""
+
+from __future__ import annotations
+
+import json
+import stat
+from pathlib import Path
+from typing import Any
+
+import yaml
+
+
+def _write_json(path: Path, data: Any) -> None:
+    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
+
+
+def _write_yaml(path: Path, data: Any) -> None:
+    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
+
+
+def _write_tutorial(path: Path, todos: list[str]) -> None:
+    lines = ["# Maistro first-run setup", ""]
+    lines.extend(f"- [ ] {todo}" for todo in todos)
+    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
+
+
+def _write_entrypoint(path: Path) -> None:
+    path.write_text(
+        "#!/usr/bin/env bash\n"
+        "set -euo pipefail\n"
+        'cd "$(dirname "$0")"\n'
+        "echo 'Maistro install artifacts are materialized in:' \"$PWD\"\n"
+        "echo 'Review install-answers.yaml and compose.override.yml before starting services.'\n"
+        "echo 'Next: docker compose -f compose.override.yml config'\n",
+        encoding="utf-8",
+    )
+    path.chmod(path.stat().st_mode | stat.S_IXUSR)
+
+
+def materialize_install_artifacts(plan: dict[str, Any], target_dir: Path) -> list[Path]:
+    """Materialize generated installer artifacts and return written paths.
+
+    This is intentionally file-only: it never starts containers, installs packages, or writes secrets.
+    """
+    artifacts = plan.get("generated_artifacts")
+    if not isinstance(artifacts, dict):
+        raise ValueError("plan is missing generated_artifacts")
+
+    target_dir.mkdir(parents=True, exist_ok=True)
+    answers = plan.get("answers", {})
+    compose = artifacts.get("compose_override_preview", {})
+    todos = artifacts.get("tutorial_todo", [])
+    if not isinstance(todos, list):
+        todos = []
+
+    files: list[tuple[str, str, Any]] = [
+        ("install-plan.json", "json", plan),
+        ("install-answers.yaml", "yaml", answers),
+        ("compose.override.yml", "yaml", compose),
+        ("sandbox-policy.json", "json", artifacts.get("sandbox_policy", {})),
+        ("bootstrap-users.json", "json", artifacts.get("bootstrap_users", [])),
+        ("delivery.json", "json", artifacts.get("delivery", {})),
+        ("first-agents.json", "json", artifacts.get("reactor", {}).get("first_agents", [])),
+        ("identity-root.json", "json", artifacts.get("identity_root", {})),
+        ("unsupported-options.json", "json", artifacts.get("unsupported_options", {})),
+    ]
+
+    written: list[Path] = []
+    for name, kind, data in files:
+        path = target_dir / name
+        if kind == "json":
+            _write_json(path, data)
+        else:
+            _write_yaml(path, data)
+        written.append(path)
+
+    tutorial = target_dir / "tutorial-todo.md"
+    _write_tutorial(tutorial, [str(todo) for todo in todos])
+    written.append(tutorial)
+
+    entrypoint = target_dir / "install.sh"
+    _write_entrypoint(entrypoint)
+    written.append(entrypoint)
+
+    return written
diff --git a/packages/maistro-bootstrap/src/maistro_bootstrap/plan.py b/packages/maistro-bootstrap/src/maistro_bootstrap/plan.py
index b1d3008..36e3be5 100644
--- a/packages/maistro-bootstrap/src/maistro_bootstrap/plan.py
+++ b/packages/maistro-bootstrap/src/maistro_bootstrap/plan.py
@@ -8,7 +8,7 @@ from typing import Any
 
 import yaml
 
-from maistro_bootstrap.platform_detect import deployment_tier_gate_message
+from maistro_bootstrap.platform_detect import deployment_tier_gate_message, environment_report
 from maistro_bootstrap.repo_root import find_maistro_engine_root
 from maistro_bootstrap.resolver import (
     commands_for,
@@ -20,6 +20,10 @@ from maistro_bootstrap.resolver import (
 )
 from maistro_bootstrap.schema import InstallAnswersV1
 
+DEFAULT_CURL_INSTALL_URL = (
+    "https://gist.githubusercontent.com/maistro-ai/maistro-install/main/install.sh"
+)
+
 
 def effective_runtime(answers: InstallAnswersV1) -> str:
     if answers.container_runtime != "auto":
@@ -87,6 +91,123 @@ def _compose_profile_hints(answers: InstallAnswersV1) -> list[str]:
     return lines
 
 
+def _safety_notes(answers: InstallAnswersV1) -> list[str]:
+    notes: list[str] = []
+    if answers.install_surface == "curl":
+        notes.append(
+            "install_surface=curl: fetcher should only identify the environment, verify prerequisites, "
+            "then run the pinned maistro-install payload; keep secrets out of shell history."
+        )
+    if answers.delivery_mode == "image_pull":
+        notes.append(
+            "delivery_mode=image_pull: default fast path pulls signed/pinned images and passes the same "
+            "answers as runtime parameters."
+        )
+    else:
+        notes.append(
+            "delivery_mode=source_build: pulls source and builds locally with the same answers; expected "
+            "runtime behavior should match image_pull, but install takes longer."
+        )
+    if answers.sandbox_profile == "safe":
+        notes.append(
+            "sandbox_profile=safe: default denies docker.sock mounts and host-privileged containers; "
+            "use explicit warnings before enabling broader agent execution."
+        )
+    else:
+        notes.append(
+            "sandbox_profile=developer: allows local iteration while retaining installer security posture: "
+            "no privileged containers, no docker.sock, no-new-privileges, and dropped capabilities. "
+            "Build from source if you need unsupported options."
+        )
+    if answers.crypto_profile == "distributed_identity_root":
+        notes.append(
+            "crypto_profile=distributed_identity_root: default installs a distributed identity/trust root "
+            "for agent specs, audit logs, approvals, and federation; wallet/spending plugins stay disabled."
+        )
+    elif answers.crypto_profile == "no_crypto":
+        notes.append(
+            "crypto_profile=no_crypto: removes the distributed identity root and crypto-backed signing; "
+            "use only for offline demos or environments that provide identity externally."
+        )
+    else:
+        notes.append(
+            "crypto_profile=full_all_crypto: enables the full crypto intent surface for downstream "
+            "installers, including DID/VC and wallet-capable components with explicit policy gates."
+        )
+    return notes
+
+
+def _generated_artifacts(answers: InstallAnswersV1) -> dict[str, Any]:
+    users = [answers.admin_user, answers.daily_driver_user, *answers.additional_users]
+    compose = {
+        "services": {
+            "maistro-reactor": {
+                "profiles": ["reactor"],
+                "environment": {
+                    "MAISTRO_DELIVERY_MODE": answers.delivery_mode,
+                    "MAISTRO_SANDBOX_PROFILE": answers.sandbox_profile,
+                    "MAISTRO_CRYPTO_PROFILE": answers.crypto_profile,
+                    "MAISTRO_FIRST_AGENTS": ",".join(answers.first_agents),
+                },
+                "security_opt": ["no-new-privileges:true"],
+                "cap_drop": ["ALL"],
+                "pids_limit": 512,
+                "tmpfs": ["/tmp:rw,noexec,nosuid,size=256m"],
+                "read_only": answers.sandbox_profile == "safe",
+            }
+        }
+    }
+    return {
+        "curl_entrypoint_url": DEFAULT_CURL_INSTALL_URL,
+        "curl_entrypoint": f"curl -fsSL {DEFAULT_CURL_INSTALL_URL} | bash -s -- --answers-file install-answers.yaml",
+        "install_script_phases": [
+            "preflight: detect OS/arch, admin ability, Docker/Podman, Hyper-V/WSL, KVM, LXC/VM hints",
+            "answers: walk operator through safe defaults and warnings for incompatible choices",
+            "render: write answers, compose override, sandbox policy, users, first agents, tutorial todo",
+            "apply: install prerequisites only with confirmation, build/pull selected compose, start reactor",
+        ],
+        "compose_override_preview": compose,
+        "bootstrap_users": users,
+        "delivery": {
+            "mode": answers.delivery_mode,
+            "behavior_contract": "image_pull and source_build consume the same answers and runtime parameters",
+            "expected_difference": "source_build takes longer; image_pull is faster",
+            "source": {
+                "enabled": answers.delivery_mode == "source_build",
+                "commands": ["git clone <maistro-engine-url>", "uv sync --extra bootstrap"],
+            },
+            "images": {
+                "enabled": answers.delivery_mode == "image_pull",
+                "parameters": answers.model_dump(mode="json"),
+            },
+        },
+        "sandbox_policy": {
+            "profile": answers.sandbox_profile,
+            "host_privileged": False,
+            "docker_socket_mount": False,
+            "no_new_privileges": True,
+            "capabilities_dropped": "ALL",
+        },
+        "unsupported_options": {
+            "installer_policy": "unsupported options are intentionally omitted from the installer",
+            "handoff": "build from source for unsupported host-privileged or experimental options",
+        },
+        "identity_root": {
+            "default": answers.crypto_profile == "distributed_identity_root",
+            "profile": answers.crypto_profile,
+            "materialize": answers.crypto_profile != "no_crypto",
+        },
+        "reactor": {"enabled": answers.reactor_enabled, "first_agents": answers.first_agents},
+        "tutorial_todo": [
+            f"Confirm admin profile for {answers.admin_user} and store recovery codes",
+            f"Complete daily-driver onboarding for {answers.daily_driver_user}",
+            "Choose provider accounts and add API keys through the secrets UI/env, not answers YAML",
+            "Run first safe sandbox task, review audit log, then unlock developer profile if needed",
+            "Record enough setup decisions to level up admin and user profiles from tutorial to operator",
+        ],
+    }
+
+
 def build_install_plan(
     answers: InstallAnswersV1,
     *,
@@ -106,6 +227,7 @@ def build_install_plan(
     shell_lines.extend(commands_for_compose_addons_run_podman(compose_addons))
 
     preview_notes = [
+        *_safety_notes(answers),
         *_stub_preview_lines(answers),
         *_preview_for_observability(answers),
         *_preview_for_gateway(answers),
@@ -156,6 +278,8 @@ def build_install_plan(
         "preview_notes": preview_notes,
         "apply_spec": apply_spec,
         "copier_command": copier_line,
+        "environment": environment_report(),
+        "generated_artifacts": _generated_artifacts(answers),
     }
 
 
diff --git a/packages/maistro-bootstrap/src/maistro_bootstrap/platform_detect.py b/packages/maistro-bootstrap/src/maistro_bootstrap/platform_detect.py
index 14459b5..3d5398b 100644
--- a/packages/maistro-bootstrap/src/maistro_bootstrap/platform_detect.py
+++ b/packages/maistro-bootstrap/src/maistro_bootstrap/platform_detect.py
@@ -5,7 +5,10 @@ from __future__ import annotations
 import os
 import platform
 import re
+import shutil
+import subprocess
 from pathlib import Path
+from typing import Any
 
 
 def uname_summary() -> str:
@@ -55,12 +58,16 @@ def deployment_hint() -> str:
 
 
 def has_command(name: str) -> bool:
-    path = os.environ.get("PATH", "")
-    for p in path.split(os.pathsep):
-        exe = Path(p) / name
-        if exe.is_file() and os.access(exe, os.X_OK):
-            return True
-    return False
+    return shutil.which(name) is not None
+
+
+def _run_probe(argv: list[str], timeout: float = 2.0) -> tuple[bool, str]:
+    try:
+        proc = subprocess.run(argv, text=True, capture_output=True, timeout=timeout, check=False)
+    except (OSError, subprocess.SubprocessError) as exc:
+        return False, str(exc)
+    out = (proc.stdout or proc.stderr).strip().splitlines()
+    return proc.returncode == 0, out[0] if out else f"exit {proc.returncode}"
 
 
 def deployment_tier_gate_message(tier: str) -> str | None:
@@ -93,3 +100,47 @@ def detect_container_runtime() -> tuple[str, str]:
     if p:
         return "podman", "podman is on PATH (no docker)."
     return "none", "No docker/podman on PATH — install a container runtime first."
+
+
+def environment_report() -> dict[str, Any]:
+    """Best-effort installer preflight; no mutations and no secrets."""
+    sys = platform.system().lower()
+    docker_ok, docker_msg = _run_probe(["docker", "info", "--format", "{{.ServerVersion}}"])
+    podman_ok, podman_msg = _run_probe(
+        ["podman", "info", "--format", "{{.Host.Os}}/{{.Host.Arch}}"]
+    )
+    kvm = Path("/dev/kvm").exists()
+    hyperv = has_command("powershell.exe") and "microsoft" in platform.release().lower()
+    admin = False
+    admin_hint = "not root/admin; installer will prefer user-scoped setup and print sudo steps"
+    if hasattr(os, "geteuid") and os.geteuid() == 0:
+        admin = True
+        admin_hint = "running as root; safe defaults still avoid host-wide changes unless confirmed"
+    elif sys == "windows":
+        ok, _msg = _run_probe(["net", "session"])
+        admin = ok
+        admin_hint = "Windows admin available" if ok else "Windows admin not detected"
+
+    runtime, runtime_hint = detect_container_runtime()
+    virtualization: list[str] = []
+    if kvm:
+        virtualization.append("kvm")
+    if hyperv:
+        virtualization.append("hyperv/wsl")
+    if is_wsl():
+        virtualization.append("wsl2")
+
+    return {
+        "os": uname_summary(),
+        "distro": linux_distro_guess(),
+        "is_wsl": is_wsl(),
+        "admin_available": admin,
+        "admin_hint": admin_hint,
+        "container_runtime": runtime,
+        "container_runtime_hint": runtime_hint,
+        "docker_daemon": {"ok": docker_ok, "message": docker_msg},
+        "podman_machine": {"ok": podman_ok, "message": podman_msg},
+        "virtualization": virtualization or ["none-detected"],
+        "kvm_device": kvm,
+        "hyperv_hint": hyperv,
+    }
diff --git a/packages/maistro-bootstrap/src/maistro_bootstrap/schema.py b/packages/maistro-bootstrap/src/maistro_bootstrap/schema.py
index 94af0e5..dc4a743 100644
--- a/packages/maistro-bootstrap/src/maistro_bootstrap/schema.py
+++ b/packages/maistro-bootstrap/src/maistro_bootstrap/schema.py
@@ -15,6 +15,10 @@ DeploymentTier = Literal["local_docker", "local_podman", "vm", "lxc", "proxmox",
 ContainerRuntime = Literal["docker", "podman", "auto"]
 UsersIntent = Literal["bootstrap_admin", "sso_later", "skip"]
 StackBringup = Literal["none", "root_full"]
+SandboxProfile = Literal["safe", "developer"]
+InstallSurface = Literal["curl", "checkout"]
+CryptoProfile = Literal["distributed_identity_root", "no_crypto", "full_all_crypto"]
+DeliveryMode = Literal["image_pull", "source_build"]
 
 
 class InstallAnswersV1(BaseModel):
@@ -32,12 +36,23 @@ class InstallAnswersV1(BaseModel):
     container_runtime: ContainerRuntime = "auto"
     users_intent: UsersIntent = "skip"
     stack_bringup: StackBringup = "none"
+    install_surface: InstallSurface = "curl"
+    delivery_mode: DeliveryMode = "image_pull"
+    sandbox_profile: SandboxProfile = "safe"
+    crypto_profile: CryptoProfile = "distributed_identity_root"
+    admin_user: str = "maistro-admin"
+    daily_driver_user: str = "maistro-user"
+    additional_users: list[str] = Field(default_factory=list)
+    first_agents: list[str] = Field(default_factory=lambda: ["guide", "operator", "builder"])
+    reactor_enabled: bool = True
     provider_accounts: dict[str, bool] = Field(
         default_factory=dict,
         description="Which cloud accounts the operator intends to use (no secrets).",
     )
 
-    @field_validator("features", "compose_addons", mode="before")
+    @field_validator(
+        "features", "compose_addons", "additional_users", "first_agents", mode="before"
+    )
     @classmethod
     def _coerce_str_lists(cls, v: object) -> list[str]:
         if v is None:
diff --git a/packages/maistro-bootstrap/src/maistro_bootstrap/wizard.py b/packages/maistro-bootstrap/src/maistro_bootstrap/wizard.py
index 3d0b71a..ea3b2f0 100644
--- a/packages/maistro-bootstrap/src/maistro_bootstrap/wizard.py
+++ b/packages/maistro-bootstrap/src/maistro_bootstrap/wizard.py
@@ -13,6 +13,7 @@ from maistro_bootstrap.platform_detect import (
     deployment_hint,
     deployment_tier_gate_message,
     detect_container_runtime,
+    environment_report,
     uname_summary,
 )
 from maistro_bootstrap.resolver import COMPOSE_ADDONS, FEATURES, PRODUCTS
@@ -99,7 +100,10 @@ def collect_answers_interactive() -> InstallAnswersV1:
         )
     )
     det, hint = detect_container_runtime()
-    console.print(f"[dim]Container runtime:[/dim] {det} — {hint}\n")
+    env = environment_report()
+    console.print(f"[dim]Container runtime:[/dim] {det} — {hint}")
+    console.print(f"[dim]Admin:[/dim] {env['admin_hint']}")
+    console.print(f"[dim]Virtualization:[/dim] {', '.join(env['virtualization'])}\n")
 
     stack_bringup = _stack_bringup()
     features = _feature_set()
@@ -144,6 +148,22 @@ def collect_answers_interactive() -> InstallAnswersV1:
         "User / tenancy intent:",
         ["skip", "bootstrap_admin", "sso_later"],
     )
+    delivery_mode = _select_str(
+        "Install delivery (same runtime behavior; source build takes longer):",
+        ["image_pull", "source_build"],
+    )
+    sandbox = _select_str(
+        "Sandbox profile (safe is default; unsupported options require building from source):",
+        ["safe", "developer"],
+    )
+    crypto_profile = _select_str(
+        "Crypto / identity profile:",
+        ["distributed_identity_root", "no_crypto", "full_all_crypto"],
+    )
+    admin_user = questionary.text("Admin user name:", default="maistro-admin").ask()
+    daily_user = questionary.text("Daily driver user 1:", default="maistro-user").ask()
+    if admin_user is None or daily_user is None:
+        _abort()
 
     raw: dict[str, Any] = {
         "schema_version": "1",
@@ -159,5 +179,12 @@ def collect_answers_interactive() -> InstallAnswersV1:
         "users_intent": users_i,
         "stack_bringup": stack_bringup,
         "provider_accounts": {"openai": oa, "anthropic": an},
+        "install_surface": "curl",
+        "delivery_mode": delivery_mode,
+        "sandbox_profile": sandbox,
+        "crypto_profile": crypto_profile,
+        "admin_user": admin_user,
+        "daily_driver_user": daily_user,
+        "reactor_enabled": True,
     }
     return parse_answers_dict(raw)
diff --git a/packages/maistro-bootstrap/tests/test_plan.py b/packages/maistro-bootstrap/tests/test_plan.py
index 7085585..8da2f19 100644
--- a/packages/maistro-bootstrap/tests/test_plan.py
+++ b/packages/maistro-bootstrap/tests/test_plan.py
@@ -6,7 +6,8 @@ from pathlib import Path
 
 import pytest
 
-from maistro_bootstrap.plan import build_install_plan
+from maistro_bootstrap.materialize import materialize_install_artifacts
+from maistro_bootstrap.plan import DEFAULT_CURL_INSTALL_URL, build_install_plan
 from maistro_bootstrap.schema import parse_answers_dict
 
 
@@ -87,3 +88,112 @@ def test_stub_manifest_preview_for_llm_proxy() -> None:
     plan = build_install_plan(answers, repo_root=None)
     joined = " ".join(plan["preview_notes"])
     assert "litellm" in joined.lower() or "preview" in joined.lower()
+
+
+def test_plan_includes_environment_and_generated_artifacts() -> None:
+    raw = {
+        "schema_version": "1",
+        "sandbox_profile": "safe",
+        "admin_user": "root-admin",
+        "daily_driver_user": "alice",
+        "additional_users": ["bob"],
+        "first_agents": ["guide", "builder"],
+        "delivery_mode": "image_pull",
+        "crypto_profile": "distributed_identity_root",
+    }
+    plan = build_install_plan(parse_answers_dict(raw), repo_root=Path("/tmp/x"))
+    assert "admin_available" in plan["environment"]
+    artifacts = plan["generated_artifacts"]
+    assert artifacts["bootstrap_users"] == ["root-admin", "alice", "bob"]
+    assert artifacts["curl_entrypoint_url"] == DEFAULT_CURL_INSTALL_URL
+    assert "gist.githubusercontent.com" in artifacts["curl_entrypoint"]
+    assert artifacts["reactor"]["first_agents"] == ["guide", "builder"]
+    assert artifacts["delivery"]["mode"] == "image_pull"
+    assert artifacts["delivery"]["images"]["enabled"] is True
+    assert artifacts["identity_root"]["default"] is True
+    assert artifacts["identity_root"]["materialize"] is True
+    assert "build from source" in artifacts["unsupported_options"]["handoff"]
+    assert artifacts["sandbox_policy"]["docker_socket_mount"] is False
+    service = artifacts["compose_override_preview"]["services"]["maistro-reactor"]
+    assert service["read_only"] is True
+    assert service["cap_drop"] == ["ALL"]
+    assert any("sandbox_profile=safe" in note for note in plan["preview_notes"])
+
+
+def test_developer_sandbox_points_unsupported_options_to_source_build() -> None:
+    raw = {"schema_version": "1", "sandbox_profile": "developer"}
+    plan = build_install_plan(parse_answers_dict(raw), repo_root=Path("/tmp/x"))
+    assert any("no privileged containers" in note for note in plan["preview_notes"])
+    artifacts = plan["generated_artifacts"]
+    assert artifacts["sandbox_policy"]["host_privileged"] is False
+    assert artifacts["sandbox_policy"]["docker_socket_mount"] is False
+    service = artifacts["compose_override_preview"]["services"]["maistro-reactor"]
+    assert service["security_opt"] == ["no-new-privileges:true"]
+    assert service["cap_drop"] == ["ALL"]
+
+
+def test_unsafe_host_profile_is_rejected_by_schema() -> None:
+    raw = {"schema_version": "1", "sandbox_profile": "unsafe_host"}
+    with pytest.raises(ValueError):
+        parse_answers_dict(raw)
+
+
+def test_no_crypto_profile_removes_identity_root_materialization() -> None:
+    raw = {"schema_version": "1", "crypto_profile": "no_crypto"}
+    plan = build_install_plan(parse_answers_dict(raw), repo_root=Path("/tmp/x"))
+    identity_root = plan["generated_artifacts"]["identity_root"]
+    assert identity_root["default"] is False
+    assert identity_root["materialize"] is False
+    assert any("crypto_profile=no_crypto" in note for note in plan["preview_notes"])
+
+
+def test_full_all_crypto_profile_is_explicit() -> None:
+    raw = {"schema_version": "1", "crypto_profile": "full_all_crypto"}
+    plan = build_install_plan(parse_answers_dict(raw), repo_root=Path("/tmp/x"))
+    assert plan["generated_artifacts"]["identity_root"]["profile"] == "full_all_crypto"
+    assert any("full_all_crypto" in note for note in plan["preview_notes"])
+
+
+def test_materialize_install_artifacts_writes_reviewable_files(tmp_path: Path) -> None:
+    raw = {
+        "schema_version": "1",
+        "admin_user": "admin",
+        "daily_driver_user": "driver",
+        "first_agents": ["guide"],
+    }
+    plan = build_install_plan(parse_answers_dict(raw), repo_root=Path("/tmp/x"))
+
+    written = materialize_install_artifacts(plan, tmp_path)
+
+    names = {path.name for path in written}
+    assert "install-plan.json" in names
+    assert "install-answers.yaml" in names
+    assert "compose.override.yml" in names
+    assert "sandbox-policy.json" in names
+    assert "bootstrap-users.json" in names
+    assert "first-agents.json" in names
+    assert "delivery.json" in names
+    assert "identity-root.json" in names
+    assert "unsupported-options.json" in names
+    assert "tutorial-todo.md" in names
+    assert "install.sh" in names
+    assert "driver" in (tmp_path / "bootstrap-users.json").read_text(encoding="utf-8")
+    assert "image_pull" in (tmp_path / "delivery.json").read_text(encoding="utf-8")
+    assert "MAISTRO_CRYPTO_PROFILE" in (tmp_path / "compose.override.yml").read_text(
+        encoding="utf-8"
+    )
+    assert "Maistro first-run setup" in (tmp_path / "tutorial-todo.md").read_text(encoding="utf-8")
+    assert (tmp_path / "install.sh").stat().st_mode & 0o100
+
+
+def test_source_build_delivery_has_same_behavior_contract() -> None:
+    raw = {"schema_version": "1", "delivery_mode": "source_build"}
+    plan = build_install_plan(parse_answers_dict(raw), repo_root=Path("/tmp/x"))
+    delivery = plan["generated_artifacts"]["delivery"]
+    assert delivery["mode"] == "source_build"
+    assert delivery["source"]["enabled"] is True
+    assert delivery["images"]["enabled"] is False
+    assert "same answers" in delivery["behavior_contract"]
+    assert any("takes longer" in note for note in plan["preview_notes"])
+    service = plan["generated_artifacts"]["compose_override_preview"]["services"]["maistro-reactor"]
+    assert service["environment"]["MAISTRO_DELIVERY_MODE"] == "source_build"
