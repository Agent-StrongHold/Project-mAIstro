"""#333/#1179: a Conductor mutation is acknowledged at the State commit, not at
queue entry.

`State.submit` alone cannot tell a caller anything: it returns once a command
has entered the writer queue, before any commit. The write APIs the Conductor
routes use — `PersistedStore.put`/`put_raw`/`delete` (`State.submit_sync`),
`ModelStore.__setitem__`, and the settings/profile/registration record stores —
must therefore only return after the writer thread has committed, and must
raise the writer's failure, so an HTTP handler can never turn a queued command
into a 2xx durable-success claim.

These tests hold that contract from the HTTP surface with a real writer thread
and a real SQLite file:

- a response does not exist while the write is only queued behind a stalled
  writer, and the acknowledged mutation is durable after a simulated crash
  (fresh `State` over the same file) once the 2xx arrived;
- a failing commit answers 503 — never a 2xx carrying the refused value — and
  the refused write is absent after restart while the prior record is intact;
- a `ModelStore.__setitem__` against a failing commit raises with memory still
  coherent with disk.

The unit-level halves (slow writer, commit failure, fire-and-forget `submit`)
are pinned in `packages/maistro-core/tests/state/test_write_acknowledgment.py`.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import stores
from fastapi.testclient import TestClient
from main import app
from models.schemas import Mission, SettingsModel
from services import profile_store, registration_policy, settings_store
from services.settings_store import RECORD_KEY as SETTINGS_KEY
from services.settings_store import STORE_NAME as SETTINGS_STORE

from maistro.state import PersistedStore, State

pytestmark = [pytest.mark.contract("behavioral")]


class _CommitFailingConnection:
    """Delegates to a real connection; ``commit()`` always fails.

    Isolates the reported failure mode: ``fn`` succeeds and the COMMIT is what
    breaks — exactly the outcome a queue-only write API would report as
    accepted.
    """

    def __init__(self, real: sqlite3.Connection) -> None:
        self._real = real

    def execute(self, sql: str, *args: Any, **kwargs: Any) -> sqlite3.Cursor:
        return self._real.execute(sql, *args, **kwargs)

    def rollback(self) -> None:
        self._real.rollback()

    def commit(self) -> None:
        raise sqlite3.OperationalError("simulated commit failure")


@pytest.fixture()
def sqlite_persistence(tmp_path: Path):
    """Real State + PersistedStore wired into every Conductor store family."""
    db = tmp_path / "state.db"
    state = State(db_path=str(db))
    persisted = PersistedStore(state)
    persisted.initialize()
    stores.configure_persistence(persisted)
    settings_store.reset(store=settings_store.PersistedSettingsRecordStore(persisted))
    profile_store.reset(store=profile_store.PersistedProfileRecordStore(persisted))
    registration_policy.reset(store=registration_policy.PersistedRegistrationRecordStore(persisted))
    yield state, persisted, db
    settings_store.reset()
    profile_store.reset()
    registration_policy.reset()
    stores.configure_persistence(None)
    state.close()


def _reopen(db: Path) -> State:
    """A fresh State over the same file — the crash/restart probe."""
    reopened = State(db_path=str(db))
    reopened_store = PersistedStore(reopened)
    reopened_store.initialize()
    settings_store.reset(store=settings_store.PersistedSettingsRecordStore(reopened_store))
    return reopened


def _settings_row_count(state: State) -> int:
    reader = state.open_reader()
    try:
        row = reader.execute(
            "SELECT COUNT(*) FROM kv_store WHERE store_name = ? AND key = ?",
            (SETTINGS_STORE, SETTINGS_KEY),
        ).fetchone()
    finally:
        reader.close()
    return int(row[0])


def _settings_writer(task_id: str) -> TestClient:
    """A logged-in client holding config.write, elevated for `task_id`."""
    from maistro.security.passwords import hash_password

    granted = ["config.write"]
    uid = f"ack-{task_id}"
    stores.users[uid] = stores.users._model_class(
        id=uid,
        username=uid,
        password_hash=hash_password("pw"),
        role="user",
        is_active=True,
        permissions=granted,
        created_at=datetime.now(UTC),
    )
    client = TestClient(app)
    assert (
        client.post("/v1/auth/login", json={"username": uid, "password": "pw"}).status_code == 200
    )
    assert (
        client.post(
            "/v1/auth/elevate",
            json={"password": "pw", "permissions": granted, "task_id": task_id},
        ).status_code
        == 200
    )
    return client


def _mission(key: str) -> Mission:
    moment = datetime.now(UTC)
    return Mission(
        id=key,
        user_id="system",
        name=f"acknowledged {key}",
        description="write-acknowledgment probe",
        status="running",
        priority="medium",
        created_at=moment,
        updated_at=moment,
        progress=0.0,
        steps_total=1,
        steps_completed=0,
        assigned_agents=[],
        tags=[],
        metadata={},
    )


class TestTwoTwentyMeansCommitted:
    def test_the_response_arrives_only_after_the_state_commit(
        self, sqlite_persistence: tuple[State, PersistedStore, Path]
    ) -> None:
        """Slow writer: while the settings write is queued behind a stalled
        writer transaction there is no response at all, and nothing on disk.
        Once the writer commits, the 2xx carries the record read back from the
        store — and a fresh State over the same file (the crash probe) holds
        the acknowledged mutation."""
        state, _, db = sqlite_persistence
        client = _settings_writer("slow")

        started = threading.Event()
        release = threading.Event()

        def stall(_conn: sqlite3.Connection) -> None:
            started.set()
            release.wait(timeout=20.0)

        state.submit(stall)  # fire-and-forget on purpose: occupy the writer
        assert started.wait(timeout=5.0)

        responses: list = []

        def do_put() -> None:
            responses.append(
                client.put(
                    "/v1/settings",
                    json=SettingsModel(default_model="ack-model").model_dump(mode="json"),
                )
            )

        pending = threading.Thread(target=do_put, daemon=True)
        pending.start()

        # The queue holds the command; the caller holds nothing.
        pending.join(timeout=1.0)
        try:
            assert pending.is_alive(), (
                "settings PUT returned while the write was still only queued; "
                f"responses={[(r.status_code) for r in responses]}"
            )
            assert _settings_row_count(state) == 0, "uncommitted write visible on disk"
        finally:
            release.set()
            pending.join(timeout=15.0)

        assert not pending.is_alive()
        assert responses[0].status_code == 200
        assert responses[0].json()["default_model"] == "ack-model"

        # Crash after the acknowledgement: the mutation is on disk.
        state.close()
        reopened = _reopen(db)
        try:
            record = settings_store.load()
            assert record.values.default_model == "ack-model"
            assert record.revision == 1
        finally:
            settings_store.reset()
            reopened.close()

    def test_a_failed_commit_is_a_503_and_is_absent_after_restart(
        self, sqlite_persistence: tuple[State, PersistedStore, Path]
    ) -> None:
        """Write failure: the commit breaking must surface as a non-2xx that
        does not carry the refused value, with the prior durable record intact
        after restart — no HTTP 2xx durable-success claim over a refused
        write."""
        state, _, db = sqlite_persistence
        client = _settings_writer("failure")

        first = client.put(
            "/v1/settings",
            json=SettingsModel(default_model="durable").model_dump(mode="json"),
        )
        assert first.status_code == 200

        real = state._writer
        assert real is not None
        state._writer = _CommitFailingConnection(real)  # type: ignore[assignment]
        status: int
        body: str
        try:
            refused = client.put(
                "/v1/settings",
                json=SettingsModel(default_model="lost-write").model_dump(mode="json"),
            )
        except sqlite3.OperationalError:
            # The auth middleware's session-activity refresh is itself an
            # acknowledged write, so with a failing commit it fails first and
            # the server answers 500 (TestClient re-raises server errors).
            # Fail-closed: still no 2xx durable-success claim.
            status, body = 500, ""
        else:
            status, body = refused.status_code, refused.text
        finally:
            state._writer = real

        assert status >= 500
        # Neither response may present the refused value as stored.
        assert "lost-write" not in body

        # Crash probe: the failed write is absent, the acknowledged one intact.
        state.close()
        reopened = _reopen(db)
        try:
            record = settings_store.load()
            assert record.values.default_model == "durable"
            assert record.revision == 1
        finally:
            settings_store.reset()
            reopened.close()

    def test_model_store_write_raises_and_memory_stays_coherent(
        self, sqlite_persistence: tuple[State, PersistedStore, Path]
    ) -> None:
        """`ModelStore.__setitem__` persists before mutating memory: against a
        failing commit it raises, memory never shows the refused mission, and
        after restart the mission is absent — the mutation was never
        acknowledged."""
        state, _, db = sqlite_persistence
        kept, refused = _mission("m-kept"), _mission("m-refused")

        stores.missions[kept.id] = kept  # acknowledged: durable on return
        assert stores.missions[kept.id] == kept

        real = state._writer
        assert real is not None
        state._writer = _CommitFailingConnection(real)  # type: ignore[assignment]
        try:
            with pytest.raises(sqlite3.OperationalError, match="simulated commit failure"):
                stores.missions[refused.id] = refused
        finally:
            state._writer = real

        assert refused.id not in stores.missions, "memory adopted a refused write"
        state.close()

        reopened = State(db_path=str(db))
        try:
            reopened_store = PersistedStore(reopened)
            reopened_store.initialize()
            assert reopened_store.get("missions", kept.id, Mission) == kept
            assert reopened_store.get("missions", refused.id, Mission) is None
        finally:
            reopened.close()


class TestHealthNamesTheDurabilityMode:
    def test_configured_persistence_reports_durable_ack(
        self, sqlite_persistence: tuple[State, PersistedStore, Path]
    ) -> None:
        _state, _, _ = sqlite_persistence
        client = TestClient(app)

        persistence = client.get("/health").json()["persistence"]

        assert persistence["ack"] == "state-commit"
        families = persistence["families"]
        assert families["model_json_stores"] == "durable-ack"
        assert families["settings"] == "durable-ack"
        assert families["profiles"] == "durable-ack"
        assert families["registration_policy"] == "durable-ack"

    def test_the_memory_mode_is_labelled_not_durable(self) -> None:
        """Without a configured backend every family says so — an in-memory
        write never wears the shape of a durable one (#333)."""
        stores.configure_persistence(None)
        settings_store.reset()
        profile_store.reset()
        registration_policy.reset()
        client = TestClient(app)

        persistence = client.get("/health").json()["persistence"]

        assert persistence["ack"] == "process-memory"
        families = persistence["families"]
        assert families["model_json_stores"] == "memory"
        assert families["settings"] == "ephemeral"
        assert families["profiles"] == "ephemeral"
        assert families["registration_policy"] == "ephemeral"
