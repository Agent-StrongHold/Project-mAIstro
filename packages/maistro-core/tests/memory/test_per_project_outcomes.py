"""Per-project Outcome scoping + thumbs-down signal.

Phase 2 deliverable: a thumbs-down on a node in Project A must not
surface in Project B's get_experience_context. Hard failures + user
thumbs-down BOTH flow into the next-run prompt for the same project.
"""

from __future__ import annotations

from maistro.memory.outcomes import InMemoryOutcomeStore
from maistro.memory.types import Outcome


async def _record_failure(
    store: InMemoryOutcomeStore,
    *,
    task_type: str,
    error: str,
    project_id: str = "",
    user_id: str = "alice",
) -> None:
    await store.record(
        Outcome(
            task_type=task_type,
            success=False,
            error_type=error,
            model_used="claude-sonnet-4-6",
            user_id=user_id,
            project_id=project_id,
        )
    )


async def _record_thumb_down(
    store: InMemoryOutcomeStore,
    *,
    task_type: str,
    project_id: str = "",
    user_id: str = "alice",
    node_id: str = "summarize",
    comment: str = "",
) -> None:
    await store.record(
        Outcome(
            task_type=task_type,
            success=True,  # the node succeeded; the human disliked it
            user_id=user_id,
            project_id=project_id,
            node_id=node_id,
            thumb="down",
            thumb_comment=comment,
        )
    )


# --- Per-project filtering -------------------------------------------------


async def test_failures_in_project_a_do_not_pollute_project_b_narrative() -> None:
    store = InMemoryOutcomeStore()
    await _record_failure(store, task_type="reporting", error="LLMTimeout", project_id="proj-a")
    await _record_failure(
        store, task_type="reporting", error="JsonDecodeError", project_id="proj-a"
    )
    await _record_failure(store, task_type="reporting", error="RateLimited", project_id="proj-b")

    narrative_a = await store.get_experience_context("reporting", project_id="proj-a")
    narrative_b = await store.get_experience_context("reporting", project_id="proj-b")

    # Project A sees its own failures, not B's.
    assert "LLMTimeout" in narrative_a
    assert "JsonDecodeError" in narrative_a
    assert "RateLimited" not in narrative_a

    # Project B sees only its own failure.
    assert "RateLimited" in narrative_b
    assert "LLMTimeout" not in narrative_b
    assert "JsonDecodeError" not in narrative_b


async def test_empty_project_id_returns_cross_project_narrative() -> None:
    """Backward-compat: callers that don't pass project_id get the global
    narrative across all projects (so legacy callers don't break)."""
    store = InMemoryOutcomeStore()
    await _record_failure(store, task_type="poll", error="Net1", project_id="proj-a")
    await _record_failure(store, task_type="poll", error="Net2", project_id="proj-b")
    await _record_failure(store, task_type="poll", error="NetGlobal", project_id="")  # legacy

    narrative = await store.get_experience_context("poll")  # no project_id arg
    assert "Net1" in narrative
    assert "Net2" in narrative
    assert "NetGlobal" in narrative


# --- Thumbs-down surfaces alongside failures -----------------------------


async def test_thumbs_down_appears_in_experience_context() -> None:
    store = InMemoryOutcomeStore()
    # The node ran successfully — but the user thumbed it down.
    await _record_thumb_down(
        store,
        task_type="reporting",
        project_id="proj-a",
        node_id="exec_summary",
        comment="Too terse for the CEO audience",
    )
    narrative = await store.get_experience_context("reporting", project_id="proj-a")
    assert "User Thumbs-Down Patterns" in narrative
    assert "exec_summary" in narrative
    assert "Too terse for the CEO audience" in narrative


async def test_thumb_down_in_one_project_does_not_leak_to_another() -> None:
    """Critical isolation check — the whole point of per-project memory."""
    store = InMemoryOutcomeStore()
    await _record_thumb_down(
        store,
        task_type="reporting",
        project_id="proj-a",
        node_id="exec_summary",
        comment="Wrong tone",
    )
    narrative_b = await store.get_experience_context("reporting", project_id="proj-b")
    assert "exec_summary" not in narrative_b
    assert "Wrong tone" not in narrative_b
    assert narrative_b == ""  # nothing for proj-b yet


async def test_failure_and_thumbs_down_appear_in_same_narrative() -> None:
    """Both signal types render in distinct sections so the LLM can
    distinguish 'we failed here' from 'human disliked this output'."""
    store = InMemoryOutcomeStore()
    await _record_failure(store, task_type="poll", error="JiraAuthFailed", project_id="p")
    await _record_thumb_down(
        store,
        task_type="poll",
        project_id="p",
        node_id="jira_filter",
        comment="Picked irrelevant tickets",
    )
    narrative = await store.get_experience_context("poll", project_id="p")
    assert "Recent Failure Patterns" in narrative
    assert "JiraAuthFailed" in narrative
    assert "User Thumbs-Down Patterns" in narrative
    assert "jira_filter" in narrative
    assert "Picked irrelevant tickets" in narrative


# --- Limit + tool_name filters still apply (backward compat) -------------


async def test_tool_name_filter_combines_with_project_id() -> None:
    store = InMemoryOutcomeStore()
    await store.record(
        Outcome(
            task_type="research",
            success=False,
            error_type="WebTimeout",
            project_id="p",
            tool_calls=[{"name": "browser_use"}],
        )
    )
    await store.record(
        Outcome(
            task_type="research",
            success=False,
            error_type="AuthDenied",
            project_id="p",
            tool_calls=[{"name": "jira_search"}],
        )
    )
    narrow = await store.get_experience_context("research", tool_name="browser_use", project_id="p")
    assert "WebTimeout" in narrow
    assert "AuthDenied" not in narrow


async def test_limit_applies_per_section() -> None:
    store = InMemoryOutcomeStore()
    for i in range(10):
        await _record_failure(store, task_type="x", error=f"E{i}", project_id="p")
    narrative = await store.get_experience_context("x", project_id="p", limit=3)
    # Only the most-recent 3 errors appear.
    assert "E9" in narrative
    assert "E8" in narrative
    assert "E7" in narrative
    assert "E0" not in narrative
    assert "E1" not in narrative
