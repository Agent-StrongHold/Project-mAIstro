"""Tests for the buildx build retry wrapper (Codex, #683).

`docker/setup-buildx-action`'s default driver runs BuildKit in its own
container with its own image store, isolated from the host daemon
`scripts/prepull-base-images.sh` retries pulls into (#204). A buildx-driven
build therefore resolves every `FROM`/`--from=` reference through a fresh,
unretried registry fetch — reopening the exact failure #204 closed, for any
job converted to buildx. `scripts/buildx-build-retry.sh` closes that gap by
retrying the whole `docker buildx build` call instead.

No real `docker` is exercised here — this sandbox has no daemon, and the
point of these tests is the retry/backoff/exit-code contract, not Docker
itself. A stub `docker` on PATH stands in, the same way a real contributor
without a spare registry outage would want to test this.
"""

from __future__ import annotations

import re
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "buildx-build-retry.sh"

#: A stub `docker` that fails its first FAIL_COUNT invocations of
#: `buildx build`, then succeeds, logging each attempt's arguments.
_STUB = """#!/usr/bin/env bash
set -euo pipefail
log="{log}"
count_file="{count_file}"
count=$(cat "$count_file")
count=$((count + 1))
echo "$count" > "$count_file"
echo "attempt $count: $*" >> "$log"
if [[ "$1" == "buildx" && "$2" == "build" ]]; then
    if [[ $count -le {fail_count} ]]; then
        exit 1
    fi
    exit 0
fi
exit 1
"""


def _stub_docker(tmp_path: Path, fail_count: int) -> tuple[Path, Path, Path]:
    """Install a stub `docker` on PATH; return (bin_dir, log, count_file)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    count_file = tmp_path / "count"
    count_file.write_text("0")
    docker_stub = bin_dir / "docker"
    docker_stub.write_text(_STUB.format(log=log, count_file=count_file, fail_count=fail_count))
    docker_stub.chmod(docker_stub.stat().st_mode | stat.S_IEXEC)
    return bin_dir, log, count_file


def _run(bin_dir: Path, args: list[str], env: dict[str, str] | None = None):
    import os

    full_env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    if env:
        full_env.update(env)
    return subprocess.run([str(SCRIPT), *args], capture_output=True, text=True, env=full_env)


def test_missing_separator_is_a_usage_error(tmp_path: Path) -> None:
    bin_dir, _log, _count = _stub_docker(tmp_path, fail_count=0)
    result = _run(bin_dir, ["-f", "Dockerfile", "-t", "x", "."])
    assert result.returncode == 2
    assert "usage:" in result.stderr


def test_a_clean_build_succeeds_on_the_first_attempt(tmp_path: Path) -> None:
    bin_dir, log, count = _stub_docker(tmp_path, fail_count=0)
    result = _run(bin_dir, ["--", "-f", "Dockerfile", "-t", "maistro-engine:test", "."])
    assert result.returncode == 0
    assert count.read_text().strip() == "1"
    assert "-f Dockerfile -t maistro-engine:test ." in log.read_text()


def test_a_transient_failure_is_retried_and_then_succeeds(tmp_path: Path) -> None:
    bin_dir, _log, count = _stub_docker(tmp_path, fail_count=1)
    result = _run(bin_dir, ["--", "-f", "Dockerfile", "-t", "x", "."])
    assert result.returncode == 0
    assert count.read_text().strip() == "2"
    assert "retrying" in result.stderr


def test_a_persistent_failure_exhausts_attempts_and_reports_clearly(
    tmp_path: Path,
) -> None:
    bin_dir, _log, count = _stub_docker(tmp_path, fail_count=99)
    result = _run(bin_dir, ["--", "-f", "Dockerfile", "-t", "x", "."])
    assert result.returncode == 1
    assert count.read_text().strip() == "2"  # default ATTEMPTS
    assert "::error::" in result.stderr
    assert "after 2 attempts" in result.stderr


def test_attempts_is_configurable_and_one_attempt_never_retries(
    tmp_path: Path,
) -> None:
    bin_dir, _log, count = _stub_docker(tmp_path, fail_count=1)
    result = _run(
        bin_dir, ["--", "-f", "Dockerfile", "-t", "x", "."], env={"BUILDX_RETRY_ATTEMPTS": "1"}
    )
    assert result.returncode == 1
    assert count.read_text().strip() == "1"


@pytest.mark.parametrize("ci_yml_or_security_yml", ["ci.yml", "security.yml"])
def test_every_workflow_call_site_passes_the_separator(
    ci_yml_or_security_yml: str,
) -> None:
    """A call missing `--` would silently swallow its first real flag as the
    (rejected) sentinel-position argument instead of building anything."""
    workflow = (ROOT / ".github/workflows" / ci_yml_or_security_yml).read_text(encoding="utf-8")
    # Every real invocation runs the script by its full repo-relative path,
    # matching every other script this repo's workflows call (e.g.
    # `scripts/prepull-base-images.sh`). Prose mentions of the script name in
    # comments deliberately drop that prefix (see the two `# ... via
    # buildx-build-retry.sh ...` comments above the real call sites), so
    # counting only the prefixed form counts invocations, not commentary.
    invocations = re.findall(r"scripts/buildx-build-retry\.sh[^\n]*", workflow)
    assert len(invocations) >= 4, workflow
    for line in invocations:
        assert re.search(r"scripts/buildx-build-retry\.sh\s+--", line), (
            f"invocation missing '--' sentinel: {line!r}"
        )
