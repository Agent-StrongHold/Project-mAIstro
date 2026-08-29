"""SPEC-082926-3b80: a dashboard layout is durable, or the save fails (#340).

The defect these pin is not "the write was missing"; it is that a write which
did not land answered `{"ok": true}`. So most of what follows drives
`services.dashboard_layouts` against an injected store that refuses, drops, or
lies about writes — failures a real store will not produce on demand — and one
test runs the whole path against a real `maistro.state.State` on a real SQLite
file, closed and reopened, because against a fake a restart proves nothing.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest
import stores
from services import dashboard_layouts

ROUTE_SOURCE = Path(__file__).resolve().parents[1] / "routes" / "dashboard_layout.py"

LAYOUT: dict[str, Any] = {
    "widgets": [{"id": "w1", "type": "stat-score", "title": "Score", "size": "md"}],
    "tabs": [],
    "activeTab": 0,
}


class _RefusingStore:
    """Every write raises. A read-only filesystem, a full disk, a lost pool."""

    def __init__(self, reason: str = "no writable backing store") -> None:
        self._reason = reason
        self._data: dict[str, Any] = {}

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def __setitem__(self, key: str, value: Any) -> None:
        raise OSError(self._reason)


class _DroppingStore:
    """Accepts every write and keeps none. The failure a bare `except` cannot see."""

    def get(self, key: str, default: Any = None) -> Any:
        return default

    def __setitem__(self, key: str, value: Any) -> None:
        return None


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Point the service at a store the test controls."""

    def use(replacement: Any) -> Any:
        monkeypatch.setattr(dashboard_layouts, "_store", lambda: replacement)
        return replacement

    return use


# --- AC-1: the layout is in the deployment's data boundary --------------------


@pytest.mark.ac("SPEC-082926-3b80/AC-1")
def test_a_saved_layout_survives_the_store_being_closed_and_reopened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The definition of done, run rather than asserted.

    A real `State` on a real file, a real `PersistedStore`, a real `JsonStore`:
    saved through the service, then closed, reopened and loaded again.
    """
    from services.model_store import JsonStore

    from maistro.state import PersistedStore, State

    db = tmp_path / "state.db"

    first = State(db_path=str(db))
    persisted = PersistedStore(first)
    persisted.initialize()
    before = JsonStore("dashboard_layouts", persisted)
    before.initialize()
    monkeypatch.setattr(dashboard_layouts, "_store", lambda: before)

    dashboard_layouts.save("alice", LAYOUT)
    first.flush()
    first.close()

    second = State(db_path=str(db))
    reopened = PersistedStore(second)
    reopened.initialize()
    after = JsonStore("dashboard_layouts", reopened)
    after.initialize()
    monkeypatch.setattr(dashboard_layouts, "_store", lambda: after)
    try:
        record = dashboard_layouts.load("alice")
    finally:
        second.close()

    assert record.revision == 1
    assert record.layout["widgets"][0]["id"] == "w1"


@pytest.mark.ac("SPEC-082926-3b80/AC-1")
def test_the_route_names_no_path_it_writes_layouts_to() -> None:
    """The old code wrote `backend/data/dashboard_layouts.json` — inside the
    image, beside the code. Structural because the claim is about where the
    module points, which no request can observe."""
    source = ROUTE_SOURCE.read_text(encoding="utf-8")

    assert "dashboard_layouts.json" not in source
    assert "stores" not in source or "dashboard_layouts.json" not in source


@pytest.mark.ac("SPEC-082926-3b80/AC-1")
def test_the_layout_store_is_registered_for_persistence() -> None:
    """A `JsonStore` that `configure_persistence` never reaches is a dict."""
    assert stores.dashboard_layouts in stores._all_json_stores


# --- AC-2: a write that did not land is not a success ------------------------


@pytest.mark.ac("SPEC-082926-3b80/AC-2")
def test_a_refused_write_raises_rather_than_returning(store: Any) -> None:
    store(_RefusingStore("read-only file system"))

    with pytest.raises(dashboard_layouts.LayoutPersistenceError, match="read-only file system"):
        dashboard_layouts.save("alice", LAYOUT)


@pytest.mark.ac("SPEC-082926-3b80/AC-2")
def test_a_write_that_is_silently_dropped_raises(store: Any) -> None:
    """The store neither raises nor keeps anything. Only the read-back sees it."""
    store(_DroppingStore())

    with pytest.raises(dashboard_layouts.LayoutPersistenceError, match="read back at revision 0"):
        dashboard_layouts.save("alice", LAYOUT)


@pytest.mark.ac("SPEC-082926-3b80/AC-2")
def test_a_refused_save_answers_503_rather_than_ok(
    authed_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise dashboard_layouts.LayoutPersistenceError("the store refused the write")

    monkeypatch.setattr(dashboard_layouts, "save", refuse)

    r = authed_client.put("/v1/dashboard/layout", json=LAYOUT)

    assert r.status_code == 503
    assert "not saved" in r.json()["detail"]


@pytest.mark.ac("SPEC-082926-3b80/AC-2")
def test_the_route_does_not_wrap_the_save_in_a_broad_handler() -> None:
    """Structural, because the defect was the handler rather than the call.

    A `try` around `dashboard_layouts.save` may catch the two failures that have
    an answer of their own. `except Exception` is what turned a failed write
    into `{"ok": true}`, and it is what must not come back.
    """
    tree = ast.parse(ROUTE_SOURCE.read_text(encoding="utf-8"))
    offenders: list[str] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        calls = [
            child
            for child in ast.walk(node)
            if isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and child.func.attr == "save"
        ]
        if not calls:
            continue
        for handler in node.handlers:
            name = ast.unparse(handler.type) if handler.type else "bare except"
            if name in {"Exception", "BaseException", "bare except"}:
                offenders.append(name)

    assert offenders == [], f"the durable save is inside {offenders}"


# --- AC-3: per principal, and no shared fallback ------------------------------


@pytest.mark.ac("SPEC-082926-3b80/AC-3")
def test_two_principals_do_not_share_a_layout(store: Any) -> None:
    from services.model_store import JsonStore

    store(JsonStore("dashboard_layouts"))
    dashboard_layouts.save("alice", {"widgets": [{"id": "a", "type": "x", "title": "A"}]})
    dashboard_layouts.save("bob", {"widgets": [{"id": "b", "type": "x", "title": "B"}]})

    assert dashboard_layouts.load("alice").layout["widgets"][0]["id"] == "a"
    assert dashboard_layouts.load("bob").layout["widgets"][0]["id"] == "b"


@pytest.mark.ac("SPEC-082926-3b80/AC-3")
def test_a_request_with_no_principal_is_refused_rather_than_pooled() -> None:
    """The `"dev"` fallback pooled every unauthenticated caller into one key."""
    from types import SimpleNamespace

    from fastapi import HTTPException
    from routes import dashboard_layout

    request = SimpleNamespace(state=SimpleNamespace(user=None))

    with pytest.raises(HTTPException) as raised:
        dashboard_layout._user_id(request)  # type: ignore[arg-type]

    assert raised.value.status_code == 401


# --- AC-4: conflicts are explicit --------------------------------------------


@pytest.mark.ac("SPEC-082926-3b80/AC-4")
def test_a_stale_expected_revision_is_refused(store: Any) -> None:
    from services.model_store import JsonStore

    store(JsonStore("dashboard_layouts"))
    dashboard_layouts.save("alice", LAYOUT)
    dashboard_layouts.save("alice", LAYOUT)

    with pytest.raises(dashboard_layouts.LayoutConflictError) as raised:
        dashboard_layouts.save("alice", LAYOUT, expected_revision=1)

    assert raised.value.stored.revision == 2


@pytest.mark.ac("SPEC-082926-3b80/AC-4")
def test_a_matching_expected_revision_is_accepted(store: Any) -> None:
    from services.model_store import JsonStore

    store(JsonStore("dashboard_layouts"))
    first = dashboard_layouts.save("alice", LAYOUT)

    second = dashboard_layouts.save("alice", LAYOUT, expected_revision=first.revision)

    assert second.revision == first.revision + 1


@pytest.mark.ac("SPEC-082926-3b80/AC-4")
def test_a_save_without_an_expectation_is_last_write_wins(store: Any) -> None:
    from services.model_store import JsonStore

    store(JsonStore("dashboard_layouts"))
    dashboard_layouts.save("alice", {"widgets": [{"id": "old", "type": "x", "title": "O"}]})
    dashboard_layouts.save("alice", {"widgets": [{"id": "new", "type": "x", "title": "N"}]})

    assert dashboard_layouts.load("alice").layout["widgets"][0]["id"] == "new"


@pytest.mark.ac("SPEC-082926-3b80/AC-4")
def test_a_stale_expectation_answers_409_with_the_current_record(authed_client: Any) -> None:
    """Through the API, against the store the app is actually wired to — a
    per-call replacement would have made every save its own fresh dict, which
    is how the first draft of this test passed for the wrong reason."""
    authed_client.put("/v1/dashboard/layout", json=LAYOUT)
    second = authed_client.put("/v1/dashboard/layout", json=LAYOUT)
    current = second.json()["revision"]

    r = authed_client.put("/v1/dashboard/layout", json={**LAYOUT, "expectedRevision": current - 1})

    assert r.status_code == 409
    assert r.json()["detail"]["revision"] == current


@pytest.mark.ac("SPEC-082926-3b80/AC-4")
def test_the_expected_revision_is_not_stored_as_part_of_the_layout(authed_client: Any) -> None:
    """It is a claim about the record, not a field of it."""
    saved = authed_client.put("/v1/dashboard/layout", json={**LAYOUT, "expectedRevision": 0})
    assert saved.status_code == 200

    read_back = authed_client.get("/v1/dashboard/layout")

    assert "expectedRevision" not in read_back.json()


# --- AC-5: a read does not depend on a write ---------------------------------


@pytest.mark.ac("SPEC-082926-3b80/AC-5")
def test_a_preset_is_returned_even_when_the_store_refuses_writes(store: Any) -> None:
    """Seeding used to persist from inside the GET handler, inside a bare
    `except`. Now the read answers and the preset becomes durable on save."""
    from routes import dashboard_layout

    store(_RefusingStore())
    preset = dashboard_layout._preset_for("demo")

    assert preset is not None
    assert preset["tabs"]


@pytest.mark.ac("SPEC-082926-3b80/AC-5")
def test_a_principal_with_no_preset_gets_no_preset() -> None:
    from routes import dashboard_layout

    assert dashboard_layout._preset_for("alice") is None


@pytest.mark.ac("SPEC-082926-3b80/AC-5")
def test_the_demo_preset_ships_in_the_image(authed_client: Any) -> None:
    """`_PRESETS` naming a file that is not there would seed nothing, silently."""
    from routes import dashboard_layout

    demos = Path(__file__).resolve().parents[1] / "data" / "demo_dashboards"
    for preset in dashboard_layout._PRESETS.values():
        assert (demos / f"{preset}.json").is_file(), preset


@pytest.mark.ac("SPEC-082926-3b80/AC-5")
def test_a_record_this_build_cannot_parse_reads_as_empty(store: Any) -> None:
    """A layout is a preference. Refusing to render the dashboard because one
    stored document is malformed helps nobody; the next save replaces it."""
    from services.model_store import JsonStore

    backing = store(JsonStore("dashboard_layouts"))
    backing["alice"] = {"schema_version": 1, "from_a_future_build": True}

    assert dashboard_layouts.load("alice").revision == 0


@pytest.mark.ac("SPEC-082926-3b80/AC-5")
def test_the_saved_layout_is_the_sanitized_one(store: Any) -> None:
    """The record holds what the sanitizer returned, never what was sent."""
    from services.model_store import JsonStore

    store(JsonStore("dashboard_layouts"))
    hostile = {
        "widgets": [
            {"id": "w", "type": "x", "title": "T", "config": {"url": "http://evil", "field": "ok"}}
        ]
    }

    record = dashboard_layouts.save("alice", hostile)

    assert record.layout["widgets"][0]["config"] == {"field": "ok"}


def test_the_promoted_demo_preset_is_the_layout_that_used_to_be_committed() -> None:
    """`data/dashboard_layouts.json` was runtime state tracked in git. It is
    gone; the layout it held ships as a demo template so the demo account sees
    what it saw before."""
    demos = Path(__file__).resolve().parents[1] / "data" / "demo_dashboards"
    promoted = json.loads((demos / "pm-command-center.json").read_text())

    ids = sorted(w["id"] for tab in promoted["tabs"] for w in tab["widgets"])
    assert "pm-kpi-velocity" in ids
    assert not (Path(__file__).resolve().parents[1] / "data" / "dashboard_layouts.json").exists()


@pytest.mark.ac("SPEC-082926-3b80/AC-5")
def test_a_preset_naming_a_missing_file_seeds_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    from routes import dashboard_layout

    monkeypatch.setitem(dashboard_layout._PRESETS, "ghost", "no-such-template")

    assert dashboard_layout._preset_for("ghost") is None


@pytest.mark.ac("SPEC-082926-3b80/AC-5")
def test_an_unreadable_preset_seeds_nothing_rather_than_raising(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A corrupt template in the image must not take the dashboard down."""
    from routes import dashboard_layout

    demos = Path(__file__).resolve().parents[1] / "data" / "demo_dashboards"
    broken = demos / "broken-for-test.json"
    broken.write_text("{ not json", encoding="utf-8")
    monkeypatch.setitem(dashboard_layout._PRESETS, "brokenuser", "broken-for-test")
    try:
        assert dashboard_layout._preset_for("brokenuser") is None
    finally:
        broken.unlink()


@pytest.mark.ac("SPEC-082926-3b80/AC-5")
@pytest.mark.asyncio
async def test_a_principal_with_a_preset_reads_it_at_revision_zero(store: Any) -> None:
    """The seed is offered, not written: revision stays 0 until a real save."""
    from types import SimpleNamespace

    from routes import dashboard_layout
    from services.model_store import JsonStore

    backing = store(JsonStore("dashboard_layouts"))
    request = SimpleNamespace(state=SimpleNamespace(user={"id": "demo"}))

    body = await dashboard_layout.get_layout(request)  # type: ignore[arg-type]

    assert body["revision"] == 0
    assert body["tabs"]
    assert "demo" not in backing
