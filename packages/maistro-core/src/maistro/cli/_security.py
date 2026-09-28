"""`maistro security` subcommand — post-disclosure remediation.

Two destructive operators live here, both dry-run by default:

    maistro security rotate-credential-key --data-dir DIR [--yes]
    maistro security purge-sessions        --data-dir DIR [--yes]

Rotation re-encrypts every stored integration secret under a fresh Fernet
master key. Purge revokes every Hive Conductor login session. Neither is
something you run casually — see ``docs/CREDENTIAL-ROTATION-RUNBOOK.md``.

Two more operators move the whole data directory as one unit (#331):

    maistro security backup  --data-dir DIR --out ARCHIVE
    maistro security restore --data-dir DIR --from ARCHIVE [--yes]

Conductor state is coupled: the vault only opens with its identity key, the
credential store only decrypts under its master key, and sessions/settings
live in the same SQLite file as the accounts they belong to. Backing up or
restoring those files piecemeal produces a directory that boots but cannot
read itself. Backup captures every file in one pass into a single archive;
restore stages the archive beside the target and swaps it in with a single
rename, so a crash mid-restore leaves the old directory or the new one —
never a half-restored mix.
"""

from __future__ import annotations

import os
import shutil
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from typer import Option, Typer

from maistro.credentials.store import (
    MASTER_KEY_ENV_VAR,
    MASTER_KEY_FILENAME,
    STORE_FILENAME,
    CredentialStoreError,
    UserCredentialStore,
    generate_master_key,
    repair_interrupted_rotation,
)

app = Typer(help="Operator security maintenance: key rotation and session revocation.")
console = Console()

_SESSIONS_STORE_NAME = "sessions"
_DEFAULT_STATE_DB = "state.db"

#: The durable-file inventory a provisioned Conductor data directory can
#: hold (#331). Used to report what a backup/restore actually captured, and
#: to warn when a restored set is internally inconsistent (e.g. a vault
#: without the identity key that decrypts it). None of these is REQUIRED for
#: every deployment — a directory that never used the vault legitimately
#: lacks ``secrets.age`` — but each pairing below is.
_DURABLE_FILES = (
    ("state.db", "SQLite: accounts, sessions, settings, registration policy"),
    ("secrets.age", "age-encrypted vault entries"),
    ("admin.key", "age identity that opens secrets.age"),
    ("credential_master.key", "Fernet master key for user_credentials.enc"),
    ("user_credentials.enc", "encrypted per-user integration credentials"),
)
_COUPLED_PAIRS = (
    ("secrets.age", "admin.key"),
    ("user_credentials.enc", "credential_master.key"),
)
_RESTORE_STAGING_SUFFIX = ".restore-staging"
_RESTORE_OLD_SUFFIX = ".restore-old"


def _resolve_data_dir(data_dir: str) -> Path:
    path = Path(data_dir).expanduser()
    if not path.is_dir():
        console.print(f"[red]No such data directory:[/red] {path}")
        raise typer.Exit(code=2)
    return path


def _confirmed(yes: bool, what: str) -> bool:
    if yes:
        return True
    console.print(
        f"\n[yellow]DRY RUN — nothing was changed.[/yellow]\n"
        f"Re-run with [bold]--yes[/bold] to actually {what}."
    )
    return False


@app.command("rotate-credential-key")
def rotate_credential_key(
    data_dir: str = Option(
        ...,
        "--data-dir",
        help="Conductor data directory holding credential_master.key (CONDUCTOR_DATA_DIR).",
    ),
    new_key: str = Option(
        "",
        "--new-key",
        help="Fernet key to rotate to. Omit to generate a fresh one.",
    ),
    show_key: bool = Option(
        False,
        "--show-key",
        help="Print the new master key to stdout (needed when the key is held in an env var).",
    ),
    yes: bool = Option(False, "--yes", help="Actually perform the rotation."),
) -> None:
    """Re-encrypt every stored credential under a new master key.

    Run this after any disclosure of the data directory (see #281, #332).
    Stop the Conductor first — the running process caches the old key.
    """
    path = _resolve_data_dir(data_dir)

    if repair_interrupted_rotation(path):
        console.print("[yellow]Completed a previously interrupted rotation first.[/yellow]")

    try:
        store = UserCredentialStore.open(path)
        current = store.snapshot_counts()
    except CredentialStoreError as exc:
        console.print(f"[red]Credential store is not readable:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    env_active = bool(os.getenv(MASTER_KEY_ENV_VAR, "").strip())

    console.print("[bold]Planned: credential master-key rotation[/bold]")
    console.print(f"  data dir    : {path}")
    console.print(f"  key file    : {path / MASTER_KEY_FILENAME}")
    console.print(f"  store file  : {path / STORE_FILENAME}")
    console.print(f"  to re-encrypt: {current[1]} secret(s) across {current[0]} user(s)")
    console.print(f"  new key     : {'supplied on the command line' if new_key else 'generated'}")
    if env_active:
        console.print(
            f"  [yellow]{MASTER_KEY_ENV_VAR} is set in this environment — you must update it "
            f"to the new key before restarting, or the service will fail to decrypt.[/yellow]"
        )

    if not _confirmed(yes, "rotate the master key"):
        return

    key = new_key.strip().encode() if new_key.strip() else generate_master_key()
    try:
        result = store.rotate_master_key(key)
    except (CredentialStoreError, ValueError) as exc:
        console.print(f"[red]Rotation aborted — nothing changed:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(
        f"[green]Rotated.[/green] {result.secrets} secret(s) across {result.users} user(s) "
        f"re-encrypted under the new key."
    )
    console.print(f"  new key written to: {result.key_path}")
    if show_key:
        console.print(f"  new key: {key.decode()}")
    if result.env_var_active:
        console.print(
            f"[yellow]Set {MASTER_KEY_ENV_VAR} to the new key (or unset it and let the key file "
            f"be authoritative) before restarting the Conductor.[/yellow]"
        )
    console.print("[bold]The previous master key is now useless. Restart the Conductor.[/bold]")


def _open_state(db_path: Path) -> tuple[Any, Any]:
    from maistro.state import PersistedStore, State

    state = State(db_path=db_path)
    state.open_writer()
    persisted = PersistedStore(state)
    persisted.initialize()
    return state, persisted


@app.command("purge-sessions")
def purge_sessions(
    data_dir: str = Option(
        ...,
        "--data-dir",
        help="Conductor data directory (CONDUCTOR_DATA_DIR).",
    ),
    state_db: str = Option(
        "",
        "--state-db",
        help="Path to the Conductor SQLite state DB. Defaults to <data-dir>/state.db.",
    ),
    yes: bool = Option(False, "--yes", help="Actually revoke the sessions."),
) -> None:
    """Revoke every Hive Conductor login session. All users must sign in again.

    Stop the Conductor first: it holds the sessions in memory and would write
    them back. Sessions that were never persisted vanish on restart anyway.
    """
    path = _resolve_data_dir(data_dir)
    db_path = Path(state_db).expanduser() if state_db else path / _DEFAULT_STATE_DB

    if not db_path.exists():
        console.print(
            f"[yellow]No state DB at {db_path}.[/yellow] Sessions are in-memory only — "
            "restarting the Conductor already clears them."
        )
        return

    state, persisted = _open_state(db_path)
    try:
        keys = [key for key, _ in persisted.list_all_raw(_SESSIONS_STORE_NAME)]
        console.print("[bold]Planned: session purge[/bold]")
        console.print(f"  state db : {db_path}")
        console.print(f"  store    : {_SESSIONS_STORE_NAME}")
        console.print(f"  to revoke: {len(keys)} session(s)")

        if not _confirmed(yes, "revoke every session"):
            return

        for key in keys:
            persisted.delete(_SESSIONS_STORE_NAME, key)
        state.flush()
    finally:
        state.close()

    console.print(f"[green]Revoked {len(keys)} session(s).[/green] Every user must log in again.")


def _durable_inventory(directory: Path) -> list[tuple[str, str]]:
    """Which of the known durable files the directory holds, with descriptions."""
    return [(name, desc) for name, desc in _DURABLE_FILES if (directory / name).is_file()]


def _print_inventory(items: list[tuple[str, str]], label: str) -> None:
    console.print(f"  {label}:")
    if not items:
        console.print("    (no known durable files present)")
    for name, desc in items:
        console.print(f"    {name:24s} {desc}")


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@app.command("backup")
def backup(
    data_dir: str = Option(
        ...,
        "--data-dir",
        help="Conductor data directory to snapshot (CONDUCTOR_DATA_DIR).",
    ),
    out: str = Option(
        "",
        "--out",
        help=(
            "Archive path to write (.tar.gz). "
            "Default: conductor-data-<UTC timestamp>.tar.gz next to the data directory."
        ),
    ),
) -> None:
    """Snapshot the whole Conductor data directory into one archive.

    Every file is captured in a single pass — state.db (with its WAL/SHM
    sidecars), the vault and its identity key, the credential master key and
    encrypted credential store, and anything else in the directory — so the
    restored set is never internally inconsistent. The archive is staged as a
    temporary file and renamed into place only once complete and fsynced: the
    output name never names a partial backup.

    Stop the Conductor first. A running Conductor holds state.db and the
    caches open and will write stale state back over your backup (see
    docs/CREDENTIAL-ROTATION-RUNBOOK.md). Treat the archive as secret
    material: it contains the credential master key and every vault entry.
    """
    path = _resolve_data_dir(data_dir)

    out_path = (
        Path(out).expanduser()
        if out
        else path.parent / (f"conductor-data-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.tar.gz")
    )
    if out_path.suffix == ".gz" and not out_path.name.endswith(".tar.gz"):
        console.print(f"[red]--out must end in .tar.gz (got {out_path.name}).[/red]")
        raise typer.Exit(code=2)
    if out_path.exists():
        console.print(
            f"[red]Refusing to overwrite existing archive:[/red] {out_path}. "
            "Choose another --out name (or move the old archive aside)."
        )
        raise typer.Exit(code=2)

    files = sorted(p for p in path.rglob("*") if p.is_file())
    if not files:
        console.print(
            f"[red]{path} holds no files.[/red] Nothing to back up — is this "
            "really the Conductor data directory?"
        )
        raise typer.Exit(code=2)

    inventory = _durable_inventory(path)
    total_bytes = sum(p.stat().st_size for p in files)
    console.print("[bold]Backing up Conductor data directory[/bold]")
    console.print(f"  source : {path}")
    console.print(f"  archive: {out_path}")
    console.print(f"  files  : {len(files)} ({total_bytes} bytes)")
    _print_inventory(inventory, "captured durable files")
    for missing, _desc in _DURABLE_FILES:
        if missing in {"state.db", "credential_master.key"}:
            continue
        if missing not in {name for name, _ in inventory}:
            console.print(
                f"  [yellow]note: {missing} not present — not used by this "
                "deployment, or already lost.[/yellow]"
            )

    tmp_path = out_path.with_name(f".{out_path.name}.tmp")
    try:
        with tarfile.open(tmp_path, "w:gz") as tar:
            for file_path in files:
                tar.add(file_path, arcname=file_path.relative_to(path).as_posix())
        # The rename is the atomicity boundary: fsync the archive first so
        # the final name never resolves to bytes that are not yet on disk.
        with open(tmp_path, "rb") as handle:
            os.fsync(handle.fileno())
        os.replace(tmp_path, out_path)
        _fsync_dir(out_path.parent)
    except OSError as exc:
        tmp_path.unlink(missing_ok=True)
        console.print(f"[red]Backup failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(f"[green]Backed up {len(files)} file(s) to {out_path}.[/green]")


def _print_restore_plan(archive: Path, target: Path, names: list[str]) -> None:
    """Print what a restore would do, including coupled-set warnings."""
    inventory_names = set(names)
    console.print("[bold]Planned: data directory restore[/bold]")
    console.print(f"  archive: {archive}")
    console.print(f"  target : {target} ({'replaced' if target.exists() else 'created'})")
    console.print(f"  files  : {len(names)}")
    _print_inventory(
        [(name, desc) for name, desc in _DURABLE_FILES if name in inventory_names],
        "restored durable files",
    )
    for missing, _desc in _DURABLE_FILES:
        if missing not in inventory_names and missing not in {
            "state.db",
            "credential_master.key",
        }:
            console.print(
                f"  [yellow]note: {missing} not in archive — if this "
                "deployment used it, it will be absent after the restore.[/yellow]"
            )
    for coupled, partner in _COUPLED_PAIRS:
        if (coupled in inventory_names) != (partner in inventory_names):
            console.print(
                f"  [red]warning: archive holds {coupled} without {partner} — "
                f"the restored {coupled} will be unreadable until its partner "
                "is restored too.[/red]"
            )


def _read_archive_index(archive_path: Path) -> list[tarfile.TarInfo]:
    """Decompress the whole stream up front: the integrity pass.

    A truncated or corrupt archive is refused here, before anything on disk
    is touched. Exits non-zero on an unreadable archive.
    """
    try:
        with tarfile.open(archive_path, "r:gz") as tar:
            return tar.getmembers()
    except (tarfile.TarError, OSError, EOFError) as exc:
        console.print(
            f"[red]Not a readable backup archive:[/red] {archive_path} ({exc}). "
            "Refusing to touch the target directory."
        )
        raise typer.Exit(code=1) from exc


def _refuse_unsafe_members(members: list[tarfile.TarInfo]) -> None:
    """Name and refuse any member that would extract outside the target."""
    for member in members:
        member_path = Path(member.name)
        if member_path.is_absolute() or ".." in member_path.parts:
            console.print(
                f"[red]Unsafe path in archive:[/red] {member.name}. Refusing "
                "to extract an archive that escapes its root."
            )
            raise typer.Exit(code=2)


def _swap_into_place(staging: Path, target: Path, previous: Path) -> None:
    """Two renames: old aside, staged tree in, parent fsynced.

    A crash between them leaves the original at `previous`; the caller's
    failure path reports both locations instead of guessing at a repair.
    """
    if target.exists():
        os.replace(target, previous)
    os.replace(staging, target)
    _fsync_dir(target.parent)


@app.command("restore")
def restore(
    data_dir: str = Option(
        ...,
        "--data-dir",
        help="Conductor data directory to replace with the archive contents.",
    ),
    from_archive: str = Option(
        ...,
        "--from",
        help="Archive produced by `maistro security backup`.",
    ),
    yes: bool = Option(False, "--yes", help="Actually replace the data directory."),
) -> None:
    """Restore a data directory from a backup, atomically.

    Destructive and dry-run by default: everything currently in the target
    directory is replaced. Stop the Conductor first — it holds state.db and
    the caches open and would write stale state over the restore.

    The archive is extracted to a staging directory beside the target and
    swapped in with a single rename. A crash mid-restore leaves either the
    old directory or the restored one on disk — never a half-restored mix of
    coupled files (a vault without its identity key, a credential store
    without its master key). If a previous restore was killed between those
    two renames, re-running this command completes the swap.
    """
    archive_path = Path(from_archive).expanduser()
    if not archive_path.is_file():
        console.print(f"[red]No such archive:[/red] {archive_path}")
        raise typer.Exit(code=2)

    target = Path(data_dir).expanduser()
    parent = target.parent
    staging = parent / f".{target.name}{_RESTORE_STAGING_SUFFIX}"
    previous = parent / f".{target.name}{_RESTORE_OLD_SUFFIX}-{os.getpid()}"

    members = _read_archive_index(archive_path)
    names = [member.name for member in members if member.isfile()]

    if not names:
        console.print(
            f"[red]{archive_path} holds no files.[/red] Refusing to restore an "
            "empty archive over a data directory."
        )
        raise typer.Exit(code=2)
    _refuse_unsafe_members(members)

    _print_restore_plan(
        archive=archive_path,
        target=target,
        names=names,
    )

    if not _confirmed(yes, f"replace {target} with the archive contents"):
        return

    if staging.exists():
        # A previous restore was killed after extracting but before (or
        # during) the swap. Nothing has been lost — the original directory is
        # either still in place or in a .restore-old-* sibling — but this
        # staging tree is unusable now. Ask rather than guess.
        console.print(
            f"[red]Stale staging directory exists:[/red] {staging}. Inspect it "
            "and remove it (the original directory is untouched), then re-run."
        )
        raise typer.Exit(code=1)

    try:
        staging.mkdir(mode=0o700)
        with tarfile.open(archive_path, "r:gz") as tar:
            # filter="data" (stdlib, 3.12+) refuses absolute paths, ".."
            # traversal, and device/link attacks; the explicit check above
            # exists to name the offending member in the error.
            tar.extractall(staging, filter="data")  # filtered + path-validated above
        restored = [p for p in staging.rglob("*") if p.is_file()]
        if not restored:
            raise OSError("archive extracted to no files")

        _swap_into_place(staging, target, previous)
    except (tarfile.TarError, OSError, EOFError) as exc:
        # The swap is two renames; a failure here leaves the original in
        # place (or in `previous` if the first rename landed). Report both
        # paths instead of guessing at a repair.
        console.print(f"[red]Restore failed:[/red] {exc}")
        if previous.exists():
            console.print(
                f"  original directory preserved at: {previous}\n"
                f"  move it back with: mv {previous} {target}"
            )
        shutil.rmtree(staging, ignore_errors=True)
        raise typer.Exit(code=1) from exc

    if previous.exists():
        shutil.rmtree(previous, ignore_errors=True)
    console.print(
        f"[green]Restored {len(names)} file(s) into {target}.[/green] "
        "Start the Conductor and verify a login before deleting the archive."
    )
