"""install.sh polls and prints the one resolved port configuration (#361).

At the base this issue fixes, the installer resolved its ports from the
process environment only — ``PORT="${MAISTRO_PORT:-8000}"`` and inline
``${HIVE_PORT:-8101}`` — while Compose interpolated the same variables from
the process environment *and then the generated .env*. A port customized in
.env (the documented way to change it) started correctly and then failed
health polling and printed the wrong URL, because the installer probed the
port it assumed rather than the one Compose bound.

The fix gives the installer one resolution with Compose interpolation's own
precedence (process environment, then .env, then the default), reads the
published mapping back from compose before polling, and routes every
consumer — compose exports, health probes, the first-run bootstrap callback,
printed URLs — through that single resolved set, with diagnostics naming the
non-secret source of each port.

``release-installer.yml`` runs ``./install.sh`` only on tags, so no PR check
executes a line of the installer. Following the established verbatim-lift
pattern (tests/test_install_engine_floor.py, tests/test_secret_env.py), these
tests sed-extract the real functions out of ``install.sh`` and run them under
``set -euo pipefail`` against stub ``docker``/``curl`` binaries, so a rewiring
mistake fails a PR check instead of a user's install.
"""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = ROOT / "install.sh"

#: The port-configuration functions, lifted verbatim from install.sh.
_FUNCTIONS = (
    "env_get",
    "normalize_env_value",
    "setting_value",
    "setting_source",
    "validate_port_value",
    "normalize_bind_host",
    "http_base_url",
    "refresh_base_urls",
    "resolve_effective_config",
    "compose_published_port",
    "read_back_effective_ports",
    "http_ok",
    "wait_for_engine_health",
    "wait_for_conductor_health",
)


def _harness(env_file: Path, shim_dir: Path, script: str) -> str:
    extract = ";".join(f"/^{name}()/,/^}}/p" for name in _FUNCTIONS)
    install = shlex.quote(str(INSTALL_SH))
    return f"""
set -euo pipefail
PATH={shlex.quote(str(shim_dir))}:$PATH
ok() {{ echo "[ok] $*"; }}
info() {{ echo "[info] $*"; }}
warn() {{ echo "[warn] $*" >&2; }}
fail() {{ echo "[error] $*" >&2; exit 1; }}
# The http_ok fallback probe runs $PYTHON_CMD when curl fails; pin it to
# `false` so a stubbed-curl failure is deterministic and no test traffic
# reaches a real port on the machine running the suite.
PYTHON_CMD=(false)
COMPOSE_CMD=(docker compose)
COMPOSE_FILES=(-f docker-compose.yml)
ENV_FILE={shlex.quote(str(env_file))}
eval "$(sed -n {shlex.quote("/^DEFAULT_[A-Z_]*=/p")} {install})"
source <(sed -n {shlex.quote(extract)} {install})
{script}
"""


def _docker_shim(engine_port: str | None, conductor_port: str | None) -> str:
    """A stub docker whose `compose ... port <service> <n>` reports the given
    host mapping per service; `None` means the subcommand fails (container
    not up, unsupported front-end). Everything else exits 0."""
    engine = "1" if engine_port is None else "0"
    conductor = "1" if conductor_port is None else "0"
    engine_line = "" if engine_port is None else f"printf '%s\\n' \"127.0.0.1:{engine_port}\"; "
    conductor_line = (
        "" if conductor_port is None else f"printf '%s\\n' \"127.0.0.1:{conductor_port}\"; "
    )
    return f"""
if [[ "${{1:-}}" == "compose" ]]; then
    while [[ $# -gt 0 ]]; do
        if [[ "${{1:-}}" == "port" ]]; then
            case "${{2:-}}" in
                maistro-engine) {engine_line}exit {engine} ;;
                hive-conductor) {conductor_line}exit {conductor} ;;
            esac
            exit 1
        fi
        shift
    done
fi
exit 0
"""


def _curl_shim(tmp_path: Path, ok_suffix: str | None) -> Path:
    """A stub curl recording every requested URL into curl.log and succeeding
    only when the URL ends with ``ok_suffix``; None fails every request."""
    shim_dir = tmp_path / "shim"
    shim_dir.mkdir(exist_ok=True)
    curl = shim_dir / "curl"
    outcome = (
        "exit 1"
        if ok_suffix is None
        else f'case "$*" in *"{ok_suffix}"*) exit 0 ;; *) exit 1 ;; esac'
    )
    curl.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$*\" >> " + shlex.quote(str(tmp_path / "curl.log")) + "\n"
        f"{outcome}\n",
        encoding="utf-8",
    )
    curl.chmod(0o755)
    return curl


def _run(
    tmp_path: Path,
    script: str,
    *,
    env: dict[str, str] | None = None,
    env_file: str = "",
    docker: tuple[str | None, str | None] | None = None,
    curl_ok_suffix: str | None = None,
) -> subprocess.CompletedProcess[str]:
    shim_dir = tmp_path / "shim"
    shim_dir.mkdir(exist_ok=True)
    if docker is not None:
        stub = shim_dir / "docker"
        stub.write_text("#!/usr/bin/env bash\n" + _docker_shim(*docker) + "\n", encoding="utf-8")
        stub.chmod(0o755)
    # Always stub curl: a real curl pointed at a port some other process on
    # the machine occupies (and never answers) would hang the harness — the
    # same occupied-port hazard the installer itself must fail closed on.
    _curl_shim(tmp_path, curl_ok_suffix)
    env_file_path = tmp_path / ".env"
    env_file_path.write_text(env_file, encoding="utf-8")
    return subprocess.run(
        ["bash", "-c", _harness(env_file_path, shim_dir, script)],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": "/usr/bin:/bin", **(env or {})},
    )


def _requested_urls(tmp_path: Path) -> list[str]:
    log = tmp_path / "curl.log"
    if not log.exists():
        return []
    return [line.split()[-1] for line in log.read_text(encoding="utf-8").splitlines()]


# ---------------------------------------------------------------------------
# Structural pins: the wiring cannot silently regress to per-consumer ports.
# ---------------------------------------------------------------------------


def test_main_resolves_the_configuration_before_starting_the_stack() -> None:
    body = INSTALL_SH.read_text(encoding="utf-8")
    main_start = body.index("\nmain() {")
    main_body = body[main_start : body.index("\n}\n", main_start)]
    resolved_at = main_body.index("resolve_effective_config")
    for earlier in ("sync_env_file", "validate_env_contract"):
        assert main_body.index(earlier) < resolved_at, f"{earlier} must precede resolution"
    assert resolved_at < main_body.index("start_engine"), (
        "the resolved configuration must exist before start_engine runs"
    )


def test_start_engine_reads_the_mapping_back_before_polling() -> None:
    body = INSTALL_SH.read_text(encoding="utf-8")
    start = body.index("\nstart_engine() {")
    steps = body[start : body.index("\n}\n", start)]
    up_at = steps.index('"${COMPOSE_UP_ARGS[@]}"')
    read_back_at = steps.index("read_back_effective_ports")
    poll_at = steps.index("wait_for_engine_health")
    assert up_at < read_back_at < poll_at, (
        "start_engine must up, then read the published mapping back, then poll"
    )


def test_health_polling_and_printed_urls_use_the_resolved_configuration() -> None:
    """No consumer hand-builds a URL from BIND_HOST/PORT anymore: probes, the
    bootstrap callback, print_success, and the browser open all read the one
    resolved configuration."""
    body = INSTALL_SH.read_text(encoding="utf-8")
    assert "http://${BIND_HOST}" not in body, (
        "URLs must come from the resolved configuration (http_base_url), not "
        "be hand-built from the process environment"
    )
    for function, variable in (
        ("wait_for_engine_health", "${ENGINE_BASE_URL}"),
        ("wait_for_conductor_health", "${CONDUCTOR_BASE_URL}"),
        ("bootstrap_first_run", "$CONDUCTOR_BASE_URL"),
        ("print_success", "${ENGINE_BASE_URL}"),
        ("open_browser", "$CONDUCTOR_BASE_URL"),
    ):
        start = body.index(f"\n{function}() {{")
        fn_body = body[start : body.index("\n}\n", start)]
        assert variable in fn_body, f"{function} must use the resolved {variable}"


def test_the_conductor_port_has_one_declared_default() -> None:
    """Every read of the Conductor port goes through the resolution: the 8101
    literal lives in DEFAULT_CONDUCTOR_PORT only, and no consumer carries an
    ad-hoc ':-8101' fallback anymore."""
    body = INSTALL_SH.read_text(encoding="utf-8")
    assert body.count('DEFAULT_CONDUCTOR_PORT="8101"') == 1
    assert ":-8101" not in body, (
        "HIVE_PORT must be read through setting_value(); an ad-hoc default "
        "reintroduces the split configuration #361 closes"
    )


# ---------------------------------------------------------------------------
# Resolution precedence: process environment, then .env, then the default —
# the same order Compose interpolation uses (#361 acceptance criterion 3).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("env", "env_file", "expected", "expected_source"),
    [
        ({}, "MAISTRO_PORT=9001\n", "9001", ".env MAISTRO_PORT"),
        ({"MAISTRO_PORT": "9002"}, "MAISTRO_PORT=9001\n", "9002", "environment MAISTRO_PORT"),
        ({}, "", "8000", "default"),
        ({}, "MAISTRO_PORT=9001 # engine\n", "9001", ".env MAISTRO_PORT"),
        ({}, 'MAISTRO_PORT="9001"\n', "9001", ".env MAISTRO_PORT"),
        ({}, "MAISTRO_PORT=\n", "8000", "default"),
    ],
)
def test_engine_port_resolution_follows_compose_precedence(
    tmp_path: Path,
    env: dict[str, str],
    env_file: str,
    expected: str,
    expected_source: str,
) -> None:
    script = (
        'printf \'%s|%s\\n\' "$(setting_value MAISTRO_PORT "$DEFAULT_ENGINE_PORT")" '
        '"$(setting_source MAISTRO_PORT)"'
    )
    result = _run(tmp_path, script, env=env, env_file=env_file)
    assert result.returncode == 0, result.stderr
    assert result.stdout == f"{expected}|{expected_source}\n"


def test_a_port_customized_only_in_the_env_file_is_resolved(tmp_path: Path) -> None:
    """The exact #361 failure: port customized in .env, nothing exported.
    The old installer polled 8000 (false health failure, wrong printed URL);
    the resolution must see 9001, where Compose binds the stack."""
    result = _run(tmp_path, "resolve_effective_config", env_file="MAISTRO_PORT=9001\n")
    assert result.returncode == 0, result.stderr
    assert "[info] Engine port 9001 (source: .env MAISTRO_PORT)" in result.stdout


@pytest.mark.parametrize(
    ("env", "env_file", "expected", "expected_source"),
    [
        ({}, "HIVE_PORT=9101\n", "9101", ".env HIVE_PORT"),
        ({"HIVE_PORT": "9102"}, "HIVE_PORT=9101\n", "9102", "environment HIVE_PORT"),
        ({}, "", "8101", "default"),
    ],
)
def test_conductor_port_resolution_follows_compose_precedence(
    tmp_path: Path,
    env: dict[str, str],
    env_file: str,
    expected: str,
    expected_source: str,
) -> None:
    result = _run(tmp_path, "resolve_effective_config", env=env, env_file=env_file)
    assert result.returncode == 0, result.stderr
    assert f"[info] Conductor port {expected} (source: {expected_source})" in result.stdout


def test_resolution_prints_the_non_secret_source_of_every_port(tmp_path: Path) -> None:
    """#361 acceptance criterion: diagnostics name where each port came from.
    Ports and bind addresses are configuration, not credentials — printed in
    full alongside their source."""
    result = _run(
        tmp_path,
        "resolve_effective_config",
        env={"MAISTRO_PORT": "9002"},
        env_file="HIVE_PORT=9101\n",
    )
    assert result.returncode == 0, result.stderr
    assert "(source: environment MAISTRO_PORT)" in result.stdout
    assert "(source: .env HIVE_PORT)" in result.stdout
    assert "(source: default)" in result.stdout  # MAISTRO_BIND_HOST


def test_resolution_exports_the_effective_values_for_the_compose_invocation(
    tmp_path: Path,
) -> None:
    """The compose child must interpolate exactly what the installer resolved,
    so the mapping it binds and the probes that follow cannot diverge."""
    result = _run(
        tmp_path,
        'resolve_effective_config > /dev/null; printf \'%s|%s|%s\\n\' "$MAISTRO_PORT" "$HIVE_PORT" "$MAISTRO_BIND_HOST"',
        env={"MAISTRO_PORT": "9002", "MAISTRO_BIND_HOST": "0.0.0.0"},
        env_file="HIVE_PORT=9101\n",
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.endswith("9002|9101|0.0.0.0\n")


# ---------------------------------------------------------------------------
# Fail-closed validation: a bad port names its source instead of surfacing
# later as a false health failure or a wrong printed URL.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["abc", "0", "65536", "-1", "80.5"])
def test_an_invalid_port_from_the_environment_fails_naming_its_source(
    tmp_path: Path, bad: str
) -> None:
    result = _run(tmp_path, "resolve_effective_config", env={"MAISTRO_PORT": bad})
    assert result.returncode != 0, result.stdout
    assert "MAISTRO_PORT" in result.stderr
    assert "(source: environment MAISTRO_PORT)" in result.stderr
    assert "expected a number between 1 and 65535" in result.stderr


def test_an_invalid_port_in_the_env_file_fails_naming_the_env_file_source(
    tmp_path: Path,
) -> None:
    result = _run(tmp_path, "resolve_effective_config", env_file="HIVE_PORT=http\n")
    assert result.returncode != 0, result.stdout
    assert "(source: .env HIVE_PORT)" in result.stderr


@pytest.mark.parametrize("edge", ["1", "65535"])
def test_valid_port_boundaries_are_accepted(tmp_path: Path, edge: str) -> None:
    result = _run(tmp_path, "resolve_effective_config", env={"MAISTRO_PORT": edge})
    assert result.returncode == 0, result.stderr
    assert f"[info] Engine port {edge} " in result.stdout


# ---------------------------------------------------------------------------
# IPv4/IPv6 and custom bind addresses (#361 acceptance criterion 4).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "normalized"),
    [
        ("127.0.0.1", "127.0.0.1"),
        ("0.0.0.0", "0.0.0.0"),
        ("::1", "[::1]"),
        ("[::1]", "[::1]"),
        ("proxy.internal", "proxy.internal"),
    ],
)
def test_bind_host_normalization_brackets_only_bare_ipv6(
    tmp_path: Path, raw: str, normalized: str
) -> None:
    result = _run(tmp_path, "resolve_effective_config", env={"MAISTRO_BIND_HOST": raw})
    assert result.returncode == 0, result.stderr
    assert f"[info] Engine bind address {normalized} " in result.stdout


@pytest.mark.parametrize(
    ("host", "port", "url"),
    [
        ("127.0.0.1", "8000", "http://127.0.0.1:8000"),
        ("[::1]", "9001", "http://[::1]:9001"),
        ("::1", "9001", "http://[::1]:9001"),
        ("0.0.0.0", "8000", "http://0.0.0.0:8000"),
    ],
)
def test_base_urls_bracket_ipv6_literals(tmp_path: Path, host: str, port: str, url: str) -> None:
    script = f"printf '%s\\n' \"$(http_base_url {shlex.quote(host)} {shlex.quote(port)})\""
    result = _run(tmp_path, script)
    assert result.returncode == 0, result.stderr
    assert url in result.stdout


# ---------------------------------------------------------------------------
# Read-back: poll what compose actually bound (#361 acceptance criterion 2),
# including an override remap — the mechanism a reverse-proxy-fronted
# deployment exercises (public port differs from the configured one).
# ---------------------------------------------------------------------------


def test_read_back_overrides_the_resolved_port_before_polling(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        "resolve_effective_config > /dev/null; read_back_effective_ports",
        env_file="MAISTRO_PORT=9001\n",
        docker=("127.0.0.1:9005", "127.0.0.1:9105"),
    )
    assert result.returncode == 0, result.stderr
    assert (
        "[info] Probing engine at http://127.0.0.1:9005 and Conductor at "
        "http://127.0.0.1:9105." in result.stdout
    )
    assert "[warn]" not in result.stderr


def test_a_failed_read_back_falls_back_to_the_resolution_and_says_so(
    tmp_path: Path,
) -> None:
    result = _run(
        tmp_path,
        "resolve_effective_config > /dev/null; read_back_effective_ports",
        env_file="MAISTRO_PORT=9001\nHIVE_PORT=9101\n",
        docker=(None, None),
    )
    assert result.returncode == 0, result.stderr
    assert (
        "[warn] Could not read the engine's published port back from compose; "
        "polling the resolved configuration (9001)." in result.stderr
    )
    assert (
        "[warn] Could not read the Conductor's published port back from compose; "
        "polling the resolved configuration (9101)." in result.stderr
    )
    assert (
        "[info] Probing engine at http://127.0.0.1:9001 and Conductor at "
        "http://127.0.0.1:9101." in result.stdout
    )


def test_health_polling_hits_the_mapping_compose_actually_bound(tmp_path: Path) -> None:
    """End-to-end at function level: .env says 9001, but an override (or a
    reverse-proxy front) publishes 9005 — the poll must go to 9005, proving
    probes follow the effective mapping, not the process environment."""
    result = _run(
        tmp_path,
        (
            "resolve_effective_config > /dev/null 2>&1; "
            "read_back_effective_ports > /dev/null 2>&1; wait_for_engine_health"
        ),
        env_file="MAISTRO_PORT=9001\n",
        docker=("127.0.0.1:9005", "127.0.0.1:9105"),
        curl_ok_suffix=":9005/health",
    )
    assert result.returncode == 0, result.stderr
    assert "[ok] Engine healthy." in result.stdout
    requested = _requested_urls(tmp_path)
    assert any(":9005/health/live" in url for url in requested), requested
    assert not any(":9001/" in url for url in requested), requested


def test_the_conductor_probe_hits_its_own_resolved_port(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        "resolve_effective_config > /dev/null 2>&1; wait_for_conductor_health",
        env_file="MAISTRO_PORT=9000\nHIVE_PORT=9101\n",
        docker=("127.0.0.1:9000", "127.0.0.1:9101"),
        curl_ok_suffix=":9101/health/ready",
    )
    assert result.returncode == 0, result.stderr
    assert "[ok] Conductor healthy." in result.stdout
    requested = _requested_urls(tmp_path)
    assert any(":9101/health/ready" in url for url in requested), requested
    assert not any(":8101/" in url for url in requested), requested


def test_an_unreachable_engine_fails_with_the_compose_log_pointer(
    tmp_path: Path,
) -> None:
    """The occupied-port / never-healthy terminal path: 61 failed probes end
    in the fail-closed message naming the compose logs command. `sleep` is
    shadowed so the bounded retry loop runs instantly."""
    result = _run(
        tmp_path,
        (
            "sleep() { :; }; resolve_effective_config > /dev/null 2>&1; "
            "read_back_effective_ports > /dev/null 2>&1; wait_for_engine_health"
        ),
        env_file="MAISTRO_PORT=9001\n",
        docker=(None, None),
        curl_ok_suffix=None,
    )
    assert result.returncode != 0, result.stdout
    assert "Engine did not become healthy" in result.stderr
    assert "logs maistro-engine" in result.stderr


def test_two_concurrent_installs_resolve_disjoint_configurations(tmp_path: Path) -> None:
    """Multiple concurrent installs (#361 acceptance criterion 4): each
    install directory's .env resolves to its own ports, and nothing bleeds
    from one resolution into the next."""
    first = _run(
        tmp_path,
        'resolve_effective_config > /dev/null; printf \'%s|%s\\n\' "$ENGINE_PORT" "$CONDUCTOR_PORT"',
        env_file="MAISTRO_PORT=9001\nHIVE_PORT=9101\n",
    )
    second = _run(
        tmp_path,
        'resolve_effective_config > /dev/null; printf \'%s|%s\\n\' "$ENGINE_PORT" "$CONDUCTOR_PORT"',
        env_file="MAISTRO_PORT=9201\nHIVE_PORT=9301\n",
    )
    assert first.returncode == 0 and second.returncode == 0, first.stderr + second.stderr
    assert first.stdout.strip() == "9001|9101"
    assert second.stdout.strip() == "9201|9301"
