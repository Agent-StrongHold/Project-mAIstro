"""Tests for the buildx build retry wrapper (Codex, #683 / #899).

`docker/setup-buildx-action`'s default driver runs BuildKit in its own
container with its own image store, isolated from the host daemon
`scripts/prepull-base-images.sh` retries pulls into (#204). A buildx-driven
build therefore resolves every `FROM`/`--from=` reference through a fresh,
unretried registry fetch — reopening the exact failure #204 closed, for any
job converted to buildx. `scripts/buildx-build-retry.sh` closes that gap by
retrying the whole `docker buildx build` call instead.

#899 adds a hard deadline around each attempt. No real `docker` is exercised
here — this sandbox has no daemon, and the point of these tests is the
retry/backoff/timeout/exit-code contract, not Docker itself. A stub `docker`
on PATH stands in, the same way a contributor without a spare registry outage
or wedged BuildKit daemon would want to test this.
"""

from __future__ import annotations

import re
import stat
import subprocess
import time
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

#: Deliberately never returns before the wrapper's test deadline. `/bin/sleep`
#: bypasses the fake `sleep` installed beside it, which exists only to remove
#: the wrapper's five-second retry backoff from this fast regression.
_HANGING_STUB = """#!/usr/bin/env bash
set -euo pipefail
count_file="{count_file}"
count=$(cat "$count_file")
count=$((count + 1))
echo "$count" > "$count_file"
if [[ "$1" == "buildx" && "$2" == "build" ]]; then
    exec /bin/sleep 60
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


def _stub_hanging_docker(tmp_path: Path) -> tuple[Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    count_file = tmp_path / "count"
    count_file.write_text("0")

    docker_stub = bin_dir / "docker"
    docker_stub.write_text(_HANGING_STUB.format(count_file=count_file))
    docker_stub.chmod(docker_stub.stat().st_mode | stat.S_IEXEC)

    # The wrapper backs off with `sleep 5` between attempts. Keep the regression
    # fast without changing production behavior; the hanging docker process
    # explicitly calls /bin/sleep so this fake cannot make the hang disappear.
    sleep_stub = bin_dir / "sleep"
    sleep_stub.write_text("#!/usr/bin/env bash\nexit 0\n")
    sleep_stub.chmod(sleep_stub.stat().st_mode | stat.S_IEXEC)
    return bin_dir, count_file


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
    assert "attempts exhausted" in result.stderr


def test_attempts_is_configurable_and_one_attempt_never_retries(
    tmp_path: Path,
) -> None:
    bin_dir, _log, count = _stub_docker(tmp_path, fail_count=1)
    result = _run(
        bin_dir, ["--", "-f", "Dockerfile", "-t", "x", "."], env={"BUILDX_RETRY_ATTEMPTS": "1"}
    )
    assert result.returncode == 1
    assert count.read_text().strip() == "1"


@pytest.mark.parametrize("bad_attempts", ["0", "-1", "not-a-number"])
def test_a_non_positive_attempts_count_errors_instead_of_silently_succeeding(
    tmp_path: Path, bad_attempts: str
) -> None:
    """A `for` loop bounded by a non-positive ATTEMPTS runs zero times: the
    script would fall off the end with no explicit exit, which is success --
    reporting a build step green without docker ever having been invoked."""
    bin_dir, _log, count = _stub_docker(tmp_path, fail_count=0)
    result = _run(
        bin_dir,
        ["--", "-f", "Dockerfile", "-t", "x", "."],
        env={"BUILDX_RETRY_ATTEMPTS": bad_attempts},
    )
    assert result.returncode == 2
    assert "::error::" in result.stderr
    assert count.read_text().strip() == "0"


def test_an_empty_attempts_value_falls_back_to_the_default_rather_than_erroring(
    tmp_path: Path,
) -> None:
    """`${VAR:-default}` substitutes on unset OR empty; an explicitly empty
    `BUILDX_RETRY_ATTEMPTS=` is not malformed input, just an unset one."""
    bin_dir, _log, count = _stub_docker(tmp_path, fail_count=0)
    result = _run(
        bin_dir, ["--", "-f", "Dockerfile", "-t", "x", "."], env={"BUILDX_RETRY_ATTEMPTS": ""}
    )
    assert result.returncode == 0
    assert count.read_text().strip() == "1"


def test_a_hung_build_times_out_retries_and_fails_without_waiting_for_the_child(
    tmp_path: Path,
) -> None:
    bin_dir, count = _stub_hanging_docker(tmp_path)
    started = time.monotonic()
    result = _run(
        bin_dir,
        ["--", "-f", "Dockerfile", "-t", "x", "."],
        env={"BUILDX_ATTEMPT_TIMEOUT": "0.1s"},
    )
    elapsed = time.monotonic() - started

    assert result.returncode == 1
    assert count.read_text().strip() == "2"
    assert "timed out after 0.1s" in result.stderr
    assert "attempts exhausted" in result.stderr
    assert elapsed < 2.0


@pytest.mark.parametrize("bad_timeout", ["0", "0s", "0.0m", "-1", "not-a-duration"])
def test_invalid_or_unbounded_attempt_timeout_is_rejected_before_docker(
    tmp_path: Path, bad_timeout: str
) -> None:
    bin_dir, _log, count = _stub_docker(tmp_path, fail_count=0)
    result = _run(
        bin_dir,
        ["--", "-f", "Dockerfile", "-t", "x", "."],
        env={"BUILDX_ATTEMPT_TIMEOUT": bad_timeout},
    )

    assert result.returncode == 2
    assert "BUILDX_ATTEMPT_TIMEOUT" in result.stderr
    assert count.read_text().strip() == "0"


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


def test_specialized_producer_and_aggregator_budgets_are_coherent() -> None:
    """#899: the waiter cannot expire while a required producer is still
    inside the runtime the repository explicitly allows it."""
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    integration = (ROOT / ".github/workflows/integration-scope.yml").read_text(encoding="utf-8")

    docker_job = ci.split("\n  docker-build:\n", 1)[1].split("\n  workflow-lint:\n", 1)[0]
    docker_timeout_match = re.search(r"^    timeout-minutes:\s*(\d+)\s*$", docker_job, re.MULTILINE)
    assert docker_timeout_match is not None, "docker-build must carry an outer timeout"
    docker_timeout_minutes = int(docker_timeout_match.group(1))

    integration_timeout_match = re.search(
        r"^    timeout-minutes:\s*(\d+)\s*$", integration, re.MULTILINE
    )
    attempts_match = re.search(r'EVIDENCE_WAIT_ATTEMPTS:\s*"(\d+)"', integration)
    interval_match = re.search(r'EVIDENCE_WAIT_INTERVAL_MS:\s*"(\d+)"', integration)
    assert integration_timeout_match and attempts_match and interval_match

    integration_timeout_minutes = int(integration_timeout_match.group(1))
    attempts = int(attempts_match.group(1))
    interval_ms = int(interval_match.group(1))
    evidence_wait_minutes = attempts * interval_ms / 60_000

    # #869: workflow-lint finished at 03:34:22 and the last required producer
    # did not start until 04:07:27, a >33 minute runner-scheduling gap. Round
    # conservatively to 35 minutes and add the producer's legitimate ceiling.
    observed_queue_lag_minutes = 35
    assert docker_timeout_minutes == 25
    assert evidence_wait_minutes >= observed_queue_lag_minutes + docker_timeout_minutes
    assert integration_timeout_minutes > evidence_wait_minutes
