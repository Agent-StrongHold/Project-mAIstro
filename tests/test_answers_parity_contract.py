"""Unattended answers-file parity between get.sh and get.ps1 (#409).

One versioned answers schema (InstallAnswersV1, ``schema_version: "1"``) must
flow identically through both public entrypoints: ``get.sh`` (``curl | bash``)
and ``get.ps1`` (``irm | iex``, forwarding into WSL). Before #409, Windows
could not express an unattended install at all — get.ps1 exposed only boolean
switches, so ``get.sh -- --answers-file`` had no twin.

These tests run the same fixture through every reachable leg of the contract
and compare the rendered effective config:

- **Unix leg (real bash):** get.sh's option passthrough and its
  relative-to-absolute answers-path resolution, captured at the install.sh
  boundary with a fake install.sh that echoes its argv.
- **Preflight leg (real bash):** install.sh validates missing/directory and
  skip-wizard-conflicting answers *before any mutation*, reporting every
  problem in one failure. Only failure paths are executed here — a passing
  guard would otherwise continue into apt/docker/compose work.
- **Rendered effective config (real uv):** ``maistro-install --answers-file
  <fixture> --json`` — the plan the installer materializes from that file.
- **Windows leg (real get.ps1 under pwsh; skipped when pwsh is absent, run
  for both shipping editions by release-installer.yml's windows job):**
  tests/installer/answers_parity_harness.ps1 drives the production preflight,
  Windows-to-WSL path translation, bash single-quoting, and the
  ``bash -s -- --answers-file`` handoff, and proves -AnswersFile survives the
  elevation relaunch / reboot-resume passthrough.

The final test ties the legs together: the path get.ps1 forwards must be the
same fixture the Unix entrypoint forwards, and rendering *that* path must
produce the identical effective config. That is the parity contract: same
file in, same install out, on both operating systems.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GET_SH = ROOT / "get.sh"
GET_PS1 = ROOT / "get.ps1"
INSTALL_SH = ROOT / "install.sh"
HARNESS = ROOT / "tests" / "installer" / "answers_parity_harness.ps1"

#: The shared fixture every leg consumes: the sanitized CI smoke answers.
#: (release-installer.yml runs its installer smoke test with this same file.)
SMOKE_FIXTURE = ROOT / "docs" / "install" / "examples" / "answers-v1-smoke.yaml"

#: The effective config the smoke fixture must render, pinned key by key from
#: the fixture itself. A fixture edit that changes install behavior must fail
#: here first.
SMOKE_EFFECTIVE_ANSWERS = {
    "schema_version": "1",
    "install_mode": "preview",
    "features": [],
    "compose_addons": [],
    "container_runtime": "docker",
    "users_intent": "bootstrap_admin",
    "stack_bringup": "none",
    "install_surface": "curl",
    "delivery_mode": "source_build",
    "crypto_profile": "no_crypto",
    "admin_user": "smoke-admin",
    "daily_driver_user": "smoke-user",
}

UNIT_CASES = [
    "translate",
    "bash-quoting",
    "preflight-unbound-is-noop",
    "preflight-empty-explicit",
    "preflight-missing-collects-all",
    "preflight-accepts-file",
]
HANDOFF_CASES = ["plain-still-uses-simple-pipe", "forwards-answers-file"]
BLOCKED_CASES = [
    "missing-and-conflict-collect-both",
    "directory",
    "valid-file-conflict-only",
]


# --- helpers -----------------------------------------------------------------


def _get_sh_library() -> str:
    """get.sh as a sourceable library: everything but its entrypoint."""
    source = GET_SH.read_text(encoding="utf-8")
    entrypoint = 'main "$@"'
    assert source.rstrip().endswith(entrypoint)
    return source[: source.rfind(entrypoint)]


def _bash(script: str, *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash"],
        input=script,
        capture_output=True,
        text=True,
        cwd=cwd,
        check=False,
        timeout=120,
        # A new session has no controlling terminal: the state cloud-init,
        # non-interactive ssh and CI all run the one-liner in.
        start_new_session=True,
    )


def _run_install_sh(
    args: list[str], env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """install.sh in an empty sandbox cwd. Only its failure paths are safe to
    run: a passing preflight would continue into dependency installation."""
    sandbox = subprocess.run(
        ["mktemp", "-d"], capture_output=True, text=True, check=True
    ).stdout.strip()
    # Keep the host's answers environment out; the caller's `env` (if any)
    # wins over the inherited environment.
    run_env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("MAISTRO_INSTALL_ANSWERS", "MAISTRO_SKIP_WIZARD")
    }
    run_env.update(env or {})
    return subprocess.run(
        ["bash", str(INSTALL_SH), *args],
        cwd=sandbox,
        env=run_env,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
        start_new_session=True,
    )


def _pwsh() -> str:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("pwsh is not installed")
    return pwsh


def _run_harness(
    mode: str, case: str, fixture: Path | None = None
) -> subprocess.CompletedProcess[str]:
    args = [
        _pwsh(),
        "-NoProfile",
        "-NonInteractive",
        "-File",
        str(HARNESS),
        "-Mode",
        mode,
        "-Case",
        case,
        "-GetPs1",
        str(GET_PS1),
    ]
    if fixture is not None:
        args += ["-Fixture", str(fixture)]
    env = os.environ.copy()
    for name in ("GITHUB_TOKEN", "MAISTRO_GITHUB_TOKEN", "MAISTRO_SHA256SUMS_URL"):
        env.pop(name, None)
    return subprocess.run(args, cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)


def _render_plan(answers_path: Path | str) -> dict:
    """The effective config maistro-install renders from an answers file."""
    result = subprocess.run(
        [
            "uv",
            "run",
            "--project",
            "packages/maistro-bootstrap",
            "maistro-install",
            "--answers-file",
            str(answers_path),
            "--json",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=600,
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    stdout = result.stdout
    payload = stdout[stdout.index("{") :]
    plan = json.loads(payload)
    assert plan["kind"] == "maistro_install_plan"
    return plan


def _fake_install_sh(install_dir: Path) -> None:
    """A stand-in install.sh that prints its argv, one argument per line."""
    install_dir.mkdir(parents=True, exist_ok=True)
    (install_dir / "install.sh").write_text(
        "#!/usr/bin/env bash\nprintf '%s\\n' \"$@\"\n", encoding="utf-8"
    )


@pytest.fixture(scope="module")
def smoke_plan() -> dict:
    return _render_plan(SMOKE_FIXTURE)


# --- Unix leg: get.sh forwards --answers-file to install.sh ------------------


def _forwarded_args(*args: str, cwd: Path) -> list[str]:
    install_dir = cwd / "engine"
    _fake_install_sh(install_dir)
    script = f"""
set -euo pipefail
{_get_sh_library()}
# After the source: the library defaults would otherwise overwrite these.
INSTALL_DIR='{install_dir}'
REF_KIND='tag'
REF='v9.9.9'
IMAGE_TAG='v9.9.9'
run_installer {" ".join(args)}
"""
    result = _bash(script, cwd=cwd)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    return result.stdout.splitlines()


def test_get_sh_forwards_relative_answers_file_as_absolute(tmp_path: Path) -> None:
    """`get.sh --answers-file relative.yaml` must reach install.sh absolute:
    run_installer cd's into INSTALL_DIR before exec'ing it, so a relative
    path would otherwise name a file inside the install tree (#409)."""
    (tmp_path / "answers.yaml").write_text('schema_version: "1"\n', encoding="utf-8")
    forwarded = _forwarded_args("--answers-file", "answers.yaml", cwd=tmp_path)
    assert forwarded == ["--answers-file", str(tmp_path / "answers.yaml")]


def test_get_sh_forwards_the_equals_form_as_absolute(tmp_path: Path) -> None:
    (tmp_path / "answers.yaml").write_text('schema_version: "1"\n', encoding="utf-8")
    forwarded = _forwarded_args("--answers-file=answers.yaml", cwd=tmp_path)
    assert forwarded == [f"--answers-file={tmp_path / 'answers.yaml'}"]


def test_get_sh_leaves_absolute_answers_paths_untouched(tmp_path: Path) -> None:
    absolute = tmp_path / "answers.yaml"
    absolute.write_text('schema_version: "1"\n', encoding="utf-8")
    forwarded = _forwarded_args("--answers-file", str(absolute), cwd=tmp_path)
    assert forwarded == ["--answers-file", str(absolute)]


def test_get_sh_still_forwards_its_other_passthrough_options(tmp_path: Path) -> None:
    """The answers twin must not disturb the existing passthrough contract:
    unrecognized options ride along verbatim (install.sh stays free to grow)."""
    forwarded = _forwarded_args("--no-start", "--answers-file", "a.yaml", cwd=tmp_path)
    assert forwarded == ["--no-start", "--answers-file", str(tmp_path / "a.yaml")]


# --- Preflight leg: install.sh validates before mutation ---------------------


def test_install_sh_reports_every_answers_problem_in_one_failure() -> None:
    """Missing file AND skip-wizard conflict in one run: an unattended install
    must fail once with the complete actionable list, not one reboot per
    finding."""
    result = _run_install_sh(["--answers-file", "nope/missing.yaml", "--skip-wizard"])
    assert result.returncode == 1, f"{result.stdout}\n{result.stderr}"
    assert "does not exist" in result.stderr
    assert "--skip-wizard" in result.stderr
    assert "never reads the answers file" in result.stderr


def test_install_sh_rejects_a_directory_answers_file() -> None:
    result = _run_install_sh(["--answers-file", str(ROOT / "docs")])
    assert result.returncode == 1, f"{result.stdout}\n{result.stderr}"
    assert "is a directory" in result.stderr


def test_install_sh_names_only_the_real_problems() -> None:
    """A missing file must not also be reported as conflicting, and a real
    file under --skip-wizard must not also be reported as missing."""
    missing = _run_install_sh(["--answers-file", "nope/missing.yaml"])
    assert missing.returncode == 1
    assert "does not exist" in missing.stderr
    assert "skip-wizard" not in missing.stderr

    conflict = _run_install_sh(["--answers-file", str(SMOKE_FIXTURE), "--skip-wizard"])
    assert conflict.returncode == 1
    assert "never reads the answers file" in conflict.stderr
    assert "does not exist" not in conflict.stderr


def test_install_sh_guards_the_environment_form_too() -> None:
    """MAISTRO_INSTALL_ANSWERS + MAISTRO_SKIP_WIZARD is the same conflict via
    environment variables — e.g. a get.sh caller setting skip-wizard in the
    environment while passing --answers-file through."""
    result = _run_install_sh(
        ["--answers-file", "nope/missing.yaml"],
        env={"MAISTRO_SKIP_WIZARD": "1"},
    )
    assert result.returncode == 1, f"{result.stdout}\n{result.stderr}"
    assert "MAISTRO_SKIP_WIZARD" in result.stderr
    assert "does not exist" in result.stderr


# --- Rendered effective config -----------------------------------------------


def test_smoke_fixture_renders_the_expected_effective_config(smoke_plan: dict) -> None:
    answers = smoke_plan["answers"]
    for key, expected in SMOKE_EFFECTIVE_ANSWERS.items():
        assert answers[key] == expected, f"fixture field {key!r} rendered as {answers[key]!r}"


# --- Windows leg: the production get.ps1 pipeline under pwsh -----------------


@pytest.mark.parametrize("case", UNIT_CASES)
def test_harness_unit_case(case: str) -> None:
    result = _run_harness("unit", case)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert f"RESULT unit:{case} ok" in result.stdout


@pytest.mark.parametrize("case", HANDOFF_CASES)
def test_harness_handoff_case(case: str) -> None:
    result = _run_harness("handoff", case)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert f"RESULT handoff:{case} ok" in result.stdout


@pytest.mark.parametrize("case", BLOCKED_CASES)
def test_harness_blocked_case(case: str) -> None:
    result = _run_harness("blocked", case)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert f"RESULT blocked:{case} ok" in result.stdout


def test_harness_case_list_matches_the_python_enumeration() -> None:
    """The Windows E2E runner enumerates cases from the harness; this pins the
    harness list to the same set pytest parametrizes, so neither side drifts."""
    result = _run_harness("List", "")
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    listed = result.stdout.splitlines()
    assert {line[len("unit:") :] for line in listed if line.startswith("unit:")} == set(UNIT_CASES)
    assert {line[len("handoff:") :] for line in listed if line.startswith("handoff:")} == set(
        HANDOFF_CASES
    )
    assert {line[len("blocked:") :] for line in listed if line.startswith("blocked:")} == set(
        BLOCKED_CASES
    )


# --- The cross-platform contract itself --------------------------------------


def test_both_entrypoints_render_the_same_effective_config(smoke_plan: dict) -> None:
    """Run the same fixture through the Windows pipeline (real get.ps1
    preflight, translation, and handoff, supervised by the harness) and render
    the config from the exact path get.ps1 forwards: it must be the same file
    the Unix entrypoint forwards, and it must render the identical effective
    config. Same fixture in, same install out — that is #409's parity bar."""
    result = _run_harness("handoff", "forwards-answers-file", fixture=SMOKE_FIXTURE)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    marker = "RESULT handoff:forwards-answers-file ok forwarded="
    line = next(
        candidate for candidate in result.stdout.splitlines() if candidate.startswith(marker)
    )
    forwarded = line[len(marker) :]

    # On a Windows host the forwarded path is the distro's /mnt view, which a
    # host-side render cannot read; the windows E2E job asserts the translation
    # structurally, and this render comparison runs where the path is local.
    if not forwarded.startswith("/"):
        pytest.skip("forwarded path is not locally readable (Windows /mnt view)")

    # The Windows entrypoint must forward the very fixture the Unix entrypoint
    # forwards: POSIX-absolute input passes through translation verbatim.
    assert Path(forwarded) == SMOKE_FIXTURE
    plan = _render_plan(forwarded)
    assert plan["answers"] == smoke_plan["answers"]
    for key, expected in SMOKE_EFFECTIVE_ANSWERS.items():
        assert plan["answers"][key] == expected
