"""Contract tests for the public installers' canonical GitHub repository."""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GET_SH = ROOT / "get.sh"
GET_PS1 = ROOT / "get.ps1"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"

CANONICAL_REPOSITORY = "Agent-StrongHold/Project-mAIstro"
OBSOLETE_REPOSITORY = "BlakeMatthews-dev/maistro-engine"
STALE_REPOSITORY = "Agent-StrongHold/maistro-engine"
OVERRIDE_REPOSITORY = "example/maistro-fork"
RELEASE_TAG = "v9.8.7"


def _clean_environment() -> dict[str, str]:
    env = os.environ.copy()
    for name in (
        "GITHUB_TOKEN",
        "MAISTRO_BRANCH",
        "MAISTRO_CHANNEL",
        "MAISTRO_DIR",
        "MAISTRO_GITHUB_TOKEN",
        "MAISTRO_REPO",
        "MAISTRO_REQUIRE_RELEASE",
        "MAISTRO_SHA256SUMS_URL",
        "MAISTRO_VERSION",
    ):
        env.pop(name, None)
    return env


def _without_entrypoint(path: Path, entrypoint: str) -> str:
    source = path.read_text(encoding="utf-8")
    assert source.rstrip().endswith(entrypoint)
    return source[: source.rfind(entrypoint)]


def _run_get_sh(
    tmp_path: Path, repository: str | None
) -> tuple[subprocess.CompletedProcess[str], str]:
    capture = tmp_path / "release-api-url"
    env = _clean_environment()
    env["CAPTURE_FILE"] = str(capture)
    if repository is not None:
        env["MAISTRO_REPO"] = repository

    harness = (
        _without_entrypoint(GET_SH, 'main "$@"')
        + f"""
curl() {{
    printf '%s' "${{@: -1}}" > "$CAPTURE_FILE"
    printf '%s' '{{"tag_name":"{RELEASE_TAG}"}}'
}}
tag="$(latest_release_tag)"
VERSION="$tag"
resolve_ref >/dev/null
printf 'repo=%s\\n' "$REPO"
printf 'tag=%s\\n' "$tag"
printf 'clone=%s\\n' "$REPO_URL"
printf 'archive=%s\\n' "$ARCHIVE_URL"
"""
    )
    result = subprocess.run(
        ["bash"],
        cwd=ROOT,
        env=env,
        input=harness,
        capture_output=True,
        text=True,
        check=False,
    )
    return result, capture.read_text(encoding="utf-8")


@pytest.mark.parametrize("override", [None, OVERRIDE_REPOSITORY])
def test_posix_installer_uses_default_or_environment_repository(
    tmp_path: Path, override: str | None
) -> None:
    expected = override or CANONICAL_REPOSITORY

    result, release_api_url = _run_get_sh(tmp_path, override)

    assert result.returncode == 0, result.stderr
    assert release_api_url == f"https://api.github.com/repos/{expected}/releases/latest"
    assert f"repo={expected}" in result.stdout
    assert f"tag={RELEASE_TAG}" in result.stdout
    assert f"clone=https://github.com/{expected}.git" in result.stdout
    assert (
        f"archive=https://github.com/{expected}/archive/refs/tags/{RELEASE_TAG}.tar.gz"
        in result.stdout
    )


def _init_checkout_with_origin(tmp_path: Path, repository: str) -> Path:
    install_dir = tmp_path / "checkout"
    install_dir.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=install_dir, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", f"https://github.com/{repository}.git"],
        cwd=install_dir,
        check=True,
    )
    return install_dir


def _run_ensure_git_origin(tmp_path: Path, install_dir: Path, repository: str) -> str:
    harness = (
        _without_entrypoint(GET_SH, 'main "$@"')
        + f"""
INSTALL_DIR={shlex.quote(str(install_dir))}
REPO={shlex.quote(repository)}
REPO_URL="https://github.com/{repository}.git"
ensure_git_origin
printf 'origin=%s\\n' "$(git -C "$INSTALL_DIR" remote get-url origin)"
"""
    )
    result = subprocess.run(
        ["bash"],
        cwd=ROOT,
        env=_clean_environment(),
        input=harness,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    match = re.search(r"^origin=(.+)$", result.stdout, flags=re.MULTILINE)
    assert match is not None, result.stdout
    return match.group(1)


def test_existing_checkout_retargets_obsolete_origin(tmp_path: Path) -> None:
    install_dir = _init_checkout_with_origin(tmp_path, OBSOLETE_REPOSITORY)

    origin = _run_ensure_git_origin(tmp_path, install_dir, CANONICAL_REPOSITORY)

    assert origin == f"https://github.com/{CANONICAL_REPOSITORY}.git"


def test_existing_checkout_keeps_canonical_origin(tmp_path: Path) -> None:
    install_dir = _init_checkout_with_origin(tmp_path, CANONICAL_REPOSITORY)

    origin = _run_ensure_git_origin(tmp_path, install_dir, CANONICAL_REPOSITORY)

    assert origin == f"https://github.com/{CANONICAL_REPOSITORY}.git"


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _run_get_ps1(tmp_path: Path, repository: str | None) -> subprocess.CompletedProcess[str]:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("pwsh is not installed")

    repo_argument = "" if repository is None else f" -Repo {_ps_quote(repository)}"
    harness = f"""
$source = Get-Content -Raw -LiteralPath {_ps_quote(str(GET_PS1))}
$source = $source -replace '(?m)^Invoke-Main\\s*$', ''
. ([scriptblock]::Create($source)){repo_argument}
$env:LOCALAPPDATA = {_ps_quote(str(tmp_path))}

function Invoke-RestMethod {{
    param(
        [string]$Uri,
        [hashtable]$Headers,
        [switch]$UseBasicParsing,
        [int]$TimeoutSec
    )
    $script:ReleaseApiUri = $Uri
    return [pscustomobject]@{{ tag_name = '{RELEASE_TAG}' }}
}}
function Invoke-WebRequest {{
    param([string]$Uri, [string]$OutFile, [switch]$UseBasicParsing)
    $script:SavedCopyUri = $Uri
    Set-Content -LiteralPath $OutFile -Value '# installer test copy'
}}
function wsl.exe {{
    $script:WslCalls += ,($args -join ' ')
    $global:LASTEXITCODE = 0
}}

Resolve-InstallRef
Save-StableCopy | Out-Null
Invoke-LinuxInstall
Write-Output "repo=$Repo"
Write-Output "api=$script:ReleaseApiUri"
Write-Output "saved=$script:SavedCopyUri"
Write-Output "passthrough=$((Get-PassthroughArgs) -join '|')"
Write-Output "wsl=$($script:WslCalls[-1])"
"""
    return subprocess.run(
        [pwsh, "-NoProfile", "-NonInteractive", "-Command", "-"],
        cwd=ROOT,
        env=_clean_environment(),
        input=harness,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("override", [None, OVERRIDE_REPOSITORY])
def test_powershell_installer_uses_default_or_parameter_repository(
    tmp_path: Path, override: str | None
) -> None:
    expected = override or CANONICAL_REPOSITORY

    result = _run_get_ps1(tmp_path, override)

    assert result.returncode == 0, result.stderr
    assert f"repo={expected}" in result.stdout
    assert f"api=https://api.github.com/repos/{expected}/releases/latest" in result.stdout
    assert (
        f"saved=https://raw.githubusercontent.com/{expected}/{RELEASE_TAG}/get.ps1" in result.stdout
    )
    wsl_call = result.stdout.split("wsl=", 1)[1].splitlines()[0]
    assert f"export MAISTRO_REPO={expected};" in wsl_call
    assert f"https://raw.githubusercontent.com/{expected}/{RELEASE_TAG}/get.sh" in wsl_call
    if override is None:
        assert "-Repo" not in result.stdout.split("passthrough=", 1)[1].splitlines()[0]
    else:
        assert f"-Repo|{override}" in result.stdout


def _run_get_ps1_repo_binding(repository: str) -> subprocess.CompletedProcess[str]:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("pwsh is not installed")

    harness = f"""
$ErrorActionPreference = 'Stop'
$source = Get-Content -Raw -LiteralPath {_ps_quote(str(GET_PS1))}
$source = $source -replace '(?m)^Invoke-Main\\s*$', ''
try {{
    . ([scriptblock]::Create($source)) -Repo {_ps_quote(repository)}
    Write-Output 'repo-parameter-accepted'
}} catch {{
    Write-Output "repo-parameter-rejected=$($_.Exception.Message)"
    exit 2
}}
"""
    return subprocess.run(
        [pwsh, "-NoProfile", "-NonInteractive", "-Command", harness],
        cwd=ROOT,
        env=_clean_environment(),
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    "repository",
    [
        pytest.param(r"owner\repo", id="backslash-separator"),
        pytest.param("owner:repo", id="colon-separator"),
        pytest.param("owner/'repo'", id="single-quote"),
        pytest.param('owner/"repo"', id="double-quote"),
        pytest.param("owner/repo name", id="space"),
        pytest.param("owner/repo\tname", id="tab"),
        pytest.param("../repo", id="parent-owner"),
        pytest.param("owner/..", id="parent-repository"),
        pytest.param("./repo", id="current-owner"),
        pytest.param("owner/.", id="current-repository"),
        pytest.param("../owner/repo", id="leading-traversal"),
        pytest.param("owner/../repo", id="embedded-traversal"),
        pytest.param("owner/repo/extra", id="extra-path-segment"),
        pytest.param(
            "owner/repo;echo PWNED_MARKER;#",
            id="demonstrated-shell-injection",
        ),
    ],
)
def test_powershell_installer_rejects_invalid_repository_before_script_body(
    repository: str,
) -> None:
    result = _run_get_ps1_repo_binding(repository)

    assert result.returncode == 2, result.stdout + result.stderr
    assert "repo-parameter-rejected=" in result.stdout
    assert "Cannot validate argument on parameter 'Repo'" in result.stdout
    assert "repo-parameter-accepted" not in result.stdout


def test_live_installer_text_does_not_advertise_the_obsolete_repository() -> None:
    for path in (GET_SH, GET_PS1):
        source = path.read_text(encoding="utf-8")
        assert OBSOLETE_REPOSITORY not in source, path
        assert CANONICAL_REPOSITORY in source, path


def test_release_workflow_uses_only_the_canonical_repository_identity() -> None:
    source = RELEASE_WORKFLOW.read_text(encoding="utf-8")

    assert f"https://github.com/{CANONICAL_REPOSITORY}/pkgs/container/maistro-engine" in source
    assert "owner: Agent-StrongHold   repository: Project-mAIstro" in source
    assert "owner Agent-StrongHold / repo Project-mAIstro / workflow release.yml" in source
    assert OBSOLETE_REPOSITORY not in source
    assert STALE_REPOSITORY not in source
    assert "BlakeMatthews-dev" not in source
    assert not re.search(
        r"\b(?:repository|repo)\s*:?\s*`?maistro-engine`?\b",
        source,
        flags=re.IGNORECASE,
    )
