"""Route-level coverage for routes/audit.py.

Bug fixed alongside this test file: ``list_entries`` filtered on
``getattr(e, "action"/"severity"/"actor", "")``, but every entry in
``stores.audit_log`` (a ``JsonStore``) is stored as a plain ``dict`` via
``.model_dump(mode="json")`` — both in ``log_audit()`` and in the seed
data (``stores._seed_audit_log``). ``getattr(some_dict, "action", "")``
always returns the *default* (dicts don't have attributes named
"action"), so every ``action=`` / ``severity=`` / ``actor=`` filter
silently matched nothing. Fixed by reading dict keys when the stored
entry is a dict (`routes/audit.py::_field`), falling back to
``getattr`` for any non-dict entry. The tests below pin the *fixed*
(filters actually work) behaviour.
"""

from __future__ import annotations

import pathlib
import sys
from typing import Any

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import stores  # noqa: E402
from routes.audit import log_audit  # noqa: E402


def _clear(store) -> None:
    for key in list(store.keys()):
        store.pop(key, None)


@pytest.fixture(autouse=True)
def _clear_audit_log():
    _clear(stores.audit_log)
    yield
    _clear(stores.audit_log)


# --------------------------------------------------------------------------- #
# log_audit() helper — stores a plain dict
# --------------------------------------------------------------------------- #


def test_log_audit_stores_dict_with_defaults() -> None:
    log_audit("did_thing", "system")
    assert len(stores.audit_log) == 1
    (entry,) = stores.audit_log.values()
    assert isinstance(entry, dict)
    assert entry["action"] == "did_thing"
    assert entry["actor"] == "system"
    assert entry["target"] is None
    assert entry["detail"] == {}
    assert entry["severity"] == "info"


def test_log_audit_with_target_detail_severity() -> None:
    log_audit("agent_invoke", "uid-1", target="a1", detail={"k": "v"}, severity="warning")
    (entry,) = stores.audit_log.values()
    assert entry["target"] == "a1"
    assert entry["detail"] == {"k": "v"}
    assert entry["severity"] == "warning"


# --------------------------------------------------------------------------- #
# GET "" — list, with filters
# --------------------------------------------------------------------------- #


def test_list_entries_no_filter_returns_all(admin_client: Any) -> None:
    log_audit("a1", "u1")
    log_audit("a2", "u2")
    r = admin_client.get("/v1/audit")
    assert r.status_code == 200
    assert len(r.json()) == 2


def test_list_entries_filtered_by_action(admin_client: Any) -> None:
    log_audit("login", "u1")
    log_audit("logout", "u1")
    r = admin_client.get("/v1/audit", params={"action": "login"})
    body = r.json()
    assert len(body) == 1
    assert body[0]["action"] == "login"


def test_list_entries_filtered_by_severity(admin_client: Any) -> None:
    log_audit("a1", "u1", severity="warning")
    log_audit("a2", "u1", severity="info")
    r = admin_client.get("/v1/audit", params={"severity": "warning"})
    body = r.json()
    assert len(body) == 1
    assert body[0]["severity"] == "warning"


def test_list_entries_filtered_by_actor(admin_client: Any) -> None:
    log_audit("a1", "alice")
    log_audit("a2", "bob")
    r = admin_client.get("/v1/audit", params={"actor": "alice"})
    body = r.json()
    assert len(body) == 1
    assert body[0]["actor"] == "alice"


def test_list_entries_combined_filters_intersect(admin_client: Any) -> None:
    log_audit("login", "alice", severity="info")
    log_audit("login", "bob", severity="info")
    log_audit("login", "alice", severity="warning")
    r = admin_client.get(
        "/v1/audit", params={"action": "login", "actor": "alice", "severity": "warning"}
    )
    body = r.json()
    assert len(body) == 1
    assert body[0]["severity"] == "warning"
    assert body[0]["actor"] == "alice"


def test_list_entries_filter_matching_nothing_returns_empty(admin_client: Any) -> None:
    log_audit("login", "alice")
    r = admin_client.get("/v1/audit", params={"action": "no-such-action"})
    assert r.json() == []


# --------------------------------------------------------------------------- #
# GET /{id}
# --------------------------------------------------------------------------- #


def test_get_entry_found(admin_client: Any) -> None:
    log_audit("login", "alice")
    (eid,) = stores.audit_log.keys()
    r = admin_client.get(f"/v1/audit/{eid}")
    assert r.status_code == 200
    assert r.json()["id"] == eid


def test_get_entry_missing_404(admin_client: Any) -> None:
    r = admin_client.get("/v1/audit/missing")
    assert r.status_code == 404
    assert r.json()["detail"] == "audit entry not found"


# --------------------------------------------------------------------------- #
# POST "" — create
# --------------------------------------------------------------------------- #


def test_create_entry_defaults(admin_client: Any) -> None:
    r = admin_client.post("/v1/audit", json={"action": "manual", "actor": "tester"})
    assert r.status_code == 201
    body = r.json()
    assert body["action"] == "manual"
    assert body["actor"] == "tester"
    assert body["severity"] == "info"
    assert body["target"] is None
    assert body["detail"] == {}
    assert body["id"] in stores.audit_log


def test_create_entry_with_all_fields(admin_client: Any) -> None:
    r = admin_client.post(
        "/v1/audit",
        json={
            "action": "manual",
            "actor": "tester",
            "target": "thing-1",
            "detail": {"x": 1},
            "severity": "critical",
        },
    )
    body = r.json()
    assert body["target"] == "thing-1"
    assert body["detail"] == {"x": 1}
    assert body["severity"] == "critical"


def test_create_entry_then_filterable_by_action(admin_client: Any) -> None:
    admin_client.post("/v1/audit", json={"action": "manual_create", "actor": "tester"})
    r = admin_client.get("/v1/audit", params={"action": "manual_create"})
    assert len(r.json()) == 1


# --------------------------------------------------------------------------- #
# Non-dict entries (model instances) — the getattr() fallback branch in
# _field(). Production code always stores plain dicts (see module
# docstring), but the helper tolerates non-dict store contents too.
# --------------------------------------------------------------------------- #


def test_list_entries_filter_tolerates_non_dict_entries(admin_client: Any) -> None:
    from routes.audit import AuditEntry, _now

    eid = "model-instance-1"
    stores.audit_log[eid] = AuditEntry(
        id=eid, action="model_action", actor="model_actor", created_at=_now()
    )
    r = admin_client.get("/v1/audit", params={"action": "model_action"})
    body = r.json()
    assert len(body) == 1
    assert body[0]["id"] == eid
