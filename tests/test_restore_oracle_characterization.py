"""Live PostgreSQL characterization of the #1881 restore oracle.

The static tests in `test_backup_restore_oracle.py` pin the fix's structure;
this module proves the oracle's *behavior* on a supported, real PostgreSQL —
the production image (`pgvector/pgvector:pg17`) — inside throwaway Docker
containers, i.e. isolated destinations with no live database, grant or
credential changes. Skipped unless Docker is reachable (set
`MAISTRO_RESTORE_ORACLE_DOCKER=0` to skip explicitly).

Four properties, each demanded by the issue's bounded acceptance:

1. **Unchanged semantic state, varying dump bytes.** Two plain pg_dump runs
   over an idle PostgreSQL 17 database differ bytewise (random psql restrict
   key) while the semantic evidence is identical — so the old raw-hash oracle
   fails a perfectly good backup on this server, and the new oracle is stable.
2. **Concurrent writes break two unconstrained dumps, not one snapshot.** A
   plain dump taken before an insert and one taken after it disagree, but the
   snapshot-bound custom archive + evidence keep describing one state, and the
   restored row count is the snapshot's count, not the later one.
3. **The real drill passes end-to-end** on artifacts produced by the real
   oracle library (provenance, custom dump, evidence, integrity hashes).
4. **Real semantic loss is rejected.** A restored copy that lost a table (and
   a drill whose recorded evidence was tampered with) both fail as SEMANTIC
   mismatches.

Explicit limits (asserted by construction here, stated in the scripts): the
oracle proves structure and cardinality, not cell-level content.
"""

from __future__ import annotations

import datetime
import hashlib
import os
import shutil
import subprocess
import time
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
ORACLE_LIB = REPO / "deploy" / "scripts" / "pg-semantic-oracle.sh"
VERIFY_SH = REPO / "deploy" / "scripts" / "verify-restore.sh"
PG_IMAGE = "pgvector/pgvector:pg17"
PG_USER = "maistro"
PG_DB = "maistro"

CONTAINER = f"maistro-ora-char-src-{os.getpid()}"
RESTORE_CONTAINER = f"maistro-ora-char-restore-{os.getpid()}"


def _docker_reachable() -> bool:
    try:
        subprocess.run(
            ["docker", "info", "--format", "ok"],
            check=True,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return True


pytestmark = [
    pytest.mark.scope("integration"),
    pytest.mark.skipif(
        not _docker_reachable(),
        reason="Docker not reachable; live PostgreSQL characterization needs it",
    ),
    pytest.mark.skipif(
        os.environ.get("MAISTRO_RESTORE_ORACLE_DOCKER") == "0",
        reason="MAISTRO_RESTORE_ORACLE_DOCKER=0",
    ),
]


def _run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kwargs)


def _psql(container: str, db: str, sql: str) -> str:
    out = _run(
        [
            "docker",
            "exec",
            container,
            "psql",
            "-X",
            "-Atq",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            PG_USER,
            "-d",
            db,
            "-c",
            sql,
        ],
    )
    return out.stdout.strip()


def _bash(script: str) -> subprocess.CompletedProcess[str]:
    return _run(["bash", "-c", script])


#: Bounded readiness for the characterization containers. The official
#: docker-entrypoint serves initdb and `docker_process_init_files` through a
#: *temporary* server on the same Unix socket the real one later uses, so
#: `pg_isready` answers "accepting connections" while the target database is
#: not being served yet or the socket is mid-swap — a probe that lands there
#: lets the first `psql` statement fail with exit status 2 ("connection to
#: server went bad"), which is exactly how the `test` CI job's
#: `pg_source_container` setup errored all four characterization tests at
#: 6e2eca944ddbac50631b4ca7d92598a16c01d112 (run 39177311554, job
#: 117822537422, 2026-10-18) and, via the coverage-gate root producer, all
#: four again at run 39130160694. `pg_isready` is a server-liveness ping, not
#: a statement channel; readiness here means one successful `SELECT 1`
#: round-trip on the target database, the same lesson #689 recorded for the
#: workflow service health checks. The probe goes over TCP (`-h 127.0.0.1`)
#: because the temporary server answers *socket* queries too — even
#: authenticated `SELECT 1`s for the target database once `docker_setup_db`
#: has run — while it never listens on TCP; only a TCP round-trip proves the
#: final server this module actually talks to is up. Both knobs are module
#: constants so the stub-docker tests in test_restore_oracle_readiness_gate.py
#: can shrink them.
_READY_TIMEOUT_S = 90.0
_READY_POLL_S = 1.0


def _wait_ready(container: str) -> None:
    """Wait until the container's *final* server answers `SELECT 1` with `1`.

    `pg_isready` alone is not readiness for this image: the official postgres
    entrypoint runs a temporary server during init that accepts connections
    *before* the `maistro` database exists. Probing the statement path itself
    closes that window. A container that has exited can never become ready, so
    we fail fast with its logs instead of burning the budget.

    Re-raises the last probe's exit code and stderr tail on timeout so a wedged
    container is diagnosable from the failure alone.
    """
    probe_cmd = [
        "docker",
        "exec",
        container,
        "psql",
        "-h",
        "127.0.0.1",
        "-X",
        "-Atq",
        "-v",
        "ON_ERROR_STOP=1",
        "-U",
        PG_USER,
        "-d",
        PG_DB,
        "-c",
        "SELECT 1",
    ]
    deadline = time.monotonic() + _READY_TIMEOUT_S
    while True:
        probe = subprocess.run(probe_cmd, capture_output=True, text=True)
        if probe.returncode == 0 and probe.stdout.strip() == "1":
            return
        state = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", container],
            capture_output=True,
            text=True,
        )
        # Real `docker inspect` prints true/false; a missing container returns
        # a non-zero status. Treat an empty stdout (e.g. a stub that does not
        # model inspect) as "unknown" rather than "exited" so readiness-gate
        # stubs that only model psql are not false-positived into the fast-fail.
        exited = state.returncode != 0 or state.stdout.strip().lower() == "false"
        if exited:
            logs = subprocess.run(["docker", "logs", container], capture_output=True, text=True)
            pytest.fail(
                f"characterization PostgreSQL {container} exited before answering SQL; "
                f"its logs:\n{logs.stdout}\n{logs.stderr}"
            )
        if time.monotonic() >= deadline:
            stderr = probe.stderr
            if isinstance(stderr, (bytes, bytearray)):
                stderr = stderr.decode(errors="replace")
            pytest.fail(
                f"characterization PostgreSQL {container} did not become ready "
                f"within {_READY_TIMEOUT_S:.0f}s; last `SELECT 1` probe "
                f"exited {probe.returncode}: {str(stderr).strip()[-400:]}"
            )
        time.sleep(_READY_POLL_S)


def _source_lib() -> str:
    return f"set -euo pipefail\nsource {ORACLE_LIB}\n"


def _lib_backup_driver(container: str, out_dir: Path) -> str:
    """Produce real backup artifacts through the shared oracle library."""
    return (
        _source_lib()
        + "\n".join(
            [
                f'oracle_psql() {{ docker exec "{container}" psql -X -U "{PG_USER}" -d "{PG_DB}" "$@"; }}',
                f'oracle_psql_coproc() {{ docker exec -i "{container}" stdbuf -oL psql -X -U "{PG_USER}" -d "{PG_DB}" "$@"; }}',
                "ORACLE_SNAPSHOT=''",
                "oracle_begin_snapshot",
                'SNAP="${ORACLE_SNAPSHOT}"',
                '{ echo "snapshot=${SNAP}"; echo "backup_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"; '
                "oracle_psql -X -Atq -v ON_ERROR_STOP=1 "
                "-c \"SELECT 'server_version=' || current_setting('server_version');\"; } "
                f'> "{out_dir}/postgres-{PG_DB}.provenance"',
                f'docker exec "{container}" pg_dump -U "{PG_USER}" -d "{PG_DB}" -Fc '
                f'--snapshot="${{SNAP}}" > "{out_dir}/postgres-{PG_DB}.dump"',
                f'oracle_collect_evidence "{out_dir}/postgres-{PG_DB}.schema" '
                f'"{out_dir}/postgres-{PG_DB}.rowcounts" "${{SNAP}}"',
                "oracle_end_snapshot",
                "for f in dump schema rowcounts; do "
                f'sha256sum "{out_dir}/postgres-{PG_DB}.$f" > "{out_dir}/postgres-{PG_DB}.$f.sha256"; done',
                f'echo "${{SNAP}}" > "{out_dir}/snapshot-id.txt"',
                "echo BACKUP_DRIVER_OK",
            ]
        )
        + "\n"
    )


def _lib_evidence_driver(container: str, db: str, schema_out: Path, rowcounts_out: Path) -> str:
    return (
        _source_lib()
        + "\n".join(
            [
                f'oracle_psql() {{ docker exec "{container}" psql -X -U "{PG_USER}" -d "{db}" "$@"; }}',
                f'oracle_collect_evidence "{schema_out}" "{rowcounts_out}"',
                "echo EVIDENCE_DRIVER_OK",
            ]
        )
        + "\n"
    )


def _make_pg_container(name: str) -> None:
    _run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            name,
            "-e",
            f"POSTGRES_USER={PG_USER}",
            "-e",
            "POSTGRES_PASSWORD=characterization-only",
            "-e",
            f"POSTGRES_DB={PG_DB}",
            PG_IMAGE,
        ],
    )


@pytest.fixture(scope="module")
def pg_source_container() -> Any:
    _run(["docker", "rm", "-f", CONTAINER, RESTORE_CONTAINER])
    try:
        _make_pg_container(CONTAINER)
        _wait_ready(CONTAINER)
        # Deterministic application state: two tables, known rows.
        _psql(CONTAINER, PG_DB, "CREATE TABLE accounts (id int primary key, name text not null);")
        _psql(
            CONTAINER, PG_DB, "CREATE TABLE ledger (id int primary key, amount numeric not null);"
        )
        _psql(CONTAINER, PG_DB, "INSERT INTO accounts VALUES (1, 'a'), (2, 'b'), (3, 'c');")
        _psql(CONTAINER, PG_DB, "INSERT INTO ledger VALUES (1, 10), (2, 20);")
        yield CONTAINER
    finally:
        subprocess.run(["docker", "rm", "-f", CONTAINER, RESTORE_CONTAINER], capture_output=True)


@pytest.fixture(scope="module")
def restore_container(pg_source_container: str) -> str:
    """A second PostgreSQL of the same image: isolated restore destination."""
    _make_pg_container(RESTORE_CONTAINER)
    _wait_ready(RESTORE_CONTAINER)
    return RESTORE_CONTAINER


def _plain_dump(container: str) -> str:
    out = _run(
        ["docker", "exec", container, "pg_dump", "-U", PG_USER, "-d", PG_DB, "--no-owner"],
    )
    return out.stdout


def _restore_copy(target_db: str, dump: Path) -> None:
    """Restore a custom-format archive into a scratch database (isolated dest)."""
    _run(
        [
            "docker",
            "exec",
            RESTORE_CONTAINER,
            "psql",
            "-X",
            "-q",
            "-U",
            PG_USER,
            "-d",
            "postgres",
            "-c",
            f'DROP DATABASE IF EXISTS "{target_db}";',
        ]
    )
    _run(
        [
            "docker",
            "exec",
            RESTORE_CONTAINER,
            "psql",
            "-X",
            "-q",
            "-U",
            PG_USER,
            "-d",
            "postgres",
            "-c",
            f'CREATE DATABASE "{target_db}";',
        ]
    )
    with dump.open("rb") as fh:
        _run(
            [
                "docker",
                "exec",
                "-i",
                RESTORE_CONTAINER,
                "pg_restore",
                "-U",
                PG_USER,
                "-d",
                target_db,
                "--no-owner",
                "--exit-on-error",
            ],
            stdin=fh,
        )


def _produce_backup(tmp_path: Path) -> Path:
    out = tmp_path / "backup"
    out.mkdir()
    assert "BACKUP_DRIVER_OK" in _bash(_lib_backup_driver(CONTAINER, out)).stdout
    return out


def _run_drill(backup_root: Path, date: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.update(
        BACKUP_ROOT=str(backup_root),
        PG_IMAGE=PG_IMAGE,
        POSTGRES_USER=PG_USER,
        POSTGRES_DB=PG_DB,
        # Merge reconciliation (#88 + #1881): the lib-driver artifact below
        # carries PostgreSQL state only, while the production drill hard-fails
        # on a missing conductor-data capture (the D-18 gap). This harness
        # exercises the PostgreSQL oracle, so it opts out exactly the way
        # Conductor-less stacks do — the same SKIP_CONDUCTOR_BACKUP=1 contract
        # as backup.sh and verify-restore.sh.
        SKIP_CONDUCTOR_BACKUP="1",
    )
    return subprocess.run(
        ["bash", str(VERIFY_SH), date],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO),
        timeout=300,
    )


def test_plain_dump_bytes_vary_but_evidence_is_stable(
    pg_source_container: str, tmp_path: Path
) -> None:
    dump1 = _plain_dump(pg_source_container)
    dump2 = _plain_dump(pg_source_container)
    schema1 = tmp_path / "s1"
    rc1 = tmp_path / "r1"
    schema2 = tmp_path / "s2"
    rc2 = tmp_path / "r2"
    _bash(_lib_evidence_driver(pg_source_container, PG_DB, schema1, rc1))
    _bash(_lib_evidence_driver(pg_source_container, PG_DB, schema2, rc2))

    h1 = hashlib.sha256(dump1.encode()).hexdigest()
    h2 = hashlib.sha256(dump2.encode()).hexdigest()
    assert h1 != h2, (
        "precondition for the #1881 defect not reproduced: PostgreSQL 17 plain dumps "
        "were expected to differ bytewise (random restrict key) under unchanged state"
    )
    assert schema1.read_text() == schema2.read_text(), "schema evidence must be stable"
    assert rc1.read_text() == rc2.read_text(), "row-count evidence must be stable"


def test_concurrent_write_breaks_two_dumps_not_one_snapshot(
    pg_source_container: str, restore_container: str, tmp_path: Path
) -> None:
    before = _plain_dump(pg_source_container)

    # Backup artifacts bound to one snapshot (the new producer flow).
    out = _produce_backup(tmp_path)
    snap_id = (out / "snapshot-id.txt").read_text().strip()

    # Concurrent write AFTER the snapshot: the old two-dump oracle compared
    # dumps from different states.
    _psql(pg_source_container, PG_DB, "INSERT INTO accounts VALUES (4, 'late');")
    after = _plain_dump(pg_source_container)
    assert (
        hashlib.sha256(before.encode()).hexdigest() != hashlib.sha256(after.encode()).hexdigest()
    ), "expected the two unconstrained plain dumps to disagree under a concurrent write"

    # The snapshot-bound evidence still describes the snapshot state (3 rows).
    assert "accounts=3" in (out / f"postgres-{PG_DB}.rowcounts").read_text()
    assert f"snapshot={snap_id}" in (out / f"postgres-{PG_DB}.provenance").read_text()

    # Restore the archive and re-verify: restored evidence == backup evidence,
    # and the restored count is the snapshot's count, not the concurrent one.
    _restore_copy("verify_a", out / f"postgres-{PG_DB}.dump")
    schema_r = tmp_path / "sr"
    rc_r = tmp_path / "rr"
    _bash(_lib_evidence_driver(restore_container, "verify_a", schema_r, rc_r))
    assert schema_r.read_text() == (out / f"postgres-{PG_DB}.schema").read_text()
    assert rc_r.read_text() == (out / f"postgres-{PG_DB}.rowcounts").read_text()
    assert "accounts=3" in rc_r.read_text(), "restore must match the snapshot, not the later write"


def test_real_verify_restore_drill_passes_end_to_end(
    pg_source_container: str, tmp_path: Path
) -> None:
    out = _produce_backup(tmp_path)
    date = datetime.datetime.now(tz=datetime.UTC).date().isoformat()
    backup_root = tmp_path / "backups" / date
    backup_root.mkdir(parents=True)
    for f in out.iterdir():
        shutil.copy2(f, backup_root / f.name)

    proc = _run_drill(tmp_path / "backups", date)
    assert proc.returncode == 0, f"PASS expected:\n{proc.stdout}\n{proc.stderr}"
    assert "PASS" in proc.stdout
    assert "semantic evidence matches" in proc.stdout
    # No raw dump-hash oracle chatter from the old world.
    assert "pg_dump hash" not in proc.stdout


def test_semantic_loss_is_rejected(
    pg_source_container: str, restore_container: str, tmp_path: Path
) -> None:
    out = _produce_backup(tmp_path)

    # A restored copy that actually lost a table must be caught.
    _restore_copy("verify_lossy", out / f"postgres-{PG_DB}.dump")
    _psql(restore_container, "verify_lossy", "DROP TABLE ledger;")
    schema_r = tmp_path / "sr"
    rc_r = tmp_path / "rr"
    _bash(_lib_evidence_driver(restore_container, "verify_lossy", schema_r, rc_r))
    assert schema_r.read_text() != (out / f"postgres-{PG_DB}.schema").read_text(), (
        "a dropped table must change the schema evidence"
    )

    # And the drill itself must report SEMANTIC FAIL when the restored state
    # disagrees with the recorded evidence. The tamper is re-signed with a
    # correct hash so the drill's artifact-integrity check passes and the
    # comparison oracle itself is what rejects the state (one table's recorded
    # count decremented, whatever it currently is).
    evidence = out / f"postgres-{PG_DB}.rowcounts"
    lines = evidence.read_text().splitlines()
    idx = next(i for i, line in enumerate(lines) if line.startswith("accounts="))
    count = int(lines[idx].split("=", 1)[1])
    lines[idx] = f"accounts={count - 1}"
    evidence.write_text("\n".join(lines) + "\n")
    sign = _bash(
        f"cd '{out}' && sha256sum 'postgres-{PG_DB}.rowcounts' > 'postgres-{PG_DB}.rowcounts.sha256'"
    )
    assert sign.returncode == 0

    proc = _run_drill(tmp_path, "backup")
    assert proc.returncode != 0, "tampered evidence must fail the drill"
    assert "SEMANTIC FAIL" in proc.stderr, f"{proc.stdout}\n{proc.stderr}"


# --- readiness wait itself ----------------------------------------------------
#
# The four characterizations above exercise `_wait_ready` only on a healthy
# image; these two pin the wait's *decision rule*, because that rule is what
# CI run 39144525906 proved wrong in the old pg_isready-only version: the
# socket ping answers 0 during the official image's temporary initdb phase,
# while the statement path it fronts still fails. Both fakes drive the
# module's `subprocess.run` directly — no container needed.


class _FakeCompleted:
    """Shape `subprocess.run(..., capture_output=True)` consumers read here."""

    def __init__(self, returncode: int, stdout: str = "", stderr: bytes = b"") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_wait_ready_concludes_on_the_statement_path_not_pg_isready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """pg_isready answering 0 must never end the wait by itself.

    Regression for CI run 39144525906: the socket ping reported ready while
    the image's temporary initdb server was still up, the fixture's first
    statement raced the restart, and all four characterizations errored with
    psql exit 2. The wait may only conclude when a statement succeeds against
    the target database — even while pg_isready keeps saying ready."""
    from tests.test_restore_oracle_characterization import _wait_ready

    seen: Counter[str] = Counter()

    def fake_run(cmd: list[str], **_kwargs: Any) -> _FakeCompleted:
        argv = " ".join(str(part) for part in cmd)
        if "inspect" in argv:
            seen["inspect"] += 1
            return _FakeCompleted(0, stdout="true\n")
        if "psql" in argv:
            seen["psql"] += 1
            if seen["psql"] < 3:
                return _FakeCompleted(
                    2,
                    stderr=b"psql: error: FATAL: the database system is starting up\n",
                )
            return _FakeCompleted(0, stdout="1\n")  # real server answering SQL
        # The old implementation polled pg_isready here and concluded on its
        # rc — the exact defect (run 39144525906). Any socket-ping command
        # reaching the fake means the wait is trusting the wrong probe again.
        raise AssertionError(f"unexpected readiness command: {argv}")

    monkeypatch.setattr("tests.test_restore_oracle_characterization.subprocess.run", fake_run)
    monkeypatch.setattr(
        "tests.test_restore_oracle_characterization.time.sleep", lambda _seconds: None
    )

    _wait_ready("container")  # must return, not fail, and only via the statement path

    assert seen["psql"] == 3, "two failed probes must not end the wait; the third succeeds"


def test_wait_ready_fails_fast_with_logs_when_the_container_exited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A container that has exited can never become ready: say so with its
    logs immediately, mirroring the hardened verify-restore.sh loop, instead
    of burning the budget on probes that cannot succeed."""
    from tests.test_restore_oracle_characterization import _wait_ready

    probes: Counter[str] = Counter()

    def fake_run(cmd: list[str], **_kwargs: Any) -> _FakeCompleted:
        argv = " ".join(str(part) for part in cmd)
        if "psql" in argv:
            probes["psql"] += 1
            return _FakeCompleted(2, stderr=b"psql: error: connection to server was lost\n")
        if "inspect" in argv:
            probes["inspect"] += 1
            return _FakeCompleted(0, stdout="false\n")  # exited: initdb crashed
        if "logs" in argv:
            probes["logs"] += 1
            return _FakeCompleted(0, stdout="postgres: initdb failed: no space left\n")
        raise AssertionError(f"unexpected command: {argv}")

    monkeypatch.setattr("tests.test_restore_oracle_characterization.subprocess.run", fake_run)

    with pytest.raises(pytest.fail.Exception, match="exited before answering SQL"):
        _wait_ready("container")

    assert probes == {"psql": 1, "inspect": 1, "logs": 1}
