"""Fail-closed verdicts for the human HITL nodes (#329 / ADR-090726-9a4e).

Every verdict node used to default a *missing* `verdict` key to "approved" —
`resumed.get("verdict", "approved")` — so an answer that never stated a
verdict counted as the strongest one. A key nobody asserted must never act as
an approval: the nodes now treat a missing, empty, or non-string verdict as
*pending* and re-pause awaiting an explicit verdict, rather than approving.

The pause that comes back is the same first-reach pause (same reason, same
payload), so the run stays PAUSED and a corrected answer can still settle it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from maistro.graph.nodes import NodeContext, get_node

#: The durable deadline `answer_record` stamps onto a resumed answer under
#: `_pause` (see `graph/durable_runs/stores.py::answer_record`), for the
#: #1097 preserved-deadline tests below.
_ORIGINAL_DEADLINE = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def _ctx(node_id: str, answers: dict[str, Any]) -> NodeContext:
    ctx = NodeContext(
        run_id="r1",
        dag_id="d1",
        node_id=node_id,
        user_id="u1",
        project_id="p1",
    )
    ctx.metadata["hitl_answers"] = {node_id: answers}
    return ctx


# --- human.approve_draft ------------------------------------------------------


@pytest.mark.ac("ADR-090726-9a4e/AC-2")
async def test_approve_draft_missing_verdict_is_pending_not_approved() -> None:
    """The core fail-closed case: no verdict key, no approval, node re-pauses."""
    node = get_node("human.approve_draft")()
    result = await node.run({"draft": {"ticket": "PROJ-1"}}, _ctx("n", {"reviewer_note": ""}))

    assert result.status == "paused"
    assert result.resume_at is not None
    assert result.metadata["paused_reason"] == "awaiting_human_approval"
    assert result.output is None  # nothing was approved; there is no verdict


@pytest.mark.ac("ADR-090726-9a4e/AC-2")
async def test_approve_draft_blank_verdict_is_pending_not_approved() -> None:
    """An explicit-but-empty verdict is as absent as a missing key."""
    node = get_node("human.approve_draft")()
    result = await node.run({"draft": {"ticket": "PROJ-1"}}, _ctx("n", {"verdict": "   "}))

    assert result.status == "paused"
    assert result.metadata["paused_reason"] == "awaiting_human_approval"


@pytest.mark.ac("ADR-090726-9a4e/AC-2")
async def test_approve_draft_non_string_verdict_is_pending_not_approved() -> None:
    """A verdict that is not a string cannot be an approval either."""
    node = get_node("human.approve_draft")()
    result = await node.run({"draft": {"ticket": "PROJ-1"}}, _ctx("n", {"verdict": 1}))

    assert result.status == "paused"


@pytest.mark.ac("ADR-090726-9a4e/AC-2")
async def test_approve_draft_explicit_verdicts_still_resume() -> None:
    """Regression guard: an answer that states its verdict still completes,
    for every verdict the output schema admits."""
    node = get_node("human.approve_draft")()
    for verdict in ("approved", "rejected", "modified", "timed_out"):
        result = await node.run(
            {"draft": {"ticket": "PROJ-1"}},
            _ctx("n", {"verdict": verdict, "timed_out": verdict == "timed_out"}),
        )
        assert result.status == "completed"
        assert result.output is not None
        assert result.output.verdict == verdict


@pytest.mark.ac("ADR-090726-9a4e/AC-2")
async def test_approve_draft_unknown_verdict_string_fails_not_approves() -> None:
    """A non-empty but unrecognized verdict string is garbage, not approval:
    the output schema rejects it and the node fails loudly rather than
    silently admitting an unmodeled verdict."""
    node = get_node("human.approve_draft")()
    result = await node.run({"draft": {"ticket": "PROJ-1"}}, _ctx("n", {"verdict": "banana"}))

    assert result.status == "failed"
    assert result.output is None


# --- human.delegate_to_role ---------------------------------------------------


class _HolderResolver:
    """Always resolves a holder, so a routing path is available to take."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def resolve(self, role: str) -> str | None:
        self.calls.append(role)
        return "alice"


@pytest.mark.ac("ADR-090726-9a4e/AC-3")
async def test_delegate_missing_verdict_never_routes_the_payload() -> None:
    """Fail closed *before* the holder lookup: a verdict nobody asserted must
    not hand the payload to a role holder as if it had been approved."""
    from maistro.graph.nodes.human_delegate_to_role import HumanDelegateToRoleNode

    resolver = _HolderResolver()
    node = HumanDelegateToRoleNode(role_resolver=resolver)
    result = await node.run(
        {"role": "on_call_pm", "payload": {"task": "sign off"}},
        _ctx("n", {"modified_payload": None}),
    )

    assert result.status == "paused"
    assert result.metadata["paused_reason"] == "awaiting_role_delegate"
    assert resolver.calls == []  # no routing happened on an asserted-less answer


@pytest.mark.ac("ADR-090726-9a4e/AC-3")
async def test_delegate_blank_verdict_is_pending_not_approved() -> None:
    from maistro.graph.nodes.human_delegate_to_role import HumanDelegateToRoleNode

    node = HumanDelegateToRoleNode(role_resolver=_HolderResolver())
    result = await node.run({"role": "on_call_pm"}, _ctx("n", {"verdict": ""}))

    assert result.status == "paused"
    assert result.metadata["paused_reason"] == "awaiting_role_delegate"


@pytest.mark.ac("ADR-090726-9a4e/AC-3")
async def test_delegate_explicit_verdict_still_routes() -> None:
    """Regression guard: an explicit verdict still resolves and completes."""
    from maistro.graph.nodes.human_delegate_to_role import HumanDelegateToRoleNode

    resolver = _HolderResolver()
    node = HumanDelegateToRoleNode(role_resolver=resolver)
    result = await node.run({"role": "on_call_pm"}, _ctx("n", {"verdict": "approved"}))

    assert result.status == "completed"
    assert result.output is not None
    assert result.output.verdict == "approved"
    assert result.output.resolved_user_id == "alice"
    assert resolver.calls == ["on_call_pm"]


# --- human.review_and_edit ----------------------------------------------------


@pytest.mark.ac("ADR-090726-9a4e/AC-4")
async def test_review_missing_verdict_is_pending_not_approved() -> None:
    """The redline gate is the same class of decision as approve_draft."""
    node = get_node("human.review_and_edit")()
    result = await node.run(
        {"document": {"terms": {"price": 10}}}, _ctx("n", {"edits": [], "reviewer_note": ""})
    )

    assert result.status == "paused"
    assert result.metadata["paused_reason"] == "awaiting_human_review"
    assert result.output is None


@pytest.mark.ac("ADR-090726-9a4e/AC-4")
async def test_review_blank_verdict_is_pending_not_approved() -> None:
    node = get_node("human.review_and_edit")()
    result = await node.run(
        {"document": {"terms": {"price": 10}}}, _ctx("n", {"verdict": "", "edits": []})
    )

    assert result.status == "paused"
    assert result.metadata["paused_reason"] == "awaiting_human_review"


@pytest.mark.ac("ADR-090726-9a4e/AC-4")
async def test_review_explicit_verdict_with_edits_still_resumes() -> None:
    """Regression guard: an explicit verdict and its edits still complete."""
    node = get_node("human.review_and_edit")()
    result = await node.run(
        {"document": {"terms": {"price": 10}}},
        _ctx(
            "n",
            {
                "verdict": "edited",
                "edits": [{"path": "terms.price", "old_value": 10, "new_value": 12}],
                "reviewer_note": "raise",
            },
        ),
    )

    assert result.status == "completed"
    assert result.output is not None
    assert result.output.verdict == "edited"
    assert [edit.new_value for edit in result.output.edits] == [12]


# --- #1097: a malformed answer must re-pause on the *original* deadline ----


def _malformed_answer_with_pause(**extra: Any) -> dict[str, Any]:
    """A resumed answer stating no verdict, carrying the `_pause` evidence
    `answer_record` stamps onto every resumed answer regardless of whether it
    is well formed (see `graph/durable_runs/stores.py::answer_record`)."""
    return {
        **extra,
        "_pause": {
            "kind": "hitl",
            "metadata": {},
            "resume_at": _ORIGINAL_DEADLINE.isoformat(),
        },
    }


@pytest.mark.ac("ADR-090726-9a4e/AC-2")
async def test_approve_draft_malformed_answer_preserves_the_original_deadline() -> None:
    node = get_node("human.approve_draft")()
    result = await node.run(
        {"draft": {"ticket": "PROJ-1"}, "timeout_seconds": 86_400},
        _ctx("n", _malformed_answer_with_pause(reviewer_note="still deciding")),
    )

    assert result.status == "paused"
    assert result.resume_at == _ORIGINAL_DEADLINE, (
        "a malformed answer must re-pause on the durable deadline the store "
        "stamped onto it, not now + timeout_seconds recomputed fresh"
    )


@pytest.mark.ac("ADR-090726-9a4e/AC-3")
async def test_delegate_malformed_answer_preserves_the_original_deadline() -> None:
    from maistro.graph.nodes.human_delegate_to_role import HumanDelegateToRoleNode

    node = HumanDelegateToRoleNode(role_resolver=_HolderResolver())
    result = await node.run(
        {"role": "on_call_pm"},
        _ctx("n", _malformed_answer_with_pause()),
    )

    assert result.status == "paused"
    assert result.resume_at == _ORIGINAL_DEADLINE


@pytest.mark.ac("ADR-090726-9a4e/AC-4")
async def test_review_malformed_answer_preserves_the_original_deadline() -> None:
    node = get_node("human.review_and_edit")()
    result = await node.run(
        {"document": {"terms": {"price": 10}}},
        _ctx("n", _malformed_answer_with_pause(edits=[])),
    )

    assert result.status == "paused"
    assert result.resume_at == _ORIGINAL_DEADLINE


@pytest.mark.ac("ADR-090726-9a4e/AC-2")
async def test_approve_draft_first_pause_has_no_preserved_deadline_to_read() -> None:
    """The fallback path: a node's very first pause has no `_pause` evidence
    yet, so it computes `now + timeout_seconds` exactly as before -- this is
    not a regression, just the base case `preserved_hitl_deadline` falls
    back to."""
    node = get_node("human.approve_draft")()
    before = datetime.now(UTC)

    result = await node.run({"draft": {"ticket": "PROJ-1"}, "timeout_seconds": 100}, _ctx("n", {}))

    assert result.status == "paused"
    assert result.resume_at is not None
    assert (
        before + timedelta(seconds=99)
        <= result.resume_at
        <= datetime.now(UTC) + timedelta(seconds=101)
    )


@pytest.mark.ac("ADR-090726-9a4e/AC-2")
async def test_approve_draft_pause_evidence_without_a_string_resume_at_falls_back() -> None:
    """`_pause` evidence is present but its `resume_at` is missing or not a
    string (a record from before this preservation existed, or corrupted
    evidence) -- there is no admitted deadline to read back, so this falls
    back to `now + timeout_seconds` exactly like the no-evidence-at-all
    case, rather than raising."""
    node = get_node("human.approve_draft")()
    before = datetime.now(UTC)

    result = await node.run(
        {"draft": {"ticket": "PROJ-1"}, "timeout_seconds": 100},
        _ctx("n", _malformed_answer_with_pause() | {"_pause": {"kind": "hitl", "metadata": {}}}),
    )

    assert result.status == "paused"
    assert result.resume_at is not None
    assert (
        before + timedelta(seconds=99)
        <= result.resume_at
        <= datetime.now(UTC) + timedelta(seconds=101)
    )


@pytest.mark.ac("ADR-090726-9a4e/AC-2")
async def test_approve_draft_repeated_malformed_answers_do_not_extend_the_deadline() -> None:
    """Repeated bad answers, as if arriving right up against the deadline,
    must all resolve to the same preserved deadline -- not one push back per
    attempt."""
    node = get_node("human.approve_draft")()
    inputs = {"draft": {"ticket": "PROJ-1"}, "timeout_seconds": 86_400}

    for note in ("first try", "second try", "third try"):
        result = await node.run(inputs, _ctx("n", _malformed_answer_with_pause(reviewer_note=note)))
        assert result.status == "paused"
        assert result.resume_at == _ORIGINAL_DEADLINE
