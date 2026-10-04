"""install.sh reconciles docker-compose.override.yml with its Compose invocation (#405).

At the develop this issue landed on, every installer compose call passed
explicit ``-f`` files (``-f docker-compose.yml``, or
``--project-directory … -f <plan>/compose.install.yml`` for image_pull, plus
the wizard's ``<plan>/compose.override.yml`` when materialized). Explicit
``-f`` disables Compose's own automatic ``docker-compose.override.yml``
loading, so an override an operator copied into the checkout — the exact
workflow three doc sites documented, including the docker-socket opt-in —
was silently ignored on installer runs while being honored by a bare
``docker compose up``.

The decision recorded here: the root override **is** a supported automatic
input. ``compose_files`` now includes it explicitly, last (operator intent
outranks the base file and the wizard's plan override), in both delivery
modes — but only after refusing a file the invoking user does not
exclusively control: an override can remap ports, disable sandbox flags, or
mount the host Docker socket, so group/world-writable or foreign-owned
override is a local privilege-escalation path and aborts the install.

Following the verbatim-lift pattern from ``tests/test_install_docker_sock.py``,
these tests source the real functions out of ``install.sh`` and drive them
against a stub ``docker`` binary that records its argv, plus one integration
test that renders the real repo compose file through the real Docker Compose
frontend using the exact documented invocation (skipped where no compose
front-end exists, e.g. CI containers without Docker).
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = ROOT / "install.sh"

#: compose_files and everything it (or show_compose_plan) calls, lifted
#: verbatim from install.sh.
_FUNCTIONS = (
    "ensure_python",
    "delivery_mode",
    "effective_delivery_mode",
    "override_file_is_safe",
    "override_file_state",
    "require_safe_override_file",
    "compose_files",
    "show_compose_plan",
)

RENDER_SENTINEL = "RENDERED-CONFIG-SENTINEL"


def _harness(shim_dir: Path) -> str:
    extract = ";".join(f"/^{name}()/,/^}}/p" for name in _FUNCTIONS)
    install = shlex.quote(str(INSTALL_SH))
    return f"""
set -euo pipefail
PATH={shlex.quote(str(shim_dir))}:$PATH
ok() {{ echo "OK: $*"; }}
info() {{ echo "INFO: $*"; }}
warn() {{ echo "WARN: $*" >&2; }}
fail() {{ echo "[error] $*" >&2; exit 1; }}
SCRIPT_DIR={str(ROOT)!r}
ENV_FILE=".env"
# Left empty on purpose: ensure_python must probe (and announce) for real in
# test_require_safe_override_file_survives_the_ensure_python_probe, which
# pins the capture bug this suite exists to keep dead. Tests that assert
# exact stdout read through _printed_lines, which filters the announcement.
PYTHON_CMD=()
COMPOSE_FILE="docker-compose.yml"
PLAN_DIR="${{MAISTRO_INSTALL_PLAN_DIR:-.maistro-install}}"
MAISTRO_IMAGE_TAG="test-tag"
COMPOSE_CMD=("docker" "compose")
source <(sed -n {extract!r} {install})
"""


def _write_compose_shim(shim_dir: Path) -> None:
    """A stub `docker` that records argv (one arg per line, blocks separated
    by `--`) and exits MAISTRO_TEST_COMPOSE_RC when that is set non-zero.
    A final `config` argument also gets a sentinel on stdout, so tests can
    tell a rendered-config dump from the `>/dev/null` validation pass."""
    shim = shim_dir / "docker"
    shim.write_text(
        "#!/usr/bin/env bash\n"
        'printf \'%s\\n\' "$@" >> "${MAISTRO_TEST_COMPOSE_LOG:?}"\n'
        "printf -- '--\\n' >> \"${MAISTRO_TEST_COMPOSE_LOG:?}\"\n"
        'if [[ "${MAISTRO_TEST_COMPOSE_RC:-0}" != "0" ]]; then\n'
        '    exit "${MAISTRO_TEST_COMPOSE_RC}"\n'
        "fi\n"
        'if [[ "${!#}" == "config" ]]; then\n'
        f'    echo "{RENDER_SENTINEL}"\n'
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    shim.chmod(0o755)


def _run(
    tmp_path: Path,
    script: str,
    *,
    env_extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    shim_dir = tmp_path / "bin"
    shim_dir.mkdir(exist_ok=True)
    _write_compose_shim(shim_dir)
    env = dict(os.environ)
    env["MAISTRO_TEST_COMPOSE_LOG"] = str(tmp_path / "compose-invocations.log")
    env.pop("MAISTRO_COMPOSE_PROFILES", None)
    env.pop("MAISTRO_PRINT_COMPOSE_CONFIG", None)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["bash", "-c", _harness(shim_dir) + script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _invocations(tmp_path: Path) -> list[list[str]]:
    log = tmp_path / "compose-invocations.log"
    blocks = log.read_text(encoding="utf-8").split("--\n") if log.exists() else []
    return [[line for line in block.splitlines() if line] for block in blocks if block.strip()]


def _printed_lines(result: subprocess.CompletedProcess[str]) -> list[str]:
    """The script's own printf output, excluding the installer's info/ok
    chatter (info() writes to the same captured stdout)."""
    return [
        line
        for line in result.stdout.splitlines()
        if not line.startswith(("INFO: ", "OK: ", "WARN: "))
    ]


def _write_override(tmp_path: Path, body: str = "services: {}\n", mode: int = 0o644) -> Path:
    path = tmp_path / "docker-compose.override.yml"
    path.write_text(body, encoding="utf-8")
    path.chmod(mode)
    return path


def _compose_files_list(tmp_path: Path, **kwargs: str) -> list[str]:
    result = _run(
        tmp_path,
        "compose_files\nprintf '%s\\n' \"${COMPOSE_FILES[@]}\"\n",
        env_extra=kwargs,
    )
    assert result.returncode == 0, result.stderr
    return _printed_lines(result)


def test_a_root_override_is_included_explicitly(tmp_path: Path) -> None:
    """The regression pin: with the override present, the file set the
    installer runs is the base plus the override — not the base alone, which
    is what the explicit `-f` invocation silently produced before #405."""
    _write_override(tmp_path)
    files = _compose_files_list(tmp_path)
    assert files == ["-f", "docker-compose.yml", "-f", "docker-compose.override.yml"]


def test_a_root_override_does_not_disturb_the_up_args(tmp_path: Path) -> None:
    """Adding the override must not silently flip the delivery mode: the
    source build still comes with `up -d --build`."""
    _write_override(tmp_path)
    result = _run(
        tmp_path,
        "compose_files\nprintf '%s\\n' \"${COMPOSE_UP_ARGS[@]}\"\n",
    )
    assert result.returncode == 0, result.stderr
    assert _printed_lines(result) == ["up", "-d", "--build"]


def test_an_absent_override_leaves_the_invocation_unchanged(tmp_path: Path) -> None:
    """No override file — exactly the pre-#405 invocation, byte for byte."""
    assert not (tmp_path / "docker-compose.override.yml").exists()
    files = _compose_files_list(tmp_path)
    assert files == ["-f", "docker-compose.yml"]


def test_the_wizard_plan_override_applies_before_the_root_override(
    tmp_path: Path,
) -> None:
    """Compose merges later files over earlier ones, so ordering is the
    precedence contract: the wizard's generated override first, the
    operator's manual override last (operator intent outranks the plan)."""
    plan = tmp_path / "plan"
    plan.mkdir()
    (plan / "compose.override.yml").write_text("services: {}\n", encoding="utf-8")
    (plan / "compose.override.yml").chmod(0o644)
    _write_override(tmp_path)
    files = _compose_files_list(tmp_path, MAISTRO_INSTALL_PLAN_DIR="plan")
    assert files == [
        "-f",
        "docker-compose.yml",
        "-f",
        "plan/compose.override.yml",
        "-f",
        "docker-compose.override.yml",
    ]


def test_the_root_override_reaches_image_pull_delivery_too(tmp_path: Path) -> None:
    """The divergence was worst in image_pull mode: the invocation is
    `--project-directory … -f <plan>/compose.install.yml`, which auto-loads
    nothing at all. The override must land there too, after the base file,
    with the mode's own `up -d` args intact."""
    plan = tmp_path / ".maistro-install"
    plan.mkdir()
    (plan / "delivery.json").write_text('{"mode": "image_pull"}\n', encoding="utf-8")
    (plan / "compose.install.yml").write_text("services: {}\n", encoding="utf-8")
    _write_override(tmp_path)
    result = _run(
        tmp_path,
        'compose_files\nprintf \'%s\\n\' "${COMPOSE_FILES[@]}" "${COMPOSE_UP_ARGS[@]}"\n',
        env_extra={"MAISTRO_IMAGE_PULL_READY": "1"},
    )
    assert result.returncode == 0, result.stderr
    assert _printed_lines(result) == [
        "--project-directory",
        os.path.realpath(tmp_path),
        "-f",
        ".maistro-install/compose.install.yml",
        "-f",
        "docker-compose.override.yml",
        "up",
        "-d",
    ]


@pytest.mark.parametrize("mode", [0o666, 0o664, 0o646])
def test_a_writable_by_others_override_is_refused(tmp_path: Path, mode: int) -> None:
    """An override can remap ports, disable sandbox flags, or mount the host
    Docker socket. Group/world-writable means any local user can rewrite what
    `up` runs, so the install aborts with remediation instead of proceeding —
    proceeding without the file would just recreate the silent divergence."""
    _write_override(tmp_path, mode=mode)
    result = _run(tmp_path, "compose_files\n")
    assert result.returncode == 1
    assert "group/world-writable" in result.stderr
    assert "chmod go-w" in result.stderr
    assert "docker-compose.override.yml" in result.stderr


def test_the_safety_decision_is_exact_over_mode_and_owner(tmp_path: Path) -> None:
    """The pure decision, over every boundary: owner-writable-only modes are
    fine, any group/other write bit is not, and a foreign owner is refused
    even at 0644 (the owner could chmod it back)."""
    script = """
declare -a cases=("600:$EUID" "644:$EUID" "0400:$EUID" "666:$EUID" "664:$EUID" "646:$EUID" "644:4242" "602:$EUID")
for c in "${cases[@]}"; do
    if override_file_is_safe "${c%%:*}" "${c##*:}"; then
        echo "SAFE ${c}"
    else
        echo "UNSAFE ${c}"
    fi
done
"""
    result = _run(tmp_path, script)
    assert result.returncode == 0, result.stderr
    euid = os.geteuid()
    assert result.stdout.splitlines() == [
        f"SAFE 600:{euid}",
        f"SAFE 644:{euid}",
        f"SAFE 0400:{euid}",
        f"UNSAFE 666:{euid}",
        f"UNSAFE 664:{euid}",
        f"UNSAFE 646:{euid}",
        "UNSAFE 644:4242",
        f"UNSAFE 602:{euid}",
    ]


def test_a_dangling_override_symlink_is_refused_not_skipped(tmp_path: Path) -> None:
    """`[[ -f ]]` is false for a dangling symlink, so a naive existence check
    would silently drop the operator's override again. The installer checks
    -e/-L and fails loudly when the path cannot be stat'ed instead."""
    os.symlink(tmp_path / "nowhere", tmp_path / "docker-compose.override.yml")
    result = _run(tmp_path, "compose_files\n")
    assert result.returncode == 1
    assert "Cannot inspect" in result.stderr


def test_a_foreign_owned_override_is_refused(tmp_path: Path) -> None:
    """Ownership is part of the contract. A chown needs privileges, so this
    only executes the real stat+decision path where it can; where it cannot,
    test_the_safety_decision_is_exact_over_mode_and_owner covers the
    foreign-owner branch at the decision level."""
    override = _write_override(tmp_path)
    try:
        os.chown(override, 65534, -1)  # nobody, where permitted
    except PermissionError:
        pytest.skip("chown to another uid requires privileges")
    result = _run(tmp_path, "compose_files\n")
    assert result.returncode == 1
    assert "owned by uid" in result.stderr


def test_multiple_profiles_are_activated_in_order(tmp_path: Path) -> None:
    """MAISTRO_COMPOSE_PROFILES feeds `--profile` flags onto every compose
    call: an override that assigns services to profiles starts nothing while
    its profiles are inactive. Comma and space separators both work."""
    assert _compose_files_list(tmp_path, MAISTRO_COMPOSE_PROFILES="llm,data") == [
        "--profile",
        "llm",
        "--profile",
        "data",
        "-f",
        "docker-compose.yml",
    ]
    assert _compose_files_list(tmp_path, MAISTRO_COMPOSE_PROFILES="llm data") == [
        "--profile",
        "llm",
        "--profile",
        "data",
        "-f",
        "docker-compose.yml",
    ]


def test_empty_profile_entries_are_dropped(tmp_path: Path) -> None:
    """Trailing separators and doubled commas must not produce empty
    `--profile ""` arguments that the compose front-end would reject."""
    assert _compose_files_list(tmp_path, MAISTRO_COMPOSE_PROFILES=",llm,,") == [
        "--profile",
        "llm",
        "-f",
        "docker-compose.yml",
    ]


def test_require_safe_override_file_survives_the_ensure_python_probe(
    tmp_path: Path,
) -> None:
    """Regression pin for a bug the end-to-end smoke run caught after the
    harness-based tests passed: ensure_python announces itself through ok(),
    and when that call sat inside the $(override_file_state ...) command
    substitution, its announcement was captured as if it were the stat data —
    the refusal then quoted "uid Python found: 3.14.4". ensure_python now
    runs outside the substitution; with the probe really happening (empty
    PYTHON_CMD, real PATH probe), the parsed mode must still be exact."""
    _write_override(tmp_path, mode=0o664)
    result = _run(tmp_path, "require_safe_override_file docker-compose.override.yml\n")
    assert result.returncode == 1
    assert "group/world-writable (mode 0664)" in result.stderr
    # The probe's announcement went to the installer's output, not into the
    # captured stat data (it would otherwise have corrupted the message).
    assert "Python found" in result.stdout
    assert "Python found" not in result.stderr


def test_show_compose_plan_prints_files_and_profiles_and_validates(
    tmp_path: Path,
) -> None:
    """Before startup the operator sees the exact invocation, each effective
    file, each active profile — and the merged render is validated by a real
    `config` pass through the selected compose front-end."""
    _write_override(tmp_path)
    result = _run(
        tmp_path,
        "compose_files\nshow_compose_plan\n",
        env_extra={"MAISTRO_COMPOSE_PROFILES": "llm,data"},
    )
    assert result.returncode == 0, result.stderr
    assert (
        "Effective Compose invocation: docker compose --profile llm --profile data" in result.stdout
    )
    assert "Compose file: docker-compose.yml" in result.stdout
    assert "Compose file: docker-compose.override.yml" in result.stdout
    assert "Active profile: llm" in result.stdout
    assert "Active profile: data" in result.stdout
    assert "Rendered Compose config validated before startup." in result.stdout
    # The validation is a real `config` invocation over the full file set…
    (only,) = _invocations(tmp_path)
    assert only == [
        "compose",
        "--profile",
        "llm",
        "--profile",
        "data",
        "-f",
        "docker-compose.yml",
        "-f",
        "docker-compose.override.yml",
        "config",
    ]
    # …whose stdout is discarded, so the rendered config does not leak by default.
    assert RENDER_SENTINEL not in result.stdout


def test_show_compose_plan_fails_loudly_when_the_render_fails(
    tmp_path: Path,
) -> None:
    """A bad override must fail at the validation step, naming the exact
    command, instead of surfacing as a half-started stack after `up`."""
    _write_override(tmp_path, body="services:\n  ???broken\n")
    result = _run(
        tmp_path,
        "compose_files\nshow_compose_plan\n",
        env_extra={"MAISTRO_TEST_COMPOSE_RC": "1"},
    )
    assert result.returncode == 1
    assert "Rendered Compose config failed validation" in result.stderr
    assert "config" in result.stderr


def test_the_rendered_config_prints_only_on_explicit_opt_in(tmp_path: Path) -> None:
    """MAISTRO_PRINT_COMPOSE_CONFIG=1 prints the merged render — with a
    warning, because every value interpolated from .env (credentials
    included) appears in it. Unset, nothing is printed."""
    _write_override(tmp_path)
    quiet = _run(tmp_path, "compose_files\nshow_compose_plan\n")
    assert quiet.returncode == 0, quiet.stderr
    assert RENDER_SENTINEL not in quiet.stdout
    assert "credentials" not in quiet.stderr

    loud = _run(
        tmp_path,
        "compose_files\nshow_compose_plan\n",
        env_extra={"MAISTRO_PRINT_COMPOSE_CONFIG": "1"},
    )
    assert loud.returncode == 0, loud.stderr
    assert RENDER_SENTINEL in loud.stdout
    assert "credentials" in loud.stderr


def _compose_available() -> bool:
    docker = shutil.which("docker")
    if docker is None:
        return False
    probe = subprocess.run(
        ["docker", "compose", "version"],
        capture_output=True,
        check=False,
    )
    return probe.returncode == 0


@pytest.mark.skipif(not _compose_available(), reason="no docker compose front-end")
def test_the_documented_invocation_renders_the_real_stack(tmp_path: Path) -> None:
    """End to end, against the real Docker Compose frontend: the exact
    installer invocation with the documented docker-socket override body —
    the file whose doc comment promised "picked up automatically" — merges
    and renders. This is the acceptance proof that the documented override
    behavior matches the exact installer command."""
    override = tmp_path / "docker-compose.override.yml"
    override.write_text(
        (ROOT / "docker-compose.docker-sock.override.example.yml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    env = dict(os.environ)
    env.update(
        {
            "DB_PASSWORD": "test-db-password",
            "LITELLM_MASTER_KEY": "sk-test-litellm-key",
            "API_KEYS": '["conductor:test-token"]',
            "ROUTER_API_KEY": "test-router-key-0123456789abcdef",
            "TASK_DELEGATION_KEY": "test-delegation-key",
            "LANGFUSE_NEXTAUTH_SECRET": "test-langfuse-secret",
            "LANGFUSE_SALT": "test-langfuse-salt",
        }
    )
    rendered = subprocess.run(
        [
            "docker",
            "compose",
            "--project-directory",
            str(tmp_path),
            "-f",
            str(ROOT / "docker-compose.yml"),
            "-f",
            str(override),
            "config",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        cwd=tmp_path,
    )
    assert rendered.returncode == 0, rendered.stderr
    # The override's socket mount and readiness flag survive the merge (the
    # rendered long syntax uses source/target keys).
    assert "source: /var/run/docker.sock" in rendered.stdout
    assert 'SANDBOX_READINESS_REQUIRED: "true"' in rendered.stdout
