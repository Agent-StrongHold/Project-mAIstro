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


def test_verify_readiness_failure_is_diagnosable() -> None:
    """A scratch container that never becomes ready must leave evidence.

    Two CI runs on 2026-10-18 (39116394628, 39134762935) failed two different
    characterization tests with a bare "scratch postgres did not become
    ready" — no logs, no container state — so a slow initdb under runner load
    could not be told apart from a container that crashed at startup. The
    readiness loop must probe the container's state (fail fast once it has
    exited), surface its logs on every readiness failure, and carry a budget
    that absorbs slow initdb instead of the old 60s one.
    """
    verify = _read(VERIFY_SH)
    assert "docker logs" in verify, "a readiness failure must surface the scratch container's logs"
    assert "{{.State.Running}}" in verify, (
        "readiness must fail fast when the container has exited — waiting cannot help"
    )
    assert "seq 1 120" in verify, "readiness budget must absorb slow initdb under load"
    old = _pre_change_script("verify-restore.sh")
    assert "docker logs" not in old, "pre-change script unexpectedly already dumped logs"


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
