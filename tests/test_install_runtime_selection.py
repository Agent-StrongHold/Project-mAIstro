"""install.sh honors the selected container runtime (#1820).

The wizard resolves ``container_runtime`` once (``plan.py::effective_runtime``)
and writes it into the materialized ``delivery.json``. install.sh used to
re-derive a runtime with its own docker-first probe: with both CLIs installed,
a selected working Podman lost to an inaccessible Docker, the apt bootstrap
installed Docker for a Podman selection, and the Docker-only preflight checks
(engine API floor, credential-helper probe, docker.sock discovery) ran against
the unselected engine. These tests lift the real functions out of install.sh
verbatim — the same technique as tests/test_install_compose_floor.py, since
``release-installer.yml`` runs the installer only on tags, so no PR check
would otherwise execute a line of it — and run them against stub runtimes.

The matrix below is the issue's regression list: both CLIs present, selected
Podman with inaccessible Docker, Docker-only, Podman-only, unavailable
selected runtime, and the documented ``auto`` choice.
"""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = ROOT / "install.sh"

#: The runtime-selection functions, lifted verbatim from install.sh.
_FUNCTIONS = (
    "delivery_mode",
    "selected_container_runtime",
    "runtime_compose_cmd",
    "detect_compose_cmd",
    "docker_daemon_ready",
    "podman_runtime_ready",
    "selected_runtime_ready",
    "selected_runtime_install_hint",
    "docker_only_preflight_checks",
    "ensure_compose_runtime",
)


def _harness(shim_dir: Path, plan_dir: Path, prelude: str = "") -> str:
    extract = ";".join(f"/^{name}()/,/^}}/p" for name in _FUNCTIONS)
    install = shlex.quote(str(INSTALL_SH))
    return f"""
set -uo pipefail
PATH={shlex.quote(str(shim_dir))}:$PATH
PLAN_DIR={shlex.quote(str(plan_dir))}
export MAISTRO_INSTALL_PLAN_DIR="$PLAN_DIR"
ok() {{ echo "[ok] $*"; }}
info() {{ :; }}
warn() {{ echo "WARN: $*" >&2; }}
fail() {{ echo "[error] $*" >&2; exit 1; }}
is_macos() {{ return 1; }}
is_wsl() {{ return 1; }}
# Bootstrap stand-ins: real installers touch brew/apt/sudo. Each records its
# call so a test can prove a runtime bootstrap never ran for the OTHER
# runtime's selection.
bootstrap_macos_runtime() {{ echo macos-bootstrap >> bootstraps.log; }}
bootstrap_apt_docker_runtime() {{ echo apt-docker-bootstrap >> bootstraps.log; }}
start_dockerd_unsupervised() {{ return 1; }}
# Docker-only preflight bodies are stubbed: the gate under test decides
# WHETHER they run, and each records its call when it does.
ensure_docker_engine_supported() {{ echo engine-floor >> docker-only-checks.log; }}
check_docker_credential_helper() {{ echo cred-helper >> docker-only-checks.log; }}
record_docker_sock() {{ echo docker-sock >> docker-only-checks.log; }}
COMPOSE_CMD=()
COMPOSE_FILES=()
mkdir -p "$PLAN_DIR"
source <(sed -n {extract!r} {install})
{prelude}
"""


def _run(
    shim_dir: Path, plan_dir: Path, script: str, *, prelude: str = ""
) -> subprocess.CompletedProcess[str]:
    harness = _harness(shim_dir, plan_dir, prelude=prelude)
    return subprocess.run(
        ["bash", "-c", harness + script],
        capture_output=True,
        text=True,
        check=False,
        cwd=shim_dir,
    )


def _write_runtime_shim(
    shim_dir: Path,
    name: str,
    *,
    compose: bool = True,
    daemon: bool = True,
    canary: str | None = None,
) -> None:
    """A stub runtime CLI implementing the subcommands the installer probes.

    ``compose=False`` models a CLI with no working Compose v2 provider (the
    front-end probe fails); ``daemon=False`` models a CLI whose compose
    answers but whose engine/store does not answer for this account — the
    "installed but inaccessible" case the readiness check must catch.
    ``canary`` names a file the shim appends to on EVERY invocation, proving
    non-invocation (an unselected probe must not even run).
    """
    lines = ["#!/usr/bin/env bash"]
    if canary:
        lines.append(f"echo invoked >> {shlex.quote(str(shim_dir / canary))}")
    lines += [
        'case " $* " in',
        '    *" version "*)',
    ]
    if compose:
        lines += ['        echo "Docker Compose version v2.39.2"; exit 0 ;;']
    else:
        lines += ['        echo "no working compose provider" >&2; exit 1 ;;']
    lines += [
        '    *" info "*)',
    ]
    if daemon:
        lines += ["        exit 0 ;;"]
    else:
        lines += ['        echo "Cannot connect to daemon" >&2; exit 1 ;;']
    lines += ["esac", "exit 0"]
    shim = shim_dir / name
    shim.write_text("\n".join(lines) + "\n", encoding="utf-8")
    shim.chmod(0o755)


def _write_plan(plan_dir: Path, runtime: str | None) -> None:
    """delivery.json as plan.py writes it (#1820 keys); None models a legacy
    plan directory written before the field existed."""
    plan_dir.mkdir(parents=True, exist_ok=True)
    if runtime is None:
        (plan_dir / "delivery.json").write_text(
            '{"mode": "image_pull", "behavior_contract": "legacy plan"}\n',
            encoding="utf-8",
        )
        return
    (plan_dir / "delivery.json").write_text(
        "{"
        f'"mode": "image_pull", "container_runtime": "{runtime}", '
        f'"container_runtime_selection": "{runtime}"'
        "}\n",
        encoding="utf-8",
    )


# --- the headline regression -------------------------------------------------


def test_selected_podman_wins_when_both_clis_are_present(tmp_path: Path) -> None:
    """Both CLIs installed, plan selects podman: the selection must survive.
    The docker-first probe used to hand the install to Docker here."""
    plan = tmp_path / "plan"
    _write_plan(plan, "podman")
    _write_runtime_shim(tmp_path, "docker", compose=True, daemon=True)
    _write_runtime_shim(tmp_path, "podman", compose=True, daemon=True)
    result = _run(
        tmp_path,
        plan,
        'if detect_compose_cmd; then echo "SELECTED: ${COMPOSE_CMD[*]}"; else echo NONE; fi\n',
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "SELECTED: podman compose", result.stdout


def test_selected_docker_survives_when_both_clis_are_present(tmp_path: Path) -> None:
    plan = tmp_path / "plan"
    _write_plan(plan, "docker")
    _write_runtime_shim(tmp_path, "docker", compose=True, daemon=True)
    _write_runtime_shim(tmp_path, "podman", compose=True, daemon=True)
    result = _run(
        tmp_path,
        plan,
        'if detect_compose_cmd; then echo "SELECTED: ${COMPOSE_CMD[*]}"; else echo NONE; fi\n',
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "SELECTED: docker compose", result.stdout


def test_selected_podman_never_probes_inaccessible_docker(tmp_path: Path) -> None:
    """Selected Podman with a Docker CLI on PATH that answers nothing: the
    install proceeds on Podman and the unselected runtime is not even
    invoked — a Docker probe that happens to succeed must not be able to
    outrank the selection."""
    plan = tmp_path / "plan"
    _write_plan(plan, "podman")
    _write_runtime_shim(
        tmp_path, "docker", compose=False, daemon=False, canary="docker-invocations.log"
    )
    _write_runtime_shim(tmp_path, "podman", compose=True, daemon=True)
    result = _run(
        tmp_path,
        plan,
        'if detect_compose_cmd; then echo "SELECTED: ${COMPOSE_CMD[*]}"; else echo NONE; fi\n'
        'if [[ -f docker-invocations.log ]]; then echo "DOCKER-PROBED"; else echo "DOCKER-UNTOUCHED"; fi\n',
    )
    assert result.returncode == 0, result.stderr
    assert "SELECTED: podman compose" in result.stdout, result.stdout
    assert "DOCKER-UNTOUCHED" in result.stdout, result.stdout


def test_docker_only_host_with_docker_selection(tmp_path: Path) -> None:
    plan = tmp_path / "plan"
    _write_plan(plan, "docker")
    _write_runtime_shim(tmp_path, "docker", compose=True, daemon=True)
    result = _run(
        tmp_path,
        plan,
        'if detect_compose_cmd; then echo "SELECTED: ${COMPOSE_CMD[*]}"; else echo NONE; fi\n',
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "SELECTED: docker compose", result.stdout


def test_podman_only_host_with_auto_selection(tmp_path: Path) -> None:
    """Documented auto policy, second branch: with no usable Docker Compose
    front-end, auto resolves to the Podman one. The docker shim is written
    even though the host models "docker-less": GitHub runners (and this
    repo's dev machines) may ship a working docker; without shadowing it the
    test measures the runner image instead of install.sh."""
    plan = tmp_path / "plan"
    _write_plan(plan, "auto")
    _write_runtime_shim(tmp_path, "docker", compose=False, daemon=False)
    _write_runtime_shim(tmp_path, "podman", compose=True, daemon=True)
    result = _run(
        tmp_path,
        plan,
        'echo "SELECTION: $(selected_container_runtime)"\n'
        'if detect_compose_cmd; then echo "SELECTED: ${COMPOSE_CMD[*]}"; else echo NONE; fi\n',
    )
    assert result.returncode == 0, result.stderr
    assert "SELECTION: auto" in result.stdout, result.stdout
    assert "SELECTED: podman compose" in result.stdout, result.stdout


def test_auto_with_both_clis_selects_docker_by_policy(tmp_path: Path) -> None:
    """The documented auto order: Docker first, then Podman. Both present
    means Docker compose — the same policy statement the docs carry."""
    plan = tmp_path / "plan"
    _write_plan(plan, "auto")
    _write_runtime_shim(tmp_path, "docker", compose=True, daemon=True)
    _write_runtime_shim(tmp_path, "podman", compose=True, daemon=True)
    result = _run(
        tmp_path,
        plan,
        'if detect_compose_cmd; then echo "SELECTED: ${COMPOSE_CMD[*]}"; else echo NONE; fi\n',
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "SELECTED: docker compose", result.stdout


# --- unavailable selected runtime: actionable failure, never a switch --------


def test_selected_podman_unavailable_fails_without_switching_to_docker(
    tmp_path: Path,
) -> None:
    """Podman selected but absent; Docker fully working. The installer must
    fail naming the selection — silently bootstrapping/using Docker is
    exactly the switch the selection forbids."""
    plan = tmp_path / "plan"
    _write_plan(plan, "podman")
    _write_runtime_shim(tmp_path, "docker", compose=True, daemon=True)
    result = _run(
        tmp_path,
        plan,
        "ensure_compose_runtime\n",
    )
    assert result.returncode != 0, result.stdout
    assert "podman" in result.stderr, result.stderr
    assert "[ok] Compose runtime: docker compose" not in result.stdout + result.stderr
    # the other runtime was never bootstrapped into service for this install
    assert not (tmp_path / "bootstraps.log").exists(), result.stdout


def test_selected_runtime_daemon_down_fails_actionably(tmp_path: Path) -> None:
    """Selected Podman present with a working compose provider, but its
    engine does not answer for this account: a recoverable prerequisite
    report naming the runtime, not a fallthrough to Docker."""
    plan = tmp_path / "plan"
    _write_plan(plan, "podman")
    _write_runtime_shim(tmp_path, "podman", compose=True, daemon=False)
    _write_runtime_shim(tmp_path, "docker", compose=True, daemon=True)
    result = _run(
        tmp_path,
        plan,
        "ensure_compose_runtime\n",
    )
    assert result.returncode != 0, result.stdout
    assert "does not answer as this account" in result.stderr, result.stderr
    assert "podman" in result.stderr, result.stderr
    assert "[ok] Compose runtime" not in result.stdout


def test_selected_docker_daemon_down_reports_and_does_not_fake_readiness(
    tmp_path: Path,
) -> None:
    """Docker selected, CLI + compose present, daemon not answering, and the
    bootstrap (stubbed failing here) cannot bring it up: the install must
    fail instead of printing the old unconditional '[ok] Compose runtime'
    and dying later inside `compose up` with a daemon error."""
    plan = tmp_path / "plan"
    _write_plan(plan, "docker")
    _write_runtime_shim(tmp_path, "docker", compose=True, daemon=False)
    result = _run(
        tmp_path,
        plan,
        "ensure_compose_runtime\n",
    )
    assert result.returncode != 0, result.stdout
    assert "does not answer as this account" in result.stderr, result.stderr


# --- selection precedence ----------------------------------------------------


def test_persisted_plan_outranks_the_environment_override(tmp_path: Path) -> None:
    """A transient MAISTRO_CONTAINER_RUNTIME must not silently overrule the
    persisted selection on a re-run."""
    plan = tmp_path / "plan"
    _write_plan(plan, "podman")
    result = _run(
        tmp_path,
        plan,
        'export MAISTRO_CONTAINER_RUNTIME=docker; echo "SELECTION: $(selected_container_runtime)"\n',
    )
    assert result.returncode == 0, result.stderr
    assert "SELECTION: podman" in result.stdout, result.stdout


def test_environment_pin_fills_the_gap_when_no_plan_selects(tmp_path: Path) -> None:
    """Wizardless runs (skip-wizard, no delivery.json) can pin the runtime via
    MAISTRO_CONTAINER_RUNTIME."""
    plan = tmp_path / "plan"
    result = _run(
        tmp_path,
        plan,
        'export MAISTRO_CONTAINER_RUNTIME=podman; echo "SELECTION: $(selected_container_runtime)"\n'
        'export MAISTRO_CONTAINER_RUNTIME=auto; echo "SELECTION: $(selected_container_runtime)"\n'
        'unset MAISTRO_CONTAINER_RUNTIME; echo "SELECTION: $(selected_container_runtime)"\n',
    )
    assert result.returncode == 0, result.stderr
    assert "SELECTION: podman" in result.stdout, result.stdout
    assert "SELECTION: auto" in result.stdout, result.stdout
    assert result.stdout.count("SELECTION: auto") == 2, result.stdout


def test_unknown_environment_token_degrades_to_auto_with_a_warning(
    tmp_path: Path,
) -> None:
    plan = tmp_path / "plan"
    result = _run(
        tmp_path,
        plan,
        'export MAISTRO_CONTAINER_RUNTIME=nerdctl; echo "SELECTION: $(selected_container_runtime)"\n',
    )
    assert result.returncode == 0, result.stderr
    assert "SELECTION: auto" in result.stdout, result.stdout
    assert "Ignoring unknown MAISTRO_CONTAINER_RUNTIME='nerdctl'" in result.stderr, result.stderr


def test_legacy_plan_without_the_runtime_field_behaves_as_auto(tmp_path: Path) -> None:
    """A delivery.json written before #1820 carries no runtime key: the
    unselected probe order must still find a supported front-end — the
    legacy format never blocks the selected supported path."""
    plan = tmp_path / "plan"
    _write_plan(plan, None)
    _write_runtime_shim(tmp_path, "docker", compose=False, daemon=False)
    _write_runtime_shim(tmp_path, "podman", compose=True, daemon=True)
    result = _run(
        tmp_path,
        plan,
        'echo "SELECTION: $(selected_container_runtime)"\n'
        'if detect_compose_cmd; then echo "SELECTED: ${COMPOSE_CMD[*]}"; else echo NONE; fi\n',
    )
    assert result.returncode == 0, result.stderr
    assert "SELECTION: auto" in result.stdout, result.stdout
    assert "SELECTED: podman compose" in result.stdout, result.stdout


# --- docker-only validations do not run for a podman selection ---------------


def test_docker_only_preflight_checks_skipped_for_podman_selection(
    tmp_path: Path,
) -> None:
    """The engine API floor, credential-helper probe, and docker.sock
    discovery are Docker-runtime validations. Under a Podman selection they
    must not run: an unrelated old Docker daemon on the same host would
    otherwise fail a working Podman install."""
    plan = tmp_path / "plan"
    _write_plan(plan, "podman")
    result = _run(
        tmp_path,
        plan,
        "COMPOSE_CMD=(podman compose)\n"
        "docker_only_preflight_checks\n"
        'if [[ -f docker-only-checks.log ]]; then echo "RAN"; else echo "SKIPPED"; fi\n',
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "SKIPPED", result.stdout


def test_docker_only_preflight_checks_run_for_docker_selection(
    tmp_path: Path,
) -> None:
    plan = tmp_path / "plan"
    _write_plan(plan, "docker")
    result = _run(
        tmp_path,
        plan,
        "COMPOSE_CMD=(docker compose)\n"
        "docker_only_preflight_checks\n"
        'if [[ -f docker-only-checks.log ]]; then echo "RAN"; else echo "SKIPPED"; fi\n',
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "RAN", result.stdout


# --- the manifest records the honored selection ------------------------------


def test_install_manifest_records_the_container_runtime() -> None:
    """`maistro upgrade` and recovery read install-manifest.json; the manifest
    heredoc must record the honored runtime beside the delivery mode (the
    pydantic field exists on maistro.core's InstallManifest for exactly this)."""
    body = INSTALL_SH.read_text(encoding="utf-8")
    assert '"container_runtime": "$(selected_container_runtime)"' in body, (
        "install.sh stopped recording the honored runtime in the install manifest"
    )
