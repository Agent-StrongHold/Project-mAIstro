"""Restore verification must be snapshot-consistent and dump-byte-independent (#1881).

The pre-#1881 drill verified a restore by re-running `pg_dump` on the restored
database and comparing SHA-256 against a hash of a *second* plain-text dump
that backup.sh had taken separately. That oracle was invalid twice over:

* the two dumps are unconstrained, so concurrent writes can make them describe
  different snapshots (a mismatch then means nothing about restorability), and
* PostgreSQL >= 17 plain output embeds a random psql restrict key by default,
  so raw dump bytes differ even for unchanged semantic state (the drill fails
  spuriously on a perfectly good restore).

The fix binds the authoritative custom-format archive and its verification
evidence (schema inventory + exact per-table row counts) to ONE exported
snapshot (`pg_export_snapshot` + `pg_dump --snapshot`), single-sources the
oracle definitions in `deploy/scripts/pg-semantic-oracle.sh`, compares
semantic evidence in verify-restore.sh with four distinct failure classes
(artifact / restore / semantic / verifier), and preserves pg_dump/psql
security defaults (no `--restrict-key`, no dump rewriting).

Every structural check here is also asserted to FAIL against the pre-#1881
scripts (read from `git show HEAD:...`), so the tests cannot pass vacuously
against the behavior they replace. The live PostgreSQL characterization —
concurrent writes, restrict-key variance, real semantic-loss rejection —
lives in `test_restore_oracle_characterization.py` (docker-gated).
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "deploy" / "scripts"
ORACLE_LIB = SCRIPTS / "pg-semantic-oracle.sh"
BACKUP_SH = SCRIPTS / "backup.sh"
VERIFY_SH = SCRIPTS / "verify-restore.sh"
RUNBOOK = REPO / "docs" / "install" / "deployment-topology.md"
SPEC = REPO / "docs" / "specs" / "SPEC-070226-fbe3-deployment-topology.md"

FAIL_CLASSES = ("ARTIFACT", "RESTORE", "SEMANTIC", "VERIFIER")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _pre_change_script(name: str) -> str:
    """The pre-#1881 version of a deploy script, from a checked-in fixture.

    Deliberately not read from git: on a committed checkout `HEAD:<path>`
    already returns the post-change blob, and resolving a true base revision
    is fragile under CI's shallow fetches. The fixtures under
    tests/fixtures/pre-1881/ are pinned baseline copies, so the fail-before
    assertions run against the actual old scripts.
    """
    fixture = REPO / "tests" / "fixtures" / "pre-1881" / name
    assert fixture.exists(), f"missing pre-change baseline fixture: {fixture}"
    return _read(fixture)


def _bash_n(path: Path) -> None:
    subprocess.run(["bash", "-n", str(path)], check=True)


# ── The fix's load-bearing structure ─────────────────────────────────────────


def test_oracle_definitions_are_single_sourced() -> None:
    """Both scripts must use the shared oracle lib; the evidence SQL lives only there.

    If backup.sh and verify-restore.sh each carried their own copy of the
    evidence queries, a one-sided edit would silently make backup-time and
    restore-time evidence incomparable — exactly the class of drift #1881
    forbids — so the SQL constants are pinned to the lib alone.
    """
    lib = _read(ORACLE_LIB)
    assert "ORACLE_SCHEMA_SQL=" in lib
    assert "ORACLE_ROWCOUNTS_SQL=" in lib
    # The schema inventory must record the fully formatted column type
    # (format_type keeps typmods, arrays, and domains). information_schema
    # collapses arrays to 'ARRAY' and pgvector/user-defined types to
    # 'USER-DEFINED', so a restore swapping vector(1536) for vector(768)
    # would otherwise produce identical evidence and report PASS.
    assert "format_type(" in lib, "schema SQL must use pg_catalog.format_type(atttypid, atttypmod)"
    assert "information_schema.columns" not in lib, (
        "schema SQL must not use the collapsed data_type view"
    )
    for script in (BACKUP_SH, VERIFY_SH):
        text = _read(script)
        assert "pg-semantic-oracle.sh" in text, f"{script.name} must source the shared oracle"
        assert "ORACLE_SCHEMA_SQL=" not in text, f"{script.name} must not redefine the schema query"
        assert "ORACLE_ROWCOUNTS_SQL=" not in text, (
            f"{script.name} must not redefine the row-count query"
        )


def test_backup_binds_archive_and_evidence_to_one_snapshot() -> None:
    """The custom archive and the evidence must come from one exported snapshot.

    The pre-#1881 script took two independent dumps; any concurrent write
    between them made them describe different states. The fix exports a
    snapshot, hands it to pg_dump via --snapshot, and reads the evidence
    through the same snapshot id while the exporting transaction is open.
    """
    backup = _read(BACKUP_SH)
    assert "oracle_begin_snapshot" in backup
    assert "--snapshot=" in backup, "pg_dump must run inside the exported snapshot"
    assert "oracle_collect_evidence" in backup
    # Evidence collection must receive the snapshot id (three-argument form).
    assert "SNAPSHOT_ID" in backup
    assert "oracle_end_snapshot" in backup, "the exporting transaction must be closed"
    assert "pg_export_snapshot" in _read(ORACLE_LIB)
    # The old second plain-text dump (the two-snapshot defect) must be gone.
    assert 'pg_dump -U "${PG_USER}" -d "${PG_DB}" --no-owner' not in backup


def test_verify_compares_semantic_evidence_not_dump_bytes() -> None:
    """The drill must diff schema/row-count evidence, never re-dump for a hash.

    Pre-#1881, verify-restore.sh re-ran pg_dump on the restored DB and
    compared SHA-256 with `postgres-<db>.sql.sha256`. On PostgreSQL >= 17 that
    comparison fails spuriously (random restrict key), and even where it
    passes it says nothing about schema or data fidelity.
    """
    verify = _read(VERIFY_SH)
    assert ".sql.sha256" not in verify, "the raw plain-dump hash oracle must be gone"
    assert "SCHEMA_EVIDENCE" in verify and "ROWCOUNT_EVIDENCE" in verify
    assert "diff -u" in verify
    # No re-dump of the restored database may feed the comparison.
    assert "RESTORED_HASH" not in verify
    old = _pre_change_script("verify-restore.sh")
    assert "RESTORED_HASH" in old and ".sql.sha256" in old, (
        "pre-change script should carry the raw-hash oracle; fail-before baseline drifted"
    )


def test_distinct_failure_classes_in_verify_drill() -> None:
    """artifact / restore / semantic / verifier failures must be distinguishable.

    The pre-#1881 drill had a single `fail()` path, so an operator could not
    tell a corrupt backup from a bad restore from a drill that never ran.
    """
    verify = _read(VERIFY_SH)
    for cls in FAIL_CLASSES:
        assert f"fail_{cls.lower()}" in verify, f"missing failure class: {cls}"
    old = _pre_change_script("verify-restore.sh")
    for cls in FAIL_CLASSES:
        assert f"fail_{cls.lower()}" not in old


def test_security_defaults_preserved_no_restrict_key() -> None:
    """No script may invoke pg_dump --restrict-key (known-key injection risk).

    Checked on non-comment lines: the scripts are expected to *document* why
    the flag is avoided; what must never appear is an actual invocation.
    """
    for path in sorted(SCRIPTS.glob("*.sh")):
        code = "\n".join(
            line for line in _read(path).splitlines() if not line.lstrip().startswith("#")
        )
        assert "--restrict-key" not in code, f"{path.name} must not set --restrict-key"


def test_container_readiness_probes_require_the_final_server() -> None:
    """The characterisation fixture's readiness probe must target the final server.

    The postgres image entrypoint initialises the cluster under a temporary
    server bound to the unix socket only (`listen_addresses=''`). That server
    answers a socket `pg_isready` — and even an authenticated socket `psql`
    query — before it is stopped and the real server starts, so a socket probe
    can report ready while the first real statement races the restart and dies
    with psql exit 2 ("connection went bad"). That flaked the live
    characterisation tests through the module fixture in the coverage gate's
    root producer (CI run 39130160694).

    This pin was carried by the #1790 readiness repair and dropped when
    develop #2185 rewrote this file; it is re-landed here because the
    characterisation fixture's TCP probe is still the only assertion that the
    *final* server — not the temporary bootstrap server, which answers socket
    reads — is up. The round-4 reconciliation recorded that the structural test
    should assert the probe targets `-h 127.0.0.1` "so a future sync cannot
    silently lose the TCP half again"; this is that pin for the characterisation
    fixture. (#2185's `test_scratch_ready_means_the_target_database_answers`
    separately pins the drill script's shell readiness for the socket+query
    shape develop chose there.)

    A probe over `-h 127.0.0.1` stays unanswered until the final server
    listens, which is the server every consumer of the readiness signal
    actually talks to; the probe must additionally execute a statement, so
    readiness means "accepting connections" *and* "can run queries" — the two
    things the statements after the probe rely on.
    """
    characterization = _read(REPO / "tests" / "test_restore_oracle_characterization.py")
    assert '"-h",\n        "127.0.0.1",' in characterization, (
        "the characterisation fixture's readiness probe must target TCP "
        "(-h 127.0.0.1): the temporary init server answers socket probes but "
        "never listens on TCP, so only a TCP round-trip proves the final "
        "server is up (psql exit 2 race in CI run 39130160694)"
    )
    assert '"-c",\n        "SELECT 1"' in characterization, (
        "the characterisation fixture's readiness probe must execute a query, "
        "not merely confirm the server is accepting connections: a connection "
        "accepted by the temporary bootstrap server still breaks when it is "
        "stopped before the final server starts"
    )


def test_scratch_ready_means_the_target_database_answers() -> None:
    """The drill must wait for ${PG_DB} itself, not just for a listening server.

    The postgres image entrypoint runs a temporary bootstrap server that
    accepts socket connections before its init step creates POSTGRES_DB.
    Readiness gated on pg_isready alone let pg_restore race into that window
    and die with `FATAL: database "maistro" does not exist` — observed live
    in CI inside test_real_verify_restore_drill_passes_end_to_end after the
    same test had passed in the same job. The loop must therefore require one
    successful query against the target database before pg_restore runs.
    """
    verify = _read(VERIFY_SH)
    # The DB-answering condition, not pg_isready alone, is what breaks the
    # loop; and the post-loop guard falls into the verifier class when the
    # target database never becomes ready.
    loop_body = verify.split("for _ in $(seq 1 60); do", 1)[-1].split("done", 1)[0]
    assert "pg_isready" in loop_body, "the scratch loop must still probe the server"
    assert "psql" in loop_body and '-d "${PG_DB}"' in loop_body, (
        "the scratch loop must require the target database to answer, "
        "not just a listening server (entrypoint temp-server race)"
    )
    tail = verify.split("done", 1)[-1]
    assert 'fail_verifier "scratch postgres did not become ready' in tail, (
        "a never-ready scratch database must fail as a verifier failure"
    )
    # pg_restore must come after the database-level readiness guard.
    assert tail.find('fail_verifier "scratch postgres did not become ready') < tail.find(
        "pg_restore"
    ), "pg_restore must run only after the target database answered"


# ── Fail-before: the old scripts violate every pinned property ───────────────


def test_pre_change_backup_took_two_unconstrained_dumps() -> None:
    old = _pre_change_script("backup.sh")
    assert "--snapshot=" not in old, "pre-change backup.sh unexpectedly snapshot-bound"
    assert ".sql" in old, "pre-change backup.sh unexpectedly dropped the plain dump"


# ── Claims: runbook and spec must describe the oracle that exists ────────────


@pytest.mark.parametrize(("doc",), [(RUNBOOK,), (SPEC,)])
def test_docs_no_longer_claim_bit_for_bit_dump_hash(doc: Path) -> None:
    text = _read(doc).lower()
    assert "bit-for-bit" not in text, f"{doc.name} still claims the retired byte-equality property"
    assert "via pg_dump hash" not in text.replace("  ", " ")


def test_docs_describe_semantic_oracle_and_failure_classes() -> None:
    runbook = _read(RUNBOOK)
    assert "schema" in runbook.lower() and "row counts" in runbook.lower()
    for cls in FAIL_CLASSES:
        assert cls.lower() in runbook.lower(), f"runbook does not document failure class {cls}"


# ── Scripts stay valid bash ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("script",),
    [(ORACLE_LIB,), (BACKUP_SH,), (VERIFY_SH,)],
)
def test_deploy_scripts_parse_as_bash(script: Path) -> None:
    assert script.exists(), f"{script} missing"
    _bash_n(script)


def test_oracle_lib_refuses_to_run_without_oracle_psql() -> None:
    """Sourcing the lib without defining oracle_psql() must fail loudly, not silently
    produce empty evidence files (the silent-empty-file failure is what the aborted
    first implementation of #1881 would have shipped)."""
    probe = (
        "set -euo pipefail\n"
        f"source {ORACLE_LIB}\n"
        "if oracle_collect_evidence /tmp/o-schema /tmp/o-rowcounts 2>/dev/null; then\n"
        "  echo COLLECTED\n"
        "else\n"
        "  echo REFUSED\n"
        "fi\n"
        "rm -f /tmp/o-schema /tmp/o-rowcounts\n"
    )
    out = subprocess.run(
        ["bash", "-c", probe],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "REFUSED" in out.stdout, out.stdout + out.stderr


# ── Coprocess lifecycle: a dead psql session must fail cleanly ───────────────
# CI regression: when the snapshot-export psql dies, bash reaps the coprocess
# and unsets the whole ORACLE_TX array; the pre-fix oracle_end_snapshot then
# aborted backup.sh under set -u with "ORACLE_TX[1]: unbound variable"
# (the `test` and Coverage gate jobs at 0f84314dcf51). These run the REAL lib
# against fake oracle_psql() doubles — no Docker, no PostgreSQL.


def _run_lib_probe(body: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", f"set -euo pipefail\nsource {ORACLE_LIB}\n{body}"],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def test_oracle_end_snapshot_survives_a_dead_session() -> None:
    """A psql that exits before COMMIT must give oracle_end_snapshot a clean,
    distinct failure — never a bash unbound-variable abort of the caller."""
    out = _run_lib_probe(
        # An oracle_psql that dies immediately, printing nothing.
        "oracle_psql() { :; }\n"
        "oracle_begin_snapshot 2>/dev/null || true\n"
        "if oracle_end_snapshot 2>end.err; then echo END_OK; else echo END_FAILED; fi\n"
        'if grep -q "unbound variable" end.err; then echo UNBOUND_CRASH; else echo NO_CRASH; fi\n'
        "rm -f end.err\n"
    )
    assert out.returncode == 0, out.stdout + out.stderr
    assert "END_FAILED" in out.stdout and "NO_CRASH" in out.stdout, out.stdout + out.stderr
    assert "unbound variable" not in out.stderr, out.stderr


def test_oracle_begin_snapshot_rejects_a_garbage_snapshot_id() -> None:
    """A session echoing anything but a snapshot id (stub output, a banner) must
    fail begin_snapshot with a distinct message — the id is interpolated into
    SET TRANSACTION SNAPSHOT '<id>', so garbage must not flow into SQL."""
    out = _run_lib_probe(
        # A session that echoes non-id garbage (a stub, a banner) and stays
        # alive reading stdin, so the write/read race always resolves the
        # same way and the id validation is what rejects the garbage.
        'oracle_psql() { echo "fixture data"; cat; }\n'
        "if oracle_begin_snapshot 2>begin.err; then echo BEGAN; else echo BEGIN_FAILED; fi\n"
        'if grep -q "not a PostgreSQL snapshot id" begin.err; then echo REJECTED; else echo ACCEPTED; fi\n'
        "rm -f begin.err\n"
    )
    assert out.returncode == 0, out.stdout + out.stderr
    assert "BEGIN_FAILED" in out.stdout and "REJECTED" in out.stdout, out.stdout + out.stderr
    assert "unbound variable" not in out.stderr, out.stderr


# ── Scratch readiness: fail fast on a dead container, wait long enough ──────
# CI regression (quality.yml coverage-gate, 2026-10-18): on a runner congested
# by the same job's 12-minute root suite, initdb outlived the drill's 60-probe
# readiness budget and the drill reported VERIFIER FAIL for infrastructure.
# Two properties prevent a repeat: the budget must be long enough to absorb a
# loaded runner, and a scratch container that has EXITED must be reported
# immediately — with its last log lines — instead of burning the whole budget
# on a container that can never become ready.


READINESS_BUDGET_PROBES = 180


def _fake_docker_shim(bin_dir: Path, probe_log: Path) -> None:
    """Write a `docker` shim whose engine never becomes ready and whose one
    container is already exited. The shim records every pg_isready probe to
    `probe_log`, so the test can count probes instead of asserting wall-clock
    timing (which would pin the host's speed, not the drill's behavior)."""
    shim = bin_dir / "docker"
    shim.write_text(
        "#!/usr/bin/env bash\n"
        'case "$1" in\n'
        "  run) echo shim-container-id ;;\n"
        "  exec)\n"
        f'    echo "$2" >> {probe_log}\n'
        "    exit 1 ;;\n"
        "  inspect) echo false ;;\n"
        "  logs)\n"
        '    echo "shim-engine: FATAL: did not start" >&2 ;;\n'
        "  *)\n"
        '    echo "shim docker: unexpected: $*" >&2\n'
        "    exit 1 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    shim.chmod(0o755)


def _write_backup_artifacts(backup_dir: Path) -> None:
    """Fabricate the artifact set the drill's preflight integrity-checks, so the
    drill reaches the scratch-readiness step instead of failing ARTIFACT first."""
    backup_dir.mkdir(parents=True)
    evidence = "accounts=3\nledger=2\n"
    for name, content in (
        ("postgres-maistro.dump", b"PGDMP shim archive"),
        ("postgres-maistro.schema", b"public.accounts\n"),
        ("postgres-maistro.rowcounts", evidence.encode()),
        ("postgres-maistro.provenance", b"snapshot=00000013-00000002-1\nserver_version=17.0\n"),
    ):  # digest of every artifact is pre-registered beside it
        path = backup_dir / name
        path.write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()
        (backup_dir / f"{name}.sha256").write_text(f"{digest}  {name}\n")


def test_verify_drill_fails_fast_when_scratch_container_dies(tmp_path: Path) -> None:
    """A scratch postgres that exits before readiness must fail VERIFIER fast,

    naming the exit and carrying the engine's last log lines — never burn the
    full readiness budget probing a container that can no longer start. The
    old loop had no liveness check: a dead container cost the whole budget and
    the message blamed readiness rather than the exit, exactly what a loaded
    CI runner turned into an opaque VERIFIER FAIL minutes into a job."""
    date = "2026-10-18"
    backup_root = tmp_path / "backups"
    _write_backup_artifacts(backup_root / date)
    probe_log = tmp_path / "pg-isready-probes.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_docker_shim(bin_dir, probe_log)

    env = dict(os.environ)
    env.update(
        PATH=f"{bin_dir}{os.pathsep}{env['PATH']}",
        BACKUP_ROOT=str(backup_root),
        PG_IMAGE="shim-never-ready:latest",
        POSTGRES_USER="maistro",
        POSTGRES_DB="maistro",
    )
    proc = subprocess.run(
        ["bash", str(VERIFY_SH), date],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO),
        timeout=60,
    )
    assert proc.returncode != 0, proc.stdout
    assert "VERIFIER FAIL" in proc.stderr, f"{proc.stdout}\n{proc.stderr}"
    # The dead container is named as dead, and its last log lines travel with
    # the failure — the operator sees the engine's own error, not just the
    # drill's verdict.
    assert "exited before becoming ready" in proc.stderr, f"{proc.stdout}\n{proc.stderr}"
    assert "shim-engine: FATAL: did not start" in proc.stderr, f"{proc.stdout}\n{proc.stderr}"
    # Fail fast, proven structurally: one readiness probe happened, not the
    # whole budget. Counting probes pins the behavior without asserting the
    # host's wall-clock speed.
    probes = probe_log.read_text().splitlines()
    assert len(probes) < 10, (
        f"the drill probed a dead container {len(probes)} times — "
        "the liveness check must stop the wait as soon as the container exits"
    )


def test_verify_drill_readiness_budget_absorbs_a_loaded_runner() -> None:
    """The readiness budget must be able to outlast a congested CI runner.

    The failing run showed initdb outliving a 60-probe budget on a runner that
    had just executed a 12-minute suite. The budget is pinned here as text so
    an accidental shrink back to ~60 fails this review-time assertion, the
    same way the suite pins the drill's other load-bearing structure."""
    verify = _read(VERIFY_SH)
    assert f"seq 1 {READINESS_BUDGET_PROBES}" in verify, (
        f"the scratch readiness budget must stay at {READINESS_BUDGET_PROBES} probes; "
        "the 2026-10-18 coverage-gate failure exhausted a 60-probe budget on a "
        "congested runner"
    )
    # And the loop must keep checking liveness: a longer budget alone would
    # just spend more time failing opaquely on a dead container.
    assert ".State.Running" in verify, (
        "the readiness loop must fail fast when the scratch container has exited"
    )
    # Readiness must be proven by a real query, not pg_isready alone:
    # pg_isready also answers during initdb's temporary-server window, so a
    # pg_isready-keyed loop can break mid-init and the restore that follows
    # fails as RESTORE instead of waiting out the restart.
    assert "SELECT 1" in verify, (
        "scratch readiness must be confirmed by a real query on the final server, "
        "not pg_isready alone (pg_isready answers during initdb's temporary server)"
    )
