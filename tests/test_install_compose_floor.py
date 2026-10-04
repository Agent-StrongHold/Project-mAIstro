"""install.sh refuses compose front-ends that cannot parse/run the stack (#407).

The stack's compose schema — conditional ``depends_on``
(``service_healthy`` / ``service_completed_successfully``), healthcheck
wiring, secrets — is Compose v2 only. The legacy python ``docker-compose``
(v1, EOL) cannot parse it, and ``detect_compose_cmd`` used to fall back to
exactly that binary when no v2 front-end existed, advertising an engine that
would die mid-install. Since #407 there is no v1 fallback, a minimum v2
version is preflighted, and a front-end that hides its version string is
feature-probed against the real compose files instead of being trusted.

``release-installer.yml`` runs ``./install.sh`` only on tags, so no PR check
executes a line of the installer — the same gap tests/test_secret_env.py and
tests/test_install_engine_floor.py close for their paths. These tests lift
the real functions out of ``install.sh`` verbatim and run them against a stub
``docker`` binary, so a rewiring mistake fails a PR check instead of a
release.
"""

from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = ROOT / "install.sh"

#: The compose-floor functions, lifted verbatim from install.sh.
_FUNCTIONS = (
    "version_ge",
    "detect_compose_cmd",
    "compose_reported_version",
    "compose_upgrade_instructions",
    "ensure_compose_supported",
)

_REFUSED_BELOW_FLOOR = "Compose v2.17.0+ is required"


def _harness(shim_dir: Path, prelude: str = "", base_path: str = "$PATH") -> str:
    extract = ";".join(f"/^{name}()/,/^}}/p" for name in _FUNCTIONS)
    install = shlex.quote(str(INSTALL_SH))
    return f"""
set -euo pipefail
PATH={shlex.quote(str(shim_dir))}:{base_path}
ok() {{ echo "[ok] $*"; }}
info() {{ :; }}
warn() {{ echo "WARN: $*" >&2; }}
fail() {{ echo "[error] $*" >&2; exit 1; }}
is_macos() {{ return 1; }}
is_wsl() {{ return 1; }}
eval "$(grep -E '^MIN_COMPOSE_VERSION=' {install})"
source <(sed -n {extract!r} {install})
COMPOSE_CMD=()
COMPOSE_FILES=(-f "$(pwd)/docker-compose.yml")
{prelude}
"""


def _run(
    shim_dir: Path, script: str, *, prelude: str = "", base_path: str | None = None
) -> subprocess.CompletedProcess[str]:
    harness = _harness(shim_dir, prelude=prelude, base_path=base_path if base_path else "$PATH")
    (shim_dir / "docker-compose.yml").write_text(
        "services:\n  maistro-engine:\n    image: nginx\n", encoding="utf-8"
    )
    return subprocess.run(
        ["bash", "-c", harness + script],
        capture_output=True,
        text=True,
        check=False,
        cwd=shim_dir,
    )


def _write_docker_shim(
    shim_dir: Path,
    version_output: str | None = "Docker Compose version v2.39.2",
    *,
    compose_plugin: bool = True,
    config_rc: int = 0,
    config_error: str = "",
) -> None:
    """A stub `docker` binary implementing just the compose subcommand.

    `compose_plugin=False` models a Docker Engine installed without the
    compose plugin (`docker: 'compose' is not a docker command`);
    `version_output=None` models a front-end that answers nothing parseable.
    """
    lines = ["#!/usr/bin/env bash"]
    if compose_plugin:
        # The subcommand position varies (`docker compose version` vs
        # `docker compose -f x.yml config --quiet`), so scan the full argv.
        lines.append('case " $* " in')
        lines.append('    *" version "*)')
        if version_output is not None:
            lines.append(f"        echo {shlex.quote(version_output)}")
        lines.append("        exit 0")
        lines.append("        ;;")
        lines.append('    *" config "*)')
        if config_error:
            lines.append(f"        echo {shlex.quote(config_error)} >&2")
        lines.append(f"        exit {config_rc}")
        lines.append("        ;;")
        lines.append("esac")
        lines.append("exit 0")
    else:
        lines.append('if [[ "${1:-}" == "compose" ]]; then')
        lines.append("    echo \"docker: 'compose' is not a docker command.\" >&2")
        lines.append("    exit 1")
        lines.append("fi")
    lines.append("exit 0")
    shim = shim_dir / "docker"
    shim.write_text("\n".join(lines) + "\n", encoding="utf-8")
    shim.chmod(0o755)


def _write_legacy_v1_binary(shim_dir: Path) -> None:
    """The legacy python `docker-compose` v1 entry point, as on an old host."""
    legacy = shim_dir / "docker-compose"
    legacy.write_text("#!/usr/bin/env bash\necho 'docker-compose version 1.29.2, build 5becea4c'\n")
    legacy.chmod(0o755)


def test_the_floor_constant_is_present_and_pins_compose_2_17() -> None:
    body = INSTALL_SH.read_text(encoding="utf-8")
    match = re.search(r'^MIN_COMPOSE_VERSION="([0-9.]+)"$', body, re.M)
    assert match, "install.sh lost the MIN_COMPOSE_VERSION floor constant"
    assert match.group(1) == "2.17.0", (
        "the floor moved; revisit the refusal boundary tests alongside it"
    )


def test_detect_compose_cmd_never_selects_the_v1_spelling(tmp_path: Path) -> None:
    """A host whose only compose is the legacy v1 binary must find nothing —
    not fall back to an engine the stack's schema breaks on."""
    _write_docker_shim(tmp_path, compose_plugin=False)
    _write_legacy_v1_binary(tmp_path)
    result = _run(
        tmp_path,
        'if detect_compose_cmd; then echo "SELECTED: ${COMPOSE_CMD[*]}"; else echo NONE; fi\n',
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "NONE", result.stdout


def test_detect_compose_cmd_selects_the_v2_plugin(tmp_path: Path) -> None:
    _write_docker_shim(tmp_path)
    result = _run(
        tmp_path,
        'if detect_compose_cmd; then echo "SELECTED: ${COMPOSE_CMD[*]}"; else echo NONE; fi\n',
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "SELECTED: docker compose", result.stdout


@pytest.mark.parametrize(
    "reported",
    [
        "docker-compose version 1.29.2, build 5becea4c",  # the legacy engine itself
        "Docker Compose version v2.16.0",  # just below the floor
        "podman-compose version 1.0.6",  # the untested podman v1-generation engine
    ],
)
def test_below_floor_and_v1_engines_are_refused_with_upgrade_help(
    tmp_path: Path, reported: str
) -> None:
    _write_docker_shim(tmp_path, reported)
    result = _run(
        tmp_path,
        "COMPOSE_CMD=(docker compose)\nensure_compose_supported\n",
    )
    assert result.returncode != 0, result.stdout
    err = result.stderr
    assert _REFUSED_BELOW_FLOOR in err
    # The refusal names what was detected and how to get a supported engine.
    assert re.search(r"detected version \d+\.\d+", err)
    assert "docker-compose-plugin" in err or "Docker Desktop" in err
    assert "[ok]" not in result.stdout


@pytest.mark.parametrize(
    "reported",
    [
        "Docker Compose version v2.17.0",  # exactly the floor
        "Docker Compose version v2.24.6-desktop.1",  # provider-suffixed string
        "Docker Compose version v2.39.2",
        "v3.0.0",
    ],
)
def test_supported_versions_pass(tmp_path: Path, reported: str) -> None:
    _write_docker_shim(tmp_path, reported)
    result = _run(
        tmp_path,
        "COMPOSE_CMD=(docker compose)\nensure_compose_supported\n",
    )
    assert result.returncode == 0, result.stderr
    assert "[ok]" in result.stdout
    assert "meets the required minimum" in result.stdout
    assert "[error]" not in result.stderr


def test_an_unparseable_version_feature_detects_the_schema_parse(tmp_path: Path) -> None:
    """Version strings are unreliable across front-ends and providers; when
    none can be read, the stack's own compose files decide."""
    _write_docker_shim(tmp_path, version_output=None, config_rc=0)
    result = _run(
        tmp_path,
        "COMPOSE_CMD=(docker compose)\nensure_compose_supported\n",
    )
    assert result.returncode == 0, result.stderr
    assert "parses the stack compose files" in result.stderr
    assert "[error]" not in result.stderr


def test_an_unparseable_version_with_an_unparseable_schema_is_refused(
    tmp_path: Path,
) -> None:
    _write_docker_shim(
        tmp_path,
        version_output=None,
        config_rc=1,
        config_error="services.depends_on contains an invalid type, it should be an array",
    )
    result = _run(
        tmp_path,
        "COMPOSE_CMD=(docker compose)\nensure_compose_supported\n",
    )
    assert result.returncode != 0, result.stdout
    assert "could not be verified against the stack compose files" in result.stderr
    assert "conditional depends_on" in result.stderr
    assert "2.17.0" in result.stderr
    # The refusal surfaces the compose error itself, so a missing .env
    # variable is distinguishable from a v1-generation engine's schema gap.
    assert "services.depends_on contains an invalid type" in result.stderr
    assert "[ok]" not in result.stdout


def test_a_docker_engine_without_the_compose_plugin_is_refused(tmp_path: Path) -> None:
    """The v1-fallback regression, end to end: Engine without the plugin and a
    legacy `docker-compose` on PATH — the support gate refuses instead of
    running the stack with v1."""
    _write_docker_shim(tmp_path, compose_plugin=False)
    _write_legacy_v1_binary(tmp_path)
    result = _run(
        tmp_path,
        "COMPOSE_CMD=(docker compose)\nensure_compose_supported\n",
    )
    assert result.returncode != 0, result.stdout
    assert "could not be verified against the stack compose files" in result.stderr
    assert "docker-compose" not in result.stdout  # never advertised as the fix


@pytest.mark.parametrize(
    ("prelude", "expected_fragment"),
    [
        ("is_macos() { return 0; }", "update Docker Desktop"),
        ("is_wsl() { return 0; }", "WSL2"),
        ("", "On Linux"),
    ],
)
def test_upgrade_instructions_are_platform_specific(
    tmp_path: Path, prelude: str, expected_fragment: str
) -> None:
    result = _run(
        tmp_path,
        "compose_upgrade_instructions\n",
        prelude=prelude,
    )
    assert result.returncode == 0, result.stderr
    assert expected_fragment in result.stdout


def test_the_stack_start_sequence_gates_the_schema_before_up(tmp_path: Path) -> None:
    """ensure_compose_supported runs inside start_engine, after compose_files
    resolved the exact file set `up` will use, and before anything is built."""
    body = INSTALL_SH.read_text(encoding="utf-8")
    start = body.index("\nstart_engine() {")
    steps = body[start : body.index("\n}\n", start)]
    gate = steps.index("ensure_compose_supported")
    assert steps.index("compose_files") < gate, "gate must see the resolved COMPOSE_FILES"
    assert gate < steps.index("\n    report_arch\n")
    assert gate < steps.index('"${COMPOSE_UP_ARGS[@]}"'), "gate must run before `up`"
