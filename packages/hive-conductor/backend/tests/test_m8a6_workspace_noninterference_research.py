"""M8-A6 research harness: Workspace noninterference across product state (#886).

Issue #886 (epic #880) hypothesizes that cross-Workspace isolation is better
tested as a global noninterference property than as scattered endpoint
assertions: every operation scoped exclusively to Workspace A must leave the
observable state of untouched Workspace B unchanged, modulo explicitly
documented global state.

This module is the bounded prototype the issue's deliverable names:

- two real Workspaces owned by two fresh principals, created through the
  product HTTP API, with the canonical `maistro.workspaces` authority and its
  Root Project pairing underneath;
- a normalized observable projection of the untouched party, taken through the
  same product APIs the untouched principal can reach plus the persistence
  stores underneath (canonical identity, memberships, Root Project, Hive
  presentation);
- a seeded, deterministic, mixed operation vocabulary executed against
  Workspace A only -- workspace archive/recover, membership add/promote/
  remove, schedule and Agent create/update/delete, memory put/delete, chat
  session create/delete, persona feedback, A-side queries, and a store
  re-initialization ("restart") -- with
  `observable(B)_after == observable(B)_before` asserted after every step;
- sensitivity controls proving the oracle can fail (a B-side write changes the
  projection; A-side writes change A's own view), i.e. the property is not
  vacuous;
- the explicitly documented global-state exceptions, pinned as behavior:
  persona feedback aggregates per persona template across every workspace
  instantiating it (services/persona_feedback.py), and the chat-session
  listing lazily seeds the reader's own starter session on first read.

Findings and the research disposition live in
docs/research/886-workspace-noninterference.md.

Out of scope for the deterministic prototype (recorded as limitations in the
research note): DAG-run execution/invocation legs need the configured engine
container, and cross-service task delegation needs the maistro-server task
backend; neither runs in this in-memory, no-credentials suite. The covered
vocabulary is exactly what the issue asks for "where supported" without them.
"""

from __future__ import annotations

import asyncio
import contextlib
import random
from typing import Any

import pytest

pytestmark = [pytest.mark.contract("behavioral"), pytest.mark.scope("property")]

#: Elevation capabilities. Alice acts on Workspace A across every gated
#: surface the vocabulary touches; Bob needs only the B-side product writes
#: the sensitivity control performs. POST /v1/workspaces is deliberately
#: ungated (an ordinary authenticated action), so neither needs
#: workspaces.write to create their own Workspace.
_A_PERMS = ["agents.write", "agents.delete", "schedules.write", "workspaces.write"]
_B_PERMS = ["agents.write", "schedules.write"]

_ALICE = "m8a6-alice"
_BOB = "m8a6-bob"

#: Distinct personas on purpose: B's observable state must not depend on A's
#: persona-level surfaces. Same-persona feedback aggregation is a documented
#: exception and gets its own pinned behavior test below.
_A_PERSONA = "pm_fleet"
_B_PERSONA = "content_creator"

_SCHEDULE_BODY = {
    "name": "m8a6-nightly",
    "cron_expression": "0 9 * * *",
    "mission_template_id": "tpl-m8a6",
}

#: Length of the seeded mixed sequence. Long enough that a fixed seed must
#: exercise every vocabulary entry at least once (asserted below), short
#: enough for a routine suite run.
_SEQUENCE_LENGTH = 64


class Harness:
    """One A/B party pair plus the registries the operation vocabulary uses."""

    def __init__(self, alice: Any, bob: Any, ws_a: Any, ws_b: Any) -> None:
        self.alice = alice
        self.bob = bob
        self.ws_a = ws_a
        self.ws_b = ws_b
        self.rng = random.Random(3)  # fixed: covers all 19 ops in 64 draws
        self.schedule_ids: list[str] = []
        self.agent_ids: list[str] = []
        self.memory_ids: list[str] = []
        self.chat_ids: list[str] = []
        self.feedback_ids: list[str] = []
        #: Members currently added to A (removed ones are popped).
        self.members: list[str] = []
        #: Whether A is archived (active=False) right now; an archived
        #: Workspace refuses DAG-scoped writes, so the schedule ops restore
        #: that precondition first.
        self.ws_a_archived = False
        #: Successful A-side mutations performed (anti-vacuous ledger).
        self.mutations = 0
        #: Read-only A-side queries performed.
        self.queries = 0
        self.ws_a_deleted = False


# ---------------------------------------------------------------------------
# Observation: the normalized observable projection of untouched B
# ---------------------------------------------------------------------------


def _sorted_by(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: str(row.get(key, "")))


def _store_level_projection(workspace_id: str) -> dict[str, Any]:
    """The persistence-store half of B's observable state.

    Read through the same authority the product reads: the canonical
    Workspace record, its memberships, the paired Root Project, and the Hive
    presentation row. Timestamps are included deliberately: an A-side
    operation that merely *touches* B's rows (a spurious `updated_at` bump)
    is a real noninterference defect this projection must catch.
    """
    from services.workspace_authority import canonical_store_for_tests, presentation_store

    async def _read() -> dict[str, Any]:
        store = canonical_store_for_tests()
        canonical = await store.get(workspace_id)
        assert canonical is not None, f"canonical Workspace {workspace_id} vanished"
        memberships = await store.list_memberships(workspace_id)
        root = await store.project_store.root_for_workspace(workspace_id)
        presentation = presentation_store().get(workspace_id)
        return {
            "canonical": canonical.model_dump(mode="json"),
            "memberships": sorted(
                (m.model_dump(mode="json") for m in memberships),
                key=lambda m: m["user_id"],
            ),
            "root_project_id": root.project_id,
            "presentation": (
                presentation.model_dump(mode="json") if presentation is not None else None
            ),
        }

    return asyncio.run(_read())


def _observe(h: Harness) -> dict[str, Any]:
    """Everything the untouched B principal can observe, normalized.

    HTTP views are taken through Bob's authenticated session, so the
    projection is exactly what the product would show B's owner. Every read
    is asserted successful: a projection read that silently degraded to 403
    would freeze a constant oracle and make the property vacuous.
    """
    bob = h.bob
    ws_b = h.ws_b.id

    listed = bob.get("/v1/workspaces")
    detail = bob.get(f"/v1/workspaces/{ws_b}")
    schedules = bob.get("/v1/schedules")
    agents = bob.get(f"/v1/agents?workspace_id={ws_b}")
    entries = bob.get("/v1/memory/entries")
    namespaces = bob.get("/v1/memory/namespaces")
    chats = bob.get("/v1/chat/sessions")
    for response in (listed, detail, schedules, agents, entries, namespaces, chats):
        assert response.status_code == 200, (
            f"projection read degraded: {response.request.url} -> "
            f"{response.status_code} {response.text}"
        )

    return {
        # The workspace universe as B sees it: A must be absent from it.
        "workspace_list_ids": sorted(w["id"] for w in listed.json()),
        "workspace_detail": detail.json(),
        "schedules": _sorted_by(schedules.json(), "id"),
        "agents": _sorted_by(agents.json(), "id"),
        "memory_entries": _sorted_by(entries.json(), "id"),
        "memory_namespaces": sorted(namespaces.json(), key=lambda n: n["name"]),
        "chat_sessions": _sorted_by(chats.json(), "id"),
        "store_level": _store_level_projection(ws_b),
    }


def _assert_untouched(before: dict[str, Any], after: dict[str, Any], step: str) -> None:
    """The property: `observable(B)_after == observable(B)_before`."""
    if before == after:
        return
    changed = [key for key in before if before[key] != after.get(key)]
    raise AssertionError(
        f"noninterference violated after {step!r}: observable(B) changed "
        f"in {changed}; a Workspace-A-scoped operation leaked into "
        f"Workspace B's observable state"
    )


# ---------------------------------------------------------------------------
# The operation vocabulary -- every entry is scoped exclusively to A
# ---------------------------------------------------------------------------


def _op_archive_workspace_a(h: Harness) -> None:
    r = h.alice.patch(f"/v1/workspaces/{h.ws_a.id}", json={"active": False})
    assert r.status_code == 200, r.text
    assert r.json()["active"] is False
    h.ws_a_archived = True
    h.mutations += 1


def _op_recover_workspace_a(h: Harness) -> None:
    r = h.alice.patch(f"/v1/workspaces/{h.ws_a.id}", json={"active": True})
    assert r.status_code == 200, r.text
    assert r.json()["active"] is True
    h.ws_a_archived = False
    h.mutations += 1


def _ensure_a_active(h: Harness) -> None:
    """An archived Workspace refuses DAG-scoped writes by design; recover it
    first so the scheduled op still performs its own mutation."""
    if h.ws_a_archived:
        _op_recover_workspace_a(h)


def _op_set_tool_bindings_a(h: Harness) -> None:
    r = h.alice.put(
        f"/v1/workspaces/{h.ws_a.id}/tool-bindings",
        json={"bindings": [{"agent_id": f"agent-{h.mutations}", "tools": ["search"]}]},
    )
    assert r.status_code == 200, r.text
    h.mutations += 1


def _op_add_member_a(h: Harness) -> None:
    r = h.alice.post(
        f"/v1/workspaces/{h.ws_a.id}/members", json={"user_id": "m8a6-carol", "role": "viewer"}
    )
    assert r.status_code == 200, r.text
    if "m8a6-carol" not in h.members:
        h.members.append("m8a6-carol")
    h.mutations += 1


def _op_promote_member_a(h: Harness) -> None:
    if "m8a6-carol" not in h.members:
        _op_add_member_a(h)
        return
    r = h.alice.post(
        f"/v1/workspaces/{h.ws_a.id}/members", json={"user_id": "m8a6-carol", "role": "editor"}
    )
    assert r.status_code == 200, r.text
    h.mutations += 1


def _op_remove_member_a(h: Harness) -> None:
    if "m8a6-carol" not in h.members:
        _op_add_member_a(h)
    r = h.alice.delete(f"/v1/workspaces/{h.ws_a.id}/members/m8a6-carol")
    assert r.status_code == 200, r.text
    if "m8a6-carol" in h.members:
        h.members.remove("m8a6-carol")
    h.mutations += 1


def _create_schedule_a(h: Harness) -> str:
    _ensure_a_active(h)
    r = h.alice.post("/v1/schedules", json={**_SCHEDULE_BODY, "workspace_id": h.ws_a.id})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["workspace_id"] == h.ws_a.id
    h.schedule_ids.append(body["id"])
    h.mutations += 1
    return body["id"]


def _op_create_schedule_a(h: Harness) -> None:
    _create_schedule_a(h)


def _op_update_schedule_a(h: Harness) -> None:
    if not h.schedule_ids:
        _create_schedule_a(h)
        return
    sid = h.rng.choice(h.schedule_ids)
    r = h.alice.put(f"/v1/schedules/{sid}", json={"name": f"m8a6-renamed-{h.mutations}"})
    assert r.status_code == 200, r.text
    h.mutations += 1


def _op_delete_schedule_a(h: Harness) -> None:
    if not h.schedule_ids:
        _create_schedule_a(h)
    sid = h.schedule_ids.pop()
    r = h.alice.delete(f"/v1/schedules/{sid}")
    assert r.status_code == 204, r.text
    h.mutations += 1


def _create_agent_a(h: Harness) -> str:
    r = h.alice.post(
        "/v1/agents",
        json={
            "name": f"m8a6-agent-{h.mutations}",
            "description": "A-scoped harness agent",
            "workspace_id": h.ws_a.id,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["workspace_id"] == h.ws_a.id
    h.agent_ids.append(body["id"])
    h.mutations += 1
    return body["id"]


def _op_create_agent_a(h: Harness) -> None:
    _create_agent_a(h)


def _op_update_agent_a(h: Harness) -> None:
    if not h.agent_ids:
        _create_agent_a(h)
        return
    aid = h.rng.choice(h.agent_ids)
    r = h.alice.put(f"/v1/agents/{aid}", json={"description": f"updated-{h.mutations}"})
    assert r.status_code == 200, r.text
    h.mutations += 1


def _op_delete_agent_a(h: Harness) -> None:
    if not h.agent_ids:
        _create_agent_a(h)
    aid = h.agent_ids.pop()
    r = h.alice.delete(f"/v1/agents/{aid}")
    assert r.status_code == 204, r.text
    h.mutations += 1


def _put_memory_a(h: Harness) -> str:
    r = h.alice.post(
        "/v1/memory/entries",
        json={"key": f"m8a6-{h.mutations}", "value": f"value-{h.mutations}", "namespace": "m8a6"},
    )
    assert r.status_code == 200, r.text
    eid = r.json()["id"]
    h.memory_ids.append(eid)
    h.mutations += 1
    return eid


def _op_put_memory_a(h: Harness) -> None:
    _put_memory_a(h)


def _op_delete_memory_a(h: Harness) -> None:
    if not h.memory_ids:
        _put_memory_a(h)
    eid = h.memory_ids.pop()
    r = h.alice.delete(f"/v1/memory/entries/{eid}")
    assert r.status_code == 204, r.text
    h.mutations += 1


def _op_create_chat_session_a(h: Harness) -> None:
    r = h.alice.post("/v1/chat/sessions", json={"title": f"m8a6-session-{h.mutations}"})
    assert r.status_code == 200, r.text
    h.chat_ids.append(r.json()["id"])
    h.mutations += 1


def _op_delete_chat_session_a(h: Harness) -> None:
    if not h.chat_ids:
        _op_create_chat_session_a(h)
    cid = h.chat_ids.pop()
    r = h.alice.delete(f"/v1/chat/sessions/{cid}")
    assert r.status_code == 204, r.text
    h.mutations += 1


def _op_submit_feedback_a(h: Harness) -> None:
    """A-scoped persona feedback.

    Workspace A instantiates `pm_fleet`; B instantiates `content_creator`.
    The aggregation exception (per-persona, cross-workspace) is pinned by
    `test_persona_feedback_aggregates_across_workspaces_of_one_persona`.
    """
    r = h.alice.post(
        f"/v1/workspaces/{h.ws_a.id}/feedback",
        json={"thumb": "up", "comment": f"m8a6-feedback-{h.mutations}"},
    )
    assert r.status_code == 201, r.text
    h.feedback_ids.append(r.json()["id"])
    h.mutations += 1


def _op_query_as_a(h: Harness) -> None:
    """Read-only A-side traffic: queries must not alter the untouched party."""
    for path in (
        "/v1/workspaces",
        f"/v1/workspaces/{h.ws_a.id}",
        "/v1/workspaces/persona-templates",
        f"/v1/workspaces/persona-templates/{_A_PERSONA}/agents",
        "/v1/schedules",
        f"/v1/agents?workspace_id={h.ws_a.id}",
        "/v1/memory/entries",
        "/v1/memory/namespaces",
        "/v1/chat/sessions",
    ):
        r = h.alice.get(path)
        assert r.status_code == 200, f"{path} -> {r.status_code} {r.text}"
    h.queries += 1


def _op_restart_stores(h: Harness) -> None:
    """A failure/restart sequence where the in-memory suite supports one.

    `initialize_stores()` reloads every store from the persistence backend
    and re-runs seed-if-empty plus the legacy-claims migration. With no
    database configured this exercises the idempotent-recovery path; the
    durable-reload leg needs the SQLite-backed suite (research limitation).
    Global side effects it may legitimately have (claim migration, catalog
    re-merge) are covered by the global-state exceptions in the research
    note; none of them are part of B's projection.
    """
    import stores

    stores.initialize_stores()
    h.mutations += 1


def _op_delete_workspace_a(h: Harness) -> None:
    """The destructive corner: A's deletion must not cascade into B."""
    _ensure_a_active(h)
    r = h.alice.delete(f"/v1/workspaces/{h.ws_a.id}")
    assert r.status_code == 204, r.text
    h.ws_a_deleted = True
    h.mutations += 1


_VOCABULARY = [
    _op_archive_workspace_a,
    _op_recover_workspace_a,
    _op_set_tool_bindings_a,
    _op_add_member_a,
    _op_promote_member_a,
    _op_remove_member_a,
    _op_create_schedule_a,
    _op_update_schedule_a,
    _op_delete_schedule_a,
    _op_create_agent_a,
    _op_update_agent_a,
    _op_delete_agent_a,
    _op_put_memory_a,
    _op_delete_memory_a,
    _op_create_chat_session_a,
    _op_delete_chat_session_a,
    _op_submit_feedback_a,
    _op_query_as_a,
    _op_restart_stores,
]

_FAMILY_CASES = [
    ("archive_recover", [_op_archive_workspace_a, _op_recover_workspace_a]),
    (
        "members",
        [_op_add_member_a, _op_promote_member_a, _op_remove_member_a],
    ),
    (
        "schedules",
        [_op_create_schedule_a, _op_update_schedule_a, _op_delete_schedule_a],
    ),
    ("agents", [_op_create_agent_a, _op_update_agent_a, _op_delete_agent_a]),
    ("memory", [_op_put_memory_a, _op_delete_memory_a]),
    ("chat_sessions", [_op_create_chat_session_a, _op_delete_chat_session_a]),
    ("feedback", [_op_submit_feedback_a]),
    ("restart", [_op_restart_stores]),
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _mint_principal(app: Any, username: str, permissions: list[str] | None = None) -> Any:
    """A fresh authenticated principal backed by a real user row.

    Elevated with ``permissions`` when given; read-only surfaces need no
    elevation, and a permissions=[] mint is exactly the daily account.
    """
    import stores
    from fastapi.testclient import TestClient

    stores.users[username] = stores.users["user"].model_copy(
        update={"id": username, "username": username, "permissions": list(permissions or [])}
    )
    client = TestClient(app)
    login = client.post("/v1/auth/login", json={"username": username, "password": "testpass"})
    assert login.status_code == 200, login.text
    if permissions:
        elevated = client.post(
            "/v1/auth/elevate",
            json={
                "password": "testpass",
                "permissions": list(permissions),
                "task_id": "m8a6-noninterference",
            },
        )
        assert elevated.status_code == 200, elevated.text
    return client


@pytest.fixture
def parties():
    """Workspace A (alice, pm_fleet) and untouched Workspace B (bob)."""
    from main import app
    from models.workspace import Workspace

    alice = _mint_principal(app, _ALICE, _A_PERMS)
    bob = _mint_principal(app, _BOB, _B_PERMS)
    created_a = alice.post(
        "/v1/workspaces", json={"persona_template_id": _A_PERSONA, "name": "M8A6 Workspace A"}
    )
    created_b = bob.post(
        "/v1/workspaces", json={"persona_template_id": _B_PERSONA, "name": "M8A6 Workspace B"}
    )
    assert created_a.status_code == 201, created_a.text
    assert created_b.status_code == 201, created_b.text
    h = Harness(
        alice=alice,
        bob=bob,
        ws_a=Workspace(**created_a.json()),
        ws_b=Workspace(**created_b.json()),
    )

    # Warm the lazily-seeding readers (chat sessions seed per owner on first
    # read) so the baseline is taken after the warm-up, not perturbed by it.
    assert alice.get("/v1/chat/sessions").status_code == 200
    assert bob.get("/v1/chat/sessions").status_code == 200
    assert alice.get("/v1/memory/namespaces").status_code == 200
    assert bob.get("/v1/memory/namespaces").status_code == 200

    try:
        yield h
    finally:
        _cleanup(h)


def _cleanup(h: Harness) -> None:
    import stores
    from services.agent_materialization import delete_workspace_agents
    from services.workspace_authority import delete_workspace

    for sid in h.schedule_ids:
        stores.schedules.pop(sid, None)
    for aid in h.agent_ids:
        stores.agents.pop(aid, None)
    for eid in h.memory_ids:
        stores.memory_entries.pop(eid, None)
    for cid in h.chat_ids:
        stores.chat_sessions.pop(cid, None)
    for fid in h.feedback_ids:
        stores.persona_feedback.pop(fid, None)
    for ws in (h.ws_a, h.ws_b):
        with contextlib.suppress(Exception):
            asyncio.run(delete_workspace(ws.id))
        # The cascade the delete route performs for materialized personas.
        delete_workspace_agents(ws.id)
        stores.workspaces.pop(ws.id, None)
    stores.users.pop(_ALICE, None)
    stores.users.pop(_BOB, None)


# ---------------------------------------------------------------------------
# Baseline sanity
# ---------------------------------------------------------------------------


def test_parties_start_independent_and_b_projection_is_populated(parties) -> None:
    h = parties
    assert h.ws_a.id != h.ws_b.id

    observed = _observe(h)

    # B's projection is live, not a constant: the untouched party has real
    # observable state (canonical identity, persona agents, Root Project).
    assert observed["workspace_detail"]["id"] == h.ws_b.id
    assert observed["workspace_detail"]["persona_template_id"] == _B_PERSONA
    assert {a["workspace_id"] for a in observed["agents"]} == {h.ws_b.id}
    assert observed["agents"], "persona materialization gave B no agents"
    assert observed["store_level"]["canonical"]["workspace_id"] == h.ws_b.id
    assert observed["store_level"]["root_project_id"]
    assert observed["store_level"]["presentation"] is not None

    # A is invisible to B's principal: the untouched party cannot even name A.
    assert h.ws_a.id not in observed["workspace_list_ids"]
    foreign = h.bob.get(f"/v1/workspaces/{h.ws_a.id}")
    assert foreign.status_code == 404


# ---------------------------------------------------------------------------
# The property
# ---------------------------------------------------------------------------


def test_mixed_operation_sequence_preserves_untouched_workspace(parties) -> None:
    h = parties
    baseline = _observe(h)
    steps: list[str] = []

    for i in range(_SEQUENCE_LENGTH):
        op = h.rng.choice(_VOCABULARY)
        op(h)
        after = _observe(h)
        _assert_untouched(baseline, after, f"step {i}: {op.__name__}")
        steps.append(op.__name__)

    # Anti-vacuous guards: the sequence did real A-side work and exercised
    # every operation family, so "B never changed" is evidence, not idleness.
    exercised = set(steps)
    missing = {op.__name__ for op in _VOCABULARY} - exercised
    assert not missing, f"seeded sequence never exercised: {sorted(missing)}"
    assert h.mutations >= _SEQUENCE_LENGTH // 2, (
        f"only {h.mutations} of {len(steps)} steps mutated A-side state"
    )

    # The destructive corner, last: deleting A leaves B exactly as observed.
    _op_delete_workspace_a(h)
    _assert_untouched(baseline, _observe(h), "final: delete workspace A")
    gone = h.alice.get(f"/v1/workspaces/{h.ws_a.id}")
    assert gone.status_code == 404


@pytest.mark.parametrize(("family", "ops"), _FAMILY_CASES, ids=[case[0] for case in _FAMILY_CASES])
def test_operation_family_preserves_untouched_workspace(
    parties, family: str, ops: list[Any]
) -> None:
    """Per-family attribution: when the mixed sequence ever fails, this
    pinpoints which operation family introduced the leak."""
    h = parties
    baseline = _observe(h)
    for op in ops:
        op(h)
        _assert_untouched(baseline, _observe(h), f"{family}:{op.__name__}")
    assert h.mutations > 0, f"family {family} performed no successful A-side mutation"


def test_deleting_a_cascades_only_into_a(parties) -> None:
    h = parties
    # Give A and B durable product rows, then delete A.
    _create_schedule_a(h)
    bob_schedule = h.bob.post(
        "/v1/schedules", json={**_SCHEDULE_BODY, "workspace_id": h.ws_b.id}
    ).json()
    h.schedule_ids.append(bob_schedule["id"])  # teardown
    before = _observe(h)

    _op_delete_workspace_a(h)

    after = _observe(h)
    _assert_untouched(before, after, "delete workspace A")
    # B's records survive A's teardown, including the persona-agent cascade.
    assert before["agents"] == after["agents"]
    assert any(s["id"] == bob_schedule["id"] for s in after["schedules"])
    assert h.bob.get(f"/v1/workspaces/{h.ws_b.id}").status_code == 200
    # A is gone everywhere.
    assert asyncio.run(_canonical_get(h.ws_a.id)) is None, (
        "A's canonical record outlived its deletion"
    )


async def _canonical_get(workspace_id: str) -> Any:
    from services.workspace_authority import canonical_store_for_tests

    return await canonical_store_for_tests().get(workspace_id)


# ---------------------------------------------------------------------------
# Sensitivity controls: the oracle can fail, so passing means something
# ---------------------------------------------------------------------------


def test_oracle_sensitivity_b_side_write_changes_the_projection(parties) -> None:
    h = parties
    baseline = _observe(h)

    r = h.bob.post("/v1/schedules", json={**_SCHEDULE_BODY, "workspace_id": h.ws_b.id})
    assert r.status_code == 201, r.text
    h.schedule_ids.append(r.json()["id"])  # teardown

    after = _observe(h)
    assert after != baseline, "oracle is blind: a real B-side write changed nothing"
    assert len(after["schedules"]) == len(baseline["schedules"]) + 1


def test_a_operations_change_a_projection(parties) -> None:
    h = parties
    sid = _create_schedule_a(h)

    listed = h.alice.get("/v1/schedules").json()
    assert any(s["id"] == sid for s in listed), "A-side write never became visible to A"

    # ...and B's principal still sees none of A's rows.
    observed = _observe(h)
    assert all(s["workspace_id"] != h.ws_a.id for s in observed["schedules"])
    assert all(a["workspace_id"] != h.ws_a.id for a in observed["agents"])


# ---------------------------------------------------------------------------
# Documented global-state exceptions, pinned as behavior
# ---------------------------------------------------------------------------


def test_persona_feedback_aggregates_across_workspaces_of_one_persona(parties) -> None:
    """The deliberate exception: `summarize()` matches by persona template,
    not workspace, so feedback left in one Workspace is aggregated into every
    other Workspace instantiating the same persona. The persona-wide summary
    is an admin-gated read, so a non-admin untouched party cannot observe it
    through the API -- but the store-level aggregation is the documented
    cross-workspace surface, pinned here through the real implementation. A
    naive projection that treated feedback rows as workspace-private would
    false-positive; the harness avoids that by giving A and B distinct
    personas and excepting this surface."""
    h = parties
    import stores
    from services.persona_feedback import summarize

    twin_a = h.alice.post(
        "/v1/workspaces", json={"persona_template_id": _B_PERSONA, "name": "M8A6 twin A"}
    ).json()
    try:
        r = h.alice.post(
            f"/v1/workspaces/{twin_a['id']}/feedback",
            json={"thumb": "down", "comment": "m8a6 exception probe"},
        )
        assert r.status_code == 201, r.text
        probe_id = r.json()["id"]
        h.feedback_ids.append(probe_id)

        summary = summarize(_B_PERSONA, list(stores.persona_feedback.values()))
        assert summary.thumbs_down >= 1
        assert any(
            f.workspace_id == twin_a["id"] and f.comment == "m8a6 exception probe"
            for f in summary.recent
        ), "expected the documented cross-workspace persona-feedback aggregation"
    finally:
        assert h.alice.delete(f"/v1/workspaces/{twin_a['id']}").status_code == 204


def test_chat_listing_seeds_reader_state_on_first_read(parties) -> None:
    """The false-positive source the harness must warm up around: the first
    chat-session listing for a principal seeds their starter session, so a
    naive first-read baseline changes between baseline capture and the next
    read without any A-side operation running."""
    import stores
    from main import app

    username = "m8a6-dave"
    dave = _mint_principal(app, username)
    try:
        first = dave.get("/v1/chat/sessions")
        assert first.status_code == 200
        seeded = {s["id"] for s in first.json()}
        assert f"chat-seed-{username}" in stores.chat_sessions, (
            "expected the lazy starter-session seed on first read"
        )
        assert f"chat-seed-{username}" in seeded
        second = dave.get("/v1/chat/sessions")
        assert second.status_code == 200
        assert {s["id"] for s in second.json()} == seeded, "warm state must be stable"
    finally:
        stores.users.pop(username, None)
        stores.chat_sessions.pop(f"chat-seed-{username}", None)
