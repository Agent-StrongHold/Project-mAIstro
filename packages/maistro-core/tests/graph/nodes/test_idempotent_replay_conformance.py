"""Idempotency conformance for every node declared IDEMPOTENT (#1194).

``ReplaySemantics.IDEMPOTENT`` is a contract, not a palette label: a node
declaring it claims that executing it repeatedly against the same logical
input/state leaves **one** resulting side effect. This suite executes each
registered IDEMPOTENT kind twice against the same logical Run/node context
(the second reach carrying a different physical ``node_run_id``, the shape a
lease-loss retry produces) and observes the effect channel directly.

The sweep test at the bottom ties the registry to the case table: a kind that
declares IDEMPOTENT without a conformance case here fails the suite, so the
claim cannot silently grow ahead of its proof.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from maistro.graph.nodes import get_node, list_kinds
from maistro.graph.nodes.base import NodeContext, ReplaySemantics
from maistro.graph.types import GraphBlackboard


def _ctx(*, node_run_id: str) -> NodeContext:
    return NodeContext(
        run_id="run-1",
        dag_id="dag-1",
        node_id="node-1",
        node_run_id=node_run_id,
        blackboard=GraphBlackboard(task_objective="conformance", workspace=""),
    )


def _idempotent_kinds() -> set[str]:
    """The kinds the registry currently declares IDEMPOTENT."""
    return {
        kind
        for kind in list_kinds()
        if get_node(kind).replay_semantics is ReplaySemantics.IDEMPOTENT
    }


# --- per-kind cases ---------------------------------------------------------
#
# Each case executes one IDEMPOTENT kind twice against the same logical
# input/state and returns what it observed, so the shared assertions below can
# check the contract on the node's own effect channel.


def _patch_read_only_transport(
    monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any], seen: dict[str, Any]
) -> None:
    """Patch httpx so a polled system returns ``payload`` and records methods.

    Every mutating verb records a failing observation: a poll's idempotency
    claim is exactly that its replay never mutates the remote system.
    """

    class _Resp:
        status_code = 200

        def json(self) -> Any:
            return payload

    class _Client:
        #: The shared-client pool reads this on a cache hit.
        is_closed = False

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *args: Any) -> None:
            pass

        async def get(self, url: str, **kwargs: Any) -> _Resp:
            seen.setdefault("methods", []).append("GET")
            seen["url"] = url
            return _Resp()

    for verb in ("post", "patch", "put", "delete"):

        def _make_mutate(verb_name: str) -> Any:

            async def _mutate(url: str, **kwargs: Any) -> _Resp:
                seen.setdefault("methods", []).append(verb_name.upper())
                raise AssertionError(f"idempotent replay issued a mutating {verb_name} to {url}")

            return _mutate

        setattr(_Client, verb, _make_mutate(verb))

    monkeypatch.setattr(httpx, "AsyncClient", _Client)


def _jira_issue_payload() -> dict[str, Any]:
    return {
        "issues": [
            {
                "key": "P-100",
                "fields": {
                    "summary": "Migrate auth to MyID",
                    "status": {"name": "In Progress"},
                    "updated": "2026-05-22T08:00:00.000+0000",
                    "issuetype": {"name": "Epic"},
                },
            }
        ]
    }


def _subtask_payload(all_done: bool = True) -> dict[str, Any]:
    status = "Done" if all_done else "Open"
    return {
        "fields": {
            "subtasks": [
                {"key": "P-100-1", "fields": {"summary": "s1", "status": {"name": status}}},
                {"key": "P-100-2", "fields": {"summary": "s2", "status": {"name": status}}},
            ]
        }
    }


_JQL_INPUTS: dict[str, Any] = {
    "base_url": "https://jira.example.com",
    "jql": "assignee=currentUser() AND resolution=Unresolved",
    "pat": "pat-token",
}

_SUBTASK_INPUTS: dict[str, Any] = {
    "base_url": "https://jira.example.com",
    "parent_key": "P-100",
    "pat": "pat-token",
}

_AIRTABLE_INPUTS: dict[str, Any] = {
    "pat": "pat-token",
    "base_id": "appXYZ",
    "table": "Initiatives",
    "since_iso": "2026-05-21T00:00:00Z",
}


async def _run_poll_kind(
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    inputs: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    seen: dict[str, Any] = {}
    _patch_read_only_transport(monkeypatch, payload, seen)
    node = get_node(kind)()
    first = await node.run(inputs, _ctx(node_run_id="node-run-1"))
    second = await node.run(inputs, _ctx(node_run_id="node-run-retry-2"))
    return {"first": first, "second": second, "http": seen}


# --- the conformance cases --------------------------------------------------


@pytest.mark.asyncio
async def test_dashboard_append_section_replay_leaves_one_section() -> None:
    """The one durable-state IDEMPOTENT kind upserts; replay appends nothing."""
    kind = "dashboard.append_section"
    first_ctx = _ctx(node_run_id="node-run-1")
    bb = first_ctx.blackboard
    assert isinstance(bb, GraphBlackboard)
    # Same logical context, new physical visit: exactly what a retry gets.
    retry_ctx = first_ctx.model_copy(update={"node_run_id": "node-run-retry-2"})
    node = get_node(kind)()
    inputs = {"dashboard_id": "daily-status", "section_title": "Jira", "markdown": "ready"}

    first = await node.run(inputs, first_ctx)
    second = await node.run(inputs, retry_ctx)

    assert first.success and second.success
    assert first.output.section_id == second.output.section_id
    sections = bb.metadata["dashboard:daily-status"]["sections"]
    assert len(sections) == 1, "replay appended a duplicate section"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "inputs", "payload"),
    [
        ("jira.poll", _JQL_INPUTS, _jira_issue_payload()),
        ("airtable.poll", _AIRTABLE_INPUTS, {"records": []}),
        ("jira.wait_for_subtasks", _SUBTASK_INPUTS, _subtask_payload(all_done=True)),
    ],
)
async def test_poll_replay_is_read_only_and_stable(
    monkeypatch: pytest.MonkeyPatch, kind: str, inputs: dict[str, Any], payload: dict[str, Any]
) -> None:
    observed = await _run_poll_kind(monkeypatch, kind, inputs, payload)
    assert observed["first"].success and observed["second"].success
    # A poll's effect channel is the outbound transport: replaying it must
    # never mutate the remote system, whatever else happens.
    methods = observed["http"]["methods"]
    assert methods, "the node never reached its declared external system"
    assert all(method == "GET" for method in methods), (
        f"{kind} replay issued a mutating transport call: {methods}"
    )
    assert observed["second"].output == observed["first"].output


# --- the registry sweep -----------------------------------------------------


def test_every_idempotent_kind_has_a_conformance_case() -> None:
    """Declaring IDEMPOTENT is a promise; this is where the promise is kept.

    The case table above must cover every registered IDEMPOTENT kind. A new
    kind that declares the semantics without landing here fails this test --
    the catalog flag can no longer outrun the enforceable contract.
    """
    covered = {
        "dashboard.append_section",
        "jira.poll",
        "airtable.poll",
        "jira.wait_for_subtasks",
    }
    assert _idempotent_kinds() == covered, (
        "IDEMPOTENT declarations and conformance cases disagree; "
        "add or remove a case in test_idempotent_replay_conformance.py"
    )
