"""The #102 authority cutover as the Conductor UI sees it.

Two acceptance surfaces live here:

- the authority flip is machine-readable: every list/detail payload carries
  the current authority statement, and after the recorded cutover
  (``quality/backlog-authority.json`` says ``db``) ``ui_authoritative``
  reads true — before it, false. A missing or unreadable marker never flips
  authority on;
- the backlog surface works against the database: with Conductor's SQLite
  persistence configured, create/edit through the HTTP surface survives a
  restart (a fresh store over the same database), and a stale-version edit
  is still refused with 409, not merged.
"""

from __future__ import annotations

import json

import pytest
import stores


@pytest.fixture(autouse=True)
def _clean_backlog():
    for key in list(stores.backlog_items.keys()):
        stores.backlog_items.pop(key, None)
    yield
    for key in list(stores.backlog_items.keys()):
        stores.backlog_items.pop(key, None)


@pytest.fixture
def marker_file(tmp_path, monkeypatch):
    """A temp authority marker the service reads via the env override."""
    path = tmp_path / "backlog-authority.json"

    def write(authority: str, revision: int) -> str:
        path.write_text(
            json.dumps({"authority": authority, "revision": revision, "export_sha256": None})
        )
        return str(path)

    monkeypatch.setenv("MAISTRO_BACKLOG_AUTHORITY_FILE", str(path))
    return write


def _create_item(client, title: str = "Cutover probe") -> dict:
    r = client.post("/v1/backlog", json={"title": title, "source": "user request"})
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------------------
# The authority statement in the payloads
# ---------------------------------------------------------------------------


def test_pre_cutover_the_ui_reports_itself_non_authoritative(authed_client, marker_file) -> None:
    marker_file("markdown", 0)
    item = _create_item(authed_client)
    listed = authed_client.get("/v1/backlog").json()["authority"]
    detail = authed_client.get(f"/v1/backlog/{item['id']}").json()["authority"]
    for statement in (listed, detail):
        assert statement["ui_authoritative"] is False
        assert statement["authority"] == "markdown"
        assert statement["cutover_issue"] == 102


def test_after_cutover_the_payload_flips_machine_readably(authed_client, marker_file) -> None:
    marker_file("db", 3)
    item = _create_item(authed_client)
    listed = authed_client.get("/v1/backlog").json()["authority"]
    detail = authed_client.get(f"/v1/backlog/{item['id']}").json()["authority"]
    for statement in (listed, detail):
        assert statement["ui_authoritative"] is True
        assert statement["authority"] == "db"
        assert statement["authority_revision"] == 3


def test_an_unreadable_marker_never_flips_authority_on(
    authed_client, tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("MAISTRO_BACKLOG_AUTHORITY_FILE", str(tmp_path / "absent.json"))
    item = _create_item(authed_client)
    statement = authed_client.get(f"/v1/backlog/{item['id']}").json()["authority"]
    assert statement["ui_authoritative"] is False
    assert statement["authority"] == "markdown"


# ---------------------------------------------------------------------------
# Create/edit/read against the database, durable across a restart
# ---------------------------------------------------------------------------


def test_backlog_surface_survives_a_restart_over_sqlite(
    authed_client, admin_client, tmp_path
) -> None:
    from maistro.state import PersistedStore, State

    state = State(db_path=str(tmp_path / "conductor-state.db"))
    try:
        persisted = PersistedStore(state)
        persisted.initialize()
        stores.configure_persistence(persisted)
        try:
            item = _create_item(admin_client, title="Durable board item")
            r = admin_client.patch(
                f"/v1/backlog/{item['id']}",
                json={"expected_version": 1, "changes": {"title": "Edited before restart"}},
            )
            assert r.status_code == 200, r.text

            # The restart: drop the process-local dict and reload the store
            # from the database a fresh boot would read.
            stores.backlog_items._data = {}
            stores.backlog_items.initialize()

            reread = admin_client.get(f"/v1/backlog/{item['id']}")
            assert reread.status_code == 200
            assert reread.json()["item"]["title"] == "Edited before restart"
            assert reread.json()["item"]["version"] == 2

            # And the concurrent-editor contract still holds on the reloaded
            # state: the pre-restart version is stale, refused with 409.
            stale = admin_client.patch(
                f"/v1/backlog/{item['id']}",
                json={"expected_version": 1, "changes": {"title": "stale"}},
            )
            assert stale.status_code == 409
        finally:
            stores.configure_persistence(None)
    finally:
        state.close()
