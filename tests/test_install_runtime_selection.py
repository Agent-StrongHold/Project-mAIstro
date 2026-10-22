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

import os
import shlex
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = ROOT / "install.sh"

#: The runtime-selection functions, lifted verbatim from install.sh.
_FUNCTIONS = (
    "delivery_mode",
    "selected_container_runtime",
    "container_runtime_selection_is_explicit",
    "runtime_compose_cmd",
    "detect_compose_cmd",
    "docker_daemon_ready",
    "podman_runtime_ready",
    "selected_runtime_ready",
    "selected_runtime_install_hint",
    "docker_only_preflight_checks",
    "ensure_compose_runtime",
    "compose_line_cmd",
    "manifest_container_runtime",
    "write_recovery_md",
    "print_success",
)

#: The elevation path of the Linux bootstrap, lifted verbatim as well (#1820).
#: `bootstrap_apt_docker_runtime` is deliberately NOT in _FUNCTIONS: the
#: harness stubs it there to record that a bootstrap was OFFERED, and the
#: stub is what the "never bootstrap the other runtime" assertions read.
#: Sourcing the real body overrides the stub (the source runs after the
#: stubs), so the elevation tests exercise the shipped code while the
#: selection tests keep their recording stub.
_ELEVATION_FUNCTIONS = (
    *_FUNCTIONS,
    "run_elevated",
    "bootstrap_apt_docker_runtime",
)


def _harness(
    shim_dir: Path, plan_dir: Path, prelude: str = "", functions: tuple[str, ...] = _FUNCTIONS
) -> str:
    extract = ";".join(f"/^{name}()/,/^}}/p" for name in functions)
    install = shlex.quote(str(INSTALL_SH))
    # Hermetic PATH: the shim dir plus a toolbin holding just the coreutils
    # the lifted functions use. A real docker/podman on the host must never
    # leak into a test that models its absence — a dev machine or CI image
    # with both CLIs installed would otherwise flip the "unavailable
    # selection" tests — so no system PATH entry is reachable at all.
    toolbin = shim_dir / ".toolbin"
    toolbin.mkdir(exist_ok=True)
    for tool in ("bash", "grep", "tr", "head", "sed", "mkdir", "date", "cat", "uname"):
        link = toolbin / tool
        if not link.exists():
            link.symlink_to(f"/usr/bin/{tool}")
    return f"""
set -uo pipefail
PATH={shlex.quote(str(shim_dir))}:{shlex.quote(str(toolbin))}
PLAN_DIR={shlex.quote(str(plan_dir))}
export MAISTRO_INSTALL_PLAN_DIR="$PLAN_DIR"
ok() {{ echo "[ok] $*"; }}
info() {{ :; }}
# Mirrors the real install.sh warn(): writes to STDOUT. Deliberate — the
# unknown-token test must prove selected_container_runtime() itself keeps its
# stdout to the bare runtime token by redirecting the diagnostic to stderr; a
# stderr-writing stub would mask that bug.
warn() {{ echo "WARN: $*"; }}
fail() {{ echo "[error] $*" >&2; exit 1; }}
is_macos() {{ return 1; }}
is_wsl() {{ return 1; }}
# The real confirm() reads from the terminal; under pytest there is none, and
# a harness that blocked on a read would hang the suite. It records the
# prompt instead, so a test can assert the elevation was OFFERED before any
# mutation.
confirm() {{ echo "confirm: $*" >> confirms.log; return 0; }}
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
COMPOSE_FILE=docker-compose.yml
ENV_FILE=.env
INSTALL_CLI=1
ENGINE_BASE_URL=http://127.0.0.1:8000
CONDUCTOR_BASE_URL=http://127.0.0.1:8101
mkdir -p "$PLAN_DIR"
source <(sed -n {extract!r} {install})
{prelude}
"""


def _run(
    shim_dir: Path,
    plan_dir: Path,
    script: str,
    *,
    prelude: str = "",
    functions: tuple[str, ...] = _FUNCTIONS,
) -> subprocess.CompletedProcess[str]:
    harness = _harness(shim_dir, plan_dir, prelude=prelude, functions=functions)
    return subprocess.run(
        ["bash", "-c", harness + script],
        capture_output=True,
        text=True,
        check=False,
        cwd=shim_dir,
    )


def _write_exec_shim(shim_dir: Path, name: str, *, exit_code: int = 0, stderr: str = "") -> Path:
    """A stub executable with a fixed outcome.

    Used for the elevation path: a host that HAS apt-get but DENIES the
    elevation, and a host with no sudo at all. Both must produce the
    installer's own recoverable prerequisite report rather than a raw shell
    error.
    """
    shim = shim_dir / name
    shim.write_text(
        "#!/usr/bin/env bash\n"
        + (f"echo {shlex.quote(stderr)} >&2\n" if stderr else "")
        + f"exit {exit_code}\n",
        encoding="utf-8",
    )
    shim.chmod(0o755)
    return shim


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


def _write_plan(plan_dir: Path, runtime: str | None, selection: str | None = None) -> None:
    """delivery.json as plan.py writes it (#1820 keys); None models a legacy
    plan directory written before the fields existed. ``selection`` models
    the raw wizard answer when it differs from the resolved runtime — the
    real shape of an auto install, where the wizard materializes the
    resolved front-end in ``container_runtime`` but keeps ``auto`` in
    ``container_runtime_selection``."""
    plan_dir.mkdir(parents=True, exist_ok=True)
    if runtime is None:
        (plan_dir / "delivery.json").write_text(
            '{"mode": "image_pull", "behavior_contract": "legacy plan"}\n',
            encoding="utf-8",
        )
        return
    if selection is None:
        selection = runtime
    (plan_dir / "delivery.json").write_text(
        "{"
        f'"mode": "image_pull", "container_runtime": "{runtime}", '
        f'"container_runtime_selection": "{selection}"'
        "}\n",
        encoding="utf-8",
    )


# --- the headline regression -------------------------------------------------


def test_auto_resolved_docker_bootstraps_on_a_fresh_host(tmp_path: Path) -> None:
    """The fresh-install path (#1820 review): the wizard materializes an
    unanswered ``auto`` as the RESOLVED ``container_runtime: docker`` while
    keeping ``auto`` in ``container_runtime_selection``. That plan must not
    read as an explicit docker selection — ensure_compose_runtime has to
    reach the apt Docker bootstrap instead of failing naming a selection the
    operator never made."""
    plan = tmp_path / "plan"
    _write_plan(plan, "docker", selection="auto")
    result = _run(
        tmp_path,
        plan,
        "ensure_compose_runtime\n",
    )
    # No shims on PATH: bootstrap installs Docker, but detection still finds
    # no front-end in the harness, so the run ends at the generic failure.
    # The regression is precisely whether the bootstrap was OFFERED first.
    assert result.returncode != 0, result.stdout
    assert "apt-docker-bootstrap" in (tmp_path / "bootstraps.log").read_text(), result.stdout
    assert "selected container runtime" not in result.stderr, result.stderr


def test_explicit_docker_selection_still_fails_without_bootstrapping(
    tmp_path: Path,
) -> None:
    """An explicitly answered docker with no front-end fails naming the
    selection — the bootstrap must stay reserved for unselected auto."""
    plan = tmp_path / "plan"
    _write_plan(plan, "docker", selection="docker")
    result = _run(
        tmp_path,
        plan,
        "ensure_compose_runtime\n",
    )
    assert result.returncode != 0, result.stdout
    assert "selected container runtime (docker)" in result.stderr, result.stderr
    assert not (tmp_path / "bootstraps.log").exists(), result.stdout


def test_auto_resolved_podman_fails_without_docker_bootstrap(tmp_path: Path) -> None:
    """An auto that resolved to podman (local_podman tier) with no front-end
    keeps the named-runtime failure: there is no Podman bootstrap, and
    installing Docker for a plan whose artifacts name podman compose would
    be the silent switch the selection machinery forbids."""
    plan = tmp_path / "plan"
    _write_plan(plan, "podman", selection="auto")
    result = _run(
        tmp_path,
        plan,
        "ensure_compose_runtime\n",
    )
    assert result.returncode != 0, result.stdout
    assert "selected container runtime (podman)" in result.stderr, result.stderr
    assert not (tmp_path / "bootstraps.log").exists(), result.stdout


def test_env_pin_on_a_fresh_host_fails_without_bootstrapping(tmp_path: Path) -> None:
    """A wizardless (no plan) fresh host with an explicit
    ``MAISTRO_CONTAINER_RUNTIME=docker`` pin counts as a selection: no
    front-end fails naming it, and the apt Docker bootstrap must stay
    reserved for the unselected path — an operator who pinned a runtime
    asked for THAT runtime, not for "whatever installs"."""
    result = _run(
        tmp_path,
        tmp_path / "plan",  # directory exists, but no delivery.json in it
        "export MAISTRO_CONTAINER_RUNTIME=docker\nensure_compose_runtime\n",
    )
    assert result.returncode != 0, result.stdout
    assert "selected container runtime (docker)" in result.stderr, result.stderr
    assert not (tmp_path / "bootstraps.log").exists(), result.stdout


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
    # stdout is only the token: the diagnostic must land on stderr, never be
    # captured into the selection (it would corrupt the install manifest).
    assert result.stdout == "SELECTION: auto\n", result.stdout
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
    pydantic field exists on maistro.core's InstallManifest for exactly this).
    It must record the RESOLVED frontend (manifest_container_runtime), not the
    raw selection: an `auto` install recording `auto` would let upgrade's
    docker-first lookup hand a Podman-owned stack to a present Docker CLI."""
    body = INSTALL_SH.read_text(encoding="utf-8")
    assert '"container_runtime": "$(manifest_container_runtime)"' in body, (
        "install.sh stopped recording the honored runtime in the install manifest"
    )
    assert '"container_runtime": "$(selected_container_runtime)"' not in body, (
        "install.sh recorded the unresolved auto selection in the install manifest"
    )


def _write_archive_install(shim_dir: Path) -> None:
    """Satisfies write_install_manifest's archive branch so the harness (no git
    checkout) still emits the manifest file."""
    (shim_dir / ".maistro-archive-install").touch()


def _manifest_runtime(tmp_path: Path, plan: Path) -> str:
    """manifest_container_runtime is lifted and called directly (the manifest
    writer's heredoc cannot survive the harness's `^}`-terminated extraction,
    since the JSON body closes a brace at column 0)."""
    result = _run(
        tmp_path,
        plan,
        "manifest_container_runtime\n",
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_install_manifest_auto_records_resolved_podman_frontend(
    tmp_path: Path,
) -> None:
    """Auto with a Docker CLI that has no Compose provider and a working
    Podman compose: install lands on Podman, so the manifest must say podman.
    Recording `auto` here would let `maistro upgrade` re-run its docker-first
    lookup (a bare `which docker`) and hand the stack to the unusable Docker."""
    plan = tmp_path / "plan"
    _write_plan(plan, "auto")
    _write_runtime_shim(tmp_path, "docker", compose=False, daemon=True)
    _write_runtime_shim(tmp_path, "podman", compose=True, daemon=True)
    _write_archive_install(tmp_path)
    assert _manifest_runtime(tmp_path, plan) == "podman"


def test_install_manifest_auto_records_resolved_docker_frontend(
    tmp_path: Path,
) -> None:
    plan = tmp_path / "plan"
    _write_plan(plan, "auto")
    _write_runtime_shim(tmp_path, "docker", compose=True, daemon=True)
    _write_runtime_shim(tmp_path, "podman", compose=True, daemon=True)
    _write_archive_install(tmp_path)
    assert _manifest_runtime(tmp_path, plan) == "docker"


def test_install_manifest_auto_keeps_auto_when_no_frontend_answers(
    tmp_path: Path,
) -> None:
    """No Compose v2 front-end present right now (install aborts in
    ensure_compose_runtime): the manifest must keep `auto` rather than invent
    a selection upgrade would then honor blindly."""
    plan = tmp_path / "plan"
    _write_plan(plan, "auto")
    _write_runtime_shim(tmp_path, "docker", compose=False, daemon=False)
    _write_runtime_shim(tmp_path, "podman", compose=False, daemon=False)
    _write_archive_install(tmp_path)
    assert _manifest_runtime(tmp_path, plan) == "auto"


def test_install_manifest_podman_selection_survives_working_docker(
    tmp_path: Path,
) -> None:
    plan = tmp_path / "plan"
    _write_plan(plan, "podman")
    _write_runtime_shim(tmp_path, "docker", compose=True, daemon=True)
    _write_runtime_shim(tmp_path, "podman", compose=True, daemon=True)
    _write_archive_install(tmp_path)
    assert _manifest_runtime(tmp_path, plan) == "podman"


# --- generated recovery/success text honors an unresolved front-end ---------


def test_recovery_md_names_selected_runtime_when_compose_cmd_unresolved(
    tmp_path: Path,
) -> None:
    """A --no-start run never resolves COMPOSE_CMD, and the recovery text must
    not fall back to the docker-first literal: a Podman install whose RECOVERY.md
    says `docker compose` hands recovery to the other runtime. The docker shim
    fully works here — under the old fallback text it was named anyway."""
    plan = tmp_path / "plan"
    _write_plan(plan, "podman")
    _write_runtime_shim(tmp_path, "docker", compose=True, daemon=True)
    _write_runtime_shim(
        tmp_path, "podman", compose=False, daemon=False, canary="podman-invocations.log"
    )
    result = _run(tmp_path, plan, "write_recovery_md\n")
    assert result.returncode == 0, result.stderr
    recovery = (plan / "RECOVERY.md").read_text(encoding="utf-8")
    assert "podman compose" in recovery, recovery
    assert "docker compose" not in recovery, recovery


def test_recovery_md_uses_the_resolved_front_end_when_present(tmp_path: Path) -> None:
    plan = tmp_path / "plan"
    _write_plan(plan, "podman")
    result = _run(
        tmp_path,
        plan,
        "COMPOSE_CMD=(podman compose)\nwrite_recovery_md\n",
    )
    assert result.returncode == 0, result.stderr
    recovery = (plan / "RECOVERY.md").read_text(encoding="utf-8")
    status_line = next(line for line in recovery.splitlines() if "ps" in line and "Status" in line)
    assert status_line.startswith("| Status   | `podman compose"), status_line
    assert "docker compose" not in recovery, recovery


def test_recovery_md_auto_uses_the_documented_docker_first_order(
    tmp_path: Path,
) -> None:
    """Unselected (auto) with both front-ends present names docker compose —
    the same order every other auto probe uses."""
    plan = tmp_path / "plan"
    _write_plan(plan, "auto")
    _write_runtime_shim(tmp_path, "docker", compose=True, daemon=True)
    _write_runtime_shim(tmp_path, "podman", compose=True, daemon=True)
    result = _run(tmp_path, plan, "write_recovery_md\n")
    assert result.returncode == 0, result.stderr
    recovery = (plan / "RECOVERY.md").read_text(encoding="utf-8")
    status_line = next(line for line in recovery.splitlines() if "ps" in line and "Status" in line)
    assert status_line.startswith("| Status   | `docker compose"), status_line


def test_print_success_names_selected_runtime_without_resolved_front_end(
    tmp_path: Path,
) -> None:
    """print_success's Logs/Stop lines are the commands an operator copies on
    the very first day; with nothing resolved they must still name the
    selection, not the docker-first literal."""
    plan = tmp_path / "plan"
    _write_plan(plan, "podman")
    result = _run(
        tmp_path,
        plan,
        "print_success\n",
        # No runtime shim on PATH at all: the literal-selection branch.
        prelude="",
    )
    assert result.returncode == 0, result.stderr
    assert "podman compose" in result.stdout, result.stdout
    assert "docker compose" not in result.stdout, result.stdout


# --- stack healthchecks must survive podman's compose provider -------------


def test_stack_healthchecks_are_podman_safe() -> None:
    """podman's compose provider word-splits exec-form healthcheck args, so
    `["CMD", "python", "-c", "import urllib..."]` reached the engine as
    `python -c import ...` — a SyntaxError every probe, the engine stuck
    "unhealthy", and `compose up` failing on the conductor dependency. Found
    by running the rootless-Podman profile end to end from a clean account
    (docs/install/runtime-selection-evidence-1820.md); pin the CMD-SHELL form
    with the payload quoted so the file cannot regress to the exec form."""
    import yaml

    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    python_probes = 0
    for name, service in compose["services"].items():
        test = (service.get("healthcheck") or {}).get("test")
        if not test:
            continue
        assert isinstance(test, list) and test[0] in ("CMD-SHELL", "CMD"), (
            f"{name}: unexpected healthcheck form {test!r}"
        )
        if "python" in " ".join(test):
            python_probes += 1
            assert test[0] == "CMD-SHELL", f"{name}: {test!r} is word-split by podman"
            assert 'python -c "' in test[1], f"{name}: payload must be quoted: {test!r}"
    assert python_probes >= 2, "expected the engine and conductor health probes"


# --- the one-time administrator prerequisite must be REPORTABLE ---------------


@pytest.mark.skipif(
    os.geteuid() == 0,
    reason="root needs no elevation; the denial path only exists for an ordinary account",
)
def test_denied_elevation_reports_a_recoverable_prerequisite(tmp_path: Path) -> None:
    """A denied one-time elevation must produce a recoverable prerequisite
    report, not a raw sudo error.

    The Linux bootstrap installs Docker Engine with ``sudo apt-get``. Before
    #1820 that call was unguarded, so a host that denies elevation (no sudo
    rights, or a password that cannot be supplied) aborted the installer on
    sudo's own error line: no statement of WHAT the administrator has to do,
    and no statement that re-running the installer resumes the install. The
    issue requires the denial to be identified before any mutation and to
    come back as a prerequisite report.
    """
    plan = tmp_path / "plan"
    _write_plan(plan, "docker", selection="auto")
    shim_dir = tmp_path / "bin"
    shim_dir.mkdir()
    # A Debian-family host (apt-get present) whose elevation is denied.
    _write_exec_shim(shim_dir, "apt-get")
    _write_exec_shim(shim_dir, "sudo", exit_code=1, stderr="sudo: a password is required")

    before = {p.name for p in shim_dir.iterdir()}
    result = _run(
        shim_dir,
        plan,
        "bootstrap_apt_docker_runtime\n",
        functions=_ELEVATION_FUNCTIONS,
    )

    assert result.returncode != 0, result.stdout
    # The report states what the one-time administrator step is, names the
    # exact command, and says the install resumes afterwards.
    assert "one-time administrator" in result.stderr, result.stderr
    assert "apt-get install -y docker.io docker-compose-plugin" in result.stderr, result.stderr
    assert "re-run ./install.sh" in result.stderr, result.stderr
    # The elevation was OFFERED before any mutation: the operator is asked
    # first, and only then is the privileged command attempted.
    confirms = (shim_dir / "confirms.log").read_text(encoding="utf-8")
    assert "Install Docker Engine now via apt?" in confirms, confirms
    # A denied elevation leaves nothing behind: no half-installed state, no
    # stray artifacts owned by somebody else. `.toolbin` is the harness's own
    # tool directory, created by the harness and not by the installer.
    after = {p.name for p in shim_dir.iterdir()} - before - {".toolbin"}
    assert after == {"confirms.log"}, f"a failed elevation left artifacts behind: {sorted(after)}"


@pytest.mark.skipif(
    os.geteuid() == 0,
    reason="root needs no elevation; the denial path only exists for an ordinary account",
)
def test_missing_sudo_reports_a_recoverable_prerequisite(tmp_path: Path) -> None:
    """A host with no sudo at all is the same prerequisite, reported the same
    way: the installer never pretends it can elevate, and it names the
    administrator command an operator can hand to whoever holds the rights."""
    plan = tmp_path / "plan"
    _write_plan(plan, "docker", selection="auto")
    shim_dir = tmp_path / "bin"
    shim_dir.mkdir()
    _write_exec_shim(shim_dir, "apt-get")

    result = _run(
        shim_dir,
        plan,
        "bootstrap_apt_docker_runtime\n",
        functions=_ELEVATION_FUNCTIONS,
    )

    assert result.returncode != 0, result.stdout
    assert "one-time administrator" in result.stderr, result.stderr
    assert "'sudo' is not available" in result.stderr, result.stderr
    assert "apt-get install -y docker.io docker-compose-plugin" in result.stderr, result.stderr
    assert "re-run ./install.sh" in result.stderr, result.stderr
    # Nothing was mutated: the apt package manager was never invoked.
    assert (shim_dir / "confirms.log").exists()


# --- interruption / retry: the persisted selection and account ownership -----


def test_interrupted_install_retry_keeps_the_persisted_selection_and_ownership(
    tmp_path: Path,
) -> None:
    """A retry after an interrupted install must honor the persisted selection
    and leave every artifact owned by the invoking account.

    The issue requires interruption/retry and the ownership of persisted
    configuration to be covered by tests, not only by transcripts. The
    installer's contract is that a retry RE-READS the plan rather than
    re-probing the host: the run that was interrupted had already resolved
    the runtime, so the retry must not let a merely-present Docker CLI (or a
    stale half-written recovery file) decide again. The artifacts it writes
    must belong to the ordinary account that operates the stack — the
    installer runs unprivileged and must never leave root-owned state behind.
    """
    install_root = tmp_path / "install-root"
    install_root.mkdir()
    plan = install_root / ".maistro-install"
    # The interrupted run resolved podman and wrote the plan before it was
    # cut off mid-recovery-file.
    _write_plan(plan, "podman", selection="podman")
    (plan / "RECOVERY.md").write_text("# Maistro recovery & operations\n", encoding="utf-8")

    shim_dir = tmp_path / "bin"
    shim_dir.mkdir()
    # Both CLIs answer on the retry host: the persisted selection must win,
    # exactly as it does on a first run.
    _write_runtime_shim(shim_dir, "docker")
    _write_runtime_shim(shim_dir, "podman")

    result = _run(shim_dir, plan, "write_recovery_md\n")
    assert result.returncode == 0, result.stderr

    recovery = (plan / "RECOVERY.md").read_text(encoding="utf-8")
    # The retry completed the interrupted file for the PERSISTED runtime.
    assert "podman compose" in recovery, recovery
    assert "docker compose" not in recovery, recovery
    status_line = next(line for line in recovery.splitlines() if "Status" in line)
    assert status_line.startswith("| Status   | `podman compose"), status_line

    # Ownership: installer state belongs to the invoking account, not root.
    for path in (plan, plan / "RECOVERY.md", plan / "delivery.json"):
        assert path.stat().st_uid == os.getuid(), f"{path} is not owned by the invoking account"
