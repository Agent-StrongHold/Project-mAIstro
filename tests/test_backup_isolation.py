"""Exercise the production scripts against real files, with only Docker faked.

The fake executes the actual container copy shell and SQLite backup program,
not a reimplementation of their allowlist. No Docker daemon or age is needed.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "deploy/scripts"
STAMP = datetime.now(UTC).strftime("%Y-%m-%d")

# Commands execute only inside tmp_path. Mounted paths in the real scripts are
# rewritten to fixture directories; the actual sh/cp/sqlite code then runs.
DOCKER = r"""
import json
import os
from pathlib import Path
import subprocess
import sys

args = sys.argv[1:]
with open(os.environ["DOCKER_TEST_LOG"], "a") as log:
    log.write(json.dumps(args) + "\n")
source = os.environ["TEST_CONDUCTOR"]
snapshot = os.environ["TEST_SNAPSHOT"]
if args[0] == "compose":
    cmd = args[args.index("-T") + 2:]
    if "psql" in cmd and "-c" not in cmd and "-V" not in cmd:
        for line in sys.stdin:
            if "pg_export_snapshot" in line:
                print("00000001-0000000A-1", flush=True)
    elif cmd[0] == "python":
        code = sys.stdin.read().replace("/data", source).replace("/tmp/state.db.backup-snapshot", snapshot)
        subprocess.run([sys.executable, "-c", code], check=True)
    elif cmd[0] == "cat":
        sys.stdout.buffer.write(Path(snapshot).read_bytes())
    elif cmd[0] == "rm":
        Path(snapshot).unlink()
    else:
        print("fixture data")
elif args[0] == "run":
    mounts = {}
    i = 1
    while args[i] != "alpine":
        if args[i] == "-v":
            host, container, *_ = args[i + 1].split(":")
            mounts[container] = host
            i += 2
        else:
            i += 1
    cmd = args[i + 1:]
    if "/escrow" in mounts or ("/data" in mounts and mounts["/data"] == source):
        for container, host in sorted(mounts.items(), key=lambda x: -len(x[0])):
            cmd = [part.replace(container, host) for part in cmd]
        subprocess.run(cmd, check=True)
# Other Docker volume copies and cleanup are irrelevant to this boundary.
"""


def _fixture(tmp_path: Path) -> dict[str, str]:
    source = tmp_path / "conductor"
    source.mkdir()
    with sqlite3.connect(source / "state.db") as db:
        db.execute("CREATE TABLE marker (value TEXT)")
        db.execute("INSERT INTO marker VALUES ('snapshot survives')")
    (source / "secrets.age").write_bytes(b"encrypted vault fixture")
    (source / "user_credentials.enc").write_bytes(b"encrypted credential fixture")
    (source / "admin.key").write_bytes(b"age identity fixture")
    (source / "credential_master.key").write_bytes(b"fernet key fixture")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(f"#!{sys.executable}\n" + DOCKER)
    docker.chmod(0o700)
    return {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "BACKUP_ROOT": str(tmp_path / "backups"),
        "ESCROW_ROOT": str(tmp_path / "escrow"),
        "CONDUCTOR_DATA_VOLUME": str(source),
        "TEST_CONDUCTOR": str(source),
        "TEST_SNAPSHOT": str(tmp_path / "snapshot.db"),
        "DOCKER_TEST_LOG": str(tmp_path / "docker.log"),
        "POSTGRES_DB": "fixture",
        "REMOTE_TARGET": "",
        "RETENTION_DAYS": "14",
        "SKIP_CONDUCTOR_BACKUP": "0",
    }


def _backup(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPTS / "backup.sh")],
        env=env,
        text=True,
        capture_output=True,
        timeout=20,
        umask=0,
        check=False,
    )


def _verify(src: Path, function: str = "verify_backup_manifest", escrow: Path | None = None):
    return subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; "$2" "$3" "$4"',
            "isolation-test",
            str(SCRIPTS / "verify-restore.sh"),
            function,
            str(src),
            str(escrow or src.parent / "escrow"),
        ],
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )


def _seal(src: Path) -> None:
    lines = [
        f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(src)}\n"
        for p in sorted(src.rglob("*"))
        if p.is_file() and p.name != "manifest.sha256"
    ]
    (src / "manifest.sha256").write_text("".join(lines))


def test_only_snapshot_and_ciphertext_enter_artifact(tmp_path: Path) -> None:
    env = _fixture(tmp_path)
    source = Path(env["TEST_CONDUCTOR"])
    # Live WAL/SHM are produced by SQLite itself, not invalid synthetic WALs.
    with sqlite3.connect(source / "state.db") as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("INSERT INTO marker VALUES ('committed WAL survives')")
        db.commit()
        (source / "state.db-journal").write_bytes(b"")
        (source / ".private").write_bytes(b"not a backup component")
        (source / "unknown").mkdir()
        (source / "unknown" / "admin.key").write_bytes(b"nested secret")
        result = _backup(env)
    assert result.returncode == 0, result.stderr
    dest = Path(env["BACKUP_ROOT"]) / STAMP
    data = dest / "conductor-data"
    assert {p.name for p in data.iterdir()} == {"state.db", "secrets.age", "user_credentials.enc"}
    with sqlite3.connect(f"file:{data / 'state.db'}?mode=ro&immutable=1", uri=True) as db:
        assert db.execute("SELECT value FROM marker ORDER BY rowid").fetchall() == [
            ("snapshot survives",),
            ("committed WAL survives",),
        ]
    for name in ("secrets.age", "user_credentials.enc"):
        assert (data / name).read_bytes() == (source / name).read_bytes()
    escrow = Path(env["ESCROW_ROOT"]) / STAMP
    for name in ("admin.key", "credential_master.key"):
        assert (escrow / name).read_bytes() == (source / name).read_bytes()
        assert (escrow / name).stat().st_mode & 0o777 == 0o600
    assert dest.stat().st_mode & 0o777 == 0o700
    assert escrow.stat().st_mode & 0o777 == 0o700
    assert _verify(dest).returncode == 0
    assert not Path(env["TEST_SNAPSHOT"]).exists()
    manifest = (dest / "manifest.sha256").read_text()
    assert "admin.key" not in manifest and "credential_master.key" not in manifest
    commands = [json.loads(line) for line in Path(env["DOCKER_TEST_LOG"]).read_text().splitlines()]
    copies = [args[-1] for args in commands if args[0] == "run" and "/dest" in " ".join(args)]
    assert not any("cp -a /data/." in command for command in copies)


@pytest.mark.parametrize(
    "missing",
    [("secrets.age",), ("user_credentials.enc",), ("secrets.age", "user_credentials.enc")],
)
def test_unprovisioned_optional_ciphertext_still_backs_up(
    tmp_path: Path, missing: tuple[str, ...]
) -> None:
    env = _fixture(tmp_path)
    source = Path(env["TEST_CONDUCTOR"])
    for name in missing:
        (source / name).unlink()
    result = _backup(env)
    assert result.returncode == 0, result.stderr
    data = Path(env["BACKUP_ROOT"]) / STAMP / "conductor-data"
    assert {p.name for p in data.iterdir()} == {
        "state.db",
        "secrets.age",
        "user_credentials.enc",
    } - set(missing)


@pytest.mark.parametrize(
    "relation",
    ["equal", "escrow_inside", "backup_inside", "symlink", "dotdot", "backup_root", "escrow_root"],
)
def test_overlapping_roots_fail_before_docker(tmp_path: Path, relation: str) -> None:
    env = _fixture(tmp_path)
    backup = Path(env["BACKUP_ROOT"])
    if relation == "equal":
        env["ESCROW_ROOT"] = str(backup)
    elif relation == "escrow_inside":
        env["ESCROW_ROOT"] = str(backup / "keys")
    elif relation == "backup_inside":
        env["BACKUP_ROOT"] = str(Path(env["ESCROW_ROOT"]) / "backups")
    elif relation == "symlink":
        backup.mkdir()
        Path(env["ESCROW_ROOT"]).symlink_to(backup, target_is_directory=True)
    elif relation == "dotdot":
        env["ESCROW_ROOT"] = str(backup / "unused" / "..")
    elif relation == "backup_root":
        env["BACKUP_ROOT"] = "/"
    else:
        env["ESCROW_ROOT"] = "/"
    result = _backup(env)
    assert result.returncode != 0
    assert "must be disjoint" in result.stderr
    assert not Path(env["DOCKER_TEST_LOG"]).exists()


@pytest.mark.parametrize("root_name", ["BACKUP_ROOT", "ESCROW_ROOT"])
@pytest.mark.parametrize("entry", ["sentinel", ".hidden", "symlink", "subdirectory", "\n"])
def test_nonempty_destinations_fail_without_mutation(
    tmp_path: Path, root_name: str, entry: str
) -> None:
    env = _fixture(tmp_path)
    dest = Path(env[root_name]) / STAMP
    dest.mkdir(parents=True, mode=0o700)
    target = tmp_path / "do-not-overwrite"
    target.write_bytes(b"unchanged")
    child = dest / entry
    if entry == "symlink":
        child.symlink_to(target)
    elif entry == "subdirectory":
        child.mkdir()
    else:
        child.write_bytes(b"existing run")
    result = _backup(env)
    assert result.returncode != 0
    assert "must be empty" in result.stderr
    assert not Path(env["DOCKER_TEST_LOG"]).exists()
    assert target.read_bytes() == b"unchanged"
    assert list(dest.iterdir()) == [child]


@pytest.mark.parametrize("shape", ["symlink", "shared", "file"])
def test_unsafe_escrow_destination_fails_before_docker(tmp_path: Path, shape: str) -> None:
    env = _fixture(tmp_path)
    root = Path(env["ESCROW_ROOT"])
    root.mkdir()
    dest = root / STAMP
    if shape == "symlink":
        target = tmp_path / "elsewhere"
        target.mkdir(mode=0o700)
        dest.symlink_to(target, target_is_directory=True)
    elif shape == "shared":
        dest.mkdir(mode=0o755)
    else:
        dest.write_text("existing")
    result = _backup(env)
    assert result.returncode != 0
    assert not Path(env["DOCKER_TEST_LOG"]).exists()


@pytest.mark.parametrize(
    "name", ["secrets.age", "user_credentials.enc", "admin.key", "credential_master.key"]
)
@pytest.mark.parametrize("shape", ["symlink", "dangling", "directory", "fifo"])
def test_nonregular_source_is_refused(tmp_path: Path, name: str, shape: str) -> None:
    env = _fixture(tmp_path)
    entry = Path(env["TEST_CONDUCTOR"]) / name
    entry.unlink()
    if shape in ("symlink", "dangling"):
        target = tmp_path / "target"
        if shape == "symlink":
            target.write_bytes(b"must not be followed")
        entry.symlink_to(target)
    elif shape == "directory":
        entry.mkdir()
    else:
        os.mkfifo(entry)
    result = _backup(env)
    assert result.returncode != 0
    assert "must be a regular file" in result.stderr


@pytest.mark.parametrize(
    "name",
    [
        "admin.key",
        "credential_master.key",
        "state.db-wal",
        "state.db-shm",
        "state.db-journal",
        ".hidden",
        "unknown",
    ],
)
def test_sealed_contamination_is_rejected(tmp_path: Path, name: str) -> None:
    data = tmp_path / "conductor-data"
    data.mkdir()
    (data / "state.db").write_bytes(b"snapshot")
    (data / name).write_bytes(b"contamination")
    _seal(tmp_path)
    result = _verify(tmp_path)
    assert result.returncode != 0
    assert "unexpected conductor-data entry" in result.stderr


@pytest.mark.parametrize(
    "name",
    [
        "conductor-data",
        "conductor-data/state.db",
        "conductor-data/secrets.age",
        "conductor-data/user_credentials.enc",
    ],
)
def test_restore_refuses_symlinked_capture(tmp_path: Path, name: str) -> None:
    src = tmp_path / "backup"
    src.mkdir()
    data = src / "conductor-data"
    data.mkdir()
    target = tmp_path / "target"
    if name == "conductor-data":
        data.rmdir()
        target.mkdir()
        (target / "state.db").write_bytes(b"external snapshot")
    else:
        target.write_bytes(b"not an owned capture")
    (src / name).symlink_to(target)
    _seal(src)
    if name == "conductor-data":
        digest = hashlib.sha256((target / "state.db").read_bytes()).hexdigest()
        (src / "manifest.sha256").write_text(f"{digest}  conductor-data/state.db\n")
    result = _verify(src)
    assert result.returncode != 0
    assert (
        "ARTIFACT FAIL: conductor-data must not be a symlink" in result.stderr
        or "ARTIFACT FAIL: conductor-data must contain only regular files" in result.stderr
    )


@pytest.mark.parametrize("nested", ["escrow_inside", "backup_inside", "alias", "root"])
def test_restore_refuses_colocated_escrow(tmp_path: Path, nested: str) -> None:
    src = tmp_path / "backup"
    (src / "conductor-data").mkdir(parents=True)
    if nested == "escrow_inside":
        escrow = src / "keys"
    elif nested == "backup_inside":
        escrow = tmp_path
    elif nested == "alias":
        escrow = tmp_path / "alias"
        escrow.symlink_to(src, target_is_directory=True)
    else:
        escrow = Path("/")
    result = _verify(src, "verify_conductor_backup", escrow)
    assert result.returncode != 0
    assert "must be disjoint" in result.stderr


def test_main_rejects_contamination_even_with_conductor_opt_out(tmp_path: Path) -> None:
    env = _fixture(tmp_path)
    env["SKIP_CONDUCTOR_BACKUP"] = "1"
    src = Path(env["BACKUP_ROOT"]) / STAMP
    (src / "conductor-data").mkdir(parents=True)
    (src / "conductor-data" / "admin.key").write_bytes(b"leaked key")
    result = subprocess.run(
        ["bash", str(SCRIPTS / "verify-restore.sh"), STAMP],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode != 0
    assert "unexpected conductor-data entry" in result.stderr
    if Path(env["DOCKER_TEST_LOG"]).exists():
        assert all(
            json.loads(line)[0] == "rm"
            for line in Path(env["DOCKER_TEST_LOG"]).read_text().splitlines()
        )


def test_repeated_wal_snapshot_verification_does_not_mutate_artifact(tmp_path: Path) -> None:
    source = sqlite3.connect(tmp_path / "live.db")
    source.execute("PRAGMA journal_mode=WAL")
    for table in (
        "canonical_runs",
        "canonical_node_runs",
        "canonical_attempts",
        "canonical_workspaces",
        "canonical_workspace_memberships",
        "graph_continuations",
        "sessions",
        "audit_log",
    ):
        source.execute(f"CREATE TABLE {table} (run_id TEXT, version INTEGER, ordinal INTEGER)")
    source.execute("INSERT INTO canonical_runs VALUES ('retained-run', 7, 1)")
    source.commit()
    src = tmp_path / "backup"
    data = src / "conductor-data"
    data.mkdir(parents=True)
    snapshot = sqlite3.connect(data / "state.db")
    source.backup(snapshot)
    snapshot.close()
    source.close()
    _seal(src)
    before = (data / "state.db").read_bytes()
    for _ in range(2):
        result = _verify(src, "verify_conductor_backup")
        assert result.returncode == 0, result.stdout + result.stderr
        assert "retained-run" in result.stdout
        assert {p.name for p in data.iterdir()} == {"state.db"}
        assert (data / "state.db").read_bytes() == before
        assert _verify(src).returncode == 0


@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses directory access bits")
@pytest.mark.parametrize("root_name", ["BACKUP_ROOT", "ESCROW_ROOT"])
def test_unreadable_destination_is_not_treated_as_empty(tmp_path: Path, root_name: str) -> None:
    env = _fixture(tmp_path)
    dest = Path(env[root_name]) / STAMP
    dest.mkdir(parents=True, mode=0o700)
    (dest / "sentinel").write_bytes(b"preserve")
    dest.chmod(0o100)
    try:
        result = _backup(env)
        assert result.returncode != 0
        assert "must be readable and searchable" in result.stderr
        assert not Path(env["DOCKER_TEST_LOG"]).exists()
    finally:
        dest.chmod(0o700)
    assert (dest / "sentinel").read_bytes() == b"preserve"


@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses directory access bits")
def test_unreadable_capture_fails_closed(tmp_path: Path) -> None:
    data = tmp_path / "conductor-data"
    data.mkdir()
    (data / "admin.key").write_bytes(b"leaked")
    data.chmod(0o100)
    try:
        result = _verify(tmp_path, "verify_conductor_isolation")
        assert result.returncode != 0
        assert "must be readable and searchable" in result.stderr
    finally:
        data.chmod(0o700)
