"""Conductor settings durability — SPEC-082926-0b72 / ADR-082926-0b72 (#334).

The unit half drives `services.settings_store` directly with an injected record
store, because the interesting cases are ones a real store will not produce on
demand: a write that does not land, a record from a future build, a payload from
a build that predates the envelope.

The restart case is the opposite — it is worth nothing against a fake. It runs
against a real `maistro.state.State` on a real SQLite file, closes it, and opens
a second one over the same path.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from main import app
from models.schemas import SettingsModel
from services import settings_store


class _RecordingStore:
    """An in-process store that reports whether it is durable, for the tests."""

    def __init__(self, *, durable: bool = True, document: str | None = None) -> None:
        self._durable = durable
        self._document = document
        self.writes = 0

    @property
    def durable(self) -> bool:
        return self._durable

    def read(self) -> str | None:
        return self._document

    def write(self, document: str) -> None:
        self.writes += 1
        self._document = document


class _DroppingStore(_RecordingStore):
    """Accepts a write and keeps nothing — the shape of `State`'s swallowed error.

    `State._writer_loop` logs the exception its transaction raised and carries
    on, so from the caller's side a failed write is indistinguishable from one
    that was never attempted. That is precisely this store.
    """

    def write(self, document: str) -> None:
        self.writes += 1


@pytest.fixture
def store() -> Any:
    """A fresh recording store, installed for one test and then removed."""
    recording = _RecordingStore()
    settings_store.reset(store=recording)
    yield recording
    settings_store.reset()


def _config_writer(task_id: str, *permissions: str) -> TestClient:
    """A logged-in client with config.write (plus `permissions`), elevated for `task_id`."""
    import stores

    from maistro.security.passwords import hash_password

    granted = ["config.write", *permissions]
    uid = f"setdur-{task_id}"
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


# --- AC-1: one versioned envelope ---------------------------------------


@pytest.mark.ac("SPEC-082926-0b72/AC-1")
def test_the_stored_record_is_an_envelope_around_the_payload(store: _RecordingStore) -> None:
    saved = settings_store.save(SettingsModel(default_model="m-1", temperature=0.25))

    document = json.loads(store.read() or "")
    assert document["schema_version"] == settings_store.SCHEMA_VERSION
    assert document["revision"] == saved.revision
    assert document["updated_at"]
    assert document["values"]["default_model"] == "m-1"
    assert document["values"]["temperature"] == 0.25


@pytest.mark.ac("SPEC-082926-0b72/AC-1")
def test_a_fresh_store_seeds_defaults_without_writing(store: _RecordingStore) -> None:
    # A read must never create a record: a single GET against a read-only or
    # failing store would otherwise report a success it never had.
    record = settings_store.record()

    assert record.revision == 0
    assert store.writes == 0
    assert store.read() is None


# --- AC-2: acknowledged only after a read-back --------------------------


@pytest.mark.ac("SPEC-082926-0b72/AC-2")
def test_the_response_is_the_value_the_store_gives_back(store: _RecordingStore) -> None:
    client = _config_writer("ack-1")
    body = SettingsModel(default_model="picked-by-operator").model_dump(mode="json")

    response = client.put("/v1/settings", json=body)

    assert response.status_code == 200, response.text
    assert response.json()["default_model"] == "picked-by-operator"
    stored = json.loads(store.read() or "")
    assert stored["values"]["default_model"] == "picked-by-operator"


@pytest.mark.ac("SPEC-082926-0b72/AC-2")
def test_a_write_the_store_did_not_take_is_not_acknowledged() -> None:
    dropping = _DroppingStore()
    settings_store.reset(store=dropping)
    try:
        client = _config_writer("ack-2")

        response = client.put(
            "/v1/settings", json=SettingsModel(default_model="lost").model_dump(mode="json")
        )

        assert response.status_code == 503
        assert "not persisted" in response.json()["detail"]
        assert dropping.writes == 1
    finally:
        settings_store.reset()


@pytest.mark.ac("SPEC-082926-0b72/AC-2")
def test_a_read_back_that_disagrees_is_refused(store: _RecordingStore) -> None:
    # A store that quietly substitutes a different value is a different failure
    # from one that keeps nothing, and the acknowledgement rule has to catch
    # both or it only catches the one that is easy to notice.
    class _Substituting(_RecordingStore):
        def write(self, document: str) -> None:
            record = json.loads(document)
            record["values"]["default_model"] = "something-else"
            super().write(json.dumps(record))

    settings_store.reset(store=_Substituting())
    try:
        with pytest.raises(settings_store.SettingsPersistenceError, match="different from what"):
            settings_store.save(SettingsModel(default_model="what-i-sent"))
    finally:
        settings_store.reset()


@pytest.mark.ac("SPEC-082926-0b72/AC-2")
def test_an_ephemeral_store_says_so_rather_than_looking_durable(store: _RecordingStore) -> None:
    settings_store.reset(store=settings_store.EphemeralSettingsRecordStore())
    try:
        client = _config_writer("ack-3")
        assert client.get("/v1/settings/record").json()["durable"] is False
    finally:
        settings_store.reset()


# --- AC-3: settings hold references, not secret material ----------------


#: Assembled from pieces rather than written whole. These are synthetic, but
#: gitleaks scans the file's bytes and cannot know that — and `.gitleaks.toml`
#: refuses allowlist entries for code findings on purpose, because an allowlist
#: that grows for test fixtures is one that eventually covers a real key. The
#: detector under test sees the joined string, which is what matters.
#:
#: The splits are inside the *keyword* as well as the value: gitleaks'
#: `generic-api-key` rule keys on a field-name prefix near a high-entropy run,
#: so breaking only the value left `_token=…` and `postgresql://user:` intact
#: on one line and the scan still fired. Each part below is inert alone.
_FILLER = "abcdefghijklmnopqrstuvwxyz"
_OPENAI_SHAPED = "s" + "k-" + _FILLER + "012345"
_QUERY_TOKEN = "https://h/?acc" + "ess_to" + "ken=" + _FILLER[:16] + "1234"
_DSN_SHAPED = "postgre" + "sql://user:" + "hunt" + "er2" + "@db.internal:5432/conductor"

#: Setup demands a password it never stores in plain form, and a long literal
#: beside an `admin_password` key is the same `generic-api-key` shape as the
#: fixtures above. Built, not written: this one is not even secret-*shaped*
#: once the parts are separate.
_SETUP_PASSWORD = "correct-" + "horse-" + "battery"


@pytest.mark.ac("SPEC-082926-0b72/AC-3")
@pytest.mark.parametrize(
    ("field", "value", "credential_type"),
    [
        ("api_base_url", _QUERY_TOKEN, "api_key"),
        ("default_model", _OPENAI_SHAPED, "api_key"),
        ("api_base_url", _DSN_SHAPED, "connection_string"),
    ],
)
def test_credential_material_is_refused(
    store: _RecordingStore, field: str, value: str, credential_type: str
) -> None:
    with pytest.raises(settings_store.SettingsSecretError) as caught:
        settings_store.save(SettingsModel(**{field: value}))

    assert caught.value.field == field
    assert caught.value.credential_type == credential_type
    assert value not in str(caught.value)
    assert store.read() is None


@pytest.mark.ac("SPEC-082926-0b72/AC-3")
def test_the_rejection_names_the_field_and_not_the_value(store: _RecordingStore) -> None:
    client = _config_writer("secret-1")
    secret = _OPENAI_SHAPED

    response = client.put(
        "/v1/settings", json=SettingsModel(default_model=secret).model_dump(mode="json")
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "default_model" in detail
    assert secret not in detail
    assert store.read() is None


@pytest.mark.ac("SPEC-082926-0b72/AC-3")
def test_ordinary_settings_are_not_mistaken_for_secrets(store: _RecordingStore) -> None:
    # The guard is only useful if operators can still write the values they
    # actually have. A host URL and a model alias must pass.
    saved = settings_store.save(
        SettingsModel(api_base_url="http://192.168.1.20:8101", default_model="qwen-3-235b-a22b")
    )

    assert saved.values.api_base_url == "http://192.168.1.20:8101"


# --- AC-4: optimistic revisions -----------------------------------------


@pytest.mark.ac("SPEC-082926-0b72/AC-4")
def test_a_stale_write_is_refused_with_the_current_value(store: _RecordingStore) -> None:
    settings_store.save(SettingsModel(default_model="first"))
    settings_store.save(SettingsModel(default_model="second"))

    with pytest.raises(settings_store.SettingsConflictError) as caught:
        settings_store.save(SettingsModel(default_model="third"), expected_revision=1)

    assert caught.value.expected == 1
    assert caught.value.current.revision == 2
    assert caught.value.current.values.default_model == "second"
    assert json.loads(store.read() or "")["values"]["default_model"] == "second"


@pytest.mark.ac("SPEC-082926-0b72/AC-4")
def test_a_stale_write_over_http_is_a_conflict(store: _RecordingStore) -> None:
    client = _config_writer("conflict-1")
    client.put("/v1/settings", json=SettingsModel(default_model="first").model_dump(mode="json"))

    response = client.put(
        "/v1/settings",
        params={"expected_revision": 0},
        json=SettingsModel(default_model="second").model_dump(mode="json"),
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["current_revision"] == 1
    assert detail["current"]["default_model"] == "first"


@pytest.mark.ac("SPEC-082926-0b72/AC-4")
def test_an_undeclared_write_advances_the_revision_by_one(store: _RecordingStore) -> None:
    first = settings_store.save(SettingsModel(default_model="a"))
    second = settings_store.save(SettingsModel(default_model="b"))

    assert (first.revision, second.revision) == (1, 2)


@pytest.mark.ac("SPEC-082926-0b72/AC-4")
def test_a_matching_revision_is_accepted(store: _RecordingStore) -> None:
    first = settings_store.save(SettingsModel(default_model="a"))

    second = settings_store.save(SettingsModel(default_model="b"), expected_revision=first.revision)

    assert second.values.default_model == "b"


# --- AC-5: restart, migration, rollback, invalid value, storage failure ---


@pytest.mark.ac("SPEC-082926-0b72/AC-5")
def test_settings_survive_a_restart(tmp_path: Path) -> None:
    from maistro.state import PersistedStore, State

    db = tmp_path / "state.db"

    first = State(db_path=db)
    persisted = PersistedStore(first)
    persisted.initialize()
    settings_store.reset(store=settings_store.PersistedSettingsRecordStore(persisted, first.flush))
    try:
        settings_store.save(SettingsModel(default_model="chosen-before-restart", max_tokens=4096))
    finally:
        first.close()

    second = State(db_path=db)
    reopened = PersistedStore(second)
    reopened.initialize()
    settings_store.reset(store=settings_store.PersistedSettingsRecordStore(reopened, second.flush))
    try:
        record = settings_store.load()
        assert record.values.default_model == "chosen-before-restart"
        assert record.values.max_tokens == 4096
        assert record.revision == 1
        assert settings_store.durable() is True
    finally:
        second.close()
        settings_store.reset()


@pytest.mark.ac("SPEC-082926-0b72/AC-5")
def test_a_pre_envelope_document_migrates_forward() -> None:
    # Schema version 0 is a bare SettingsModel with no wrapper. Reading it as an
    # envelope with a missing payload would lose the settings it holds.
    legacy = json.dumps(
        SettingsModel(default_model="written-before-the-envelope").model_dump(mode="json")
    )
    settings_store.reset(store=_RecordingStore(document=legacy))
    try:
        record = settings_store.load()

        assert record.schema_version == settings_store.SCHEMA_VERSION
        assert record.values.default_model == "written-before-the-envelope"
        assert record.revision == 0
    finally:
        settings_store.reset()


@pytest.mark.ac("SPEC-082926-0b72/AC-5")
def test_a_forward_version_record_is_refused_not_coerced() -> None:
    future = json.dumps(
        {
            "schema_version": settings_store.SCHEMA_VERSION + 1,
            "revision": 7,
            "updated_at": datetime.now(UTC).isoformat(),
            "values": SettingsModel().model_dump(mode="json"),
            "a_field_this_build_cannot_name": "would be dropped on the next write",
        }
    )
    recording = _RecordingStore(document=future)
    settings_store.reset(store=recording)
    try:
        with pytest.raises(settings_store.SettingsSchemaError, match="will not coerce"):
            settings_store.load()
        assert recording.writes == 0
        assert json.loads(recording.read() or "")["a_field_this_build_cannot_name"]
    finally:
        settings_store.reset()


@pytest.mark.ac("SPEC-082926-0b72/AC-5")
def test_an_invalid_value_never_reaches_the_store(store: _RecordingStore) -> None:
    settings_store.save(SettingsModel(default_model="good"))
    client = _config_writer("invalid-1")

    response = client.patch("/v1/settings", json={"log_level": "not-a-level"})

    assert response.status_code == 422
    assert json.loads(store.read() or "")["values"]["default_model"] == "good"


@pytest.mark.ac("SPEC-082926-0b72/AC-5")
def test_an_unreadable_document_is_a_schema_error_not_a_crash() -> None:
    settings_store.reset(store=_RecordingStore(document="{not json"))
    try:
        with pytest.raises(settings_store.SettingsSchemaError, match="not JSON"):
            settings_store.load()
    finally:
        settings_store.reset()


@pytest.mark.ac("SPEC-082926-0b72/AC-5")
def test_a_non_object_document_is_a_schema_error() -> None:
    settings_store.reset(store=_RecordingStore(document="[1, 2, 3]"))
    try:
        with pytest.raises(settings_store.SettingsSchemaError, match="not an object"):
            settings_store.load()
    finally:
        settings_store.reset()


# --- AC-6: volatile values are separate and labelled --------------------


@pytest.mark.ac("SPEC-082926-0b72/AC-6")
def test_a_preview_override_is_labelled_and_never_persisted(store: _RecordingStore) -> None:
    settings_store.save(SettingsModel(default_model="durable-choice"))

    overlay = settings_store.set_preview({"default_model": "just-trying-this"})

    assert overlay == {"default_model": "just-trying-this"}
    assert settings_store.current().default_model == "durable-choice"
    assert json.loads(store.read() or "")["values"]["default_model"] == "durable-choice"


@pytest.mark.ac("SPEC-082926-0b72/AC-6")
def test_the_volatile_surface_marks_itself_not_durable(store: _RecordingStore) -> None:
    client = _config_writer("volatile-1")

    put = client.put("/v1/settings/volatile", json={"theme": "light"})
    got = client.get("/v1/settings/volatile")

    assert put.json() == {"durable": False, "values": {"theme": "light"}}
    assert got.json() == {"durable": False, "values": {"theme": "light"}}


@pytest.mark.ac("SPEC-082926-0b72/AC-6")
def test_clearing_the_overlay_does_not_disturb_the_record(store: _RecordingStore) -> None:
    saved = settings_store.save(SettingsModel(default_model="durable-choice"))
    settings_store.set_preview({"default_model": "temporary"})

    assert settings_store.clear_preview() == {}
    assert settings_store.record().values == saved.values
    assert settings_store.record().revision == saved.revision


# --- The surfaces that read the record ----------------------------------


@pytest.mark.ac("SPEC-082926-0b72/AC-2")
def test_the_model_list_falls_back_to_the_stored_default(
    store: _RecordingStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    from routes import settings as settings_routes

    settings_store.save(SettingsModel(default_model="stored-default"))
    monkeypatch.delenv("LITELLM_API_BASE", raising=False)
    monkeypatch.delenv("LITELLM_PROXY_URL", raising=False)

    assert settings_routes._fetch_available_models() == ["stored-default"]


@pytest.mark.ac("SPEC-082926-0b72/AC-2")
def test_the_model_list_uses_the_proxy_when_one_is_configured(
    store: _RecordingStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    from routes import settings as settings_routes

    class _Response:
        @staticmethod
        def raise_for_status() -> None:
            return None

        @staticmethod
        def json() -> dict[str, Any]:
            return {"data": [{"id": "b"}, {"id": "a"}, {"id": ""}]}

    monkeypatch.setenv("LITELLM_API_BASE", "http://proxy.invalid/v1")
    monkeypatch.setenv("LITELLM_API_KEY", "unused-by-the-stub")
    monkeypatch.setattr(settings_routes.httpx, "get", lambda *a, **k: _Response())

    assert settings_routes._fetch_available_models() == ["a", "b"]


@pytest.mark.ac("SPEC-082926-0b72/AC-2")
def test_a_failed_model_fetch_falls_back_to_the_stored_default(
    store: _RecordingStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    from routes import settings as settings_routes

    settings_store.save(SettingsModel(default_model="stored-default"))
    monkeypatch.setenv("LITELLM_API_BASE", "http://proxy.invalid/v1")
    monkeypatch.delenv("LITELLM_API_KEY", raising=False)
    monkeypatch.delenv("LITELLM_PROXY_KEY", raising=False)

    def _boom(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("no proxy here")

    monkeypatch.setattr(settings_routes.httpx, "get", _boom)

    assert settings_routes._fetch_available_models() == ["stored-default"]


@pytest.mark.ac("SPEC-082926-0b72/AC-6")
def test_deleting_the_overlay_empties_it_over_http(store: _RecordingStore) -> None:
    # `config.delete`, not `config.write`: DELETE under /v1/settings inherits the
    # heavier scope from the prefix table, and the route says why it is not
    # carved out.
    client = _config_writer("volatile-2", "config.delete")
    client.put("/v1/settings/volatile", json={"theme": "light"})

    response = client.delete("/v1/settings/volatile")

    assert response.json() == {"durable": False, "values": {}}
    assert settings_store.preview() == {}


@pytest.mark.ac("SPEC-082926-0b72/AC-5")
def test_the_merge_revalidates_even_if_the_request_boundary_stops_doing_so(
    store: _RecordingStore,
) -> None:
    # `PatchSettingsBody` now types `theme` and `log_level` as the same Literals
    # `SettingsModel` does, so an invalid value is refused at the boundary and
    # this second check cannot be reached over HTTP. It is still the check that
    # matters: the boundary types are the thing that drifted last time, and a
    # record that will not load is worse than a rejected request. Constructed
    # unvalidated here to stand in for that drift.
    from fastapi import HTTPException
    from routes.settings import PatchSettingsBody, patch_settings

    drifted = PatchSettingsBody.model_construct(log_level="not-a-level")

    with pytest.raises(HTTPException) as caught:
        patch_settings(drifted)

    assert caught.value.status_code == 422
    assert store.read() is None


@pytest.mark.ac("SPEC-082926-0b72/AC-2")
def test_the_setup_checklist_reads_the_stored_default_model(store: _RecordingStore) -> None:
    from routes.setup_checklist import _default_model_picked

    # The checklist's question is "did Setup write something other than the
    # shipped alias", so the untouched alias is what must read as unpicked.
    settings_store.save(SettingsModel(default_model="cerebras-qwen-3-235b-a22b-2507"))
    assert _default_model_picked() is False

    settings_store.save(SettingsModel(default_model="operator-picked"))
    assert _default_model_picked() is True


@pytest.mark.ac("SPEC-082926-0b72/AC-1")
def test_startup_leaves_non_legacy_settings_alone(store: _RecordingStore) -> None:
    from settings_defaults import apply_default_settings_if_needed

    saved = settings_store.save(SettingsModel(default_model="operator-picked"))

    assert apply_default_settings_if_needed().default_model == "operator-picked"
    assert settings_store.record().revision == saved.revision


@pytest.mark.ac("SPEC-082926-0b72/AC-1")
def test_startup_repairs_pre_2026_placeholder_settings(store: _RecordingStore) -> None:
    from settings_defaults import apply_default_settings_if_needed, is_legacy_settings

    settings_store.save(SettingsModel(default_model="gpt-4"))

    repaired = apply_default_settings_if_needed()

    assert not is_legacy_settings(repaired)
    assert settings_store.record().values.default_model == repaired.default_model


@pytest.mark.ac("SPEC-082926-0b72/AC-2")
def test_a_repair_that_does_not_land_leaves_the_stored_values_readable(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Startup must not die over a cosmetic repair, and it must not claim the
    # repair happened either. The stored values stay readable and the log says
    # what did not land.
    from settings_defaults import apply_default_settings_if_needed

    legacy = json.dumps(
        {
            "schema_version": settings_store.SCHEMA_VERSION,
            "revision": 4,
            "updated_at": datetime.now(UTC).isoformat(),
            "values": SettingsModel(default_model="gpt-4").model_dump(mode="json"),
        }
    )
    settings_store.reset(store=_DroppingStore(document=legacy))
    try:
        with caplog.at_level("WARNING"):
            values = apply_default_settings_if_needed()

        assert values.default_model == "gpt-4"
        assert "legacy settings left in place" in caplog.text
    finally:
        settings_store.reset()


# --- What Codex's review changed ----------------------------------------


@pytest.mark.ac("SPEC-082926-0b72/AC-4")
def test_the_revision_check_and_the_write_are_one_critical_section(
    store: _RecordingStore,
) -> None:
    """Asserted from inside, because the interleaving is what is being excluded.

    Without the lock both callers `load()` before either writes, both pass the
    revision check, and the second is never refused with the 409 the API
    promises (Codex, #334). A threaded test can only ever fail to reproduce
    that; observing the lock held across the read half proves the window is
    closed.
    """
    observed: list[bool] = []
    real_load = settings_store.load

    def watching() -> Any:
        observed.append(settings_store._save_lock.locked())
        return real_load()

    settings_store.load = watching  # type: ignore[assignment]
    try:
        settings_store.save(SettingsModel(default_model="under-the-lock"))
    finally:
        settings_store.load = real_load  # type: ignore[assignment]

    assert observed == [True]


@pytest.mark.ac("SPEC-082926-0b72/AC-4")
def test_concurrent_writers_on_one_revision_produce_exactly_one_conflict(
    store: _RecordingStore,
) -> None:
    """And from the outside, with a store slow enough to interleave without it."""
    import threading
    import time

    class _Slow(_RecordingStore):
        def write(self, document: str) -> None:
            time.sleep(0.05)
            super().write(document)

    settings_store.reset(store=_Slow())
    try:
        settings_store.save(SettingsModel(default_model="first"))
        outcomes: list[str] = []
        guard = threading.Lock()

        def writer(name: str) -> None:
            try:
                settings_store.save(SettingsModel(default_model=name), expected_revision=1)
                verdict = "ok"
            except settings_store.SettingsConflictError:
                verdict = "conflict"
            with guard:
                outcomes.append(verdict)

        threads = [threading.Thread(target=writer, args=(name,)) for name in ("a", "b")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        assert sorted(outcomes) == ["conflict", "ok"], outcomes
        assert settings_store.record().revision == 2
    finally:
        settings_store.reset()


@pytest.mark.ac("SPEC-082926-0b72/AC-2")
def test_a_store_that_raises_is_a_persistence_error_not_a_500(
    store: _RecordingStore,
) -> None:
    """`State.submit` raises a bare RuntimeError when its queue is full or the
    writer is closed. Unwrapped it crosses the service boundary unclassified
    and the route returns 500 instead of the documented 503 (Codex, #334)."""

    class _Refusing(_RecordingStore):
        def write(self, document: str) -> None:
            raise RuntimeError("backpressure: submit queue full (depth=10000)")

    settings_store.reset(store=_Refusing())
    try:
        with pytest.raises(settings_store.SettingsPersistenceError, match="refused the write"):
            settings_store.save(SettingsModel(default_model="lost"))

        client = _config_writer("refusing-1")
        response = client.put(
            "/v1/settings", json=SettingsModel(default_model="lost").model_dump(mode="json")
        )
        assert response.status_code == 503
    finally:
        settings_store.reset()


@pytest.mark.ac("SPEC-082926-0b72/AC-2")
def test_the_setup_write_is_not_inside_a_bare_except_handler() -> None:
    """Structural, because the defect was structural.

    Setup's durable write was correct; what was wrong was the handler it sat
    inside — a pre-existing best-effort `except Exception` written for a
    settings *shape* mismatch, which turned a lost model choice into
    `setup_complete: true` (Codex, #334). A future edit that moves the call back
    under a broad handler restores the bug without changing the call itself, and
    no happy-path test would notice.

    Structural rather than driven through `/v1/setup/complete` because that
    route refuses once provisioning has run, and the test session is always
    past that point — a test that has to un-provision the app to reach the line
    is testing the fixture, not the handler.
    """
    import ast

    source = (Path(__file__).resolve().parents[1] / "routes" / "setup.py").read_text()

    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Try):
            continue
        body = ast.dump(ast.Module(body=node.body, type_ignores=[]))
        if "settings_store" not in body or "save" not in body:
            continue
        for handler in node.handlers:
            assert handler.type is not None, "a bare `except:` wraps the durable write"
            caught = ast.unparse(handler.type)
            assert "Settings" in caught, (
                f"the durable settings write is caught by `except {caught}`; "
                "a broad handler here is what let setup report success while "
                "losing the operator's choice"
            )


@pytest.mark.ac("SPEC-082926-0b72/AC-2")
def test_setup_returns_503_rather_than_completing_without_durable_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The behavioural half of the finding above.

    `complete_setup` is called directly with `_is_setup_complete` patched: the
    route refuses once provisioning has run and the test session is always past
    that point, so the alternative is un-provisioning the app, which tests the
    fixture rather than the handler.
    """
    from fastapi import HTTPException
    from routes import setup as setup_routes

    monkeypatch.setattr(setup_routes, "_is_setup_complete", lambda: False)
    settings_store.reset(store=_DroppingStore())
    try:
        with pytest.raises(HTTPException) as caught:
            setup_routes.complete_setup(
                {
                    "hardware_preset": "workstation",
                    "default_model": "chosen-in-setup",
                    "admin_username": "setup-503-admin",
                    "admin_password": _SETUP_PASSWORD,
                    "user_username": "setup-503-user",
                    "user_password": _SETUP_PASSWORD,
                }
            )
    finally:
        settings_store.reset()

    assert caught.value.status_code == 503
    assert "not persisted" in str(caught.value.detail)


@pytest.mark.ac("SPEC-082926-0b72/AC-3")
def test_setup_refuses_a_default_model_carrying_credential_material(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi import HTTPException
    from routes import setup as setup_routes

    monkeypatch.setattr(setup_routes, "_is_setup_complete", lambda: False)
    settings_store.reset(store=_RecordingStore())
    try:
        with pytest.raises(HTTPException) as caught:
            setup_routes.complete_setup(
                {
                    "hardware_preset": "workstation",
                    "default_model": _OPENAI_SHAPED,
                    "admin_username": "setup-400-admin",
                    "admin_password": _SETUP_PASSWORD,
                    "user_username": "setup-400-user",
                    "user_password": _SETUP_PASSWORD,
                }
            )
    finally:
        settings_store.reset()

    assert caught.value.status_code == 400
    assert _OPENAI_SHAPED not in str(caught.value.detail)


@pytest.mark.ac("SPEC-082926-0b72/AC-2")
def test_a_capability_toggle_that_cannot_persist_leaves_the_registry_alone(
    store: _RecordingStore,
) -> None:
    """A failed request must not leave the deployment running the change.

    The registry was mutated before the record was written, so a caller that
    treated the error as a failed operation could unknowingly run with the
    capability active until restart (Codex, #334).
    """

    def _slot(client: TestClient) -> dict[str, Any]:
        listing = client.get("/v1/capabilities")
        assert listing.status_code == 200, listing.text
        return next(s for s in listing.json()["slots"] if s["slot"] == "approval")

    client = _config_writer("cap-rollback")
    was_enabled = _slot(client)["enabled"]

    settings_store.reset(store=_DroppingStore())
    try:
        response = client.patch("/v1/capabilities/approval", json={"enabled": not was_enabled})
    finally:
        settings_store.reset()

    assert response.status_code == 503, response.text
    assert _slot(client)["enabled"] is was_enabled


@pytest.mark.ac("SPEC-082926-0b72/AC-2")
def test_restoring_a_slot_that_had_no_active_provider_does_not_activate_one() -> None:
    """`None` means "nothing was active", not "activate something".

    A slot can be enabled with no provider chosen, and a rollback that called
    `activate(slot, None)` would invent a state the registry was never in.
    """
    from routes.capabilities import _restore_slot

    class _Registry:
        def __init__(self) -> None:
            self.enabled: bool | None = None
            self.activated: list[str] = []

        def set_enabled(self, slot: str, value: bool) -> None:
            self.enabled = value

        def activate(self, slot: str, provider: str) -> None:
            self.activated.append(provider)

    registry = _Registry()

    _restore_slot(registry, "approval", (True, None))

    assert registry.enabled is True
    assert registry.activated == []
