"""Production backups must be private even under a permissive caller umask."""

from __future__ import annotations

import os
import stat
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "deploy/scripts/backup.sh"


def _run_backup(tmp_path: Path) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker_log = tmp_path / "docker.log"
    docker = bin_dir / "docker"
    # The #1881 producer (backup.sh + pg-semantic-oracle.sh) opens ONE
    # long-lived psql session — `docker compose exec -T <svc> stdbuf -oL psql
    # ...` with no `-c` — to export its snapshot, so the stub must speak that
    # protocol: answer pg_export_snapshot() with an id in PostgreSQL's
    # dash-separated-hex form, then hold the session open (consume stdin)
    # until the library COMMITs and closes the pipe. Every other invocation
    # (one-shot `psql -c` queries, pg_dump, redis-cli, docker run) keeps the
    # old behavior of echoing fixture data.
    docker.write_text(
        "#!/bin/sh\n"
        'echo invoked >> "$DOCKER_TEST_LOG"\n'
        "session=0\n"
        'for arg in "$@"; do\n'
        '  case "$arg" in\n'
        "    psql) session=1 ;;\n"
        "    -c) session=0 ;;\n"
        "  esac\n"
        "done\n"
        'if [ "$session" = 1 ]; then\n'
        "  while IFS= read -r line; do\n"
        '    case "$line" in\n'
        "      *pg_export_snapshot*) echo '00000001-0000000A-1' ;;\n"
        "    esac\n"
        "  done\n"
        "  exit 0\n"
        "fi\n"
        'printf "fixture data\\n"\n'
    )
    docker.chmod(0o700)
    root = tmp_path / "backups"
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "BACKUP_ROOT": str(root),
        "DOCKER_TEST_LOG": str(docker_log),
        "POSTGRES_DB": "fixture",
        "REMOTE_TARGET": "",
        "RETENTION_DAYS": "14",
    }
    result = subprocess.run(
        ["bash", str(_SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        umask=0,
    )
    return result, root / datetime.now(UTC).strftime("%Y-%m-%d"), docker_log


def test_new_backup_is_private_under_permissive_umask(tmp_path: Path) -> None:
    result, destination, docker_log = _run_backup(tmp_path)
    assert result.returncode == 0, result.stderr
    assert docker_log.exists()
    assert stat.S_IMODE(destination.stat().st_mode) == 0o700
    files = list(destination.iterdir())
    # The #1881 artifact contract: the custom-format archive, its provenance,
    # the semantic evidence (schema inventory + row counts) and a sha256 side
    # car for each — plus the deployed ref. Every one of them must be private.
    assert {p.name for p in files} == {
        "postgres-fixture.dump",
        "postgres-fixture.dump.sha256",
        "postgres-fixture.provenance",
        "postgres-fixture.schema",
        "postgres-fixture.schema.sha256",
        "postgres-fixture.rowcounts",
        "postgres-fixture.rowcounts.sha256",
        "deployed-git-ref.txt",
    }
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in files)


@pytest.mark.parametrize("mode", [0o755, 0o750, 0o707])
def test_existing_shared_backup_is_rejected_before_dump(tmp_path: Path, mode: int) -> None:
    destination = tmp_path / "backups" / datetime.now(UTC).strftime("%Y-%m-%d")
    destination.mkdir(parents=True)
    destination.chmod(mode)
    result, _, docker_log = _run_backup(tmp_path)
    assert result.returncode != 0
    assert "owner-only permissions" in result.stderr
    assert not docker_log.exists()
    assert stat.S_IMODE(destination.stat().st_mode) == mode
    assert list(destination.iterdir()) == []


def test_existing_private_backup_remains_supported(tmp_path: Path) -> None:
    destination = tmp_path / "backups" / datetime.now(UTC).strftime("%Y-%m-%d")
    destination.mkdir(parents=True, mode=0o700)
    result, _, docker_log = _run_backup(tmp_path)
    assert result.returncode == 0, result.stderr
    assert docker_log.exists()
    assert stat.S_IMODE(destination.stat().st_mode) == 0o700


def test_symlink_backup_is_rejected_before_dump(tmp_path: Path) -> None:
    root = tmp_path / "backups"
    root.mkdir()
    target = tmp_path / "target"
    target.mkdir(mode=0o700)
    (root / datetime.now(UTC).strftime("%Y-%m-%d")).symlink_to(target, target_is_directory=True)
    result, _, docker_log = _run_backup(tmp_path)
    assert result.returncode != 0
    assert "must not be a symlink" in result.stderr
    assert not docker_log.exists()
    assert list(target.iterdir()) == []
