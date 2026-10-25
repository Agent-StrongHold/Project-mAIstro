"""Final gap-closers for nodes/__init__.py + jira_poll + human_* + dashboard_*.

Targets:
- __init__.py: lines 45 (kind '' guard), 104 (missing model_fields fallback),
  120 (annotation None fallback in _annotation_str).
- jira_poll.py: lines 89 (cloud + email but Basic auth case), 105 (403),
  107 (generic 4xx).
- human_approve_draft.py: line 78 (timed_out=True resume path).
- human_ask_question.py: line 104 (Same answer round-trip with timed_out=True).
- dashboard_append_section.py: lines 96, 99 (blackboard=None fallback to
  ctx.metadata; non-dict bb.metadata fallback).
"""

from __future__ import annotations

from typing import Any, ClassVar

import httpx
import pytest
from pydantic import BaseModel

from maistro.graph.nodes import (  # type: ignore[attr-defined]
    BaseNode,
    NodeContext,
    _annotation_str,
    _schema_summary,
    get_node,
)


def _ctx(**o: Any) -> NodeContext:
    base = {"run_id": "r", "dag_id": "d", "node_id": "n", "user_id": "u", "project_id": "p"}
    base.update(o)
    return NodeContext(**base)


# --- nodes/__init__.py registry edges ---


def test_register_node_empty_kind_string_raises() -> None:
    """Line 45 of __init__.py: explicit '' kind raises ValueError."""

    class _NoKind(BaseNode):
        kind: ClassVar[str] = ""
        input_schema: ClassVar[type[BaseModel]] = type("I", (BaseModel,), {})
        output_schema: ClassVar[type[BaseModel]] = type("O", (BaseModel,), {})

    from maistro.graph.nodes import register_node as _reg

    with pytest.raises(ValueError, match="missing required `kind`"):
        _reg(_NoKind)


def test_schema_summary_without_model_fields_falls_back() -> None:
    """Line 104: when the input/output 'schema' isn't a Pydantic class
    (lacks model_fields), _schema_summary returns the empty-fields shape."""
    summary = _schema_summary(object)  # plain `object` lacks model_fields
    assert summary == {"fields": []}


def test_annotation_str_none_returns_any() -> None:
    """Line 120: _annotation_str(None) → 'Any'."""
    assert _annotation_str(None) == "Any"


# --- jira_poll: cloud with email (Basic auth) + 403 + generic 4xx ---


def _patch_jira(
    monkeypatch: pytest.MonkeyPatch,
    *,
    status_code: int,
    body: Any = None,
    seen: dict[str, Any] | None = None,
) -> None:
    class _Resp:
        def __init__(self) -> None:
            self.status_code = status_code

        def json(self) -> Any:
            return body or {"issues": []}

    class _Client:
        def __init__(self, *a: Any, **kw: Any) -> None: ...
        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *a: Any) -> None: ...
        async def get(
            self, url: str, *, params: Any = None, headers: Any = None, auth: Any = None
        ) -> _Resp:
            if seen is not None:
                seen["url"] = url
                seen["params"] = params
                seen["headers"] = headers
                seen["auth"] = auth
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)


async def test_jira_poll_cloud_with_email_basic_auth_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Line 89 (poll node): cloud + email branch uses Basic auth, NOT Bearer."""
    seen: dict[str, Any] = {}
    _patch_jira(monkeypatch, status_code=200, body={"issues": []}, seen=seen)
    node = get_node("jira.poll")()
    out = await node.run(
        {
            "base_url": "https://acme.atlassian.net",
            "jql": "x",
            "pat": "tk",
            "flavor": "cloud",
            "email": "a@b.com",
        },
        _ctx(),
    )
    assert out.success
    assert seen["auth"] == ("a@b.com", "tk")
    assert "Authorization" not in seen["headers"]


async def test_jira_poll_403_raises_permission(monkeypatch: pytest.MonkeyPatch) -> None:
    """Line 105: 403 → PermissionError."""
    _patch_jira(monkeypatch, status_code=403)
    node = get_node("jira.poll")()
    out = await node.run(
        {"base_url": "https://x", "jql": "x", "pat": "p", "flavor": "server"},
        _ctx(),
    )
    assert out.success is False
    assert out.error_code == "PermissionError"
    assert "jira_forbidden" in (out.error_message or "")


async def test_jira_poll_500_raises_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    """Line 107: generic ≥400 → RuntimeError."""
    _patch_jira(monkeypatch, status_code=500)
    node = get_node("jira.poll")()
    out = await node.run(
        {"base_url": "https://x", "jql": "x", "pat": "p", "flavor": "server"},
        _ctx(),
    )
    assert out.success is False
    assert out.error_code == "RuntimeError"
    assert "status=500" in (out.error_message or "")


# --- human.approve_draft + human.ask_question: timed_out=True resume ---


async def test_approve_draft_resume_with_timed_out_true_propagates() -> None:
    """Line 78 of human_approve_draft.py: the timed_out=True resume path."""
    ctx = _ctx(node_id="x")
    ctx.metadata["hitl_answers"] = {
        "x": {"verdict": "timed_out", "timed_out": True, "reviewer_note": "no response"}
    }
    node = get_node("human.approve_draft")()
    out = await node.run({"draft": {"x": 1}}, ctx)
    assert out.success
    assert out.output.verdict == "timed_out"
    assert out.output.timed_out is True
    assert out.output.reviewer_note == "no response"


async def test_ask_question_resume_with_timed_out_true_propagates() -> None:
    """Line 104 of human_ask_question.py: explicit timed_out=True branch."""
    ctx = _ctx(node_id="ask")
    ctx.metadata["hitl_answers"] = {"ask": {"answer": None, "answered_at": "", "timed_out": True}}
    node = get_node("human.ask_question")()
    out = await node.run({"question": "?"}, ctx)
    assert out.success
    assert out.output.timed_out is True
    assert out.output.answer is None


# --- dashboard.append_section: blackboard=None + non-dict metadata fallback ---


async def test_dashboard_append_section_falls_back_to_ctx_metadata_when_no_blackboard() -> None:
    """Line 96/99: blackboard is None → write to ctx.metadata."""
    ctx = _ctx(node_id="d", blackboard=None)
    node = get_node("dashboard.append_section")()
    out = await node.run(
        {"dashboard_id": "x", "section_title": "S1", "markdown": "v"},
        ctx,
    )
    assert out.success
    assert "dashboard:x" in ctx.metadata
    assert ctx.metadata["dashboard:x"]["sections"][0]["title"] == "S1"


async def test_dashboard_append_section_falls_back_when_bb_has_no_metadata_dict() -> None:
    """Line 99: blackboard exists but its metadata isn't a dict."""

    class _BogusBB:
        metadata = "not-a-dict"

    ctx = _ctx(node_id="d", blackboard=_BogusBB())
    node = get_node("dashboard.append_section")()
    out = await node.run(
        {"dashboard_id": "x", "section_title": "S1", "markdown": "v"},
        ctx,
    )
    assert out.success
    # The node should fall through to ctx.metadata, not corrupt the bogus bb.
    assert "dashboard:x" in ctx.metadata
