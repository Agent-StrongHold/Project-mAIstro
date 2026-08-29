"""Conductor state durability mode — SPEC-082926-87bb / ADR-082926-87bb (#333).

The failures that matter here are ones a healthy machine will not produce: an
unwritable data directory, a migration that fails part-way, an import that is
not there, a database that goes away. Each is injected at the seam it actually
enters through — `maistro.state` — rather than simulated one layer up, because
the defect being closed was precisely that all four entered through one `except`
and came out indistinguishable.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import stores
from fastapi.testclient import TestClient
from main import app
from services import durability, settings_store
from services.durability import InvalidDurabilityMode, StateStatus, StoreUnavailableError
from services.foundation import Foundation


def _settings(tmp_path: Path, mode: str = "durable") -> Any:
    return SimpleNamespace(
        conductor_data_dir=str(tmp_path),
        conductor_vault_path="",
        conductor_identity_path="",
        conductor_state_db=str(tmp_path / "state.db"),
        conductor_durability=mode,
        conductor_admin_public_key="",
        conductor_user_public_key="",
    )


def _break_state(monkeypatch: pytest.MonkeyPatch, message: str) -> None:
    """Make `from maistro.state import ...` raise, as a missing dependency would."""
    broken = types.ModuleType("maistro.state")

    def _raise(name: str) -> Any:
        raise ImportError(f"{message} ({name})")

    broken.__getattr__ = _raise  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "maistro.state", broken)


@pytest.fixture(autouse=True)
def _restore_state():
    """Every test here degrades or re-modes the shared stores. Put them back."""
    user_snapshot = dict(stores.users._data)
    prev_persisted = stores._persisted
    yield
    stores.restore_all()
    durability.reset()
    settings_store.reset()
    stores._persisted = prev_persisted
    for store in stores._all_model_stores:
        store._persisted = prev_persisted
    for json_store in stores._all_json_stores:
        json_store._persisted = prev_persisted
    stores.users._data.clear()
    stores.users._data.update(user_snapshot)


# --- AC-1: readiness follows the declared requirement -------------------


@pytest.mark.ac("SPEC-082926-87bb/AC-1")
def test_a_durable_deployment_that_cannot_open_its_state_is_not_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _break_state(monkeypatch, "no state module")
    Foundation()._init_state(_settings(tmp_path), tmp_path)

    body = TestClient(app).get("/health/ready").json()

    assert body["ready"] is False
    assert body["checks"]["durability"] is False
    recorded = durability.status()
    assert recorded is not None and "no state module" in (recorded.error or "")


@pytest.mark.ac("SPEC-082926-87bb/AC-1")
def test_a_durable_deployment_that_opens_its_state_is_ready(tmp_path: Path) -> None:
    Foundation()._init_state(_settings(tmp_path), tmp_path)

    body = TestClient(app).get("/health/ready").json()

    assert body["ready"] is True
    assert body["checks"]["durability"] is True
    recorded = durability.status()
    assert recorded is not None
    assert (recorded.backend, recorded.durable) == ("sqlite", True)


@pytest.mark.ac("SPEC-082926-87bb/AC-1")
def test_an_unwritable_state_path_is_a_recorded_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The issue's first named cause. A directory where the file should be is a
    # real, reachable way for sqlite3.connect to fail without any stubbing.
    blocked = tmp_path / "state.db"
    blocked.mkdir()
    settings = _settings(tmp_path)

    Foundation()._init_state(settings, tmp_path)

    recorded = durability.status()
    assert recorded is not None
    assert recorded.writes_refused is True
    assert recorded.satisfied is False


@pytest.mark.ac("SPEC-082926-87bb/AC-1")
def test_a_failing_migration_is_a_recorded_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The issue's second named cause, injected where migrations actually run.
    import maistro.state as real_state

    class _FailingPersist(real_state.PersistedStore):  # type: ignore[misc]
        def initialize(self) -> None:
            raise real_state.MigrationFailedError("kv_store_001 failed")

    module = types.ModuleType("maistro.state")
    module.State = real_state.State  # type: ignore[attr-defined]
    module.PersistedStore = _FailingPersist  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "maistro.state", module)

    Foundation()._init_state(_settings(tmp_path), tmp_path)

    recorded = durability.status()
    assert recorded is not None
    assert "kv_store_001 failed" in (recorded.error or "")
    assert recorded.durable is False


# --- AC-2: the mode is declared -----------------------------------------


@pytest.mark.ac("SPEC-082926-87bb/AC-2")
def test_ephemeral_mode_is_entered_by_declaration(tmp_path: Path) -> None:
    Foundation()._init_state(_settings(tmp_path, "ephemeral"), tmp_path)

    recorded = durability.status()
    assert recorded is not None
    assert recorded.requested == "ephemeral"
    assert (recorded.backend, recorded.durable, recorded.writes_refused) == (
        "memory",
        False,
        False,
    )
    assert recorded.satisfied is True
    assert not (tmp_path / "state.db").exists()


@pytest.mark.ac("SPEC-082926-87bb/AC-2")
def test_an_exception_cannot_produce_an_ephemeral_deployment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The whole point. The old code answered this question with a stack trace.
    _break_state(monkeypatch, "boom")
    Foundation()._init_state(_settings(tmp_path, "durable"), tmp_path)

    recorded = durability.status()
    assert recorded is not None
    assert recorded.requested == "durable"
    assert recorded.satisfied is False


@pytest.mark.ac("SPEC-082926-87bb/AC-2")
@pytest.mark.parametrize("raw", ["", "   ", None])
def test_an_unset_mode_is_the_documented_default(raw: str | None) -> None:
    assert durability.read_mode(raw) == "durable"


@pytest.mark.ac("SPEC-082926-87bb/AC-2")
@pytest.mark.parametrize("raw", ["memory", "off", "DURABLE!", "true"])
def test_an_unrecognised_mode_is_refused(raw: str) -> None:
    with pytest.raises(InvalidDurabilityMode, match="CONDUCTOR_DURABILITY"):
        durability.read_mode(raw)


@pytest.mark.ac("SPEC-082926-87bb/AC-2")
@pytest.mark.parametrize(
    ("raw", "expected"), [("DURABLE", "durable"), (" Ephemeral ", "ephemeral")]
)
def test_a_declared_mode_is_read_case_and_space_insensitively(raw: str, expected: str) -> None:
    assert durability.read_mode(raw) == expected


# --- AC-3: health says what is true -------------------------------------


@pytest.mark.ac("SPEC-082926-87bb/AC-3")
def test_health_names_the_mode_the_backend_and_the_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _break_state(monkeypatch, "database is gone")
    Foundation()._init_state(_settings(tmp_path), tmp_path)

    body = TestClient(app).get("/health").json()

    state = body["state"]
    assert state["requested"] == "durable"
    assert state["backend"] == "none"
    assert state["durable"] is False
    assert state["writes_refused"] is True
    assert "database is gone" in state["error"]
    assert body["degraded"] is True


@pytest.mark.ac("SPEC-082926-87bb/AC-3")
def test_health_before_startup_reports_unstarted_not_failed() -> None:
    # None and a failed status are different, and conflating them would make
    # every app built without a lifespan unready for a requirement nothing has
    # tried to meet yet.
    durability.reset()

    body = TestClient(app).get("/health").json()

    assert body["state"]["backend"] == "unstarted"
    assert body["state"]["satisfied"] is True
    assert TestClient(app).get("/health/ready").json()["ready"] is True


@pytest.mark.ac("SPEC-082926-87bb/AC-3")
def test_an_ephemeral_deployment_is_labelled_not_degraded(tmp_path: Path) -> None:
    Foundation()._init_state(_settings(tmp_path, "ephemeral"), tmp_path)

    state = TestClient(app).get("/health").json()["state"]

    assert state == {
        "requested": "ephemeral",
        "backend": "memory",
        "durable": False,
        "writes_refused": False,
        "error": None,
        "satisfied": True,
    }


# --- AC-4: no partly-authoritative tree ---------------------------------


@pytest.mark.ac("SPEC-082926-87bb/AC-4")
def test_a_failure_after_some_stores_loaded_degrades_all_of_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `initialize_stores` walks the stores in order. Failing part-way used to
    # leave the ones already loaded taking writes as an authority while the
    # rest were empty and taking writes too.
    import maistro.state as real_state

    loaded: list[str] = []

    class _PartialPersist(real_state.PersistedStore):  # type: ignore[misc]
        def list_all(self, store_name: str, model_class: Any) -> list[Any]:
            loaded.append(store_name)
            if len(loaded) > 2:
                raise RuntimeError("connection lost mid-load")
            return []

    module = types.ModuleType("maistro.state")
    module.State = real_state.State  # type: ignore[attr-defined]
    module.PersistedStore = _PartialPersist  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "maistro.state", module)

    Foundation()._init_state(_settings(tmp_path), tmp_path)

    assert len(loaded) > 2, "the failure must happen after at least one store loaded"
    assert all(store.degraded for store in stores._all_model_stores)
    assert all(store.degraded for store in stores._all_json_stores)


# --- AC-5: nothing accumulates that a recovery could flush ---------------


@pytest.mark.ac("SPEC-082926-87bb/AC-5")
def test_a_degraded_process_holds_no_write_to_flush(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _break_state(monkeypatch, "no state module")
    Foundation()._init_state(_settings(tmp_path), tmp_path)
    before = dict(stores.dags._data)

    with pytest.raises(StoreUnavailableError):
        stores.dags["would-be-lost"] = {"nodes": []}

    assert stores.dags._data == before


@pytest.mark.ac("SPEC-082926-87bb/AC-5")
def test_settings_cannot_be_acknowledged_without_durable_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from models.schemas import SettingsModel

    _break_state(monkeypatch, "no state module")
    Foundation()._init_state(_settings(tmp_path), tmp_path)

    with pytest.raises(settings_store.SettingsPersistenceError, match="durable state"):
        settings_store.save(SettingsModel(default_model="would-be-lost"))


# --- AC-6: the store itself refuses ------------------------------------


@pytest.mark.ac("SPEC-082926-87bb/AC-6")
def test_a_degraded_store_refuses_writes_and_still_reads() -> None:
    from models.schemas import Skill
    from services.model_store import JsonStore, ModelStore

    model_store = ModelStore("demo", Skill)
    json_store = JsonStore("demo_json")
    json_store["already-here"] = {"kept": True}

    model_store.degrade("no durable backing")
    json_store.degrade("no durable backing")

    assert json_store["already-here"] == {"kept": True}
    assert len(json_store) == 1
    with pytest.raises(StoreUnavailableError, match="demo_json"):
        json_store["new"] = {}
    with pytest.raises(StoreUnavailableError, match="demo_json"):
        json_store.pop("already-here")
    with pytest.raises(StoreUnavailableError, match="demo"):
        model_store.pop("anything", None)


@pytest.mark.ac("SPEC-082926-87bb/AC-6")
def test_restore_lets_a_store_take_writes_again() -> None:
    from services.model_store import JsonStore

    store = JsonStore("demo_restore")
    store.degrade("no durable backing")
    store.restore()

    store["fine"] = {"now": True}

    assert store.degraded is False
    assert store["fine"] == {"now": True}


@pytest.mark.ac("SPEC-082926-87bb/AC-6")
def test_a_refused_write_reaches_the_caller_as_503(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, datetime

    from maistro.security.passwords import hash_password

    # Seed and log in before degrading: the point is that a write fails, not
    # that authentication does.
    uid = "durability-503"
    stores.users[uid] = stores.users._model_class(
        id=uid,
        username=uid,
        password_hash=hash_password("pw"),
        role="user",
        is_active=True,
        permissions=["config.write"],
        created_at=datetime.now(UTC),
    )
    client = TestClient(app, raise_server_exceptions=False)
    assert (
        client.post("/v1/auth/login", json={"username": uid, "password": "pw"}).status_code == 200
    )
    assert (
        client.post(
            "/v1/auth/elevate",
            json={"password": "pw", "permissions": ["config.write"], "task_id": "durability-503"},
        ).status_code
        == 200
    )

    _break_state(monkeypatch, "no state module")
    Foundation()._init_state(_settings(tmp_path), tmp_path)

    response = client.put(
        "/v1/settings",
        json={"default_model": "would-be-lost", "api_base_url": "http://127.0.0.1:8101"},
    )

    assert response.status_code == 503
    assert "durable state is unavailable" in response.json()["detail"]


@pytest.mark.ac("SPEC-082926-87bb/AC-6")
def test_the_recorded_status_is_what_every_surface_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _break_state(monkeypatch, "one truth")
    Foundation()._init_state(_settings(tmp_path), tmp_path)

    recorded = durability.status()
    assert recorded is not None
    assert durability.health_view() == recorded.as_dict()
    assert durability.writes_refused() is True
    assert durability.durability_satisfied() is False
    assert TestClient(app).get("/health").json()["state"] == recorded.as_dict()


@pytest.mark.ac("SPEC-082926-87bb/AC-6")
def test_a_status_dataclass_reports_satisfaction_from_the_mode() -> None:
    durable_ok = StateStatus("durable", "sqlite", True, False)
    durable_bad = StateStatus("durable", "none", False, True, "boom")
    ephemeral = StateStatus("ephemeral", "memory", False, False)

    assert (durable_ok.satisfied, durable_bad.satisfied, ephemeral.satisfied) == (True, False, True)


@pytest.mark.ac("SPEC-082926-87bb/AC-6")
def test_a_login_cannot_mint_a_session_the_restart_will_lose(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The refusal reaches HTTP through the handler, not through a route's own catch.

    Login is the sharpest case: `stores.sessions[...] = ...` is the whole point
    of the request, and a session minted into a store with no durable backing
    is exactly the "users keep working, and lose it at restart" shape #333 is
    about.
    """
    from datetime import UTC, datetime

    from maistro.security.passwords import hash_password

    uid = "durability-login"
    stores.users[uid] = stores.users._model_class(
        id=uid,
        username=uid,
        password_hash=hash_password("pw"),
        role="user",
        is_active=True,
        permissions=[],
        created_at=datetime.now(UTC),
    )

    _break_state(monkeypatch, "no state module")
    Foundation()._init_state(_settings(tmp_path), tmp_path)

    response = TestClient(app, raise_server_exceptions=False).post(
        "/v1/auth/login", json={"username": uid, "password": "pw"}
    )

    assert response.status_code == 503
    assert "no durable backing" in response.json()["detail"]


@pytest.mark.ac("SPEC-082926-87bb/AC-3")
def test_an_unreadable_status_reports_unreadable_rather_than_failing_the_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # /health is a liveness probe. It must answer even if this block cannot be
    # computed, and an unreadable state must not read as a durability failure —
    # a probe that reports an outage it cannot see is worse than one that says
    # it cannot see.
    def _boom() -> Any:
        raise RuntimeError("status unreadable")

    monkeypatch.setattr(durability, "health_view", _boom)
    monkeypatch.setattr(durability, "durability_satisfied", _boom)

    client = TestClient(app)
    body = client.get("/health").json()

    assert body["state"]["backend"] == "unreadable"
    assert body["state"]["satisfied"] is True
    assert client.get("/health/ready").json()["checks"]["durability"] is True
