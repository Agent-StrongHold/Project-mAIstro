from __future__ import annotations

import asyncio
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest
import stores
from models.schemas import HiveUser
from services.model_store import JsonStore
from services.oauth_login import HiveIdentityLinkStore, IdentityLinkConflictError

from maistro.state import PersistedStore, State

TENANT = "11111111-2222-3333-4444-555555555555"
OBJECT = "99999999-8888-7777-6666-555555555555"
SUBJECT = f"{TENANT}:{OBJECT}"


def _user() -> HiveUser:
    return HiveUser(
        id="entra-user",
        username="entra-user",
        password_hash="unused",
        role="user",
        is_active=True,
        permissions=[],
        did=None,
        created_at=datetime.now(UTC),
    )


def test_entra_tid_oid_link_survives_state_db_backup_and_restore(tmp_path: Path) -> None:
    """Prove the actual Entra external key survives a file-level state backup."""
    source_db = tmp_path / "source-state.db"
    backup_db = tmp_path / "backup-state.db"
    user = _user()
    stores.users[user.id] = user

    first_state = State(source_db)
    first_persisted = PersistedStore(first_state)
    first_persisted.initialize()
    first_json = JsonStore("oauth_identity_links", first_persisted)
    first_json.initialize()
    first_links = HiveIdentityLinkStore(first_json)
    asyncio.run(first_links.link("entra", SUBJECT, user.id))
    first_state.flush()
    first_state.close()

    # A closed SQLite state database is a self-contained backup artifact. Copy
    # it as deployment backup tooling would, then reopen the copy as a fresh
    # process/store rather than reusing any in-memory records.
    shutil.copy2(source_db, backup_db)

    restored_state = State(backup_db)
    restored_persisted = PersistedStore(restored_state)
    restored_persisted.initialize()
    restored_json = JsonStore("oauth_identity_links", restored_persisted)
    restored_json.initialize()
    restored_links = HiveIdentityLinkStore(restored_json)
    try:
        assert asyncio.run(restored_links.resolve("entra", SUBJECT)) == user.id
        with pytest.raises(IdentityLinkConflictError):
            asyncio.run(restored_links.link("entra", SUBJECT, "different-user"))
        assert asyncio.run(restored_links.resolve("entra", SUBJECT)) == user.id
    finally:
        restored_state.close()
