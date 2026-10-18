"""Issue #88 (M3-A6): the backup/restore drill proves the Conductor's durable state.

The D-18 audit found that ``deploy/scripts/backup.sh`` never captured the
``conductor-data`` volume — the authoritative ``state.db``, the age-encrypted
vault (``secrets.age``), and the per-user credential store — and that the
decrypting identity (``admin.key``) had no escrow at all. Losing it makes every
stored secret cryptographically unrecoverable.

The drill in ``deploy/scripts/verify-restore.sh`` is where that gap is proven
closed, so these tests drive the real script functions (sourced, not reimplemented)
against real artifacts: a real age identity + vault built with ``age-keygen``/``age``,
and a real SQLite ``state.db`` carrying the canonical spine tables. Each acceptance
failure mode is exercised: absent escrow (for a captured ciphertext), wrong identity,
corrupt component, missing state.db, a captured ciphertext without its escrow root,
and a pinned known secret that must decrypt. The optional stores are also proven to
pass when legitimately absent: a Conductor has no ``secrets.age`` until its optional
vault is provisioned, and no ``user_credentials.enc`` until the first credential is
persisted, so a valid backup may lack either (and then need no escrow at all).
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
VERIFY_SCRIPT = REPO_ROOT / "deploy" / "scripts" / "verify-restore.sh"
BACKUP_SCRIPT = REPO_ROOT / "deploy" / "scripts" / "backup.sh"

requires_age = pytest.mark.skipif(
    shutil.which("age") is None or shutil.which("age-keygen") is None,
    reason="age/age-keygen not on PATH — the decrypt proof cannot run",
)

KNOWN_SECRET_NAME = "PROOF_SECRET"
KNOWN_SECRET_VALUE = "drill-value-12345"

#: The canonical spine the drill requires in state.db, matching the stores the
#: Conductor actually persists (runs/sqlite_store.py, workspaces/sqlite_store.py,
#: graph/durable_runs/continuation.py, sessions, audit log).
CANONICAL_SCHEMA = """
CREATE TABLE canonical_runs (
    run_id TEXT PRIMARY KEY, status TEXT, workspace_id TEXT, payload TEXT);
CREATE TABLE canonical_node_runs (
    node_run_id TEXT PRIMARY KEY, run_id TEXT, node_id TEXT,
    ordinal INTEGER, status TEXT, payload TEXT);
CREATE TABLE canonical_attempts (
    attempt_id TEXT PRIMARY KEY, node_run_id TEXT,
    ordinal INTEGER, status TEXT, payload TEXT);
CREATE TABLE canonical_workspaces (
    workspace_id TEXT PRIMARY KEY, payload TEXT);
CREATE TABLE canonical_workspace_memberships (
    membership_id TEXT PRIMARY KEY, workspace_id TEXT, payload TEXT);
CREATE TABLE graph_continuations (
    run_id TEXT PRIMARY KEY, status TEXT, project_id TEXT,
    version INTEGER NOT NULL DEFAULT 0, continuation_json TEXT);
CREATE TABLE sessions (session_id TEXT PRIMARY KEY, payload TEXT);
CREATE TABLE audit_log (id INTEGER PRIMARY KEY, payload TEXT);
"""


def _build_state_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(CANONICAL_SCHEMA)
        conn.execute(
            "INSERT INTO canonical_runs VALUES ('run-drill-001', 'completed', 'ws-1', '{}')"
        )
        conn.execute(
            "INSERT INTO canonical_node_runs VALUES"
            " ('nr-1', 'run-drill-001', 'node-a', 0, 'completed', '{}')"
        )
        # ordinal 1 on the completed attempt IS the inter-replica fence
        # (the conditional UPDATE in runs/sqlite_store.py compares on it).
        conn.execute(
            "INSERT INTO canonical_attempts VALUES ('att-1', 'nr-1', 1, 'completed', '{}')"
        )
        conn.execute("INSERT INTO canonical_workspaces VALUES ('ws-1', '{}')")
        conn.execute("INSERT INTO canonical_workspace_memberships VALUES ('m-1', 'ws-1', '{}')")
        conn.execute(
            "INSERT INTO graph_continuations VALUES"
            " ('run-drill-001', 'waiting_input', 'ws-1', 7, '{}')"
        )
        conn.execute("INSERT INTO sessions VALUES ('sess-1', '{}')")
        conn.execute("INSERT INTO audit_log VALUES (1, '{}')")
        conn.commit()
    finally:
        conn.close()


def _build_vault(data_dir: Path) -> str:
    """Create a real age identity + encrypted vault; return the public key."""
    identity = data_dir / "admin.key"
    subprocess.run(
        ["age-keygen", "-o", str(identity)],
        check=True,
        capture_output=True,
        timeout=30,
    )
    public_key = ""
    for line in identity.read_text().splitlines():
        if line.startswith("# public key: "):
            public_key = line[len("# public key: ") :].strip()
    assert public_key, "age-keygen produced an identity without a public key line"
    vault = data_dir / "secrets.age"
    subprocess.run(
        ["age", "-r", public_key, "-o", str(vault)],
        input=f"{KNOWN_SECRET_NAME} = {KNOWN_SECRET_VALUE}\n".encode(),
        check=True,
        capture_output=True,
        timeout=30,
    )
    return public_key


def _write_manifest(root: Path, files: list[str]) -> None:
    lines = [
        subprocess.run(
            ["sha256sum", str((root / name).relative_to(root))],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout
        for name in files
    ]
    (root / "manifest.sha256").write_text("".join(lines), encoding="utf-8")


@pytest.fixture()
def backup_and_escrow(tmp_path: Path) -> tuple[Path, Path]:
    """A realistic backup artifact + matching credential escrow."""
    data = tmp_path / "backup" / "conductor-data"
    data.mkdir(parents=True)
    _build_state_db(data / "state.db")
    _build_vault(data)
    (data / "user_credentials.enc").write_bytes(b"fernet-ciphertext-stand-in\n")

    escrow = tmp_path / "escrow"
    escrow.mkdir()
    shutil.copy2(data / "admin.key", escrow / "admin.key")
    (escrow / "credential_master.key").write_bytes(b"fernet-master-key-stand-in\n")
    os.chmod(escrow / "admin.key", 0o600)
    os.chmod(escrow / "credential_master.key", 0o600)
    _write_manifest(escrow, ["admin.key", "credential_master.key"])
    _write_manifest(
        tmp_path / "backup",
        [
            "conductor-data/state.db",
            "conductor-data/secrets.age",
            "conductor-data/user_credentials.enc",
        ],
    )
    return tmp_path / "backup", escrow


def _run_drill(
    backup: Path,
    escrow: Path,
    *,
    expected_secret: str | None = None,
    manifest: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Source the real script and run its verification functions.

    ``manifest=False`` skips ``verify_backup_manifest`` so a test can exercise a
    specific conductor check on a deliberately mutated artifact; the happy-path
    test always runs the full pipeline.
    """
    calls = f'verify_backup_manifest "{backup}"\n' if manifest else ""
    script = f'source "{VERIFY_SCRIPT}"\n{calls}verify_conductor_backup "{backup}" "{escrow}"\n'
    env = {k: v for k, v in os.environ.items() if k != "EXPECTED_SECRET_NAME"}
    if expected_secret is not None:
        env["EXPECTED_SECRET_NAME"] = expected_secret
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )


@requires_age
def test_drill_proves_conductor_restore_end_to_end(
    backup_and_escrow: tuple[Path, Path],
) -> None:
    """The happy path: integrity, schema, history, fencing, and the decrypt proof."""
    backup, escrow = backup_and_escrow
    proc = _run_drill(backup, escrow)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, combined
    # IDs/provenance preserved and inspectable (not assumed from PostgreSQL).
    assert "historical Run inspectable: run-drill-001" in proc.stdout
    # Fencing state survived restore as data.
    assert "continuation fencing version preserved: 7" in proc.stdout
    assert "canonical_attempts: 1 row(s)" in proc.stdout
    # The decrypt proof: the escrowed identity actually opened the vault.
    assert "decrypt proof: escrowed admin.key decrypted secrets.age" in proc.stdout


@requires_age
def test_drill_proves_known_backed_up_secret_decrypts(
    backup_and_escrow: tuple[Path, Path],
) -> None:
    backup, escrow = backup_and_escrow
    proc = _run_drill(backup, escrow, expected_secret=KNOWN_SECRET_NAME)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert f"known secret '{KNOWN_SECRET_NAME}' is readable" in proc.stdout


@requires_age
def test_wrong_pinned_secret_fails(backup_and_escrow: tuple[Path, Path]) -> None:
    backup, escrow = backup_and_escrow
    proc = _run_drill(backup, escrow, expected_secret="SECRET_THAT_WAS_NEVER_STORED")
    assert proc.returncode != 0
    assert "SECRET_THAT_WAS_NEVER_STORED" in proc.stderr


@requires_age
def test_absent_credential_escrow_is_a_hard_failure(
    backup_and_escrow: tuple[Path, Path],
) -> None:
    """The core #88 detection: a backup without its escrow must not verify."""
    backup, _escrow = backup_and_escrow
    proc = _run_drill(backup, backup.parent / "escrow-that-does-not-exist")
    assert proc.returncode != 0
    assert "credential escrow missing" in proc.stderr


@requires_age
def test_unrelated_identity_fails_decrypt_proof(
    backup_and_escrow: tuple[Path, Path],
) -> None:
    """An escrowed key that is not THE identity must fail loudly, not pass."""
    backup, escrow = backup_and_escrow
    stranger_tmp = escrow / "admin.key.stranger"
    subprocess.run(
        ["age-keygen", "-o", str(stranger_tmp)],
        check=True,
        capture_output=True,
        timeout=30,
    )
    os.replace(stranger_tmp, escrow / "admin.key")
    os.chmod(escrow / "admin.key", 0o600)
    _write_manifest(escrow, ["admin.key", "credential_master.key"])
    proc = _run_drill(backup, escrow, manifest=False)
    assert proc.returncode != 0
    assert "DECRYPT PROOF FAILED" in proc.stderr


@requires_age
def test_corrupt_backup_component_fails_manifest(
    backup_and_escrow: tuple[Path, Path],
) -> None:
    backup, escrow = backup_and_escrow
    vault = backup / "conductor-data" / "secrets.age"
    vault.write_bytes(b"\x00" + vault.read_bytes()[1:])
    proc = _run_drill(backup, escrow)
    assert proc.returncode != 0
    assert "integrity manifest check failed" in proc.stderr


@requires_age
def test_optional_store_absent_still_verifies(
    backup_and_escrow: tuple[Path, Path],
) -> None:
    """user_credentials.enc is written only with the first persisted credential.

    A valid backup of such a Conductor legitimately lacks it, so the drill must
    skip its escrow-root check — not page an operator over a non-problem.
    """
    backup, escrow = backup_and_escrow
    (backup / "conductor-data" / "user_credentials.enc").unlink()
    proc = _run_drill(backup, escrow, manifest=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "user_credentials.enc not captured" in proc.stdout


@requires_age
def test_unprovisioned_conductor_backup_verifies_without_escrow(
    tmp_path: Path,
) -> None:
    """A fresh Conductor has neither secrets.age nor user_credentials.enc.

    state.db alone is authoritative and mandatory; with no ciphertext captured,
    no escrow can exist yet, and the drill must not demand one.
    """
    backup = tmp_path / "backup"
    data = backup / "conductor-data"
    data.mkdir(parents=True)
    _build_state_db(data / "state.db")
    proc = _run_drill(backup, tmp_path / "escrow-that-does-not-exist", manifest=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "nothing ciphertext to verify" in proc.stdout


@requires_age
def test_captured_credential_store_without_its_root_fails(
    backup_and_escrow: tuple[Path, Path],
) -> None:
    """Conditionality is one-way: a captured ciphertext always demands its root."""
    backup, escrow = backup_and_escrow
    (escrow / "credential_master.key").unlink()
    _write_manifest(escrow, ["admin.key"])
    proc = _run_drill(backup, escrow, manifest=False)
    assert proc.returncode != 0
    assert "credential escrow has no credential_master.key" in proc.stderr


@requires_age
def test_missing_state_db_fails(
    backup_and_escrow: tuple[Path, Path],
) -> None:
    """state.db is the authoritative spine: it is never optional."""
    backup, escrow = backup_and_escrow
    (backup / "conductor-data" / "state.db").unlink()
    proc = _run_drill(backup, escrow, manifest=False)
    assert proc.returncode != 0
    assert "conductor-data/state.db is missing or empty" in proc.stderr


@requires_age
def test_truncated_state_db_fails_integrity(
    backup_and_escrow: tuple[Path, Path],
) -> None:
    backup, escrow = backup_and_escrow
    (backup / "conductor-data" / "state.db").write_bytes(b"not sqlite at all")
    proc = _run_drill(backup, escrow, manifest=False)
    assert proc.returncode != 0
    assert "integrity/schema verification" in proc.stderr


def test_deploy_drill_scripts_are_valid_bash() -> None:
    for script in (BACKUP_SCRIPT, VERIFY_SCRIPT):
        proc = subprocess.run(
            ["bash", "-n", str(script)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert proc.returncode == 0, f"{script.name}: {proc.stderr}"
