"""The characterization containers' readiness gate goes through psql (#repair).

`pg_isready` answers "accepting connections" when *any* PostgreSQL on the
socket responds — including the docker-entrypoint's temporary bootstrap server,
which serves initdb and `docker_process_init_files` on the same Unix socket the
real server later takes over. A `pg_isready`-gated setup can therefore reach
its first application statement while the target database is not actually
being served, and `psql` fails with exit status 2 ("connection to server went
bad"). That is how all four `test_restore_oracle_characterization` tests
errored at setup in the `test` CI job at 6e2eca944ddbac50631b4ca7d92598a16c01d112
(run 39177311554, job 117822537422): `pg_isready` passed, the very next
`CREATE TABLE` failed. It is the same lesson #689 recorded for workflow
service health checks, one layer down: a server-liveness ping is not a
statement channel.

These tests pin the corrected gate in `test_restore_oracle_characterization`
without Docker: a stub `docker` binary answers `pg_isready` with exit 0 — the
misleading bootstrap-server state — while `psql` exits 2 until the stub's
`STUB_PSQL_FAILS_FIRST` calls have passed, mimicking the startup window. The
first test fails against the pre-fix `_wait_ready` by construction: that
version returned after a single successful `pg_isready` probe (observed:
declared ready in 0.02s against this exact stub while the next `psql` exited 2).
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from tests import test_restore_oracle_characterization as roc

#: `pg_isready` exits 0 no matter how unready the target database is: that is
#: the whole defect. Constant here so a stub change cannot hide it.
PG_ISREADY_EXIT = 0

STUB_DOCKER = f"""\
#!/usr/bin/env python3
import os, sys

argv = sys.argv[1:]
log = os.environ["STUB_LOG"]
with open(log, "a") as fh:
    fh.write("\\x1f".join(argv) + "\\n")

is_psql = len(argv) > 2 and argv[2] == "psql"
if not is_psql:
    # pg_isready (and docker run/rm): the bootstrap server always answers.
    sys.exit({PG_ISREADY_EXIT})

psql_calls = sum(
    1
    for line in open(log)
    if len(line.split("\\x1f")) > 2 and line.split("\\x1f")[2] == "psql"
)
if psql_calls <= int(os.environ.get("STUB_PSQL_FAILS_FIRST", "0")):
    sys.stderr.write("psql: error: connection to server went bad\\n")
    sys.exit(2)
if "SELECT 1" in argv:
    print("1")
sys.exit(0)
"""


@pytest.fixture
def stub_docker(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Put a logging stub `docker` first on `$PATH`; return its call log."""
    log = tmp_path / "docker-calls.log"
    shim_dir = tmp_path / "bin"
    shim_dir.mkdir()
    shim = shim_dir / "docker"
    shim.write_text(STUB_DOCKER)
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", f"{shim_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("STUB_LOG", str(log))
    return log


@pytest.fixture
def fast_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Shrink the gate's window so a failing path fails in milliseconds."""
    monkeypatch.setattr(roc, "_READY_TIMEOUT_S", 1.5)
    monkeypatch.setattr(roc, "_READY_POLL_S", 0.01)


def test_pg_isready_alone_is_not_readiness(
    stub_docker: Path, fast_gate: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The CI regression, pinned: a container whose `pg_isready` answers 0 but
    whose every `psql` call exits 2 must never be declared ready.

    The pre-fix gate returned after one `pg_isready` probe (observed against
    this stub: ready in 0.02s) and let the fixture's first `CREATE TABLE` hit
    psql exit status 2 — the exact failure recorded in job 117822537422.
    """
    monkeypatch.setenv("STUB_PSQL_FAILS_FIRST", "1000000")  # never serves SQL
    with pytest.raises(pytest.fail.Exception, match="did not become ready"):
        roc._wait_ready("stub-container")
    # The probes went through the statement channel and it kept refusing:
    calls = [line.split("\x1f") for line in stub_docker.read_text().splitlines()]
    assert calls, "the gate never probed at all"
    assert not any("pg_isready" in call for call in calls), (
        "a probe bypassed psql; pg_isready alone is the defect under test"
    )
    psql_calls = [call for call in calls if "psql" in call]
    assert psql_calls, "the gate never probed psql at all"


def test_the_failure_names_the_last_probe_exit_and_stderr(
    stub_docker: Path, fast_gate: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A timeout must be diagnosable from the failure alone: exit code and the
    server's stderr tail travel with it."""
    monkeypatch.setenv("STUB_PSQL_FAILS_FIRST", "1000000")
    with pytest.raises(pytest.fail.Exception) as excinfo:
        roc._wait_ready("stub-container")
    text = str(excinfo.value)
    assert "probe exited 2" in text, f"last probe exit code missing from: {text}"
    assert "connection to server went bad" in text, f"stderr tail missing from: {text}"


def test_ready_only_after_a_real_select_round_trip(
    stub_docker: Path, fast_gate: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A container that refuses its first probes and then answers `SELECT 1`
    with `1` is declared ready — retries happen, and only the round-trip ends
    the wait."""
    monkeypatch.setenv("STUB_PSQL_FAILS_FIRST", "3")
    roc._wait_ready("stub-container")  # must not raise

    calls = [line.split("\x1f") for line in stub_docker.read_text().splitlines()]
    psql_calls = [call for call in calls if "psql" in call]
    assert len(psql_calls) >= 4, "the failing probes before readiness were retried"


def test_every_probe_is_select_1_against_the_target_database(
    stub_docker: Path, fast_gate: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Structural pin: each readiness probe opens `PG_DB` through `psql` and
    requires a `SELECT 1` round-trip. A regression to a bare `pg_isready` (the
    CI defect) or to probing another database makes this red, whatever the
    runtime looks like."""
    monkeypatch.setenv("STUB_PSQL_FAILS_FIRST", "1")
    roc._wait_ready("stub-container")

    calls = [line.split("\x1f") for line in stub_docker.read_text().splitlines()]
    psql_calls = [call for call in calls if "psql" in call]
    assert psql_calls
    for call in psql_calls:
        assert call[0] == "exec", call
        assert "psql" in call, f"probe bypassed the statement channel: {call}"
        # Over TCP, deliberately: the entrypoint's temporary bootstrap server
        # answers *socket* queries (even authenticated SELECT 1s for PG_DB)
        # until it is stopped, and never listens on TCP — so only a `-h
        # 127.0.0.1` round-trip proves the final server is the one answering.
        # Seen live in the coverage-gate root producer (run 39130160694):
        # a socket-gated fixture raced the temp→final restart and every
        # statement after "ready" died with psql exit status 2.
        assert call[call.index("-h") + 1] == "127.0.0.1", call
        assert call[call.index("-d") + 1] == roc.PG_DB, call
        assert call[call.index("-c") + 1] == "SELECT 1", call


#: The coverage-gate root producer (quality.yml `combine`) runs this suite with
#: pytest-timeout's `--timeout=30`; this file's own runs have no CLI flag, so
#: pytest-timeout's library default applies. Constant so the comparison below
#: cannot silently drift from the producer's flag.
PRODUCER_DEFAULT_TIMEOUT_S = 30


def test_characterization_module_budgets_beyond_the_producers_30s_default() -> None:
    """The characterization module must override the producers' 30s per-test
    timeout for its own setup.

    Its module-scoped fixtures pull `pgvector/pgvector:pg17` and wait two full
    readiness cycles (source + restore containers) before the first statement
    of the first test runs — all inside that test's setup phase, which is what
    pytest-timeout budgets. On a cold or loaded runner the image pull alone
    exceeded the 30s default and errored all four tests at fixture setup in
    the Coverage gate's combine step at 625879d0 (run 43878191747, job
    133345309671, 2026-11-16) while the parallel instance of the same job on
    the same head passed. Without a module-level `timeout` mark, the effective
    budget is the producer's 30s and this test fails for the intended reason.
    """
    timeout_marks = [m for m in roc.pytestmark if getattr(m, "name", "") == "timeout"]
    assert timeout_marks, (
        "test_restore_oracle_characterization carries no per-module timeout "
        f"override: the producer's {PRODUCER_DEFAULT_TIMEOUT_S}s budget again "
        "caps a setup that legitimately needs an image pull plus two readiness "
        "cycles"
    )
    effective = min(
        int(arg) for m in timeout_marks for arg in m.args if isinstance(arg, (int, float))
    )
    assert effective > PRODUCER_DEFAULT_TIMEOUT_S, (
        f"the module's timeout override ({effective}s) does not clear the "
        f"producer default ({PRODUCER_DEFAULT_TIMEOUT_S}s)"
    )
    # One image pull plus BOTH readiness cycles happen inside setup: the
    # budget must exceed two full _wait_ready windows, not just one.
    assert effective >= 2 * roc._READY_TIMEOUT_S, (
        f"the module's timeout override ({effective}s) does not cover two "
        f"readiness cycles (2 x {roc._READY_TIMEOUT_S:.0f}s) plus the pull"
    )
