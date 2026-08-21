"""`maistro security` subcommand — post-disclosure remediation.

Two destructive operators live here, both dry-run by default:

    maistro security rotate-credential-key --data-dir DIR [--yes]
    maistro security purge-sessions        --data-dir DIR [--yes]

Rotation re-encrypts every stored integration secret under a fresh Fernet
master key. Purge revokes every Hive Conductor login session. Neither is
something you run casually — see ``docs/CREDENTIAL-ROTATION-RUNBOOK.md``.
"""

from __future__ import annotations

import os
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
