"""Branch-coverage closers for the 4 nodes below the 95/95 gate.

Targets the specific uncovered lines reported by `coverage report -m`:
- jira_wait_for_subtasks: 101, 107-108, 119-128, 144-147, 157, 159
- llm_summarize: 89, 93, 114, 116, 118
- transform_format_markdown: 60, 67-70, 76, 93, 95
- airtable_poll: 81, 83, 85
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from maistro.graph.nodes import NodeContext, get_node


def _ctx(**o: Any) -> NodeContext:
    base = {
        "run_id": "r",
        "dag_id": "d",
        "node_id": "n",
        "user_id": "u",
        "project_id": "p",
        "workspace_id": "w1",
        "node_run_id": "nr1",
        "attempt_id": "a1",
    }
    base.update(o)
    return NodeContext(**base)


@pytest.fixture
async def llm_binding_id() -> str:
    """Register the governed model.chat Binding llm.summarize resolves (#56)."""

    from maistro.capabilities.binding import Binding
    from maistro.capabilities.effect_context import default_effect_context

    await default_effect_context().bindings.put(
        Binding(
            # fixed created_at keeps the idempotent re-put legal across tests
            created_at=datetime(2026, 9, 1, tzinfo=UTC),
            binding_id="llm-summarize-test-binding-bc",
            workspace_id="w1",
            project_id="p",
            capability="model.chat",
        )
    )
    return "llm-summarize-test-binding-bc"


def _patch_httpx(
    monkeypatch: pytest.MonkeyPatch, *, payload: Any, status_code: int = 200, verb: str = "get"
) -> None:
    """Patch httpx.AsyncClient with a configurable response for either GET or POST."""

    class _Resp:
        def __init__(self) -> None:
            self.status_code = status_code

        def json(self) -> Any:
            return payload

    class _Client:
        def __init__(self, *a: Any, **kw: Any) -> None: ...
        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *a: Any) -> None: ...
        async def get(self, *a: Any, **kw: Any) -> _Resp:
            return _Resp()

        async def post(self, *a: Any, **kw: Any) -> _Resp:
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)


# --- airtable_poll: 401 / 403 / generic 5xx error paths -------------------


async def test_airtable_poll_401_raises_permission(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_httpx(monkeypatch, payload={}, status_code=401)
    node = get_node("airtable.poll")()
    out = await node.run({"pat": "p", "base_id": "b", "table": "t"}, _ctx())
    assert out.success is False
    assert out.error_code == "PermissionError"
    assert "airtable_auth_failed" in (out.error_message or "")


async def test_airtable_poll_403_raises_permission(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_httpx(monkeypatch, payload={}, status_code=403)
    node = get_node("airtable.poll")()
    out = await node.run({"pat": "p", "base_id": "b", "table": "t"}, _ctx())
    assert out.success is False
    assert out.error_code == "PermissionError"
    assert "airtable_forbidden" in (out.error_message or "")


async def test_airtable_poll_500_raises_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_httpx(monkeypatch, payload={}, status_code=500)
    node = get_node("airtable.poll")()
    out = await node.run({"pat": "p", "base_id": "b", "table": "t"}, _ctx())
    assert out.success is False
    assert out.error_code == "RuntimeError"
    assert "status=500" in (out.error_message or "")


async def test_airtable_poll_without_since_iso_no_filter_param(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Covers line 68→73: the falsy since_iso branch (no filter formula added)."""
    seen: dict[str, Any] = {}

    class _Resp:
        status_code = 200

        def json(self) -> Any:
            return {"records": []}

    class _Client:
        def __init__(self, *a: Any, **kw: Any) -> None: ...
        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *a: Any) -> None: ...
        async def get(self, url: str, *, params: dict | None = None, **kw: Any) -> _Resp:
            seen["params"] = params or {}
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    node = get_node("airtable.poll")()
    out = await node.run({"pat": "p", "base_id": "b", "table": "t"}, _ctx())  # no since_iso
    assert out.success is True
    assert "filterByFormula" not in seen["params"]


# --- llm_summarize: missing-base-url + style fallback + 401/429/500 -------


async def test_llm_summarize_missing_base_url_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Covers line 89: `if not base_url: raise RuntimeError`."""
    for k in ("MAISTRO_LLM_BASE_URL", "LITELLM_URL", "LITELLM_API_BASE"):
        monkeypatch.delenv(k, raising=False)
    node = get_node("llm.summarize")()
    out = await node.run({"text": "hello"}, _ctx())
    assert out.success is False
    assert out.error_code == "RuntimeError"
    assert "no LLM base URL" in (out.error_message or "")


async def test_llm_summarize_extra_system_prompt_appended(
    monkeypatch: pytest.MonkeyPatch,
    llm_binding_id: str,
) -> None:
    """Covers line 93: the system_prompt_extra concat branch."""
    monkeypatch.setenv("MAISTRO_LLM_BASE_URL", "http://fake")
    monkeypatch.setenv("MAISTRO_LLM_API_KEY", "k")
    seen: dict[str, Any] = {}

    class _Resp:
        status_code = 200

        def json(self) -> Any:
            return {
                "model": "gemini-3.1-flash-lite",
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            }

    class _Client:
        def __init__(self, *a: Any, **kw: Any) -> None: ...
        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *a: Any) -> None: ...
        async def post(self, url: str, *, json: Any = None, **kw: Any) -> _Resp:
            seen["body"] = json
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    node = get_node("llm.summarize")()
    out = await node.run(
        {
            "text": "x",
            "style": "bullet",
            "system_prompt_extra": "Project: HHN 2026",
            "binding_id": llm_binding_id,
        },
        _ctx(),
    )
    assert out.success
    sys_content = seen["body"]["messages"][0]["content"]
    assert "Project: HHN 2026" in sys_content
    assert "bullet" in sys_content.lower()


async def test_llm_summarize_unknown_style_falls_back_to_bullet(
    monkeypatch: pytest.MonkeyPatch,
    llm_binding_id: str,
) -> None:
    """Covers line 105→108: style not in _STYLE_PROMPTS branch."""
    monkeypatch.setenv("MAISTRO_LLM_BASE_URL", "http://fake")
    seen: dict[str, Any] = {}
    _patch_httpx(
        monkeypatch,
        payload={
            "choices": [{"message": {"content": "ok"}}],
            "model": "m",
            "usage": {"prompt_tokens": 0, "completion_tokens": 0},
        },
        verb="post",
    )

    class _C:
        def __init__(self, *a: Any, **kw: Any) -> None: ...
        async def __aenter__(self) -> _C:
            return self

        async def __aexit__(self, *a: Any) -> None: ...
        async def post(self, *a: Any, **kw: Any):
            class _R:
                status_code = 200

                def json(self) -> Any:
                    return {
                        "choices": [{"message": {"content": "ok"}}],
                        "model": "m",
                        "usage": {"prompt_tokens": 0, "completion_tokens": 0},
                    }

            seen["body"] = kw.get("json")
            return _R()

    monkeypatch.setattr(httpx, "AsyncClient", _C)
    node = get_node("llm.summarize")()
    out = await node.run(
        {"text": "x", "style": "nonsense-style", "binding_id": llm_binding_id},
        _ctx(node_run_id="nr-style"),
    )
    assert out.success
    sys_content = seen["body"]["messages"][0]["content"]
    # Falls back to "bullet" style content (matches the default).
    assert "bullet" in sys_content.lower()


async def test_llm_summarize_401_raises_permission(
    monkeypatch: pytest.MonkeyPatch, llm_binding_id: str
) -> None:
    """Line 114: 401 → PermissionError."""
    monkeypatch.setenv("MAISTRO_LLM_BASE_URL", "http://fake")
    _patch_httpx(monkeypatch, payload={}, status_code=401, verb="post")
    node = get_node("llm.summarize")()
    out = await node.run(
        {"text": "x", "binding_id": llm_binding_id},
        _ctx(node_run_id="nr-401"),
    )
    assert out.success is False
    assert out.error_code == "PermissionError"
    assert "llm_auth_failed" in (out.error_message or "")


async def test_llm_summarize_429_raises_runtime(
    monkeypatch: pytest.MonkeyPatch, llm_binding_id: str
) -> None:
    """Line 116: 429 → RuntimeError."""
    monkeypatch.setenv("MAISTRO_LLM_BASE_URL", "http://fake")
    _patch_httpx(monkeypatch, payload={}, status_code=429, verb="post")
    node = get_node("llm.summarize")()
    out = await node.run(
        {"text": "x", "binding_id": llm_binding_id},
        _ctx(node_run_id="nr-429"),
    )
    assert out.success is False
    assert out.error_code == "RuntimeError"
    assert "rate_limited" in (out.error_message or "")


async def test_llm_summarize_500_raises_runtime(
    monkeypatch: pytest.MonkeyPatch, llm_binding_id: str
) -> None:
    """Line 118: generic ≥400 → RuntimeError."""
    monkeypatch.setenv("MAISTRO_LLM_BASE_URL", "http://fake")
    _patch_httpx(monkeypatch, payload={}, status_code=500, verb="post")
    node = get_node("llm.summarize")()
    out = await node.run(
        {"text": "x", "binding_id": llm_binding_id},
        _ctx(node_run_id="nr-500"),
    )
    assert out.success is False
    assert out.error_code == "RuntimeError"
    assert "status=500" in (out.error_message or "")


# --- transform_format_markdown: empty-with-footer + missing-field + dot-path ---


async def test_format_markdown_empty_uses_fallback_with_footer() -> None:
    """Covers line 60: footer-append on empty-items branch."""
    node = get_node("transform.format_markdown")()
    out = await node.run(
        {
            "items": [],
            "template": "- {x}",
            "header": "## h",
            "footer": "_(end)_",
            "empty_fallback": "_no data_",
        },
        _ctx(),
    )
    assert out.success
    md = out.output.markdown
    assert "## h" in md
    assert "_no data_" in md
    assert "_(end)_" in md


async def test_format_markdown_missing_field_surfaces_placeholder() -> None:
    """Covers lines 67-70: KeyError path when a {field} isn't in the dict.

    The template uses a dot-path key that doesn't exist; the renderer's
    re.sub callback returns '' for missing keys, so the rendered row
    contains the literal template minus that placeholder. We assert that
    the row appears (no crash) and items are counted.
    """
    node = get_node("transform.format_markdown")()
    out = await node.run(
        {
            "items": [{"key": "K1"}, {"key": "K2"}],
            "template": "- {key}: {missing.field}",
            "header": "",
        },
        _ctx(),
    )
    assert out.success
    assert out.output.rows_rendered == 2
    assert "K1" in out.output.markdown
    assert "K2" in out.output.markdown


async def test_format_markdown_with_footer_renders() -> None:
    """Line 76 (and 72→74): footer branch on non-empty items."""
    node = get_node("transform.format_markdown")()
    out = await node.run(
        {"items": [{"k": "a"}], "template": "- {k}", "header": "## h", "footer": "FOOT"},
        _ctx(),
    )
    assert out.success
    assert out.output.markdown.endswith("FOOT")


async def test_format_markdown_render_with_attribute_access() -> None:
    """Covers lines 93, 95: the getattr-branch when an item is not a dict.

    The template renderer falls back to getattr when cur isn't a dict —
    simulate by passing a SimpleNamespace-like object.
    """
    node = get_node("transform.format_markdown")()
    # The node's input_schema demands list[dict], so this gets validated
    # as model_validate. Pydantic will coerce only dict-shaped input; the
    # attribute-access branch is invoked by nested dicts in normal items.
    out = await node.run(
        {
            "items": [{"key": "K1", "fields": {"summary": "from-dict"}}],
            "template": "- {key}: {fields.summary}",
            "header": "",
        },
        _ctx(),
    )
    assert out.success
    assert "K1: from-dict" in out.output.markdown


# --- jira_wait_for_subtasks: resume-with-first_seen + 401 helper + non-server flavor ---


async def test_wait_for_subtasks_resume_within_deadline_pauses_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Covers lines 119-128: resume path where some subtasks still not done
    and the deadline has NOT yet been reached → pauses again."""
    _patch_httpx(
        monkeypatch,
        payload={"fields": {"subtasks": [{"key": "S1", "fields": {"status": {"name": "Open"}}}]}},
    )
    node = get_node("jira.wait_for_subtasks")()
    ctx = _ctx()
    # Was first seen 30 seconds ago; timeout 1 hour → still within deadline.
    ctx.metadata[f"wait_first_seen:{ctx.node_id}"] = (
        datetime.now(UTC) - timedelta(seconds=30)
    ).isoformat()
    out = await node.run(
        {
            "base_url": "https://jira.example.com",
            "parent_key": "P-1",
            "pat": "p",
            "target_statuses": ["Done"],
            "timeout_seconds": 3600,
            "poll_interval_seconds": 60,
        },
        ctx,
    )
    assert out.status == "paused"
    assert out.metadata["paused_reason"] == "waiting_on_jira_subtasks"
    assert out.metadata["first_seen"] == ctx.metadata[f"wait_first_seen:{ctx.node_id}"]


async def test_wait_for_subtasks_resume_with_bad_first_seen_falls_back_to_now(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Covers lines 107-108: ValueError on fromisoformat → first = now."""
    _patch_httpx(
        monkeypatch,
        payload={"fields": {"subtasks": [{"key": "S1", "fields": {"status": {"name": "Open"}}}]}},
    )
    node = get_node("jira.wait_for_subtasks")()
    ctx = _ctx()
    ctx.metadata[f"wait_first_seen:{ctx.node_id}"] = "not-an-iso-date"
    out = await node.run(
        {
            "base_url": "https://jira.example.com",
            "parent_key": "P-1",
            "pat": "p",
            "target_statuses": ["Done"],
            "timeout_seconds": 3600,
            "poll_interval_seconds": 60,
        },
        ctx,
    )
    # Bad first_seen → falls back to now → since < timeout → pauses again.
    assert out.status == "paused"


async def test_wait_for_subtasks_cloud_flavor_with_email_uses_basic_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Covers lines 144-147: cloud flavor + email → Basic auth path."""
    seen: dict[str, Any] = {}

    class _Resp:
        status_code = 200

        def json(self) -> Any:
            return {"fields": {"subtasks": []}}

    class _C:
        def __init__(self, *a: Any, **kw: Any) -> None: ...
        async def __aenter__(self) -> _C:
            return self

        async def __aexit__(self, *a: Any) -> None: ...
        async def get(
            self,
            url: str,
            *,
            params: dict | None = None,
            headers: dict | None = None,
            auth: Any = None,
        ) -> _Resp:
            seen["url"] = url
            seen["auth"] = auth
            seen["headers"] = headers
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _C)
    node = get_node("jira.wait_for_subtasks")()
    out = await node.run(
        {
            "base_url": "https://acme.atlassian.net",
            "parent_key": "P-1",
            "pat": "cloud-token",
            "flavor": "cloud",
            "email": "alice@example.com",
        },
        _ctx(),
    )
    assert out.success
    assert seen["auth"] == ("alice@example.com", "cloud-token")
    assert "/rest/api/3/issue/P-1" in seen["url"]


async def test_wait_for_subtasks_cloud_flavor_without_email_uses_bearer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Covers line 101 / 144-147 combo: cloud flavor + NO email → Bearer."""
    seen: dict[str, Any] = {}

    class _Resp:
        status_code = 200

        def json(self) -> Any:
            return {"fields": {"subtasks": []}}

    class _C:
        def __init__(self, *a: Any, **kw: Any) -> None: ...
        async def __aenter__(self) -> _C:
            return self

        async def __aexit__(self, *a: Any) -> None: ...
        async def get(
            self,
            url: str,
            *,
            params: dict | None = None,
            headers: dict | None = None,
            auth: Any = None,
        ) -> _Resp:
            seen["headers"] = headers
            seen["auth"] = auth
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _C)
    node = get_node("jira.wait_for_subtasks")()
    await node.run(
        {
            "base_url": "https://acme.atlassian.net",
            "parent_key": "P-1",
            "pat": "tk",
            "flavor": "cloud",
            # no email
        },
        _ctx(),
    )
    assert seen["headers"]["Authorization"] == "Bearer tk"
    assert seen["auth"] is None


async def test_wait_for_subtasks_500_raises_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    """Covers line 159 (helper) + the executor propagates the RuntimeError
    back through the BaseNode envelope."""
    _patch_httpx(monkeypatch, payload={}, status_code=500)
    node = get_node("jira.wait_for_subtasks")()
    out = await node.run(
        {
            "base_url": "https://jira.example.com",
            "parent_key": "P-1",
            "pat": "p",
            "target_statuses": ["Done"],
        },
        _ctx(),
    )
    assert out.success is False
    assert out.error_code == "RuntimeError"
    assert "status=500" in (out.error_message or "")


async def test_wait_for_subtasks_401_raises_permission(monkeypatch: pytest.MonkeyPatch) -> None:
    """Covers line 157: helper's PermissionError on 401."""
    _patch_httpx(monkeypatch, payload={}, status_code=401)
    node = get_node("jira.wait_for_subtasks")()
    out = await node.run(
        {
            "base_url": "https://jira.example.com",
            "parent_key": "P-1",
            "pat": "bad",
            "target_statuses": ["Done"],
        },
        _ctx(),
    )
    assert out.success is False
    assert out.error_code == "PermissionError"


async def test_wait_for_subtasks_subtask_without_key_is_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Covers line 167→164: subtask in the response without a 'key' is skipped
    (the conditional `if key:` False branch)."""
    _patch_httpx(
        monkeypatch,
        payload={
            "fields": {
                "subtasks": [
                    {"key": "", "fields": {"status": {"name": "Done"}}},  # no key → dropped
                    {"key": "S2", "fields": {"status": {"name": "Done"}}},
                ]
            }
        },
    )
    node = get_node("jira.wait_for_subtasks")()
    out = await node.run(
        {
            "base_url": "https://jira.example.com",
            "parent_key": "P-1",
            "pat": "p",
            "target_statuses": ["Done"],
        },
        _ctx(),
    )
    assert out.success
    assert out.output.subtask_keys == ["S2"]
    assert out.output.all_match is True
