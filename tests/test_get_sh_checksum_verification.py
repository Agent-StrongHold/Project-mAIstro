"""get.sh verifies install.sh against the release SHA256SUMS by default (#84).

A tagged install must verify the laid-down `install.sh` against the
`SHA256SUMS` manifest the release workflow attaches to that release — without
requiring an env var. Before the repair this verification was opt-in only
(`MAISTRO_SHA256SUMS_URL` unset meant "skip silently"), so the default
`curl ... | bash` path never verified anything even though `release.yml`
attaches the manifest precisely so `get.sh` can consume it. These tests pin
the default-on behavior for tag installs, the fail-closed failure modes, and
the preserved override/branch behavior.
"""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GET_SH = ROOT / "get.sh"
RELEASE_TAG = "v9.8.7"
OVERRIDE_URL = "https://mirror.example/SHA256SUMS"

INSTALLER_BODY = "#!/usr/bin/env bash\necho 'installer under test'\n"


def _clean_environment() -> dict[str, str]:
    env = os.environ.copy()
    for name in ("MAISTRO_REPO", "MAISTRO_SHA256SUMS_URL", "MAISTRO_VERSION"):
        env.pop(name, None)
    return env


def _without_entrypoint(path: Path, entrypoint: str) -> str:
    source = path.read_text(encoding="utf-8")
    assert source.rstrip().endswith(entrypoint)
    return source[: source.rfind(entrypoint)]


def _harness(
    *,
    install_dir: Path,
    capture: Path,
    manifest: str,
    manifest_fail: bool = False,
) -> str:
    """get.sh minus its entrypoint, plus a recording `curl` stub.

    The stub appends every requested URL to `capture`, serves the manifest
    from `$HARNESS_MANIFEST` for a SHA256SUMS request (or fails the request
    when `$HARNESS_MANIFEST_FAIL=1`), and serves nothing for anything else.
    The manifest travels through the environment rather than string
    interpolation so quoting cannot mangle it.
    """
    q = shlex.quote
    fail_clause = "printf '%s' \"$HARNESS_MANIFEST\"" if not manifest_fail else "return 1"
    return (
        _without_entrypoint(GET_SH, 'main "$@"')
        + f"""
curl() {{
    local url="${{@: -1}}"
    printf '%s\\n' "$url" >> {q(str(capture))}
    case "$url" in
        *SHA256SUMS*) {fail_clause} ;;
        *) printf '%s' "" ;;
    esac
    return 0
}}
INSTALL_DIR={q(str(install_dir))}
VERSION={q(RELEASE_TAG)}
resolve_ref
verify_installer_checksum
printf 'sha_url=%s\\n' "${{MAISTRO_SHA256SUMS_URL:-<unset>}}"
"""
    )


def _run(harness: str, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = _clean_environment()
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash"],
        cwd=ROOT,
        env=env,
        input=harness,
        capture_output=True,
        text=True,
        check=False,
    )


def _staged_installer(tmp_path: Path) -> Path:
    install_dir = tmp_path / "maistro-engine"
    install_dir.mkdir()
    (install_dir / "install.sh").write_text(INSTALLER_BODY, encoding="utf-8")
    return install_dir


def _true_manifest(install_dir: Path) -> str:
    import hashlib

    digest = hashlib.sha256((install_dir / "install.sh").read_bytes()).hexdigest()
    return f"{digest}  install.sh\n"


def test_tag_install_verifies_against_the_release_manifest_by_default(
    tmp_path: Path,
) -> None:
    install_dir = _staged_installer(tmp_path)
    capture = tmp_path / "urls.txt"
    harness = _harness(
        install_dir=install_dir,
        capture=capture,
        manifest=_true_manifest(install_dir),
    )

    result = _run(harness, {"HARNESS_MANIFEST": _true_manifest(install_dir)})

    assert result.returncode == 0, result.stderr
    expected_url = (
        f"https://github.com/Agent-StrongHold/Project-mAIstro"
        f"/releases/download/{RELEASE_TAG}/SHA256SUMS"
    )
    assert expected_url in capture.read_text(encoding="utf-8"), (
        "a tagged install must fetch the release's own SHA256SUMS asset"
    )
    assert result.stdout.count("install.sh checksum verified.") == 1
    assert f"sha_url={expected_url}" in result.stdout


def test_tag_install_fails_closed_on_a_checksum_mismatch(tmp_path: Path) -> None:
    install_dir = _staged_installer(tmp_path)
    capture = tmp_path / "urls.txt"
    wrong = "0" * 64
    harness = _harness(
        install_dir=install_dir,
        capture=capture,
        manifest=f"{wrong}  install.sh\n",
    )

    result = _run(harness, {"HARNESS_MANIFEST": f"{wrong}  install.sh\n"})

    assert result.returncode != 0
    assert "checksum mismatch" in result.stderr
    assert "Refusing to run it" in result.stderr
    assert "install.sh checksum verified." not in result.stdout


def test_tag_install_fails_when_the_manifest_has_no_installer_entry(
    tmp_path: Path,
) -> None:
    install_dir = _staged_installer(tmp_path)
    capture = tmp_path / "urls.txt"
    harness = _harness(
        install_dir=install_dir,
        capture=capture,
        manifest="0" * 64 + "  some-other-file\n",
    )

    result = _run(harness, {"HARNESS_MANIFEST": "0" * 64 + "  some-other-file\n"})

    assert result.returncode != 0
    assert "no entry for install.sh" in result.stderr


def test_tag_install_fails_when_the_manifest_cannot_be_fetched(
    tmp_path: Path,
) -> None:
    install_dir = _staged_installer(tmp_path)
    capture = tmp_path / "urls.txt"
    harness = _harness(
        install_dir=install_dir,
        capture=capture,
        manifest="",
        manifest_fail=True,
    )

    result = _run(harness)

    assert result.returncode != 0
    assert "Could not fetch checksum manifest" in result.stderr


def test_tag_install_honors_an_explicit_override_url(tmp_path: Path) -> None:
    install_dir = _staged_installer(tmp_path)
    capture = tmp_path / "urls.txt"
    harness = _harness(
        install_dir=install_dir,
        capture=capture,
        manifest=_true_manifest(install_dir),
    )

    result = _run(
        harness,
        {
            "HARNESS_MANIFEST": _true_manifest(install_dir),
            "MAISTRO_SHA256SUMS_URL": OVERRIDE_URL,
        },
    )

    assert result.returncode == 0, result.stderr
    assert OVERRIDE_URL in capture.read_text(encoding="utf-8")
    release_url = (
        f"https://github.com/Agent-StrongHold/Project-mAIstro"
        f"/releases/download/{RELEASE_TAG}/SHA256SUMS"
    )
    assert release_url not in capture.read_text(encoding="utf-8")


def test_branch_install_does_not_verify_by_default(tmp_path: Path) -> None:
    """A moving branch has no release manifest; nothing is fetched."""
    install_dir = _staged_installer(tmp_path)
    capture = tmp_path / "urls.txt"
    harness = (
        _without_entrypoint(GET_SH, 'main "$@"')
        + f"""
curl() {{
    printf '%s\\n' "${{@: -1}}" >> {shlex.quote(str(capture))}
    return 0
}}
INSTALL_DIR={shlex.quote(str(install_dir))}
MAISTRO_BRANCH=some-branch
resolve_ref
verify_installer_checksum
printf 'sha_url=%s\\n' "${{MAISTRO_SHA256SUMS_URL:-<unset>}}"
"""
    )

    result = _run(harness)

    assert result.returncode == 0, result.stderr
    assert "SHA256SUMS" not in capture.read_text(encoding="utf-8")
    assert "sha_url=<unset>" in result.stdout


def test_branch_install_verifies_when_an_override_is_set(tmp_path: Path) -> None:
    """The pre-repair opt-in behavior is preserved for branch installs."""
    install_dir = _staged_installer(tmp_path)
    capture = tmp_path / "urls.txt"
    harness = _harness(
        install_dir=install_dir,
        capture=capture,
        manifest=_true_manifest(install_dir),
    ).replace(f"VERSION={shlex.quote(RELEASE_TAG)}\n", "MAISTRO_BRANCH=some-branch\n")

    result = _run(
        harness,
        {
            "HARNESS_MANIFEST": _true_manifest(install_dir),
            "MAISTRO_SHA256SUMS_URL": OVERRIDE_URL,
        },
    )

    assert result.returncode == 0, result.stderr
    assert OVERRIDE_URL in capture.read_text(encoding="utf-8")
    assert result.stdout.count("install.sh checksum verified.") == 1
