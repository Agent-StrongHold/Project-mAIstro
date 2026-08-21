"""Tests for the `human.review_and_edit` node.

Generalizes `human.approve_draft`'s flat approve/reject/modify verdict into
a structured list of field-level edits.
"""

from __future__ import annotations

from typing import Any

from maistro.graph.nodes import NodeContext, get_node, list_kinds


def _ctx(**overrides: Any) -> NodeContext:
    base = {
        "run_id": "r1",
        "dag_id": "d1",
        "node_id": "n1",
        "user_id": "u1",
        "project_id": "p1",
    }
    base.update(overrides)
    return NodeContext(**base)


async def test_first_reach_pauses_with_document_payload() -> None:
    Node = get_node("human.review_and_edit")
    document = {"terms": {"price": 100}, "party": "Acme"}
    result = await Node().run(
        {"document": document, "document_kind": "contract", "title": "Redline Acme MSA"},
        _ctx(node_id="redline-acme"),
    )
    assert result.success is True
    assert result.status == "paused"
    assert result.resume_at is not None
    assert result.metadata["paused_reason"] == "awaiting_human_review"
    assert result.metadata["document"] == document
    assert result.metadata["document_kind"] == "contract"
    assert result.metadata["title"] == "Redline Acme MSA"


async def test_resume_with_verdict_approved_has_no_edits() -> None:
    Node = get_node("human.review_and_edit")
    ctx = _ctx(node_id="redline-acme")
    ctx.metadata["hitl_answers"] = {"redline-acme": {"verdict": "approved"}}
    result = await Node().run({"document": {"x": 1}}, ctx)
    assert result.status == "completed"
    assert result.output.verdict == "approved"
    assert result.output.edits == []
    assert result.output.timed_out is False


async def test_resume_with_verdict_edited_returns_structured_edits() -> None:
    Node = get_node("human.review_and_edit")
    ctx = _ctx(node_id="redline-acme")
    ctx.metadata["hitl_answers"] = {
        "redline-acme": {
            "verdict": "edited",
            "edits": [
                {
                    "path": "terms.price",
                    "old_value": 100,
                    "new_value": 90,
                    "note": "Negotiated discount",
                }
            ],
            "reviewer_note": "Approved with one price edit",
        }
    }
    result = await Node().run({"document": {"terms": {"price": 100}}}, ctx)
    assert result.status == "completed"
    assert result.output.verdict == "edited"
    assert len(result.output.edits) == 1
    edit = result.output.edits[0]
    assert edit.path == "terms.price"
    assert edit.old_value == 100
    assert edit.new_value == 90
    assert edit.note == "Negotiated discount"
    assert result.output.reviewer_note == "Approved with one price edit"


async def test_resume_with_rejected_verdict() -> None:
    Node = get_node("human.review_and_edit")
    ctx = _ctx(node_id="redline-acme")
    ctx.metadata["hitl_answers"] = {
        "redline-acme": {"verdict": "rejected", "reviewer_note": "Unacceptable terms"}
    }
    result = await Node().run({"document": {"x": 1}}, ctx)
    assert result.output.verdict == "rejected"
    assert result.output.edits == []
    assert result.output.reviewer_note == "Unacceptable terms"


async def test_resume_with_timed_out_flag() -> None:
    Node = get_node("human.review_and_edit")
    ctx = _ctx(node_id="redline-acme")
    ctx.metadata["hitl_answers"] = {"redline-acme": {"verdict": "timed_out", "timed_out": True}}
    result = await Node().run({"document": {"x": 1}}, ctx)
    assert result.output.verdict == "timed_out"
    assert result.output.timed_out is True


def test_kind_is_registered() -> None:
    assert "human.review_and_edit" in set(list_kinds())
