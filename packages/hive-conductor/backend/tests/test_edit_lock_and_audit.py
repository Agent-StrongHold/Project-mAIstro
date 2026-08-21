"""Boy Scout — Phase 5 Signal #2: dag_edit audit + edit-lock service.

Tests cover:
- diff_dag_snapshots returns the correct list of dotted paths
- mark_edited + is_locked + locked_fields TTL behavior
- clear() wipes state (all OR per-dag)
- PUT /v1/dags/{id} writes a dag_edit audit entry with the field list
- PUT /v1/dags/{id} marks the edited paths as locked
- Locks expire after EDIT_LOCK_DAYS via a synthetic future `now`
- Edit-lock prefix match: editing nodes[abc].config locks
  nodes[abc].config.temperature too
- mark_edited("") raises ValueError (defensive contract)
- mark_edited with empty field list is a no-op
"""

from __future__ import annotations

import pathlib
import sys
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


@pytest.fixture(autouse=True)
def _isolated_edit_lock_store():
    """Wipe the edit-lock module store before AND after each test so
    they don't poison each other."""
    from services import edit_lock

    edit_lock.clear()
    yield
    edit_lock.clear()


# --- diff_dag_snapshots --------------------------------------------------


def _bare_snapshot(**overrides: Any) -> dict[str, Any]:
    base = {
        "id": "d1",
        "name": "test",
        "description": "",
        "nodes": [
            {
                "id": "n-A",
                "role": "queen",
                "name": "Conductor",
                "agent_id": None,
                "model": None,
                "strategy": "react",
                "prompt": None,
                "config": {},
            },
            {
                "id": "n-B",
                "role": "worker",
                "name": "Worker",
                "agent_id": None,
                "model": None,
                "strategy": "react",
                "prompt": None,
                "config": {},
            },
        ],
        "edges": [
            {"id": "e-1", "from_node": "n-A", "to_node": "n-B", "condition": None},
        ],
        "entry_node": "n-A",
        "max_cycles": 10,
        "run_scout": False,
        "status": "draft",
    }
    base.update(overrides)
    return base


def test_diff_top_level_name_change_only() -> None:
    from services.edit_lock import diff_dag_snapshots

    old = _bare_snapshot()
    new = _bare_snapshot(name="renamed")
    assert diff_dag_snapshots(old, new) == ["name"]


def test_diff_top_level_multiple_fields() -> None:
    from services.edit_lock import diff_dag_snapshots

    old = _bare_snapshot()
    new = _bare_snapshot(name="x", status="active", max_cycles=20)
    diff = diff_dag_snapshots(old, new)
    assert set(diff) == {"name", "status", "max_cycles"}


def test_diff_node_config_change_uses_node_id_key() -> None:
    from services.edit_lock import diff_dag_snapshots

    old = _bare_snapshot()
    new = _bare_snapshot()
    new["nodes"][0]["config"] = {"temperature": 0.7}
    diff = diff_dag_snapshots(old, new)
    assert diff == ["nodes[n-A].config"]


def test_diff_added_and_removed_node() -> None:
    from services.edit_lock import diff_dag_snapshots

    old = _bare_snapshot()
    new = _bare_snapshot()
    new["nodes"].append(
        {
            "id": "n-C",
            "role": "scout",
            "name": "Scout",
            "agent_id": None,
            "model": None,
            "strategy": "react",
            "prompt": None,
            "config": {},
        }
    )
    new["nodes"] = [n for n in new["nodes"] if n["id"] != "n-B"]
    diff = diff_dag_snapshots(old, new)
    assert "nodes[n-C]" in diff
    assert "nodes[n-B]" in diff


def test_diff_edge_field_change() -> None:
    from services.edit_lock import diff_dag_snapshots

    old = _bare_snapshot()
    new = _bare_snapshot()
    new["edges"][0]["condition"] = "if x"
    diff = diff_dag_snapshots(old, new)
    assert diff == ["edges[e-1].condition"]


def test_diff_added_and_removed_edge() -> None:
    from services.edit_lock import diff_dag_snapshots

    old = _bare_snapshot()
    new = _bare_snapshot()
    new["edges"].append({"id": "e-2", "from_node": "n-A", "to_node": "n-B", "condition": None})
    new["edges"] = [e for e in new["edges"] if e["id"] != "e-1"]
    diff = diff_dag_snapshots(old, new)
    assert "edges[e-2]" in diff
    assert "edges[e-1]" in diff


def test_diff_no_change_returns_empty_list() -> None:
    from services.edit_lock import diff_dag_snapshots

    snap = _bare_snapshot()
    assert diff_dag_snapshots(snap, snap) == []


# --- mark_edited + is_locked --------------------------------------------


def test_mark_edited_locks_field_paths() -> None:
    from services.edit_lock import is_locked, mark_edited

    mark_edited("dag-A", ["name", "nodes[n-A].config"], user_id="u1")
    assert is_locked("dag-A", "name") is True
    assert is_locked("dag-A", "nodes[n-A].config") is True
    assert is_locked("dag-A", "status") is False  # untouched field


def test_mark_edited_prefix_match_locks_nested_paths() -> None:
    """Editing nodes[n-A].config must also lock
    nodes[n-A].config.temperature so the optimizer can't sneak under."""
    from services.edit_lock import is_locked, mark_edited

    mark_edited("dag-B", ["nodes[n-A].config"])
    assert is_locked("dag-B", "nodes[n-A].config.temperature") is True
    assert is_locked("dag-B", "nodes[n-A].config.max_tokens") is True
    # but not a sibling node
    assert is_locked("dag-B", "nodes[n-Z].config.temperature") is False


def test_lock_expires_after_edit_lock_days() -> None:
    from services.edit_lock import EDIT_LOCK_DAYS, is_locked, mark_edited

    fixed_now = datetime(2026, 5, 22, tzinfo=UTC)
    mark_edited("dag-C", ["status"], now=fixed_now)
    # 29 days later → still locked
    assert is_locked("dag-C", "status", now=fixed_now + timedelta(days=29)) is True
    # 31 days later → expired
    assert is_locked("dag-C", "status", now=fixed_now + timedelta(days=EDIT_LOCK_DAYS + 1)) is False


def test_mark_edited_refreshes_ttl_on_repeat_edits() -> None:
    from services.edit_lock import is_locked, mark_edited

    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    mark_edited("dag-D", ["name"], now=t0)
    # 25 days later — still locked, user edits again → refreshes
    t1 = t0 + timedelta(days=25)
    mark_edited("dag-D", ["name"], now=t1)
    # 25 days after the SECOND edit, lock should still be active even
    # though we're now 50 days past the original
    assert is_locked("dag-D", "name", now=t1 + timedelta(days=25)) is True


def test_locked_fields_returns_active_only() -> None:
    from services.edit_lock import locked_fields, mark_edited

    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    mark_edited("dag-E", ["name"], now=t0)
    # 35 days later — name has expired, status is freshly locked
    t1 = t0 + timedelta(days=35)
    mark_edited("dag-E", ["status"], now=t1)
    active = locked_fields("dag-E", now=t1)
    assert active == ["status"]


def test_clear_all_wipes_state() -> None:
    from services.edit_lock import clear, is_locked, mark_edited

    mark_edited("dag-F", ["x"])
    clear()
    assert is_locked("dag-F", "x") is False


def test_clear_one_dag_only() -> None:
    from services.edit_lock import clear, is_locked, mark_edited

    mark_edited("dag-G1", ["a"])
    mark_edited("dag-G2", ["b"])
    clear("dag-G1")
    assert is_locked("dag-G1", "a") is False
    assert is_locked("dag-G2", "b") is True


def test_mark_edited_empty_field_list_is_noop() -> None:
    from services.edit_lock import locked_fields, mark_edited

    mark_edited("dag-H", [])
    assert locked_fields("dag-H") == []


def test_mark_edited_empty_dag_id_raises_value_error() -> None:
    from services.edit_lock import mark_edited

    with pytest.raises(ValueError, match="dag_id is required"):
        mark_edited("", ["field"])


def test_is_locked_unknown_dag_returns_false() -> None:
    from services.edit_lock import is_locked

    assert is_locked("never-edited-dag", "any") is False


# --- HTTP PUT /v1/dags/{id} integration --------------------------------


def _seed_dag(client: Any) -> str:
    r = client.post("/v1/dags", json={"name": "seed", "description": ""})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_put_dag_writes_dag_edit_audit_entry(admin_client: Any) -> None:
    import stores

    dag_id = _seed_dag(admin_client)
    before = len(stores.audit_log)
    r = admin_client.put(
        f"/v1/dags/{dag_id}",
        json={"name": "renamed", "description": "now updated"},
    )
    assert r.status_code == 200
    # New audit entry
    assert len(stores.audit_log) == before + 1
    entries = list(stores.audit_log.values())
    last = entries[-1]
    assert last["action"] == "dag_edit"
    assert last["target"] == dag_id
    assert last["actor"] == "admin"  # dag edits now require dags.write; admin fixture drives them
    assert set(last["detail"]["changed"]) == {"name", "description"}
    assert last["detail"]["field_count"] == 2


def test_put_dag_no_changes_writes_no_audit(admin_client: Any) -> None:
    """Empty PUT body (or only no-op fields) MUST NOT write an audit entry
    or refresh the edit-lock. A no-op edit is not a 'manual override'."""
    import stores
    from services.edit_lock import locked_fields

    dag_id = _seed_dag(admin_client)
    before_audit = len(stores.audit_log)
    r = admin_client.put(f"/v1/dags/{dag_id}", json={})
    assert r.status_code == 200
    assert len(stores.audit_log) == before_audit
    assert locked_fields(dag_id) == []


def test_put_dag_marks_edited_fields_as_locked(admin_client: Any) -> None:
    from services.edit_lock import is_locked

    dag_id = _seed_dag(admin_client)
    admin_client.put(f"/v1/dags/{dag_id}", json={"max_cycles": 99, "status": "active"})
    assert is_locked(dag_id, "max_cycles") is True
    assert is_locked(dag_id, "status") is True
    assert is_locked(dag_id, "description") is False  # untouched


def test_put_dag_unauthorized_returns_401() -> None:
    """The route is auth-gated by AuthMiddleware; no session → no actor."""
    from fastapi.testclient import TestClient
    from main import app

    client = TestClient(app)
    r = client.put("/v1/dags/anything", json={"name": "x"})
    assert r.status_code == 401


def test_put_dag_404_when_id_missing(admin_client: Any) -> None:
    import stores

    before_audit = len(stores.audit_log)
    r = admin_client.put("/v1/dags/does-not-exist", json={"name": "x"})
    assert r.status_code == 404
    # No audit on the failure path
    assert len(stores.audit_log) == before_audit
