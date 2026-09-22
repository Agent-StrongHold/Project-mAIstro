"""Service-level lazy imports the #1134 namespace move rewired.

`chat_completion.py`, `pipeline_orchestrator.py`, `ui_auto_climb.py` and
`credential_store_v2.py` each resolve collaborators lazily from inside
function bodies. The migration rewrote those imports from flat
``from services.x import y`` spellings to package-qualified ones; these tests
execute each path (with external collaborators stubbed at their seam) so the
rewritten import authority stays on a covered, executed path.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from typing import Any

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]


# --- chat_completion tool handlers ------------------------------------------


async def test_confluence_pat_resolution_without_a_credential_store() -> None:
    from hive_conductor.services.chat_completion import _get_confluence_pat

    assert _get_confluence_pat("user-1134") is None


async def test_list_agent_buttons_reads_the_agent_store() -> None:
    import hive_conductor.stores as stores
    from hive_conductor.services.chat_completion import _tool_list_agent_buttons

    dag_agent = {"name": "dict-agent", "capabilities": ["x"]}
    stores.agents["agent-1134"] = dag_agent
    try:
        result = await _tool_list_agent_buttons({}, "user-1134", None)
    finally:
        stores.agents.pop("agent-1134", None)

    assert {
        "id": result["agents"][0]["id"],
        "name": result["agents"][0]["name"],
    } == {"id": "agent-1134", "name": "dict-agent"}


async def test_web_search_and_browse_url_dispatch_to_the_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hive_conductor.services.tool_executor as tool_executor
    from hive_conductor.services.chat_completion import _tool_browse_url, _tool_web_search

    async def fake_web_search(query: str, *, max_results: int = 5) -> dict[str, Any]:
        return {"results": [{"title": query, "max": max_results}]}

    async def fake_browse(url: str, task: str) -> dict[str, Any]:
        return {"url": url, "task": task}

    monkeypatch.setattr(tool_executor, "web_search", fake_web_search)
    monkeypatch.setattr(tool_executor, "browse_url", fake_browse)

    searched = await _tool_web_search({"query": "canonical runs", "max_results": 2}, "u", None)
    browsed = await _tool_browse_url(
        {"url": "https://example.test", "task": "summarize"}, "u", None
    )

    assert searched["results"][0]["max"] == 2
    assert browsed == {"url": "https://example.test", "task": "summarize"}


async def test_workflow_crud_handlers_use_the_dag_store() -> None:
    import hive_conductor.stores as stores
    from hive_conductor.services.chat_completion import (
        _tool_create_workflow,
        _tool_list_workflows,
        _tool_update_eval,
    )

    created = await _tool_create_workflow(
        {"name": "wf-1134", "nodes": [{"label": "step"}], "edges": []}, "u", None
    )
    assert created["created"] is True

    try:
        listed = await _tool_list_workflows({}, "u", None)
        assert any(w["id"] == created["dag_id"] for w in listed["workflows"])

        updated = await _tool_update_eval(
            {"dag_id": created["dag_id"], "rubric": "quality over speed"}, "u", None
        )
        assert updated["updated"] is True
        assert stores.dags[created["dag_id"]]["eval_rubric"] == "quality over speed"
    finally:
        stores.dags.pop(created["dag_id"], None)


async def test_analyze_dashboard_reports_a_missing_llm_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Screenshot succeeds; the vision step then refuses without a gateway."""
    from hive_conductor.services import chat_completion as cc

    class _FakeResponse:
        @staticmethod
        def json() -> dict[str, Any]:
            return {"screenshot": "cHh4"}

    class _FakeClient:
        @staticmethod
        async def post(*_args: Any, **_kwargs: Any) -> _FakeResponse:
            return _FakeResponse()

    class _FakeCtx:
        async def __aenter__(self) -> _FakeClient:
            return _FakeClient()

        async def __aexit__(self, *_exc: Any) -> None:
            return None

    def fake_shared_client(*_args: Any, **_kwargs: Any) -> _FakeCtx:
        return _FakeCtx()

    monkeypatch.setattr(cc, "shared_client", fake_shared_client)
    monkeypatch.delenv("LITELLM_API_BASE", raising=False)
    monkeypatch.delenv("LITELLM_PROXY_URL", raising=False)

    result = await cc._tool_analyze_dashboard({}, "u", None)

    assert result["error"] == "LLM not configured"


# --- the optional PG persistence wrappers ------------------------------------


def _fresh_chat_completion_with_deploy_target(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Load an isolated copy of chat_completion with the deploy-target env set.

    The PG memory wrappers are installed at import time behind
    ``DEPLOY_TARGET_APP_ENV``; loading a fresh copy (rather than reloading the
    shared module) leaves every other test's module bindings untouched.
    """
    monkeypatch.setenv("DEPLOY_TARGET_APP_ENV", "test")
    script = BACKEND_ROOT / "hive_conductor" / "services" / "chat_completion.py"
    spec = importlib.util.spec_from_file_location("_chat_completion_deploy_target", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[spec.name]
        raise
    return module


async def test_deploy_target_memory_add_persists_through_pg_upsert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fresh = _fresh_chat_completion_with_deploy_target(monkeypatch)

    async def fake_add(_args: Any, _user_id: Any, _jira_pat: Any = None) -> dict[str, Any]:
        return {"saved": True, "id": "mem-1134"}

    calls: list[tuple[str, dict[str, Any]]] = []

    import hive_conductor.services.pg_store as pg_store

    async def fake_upsert(table: str, row: dict[str, Any]) -> None:
        calls.append((table, row))

    monkeypatch.setattr(fresh, "_orig_memory_add", fake_add)
    monkeypatch.setattr(pg_store, "pg_upsert", fake_upsert)

    handler = fresh._TOOL_HANDLERS["memory_add"]
    result = await handler({"content": "note", "namespace": "general"}, "user-1134")

    assert result["id"] == "mem-1134"
    assert calls and calls[0][0] == "hive_memory_entries"
    assert calls[0][1]["id"] == "mem-1134"


async def test_deploy_target_memory_delete_persists_through_pg_delete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fresh = _fresh_chat_completion_with_deploy_target(monkeypatch)

    async def fake_delete(_args: Any, _user_id: Any, _jira_pat: Any = None) -> dict[str, Any]:
        return {"deleted": True, "id": "mem-1135"}

    deleted: list[tuple[str, str]] = []

    import hive_conductor.services.pg_store as pg_store

    async def fake_pg_delete(table: str, row_id: str) -> None:
        deleted.append((table, row_id))

    monkeypatch.setattr(fresh, "_orig_memory_delete", fake_delete)
    monkeypatch.setattr(pg_store, "pg_delete", fake_pg_delete)

    handler = fresh._TOOL_HANDLERS["memory_delete"]
    result = await handler({"id": "mem-1135"}, "user-1134")

    assert result["deleted"] is True
    assert deleted == [("hive_memory_entries", "mem-1135")]


# --- pipeline_orchestrator: the external-CI trigger --------------------------


async def test_trigger_deploy_force_overrides_a_blocking_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The force flag must skip the refusal and submit the build job.

    ``tork_client`` is the external CI collaborator; it is stubbed at the
    package seam so the trigger's own logic — refusal, YAML build, submit —
    is what executes, through the package-qualified lazy import.
    """
    from hive_conductor.services import pipeline_orchestrator

    submitted: list[str] = []

    def fake_build_job_yaml(**kwargs: Any) -> str:
        return f"yaml-for-{kwargs['project_id']}"

    async def fake_submit_job(yaml: str) -> str:
        submitted.append(yaml)
        return "job-1134"

    fake_tork = types.SimpleNamespace(
        build_job_yaml=fake_build_job_yaml, submit_job=fake_submit_job
    )
    # The lazy import resolves `hive_conductor.services.tork_client` at call
    # time, so the attribute has to exist on the package itself.
    import hive_conductor.services as services_pkg

    monkeypatch.setattr(services_pkg, "tork_client", fake_tork, raising=False)

    result = await pipeline_orchestrator.trigger_deploy(
        "proj-1134",
        scan_summary={"blocking": True},
        force=True,
    )

    assert result == {"tork_job_id": "job-1134", "status": "building"}
    assert submitted == ["yaml-for-proj-1134"]


async def test_trigger_deploy_refuses_a_blocking_scan_without_force(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from hive_conductor.services import pipeline_orchestrator

    with pytest.raises(Exception, match="blocking"):
        await pipeline_orchestrator.trigger_deploy(
            "proj-1134", scan_summary={"blocking": True}, force=False
        )


# --- ui_auto_climb: one autonomous pass ---------------------------------------


async def test_auto_climb_runs_one_pass_over_the_component(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from hive_conductor.services import ui_auto_climb

    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "Chat.tsx").write_text("export const Chat = () => null;\n", encoding="utf-8")
    monkeypatch.setattr(ui_auto_climb, "PAGES_DIR", pages)

    async def fake_screenshot(_url: str, _path: str) -> str:
        return "c3RhYiI="  # a captured frame, so the visual scorer runs too

    async def fake_score_visual(_img: Any) -> dict[str, Any]:
        return {"score": 60, "top_issue": "cramped"}

    async def fake_generate_edit(*_args: Any) -> None:
        return None  # no LLM in CI: no edit is produced

    monkeypatch.setattr(ui_auto_climb, "screenshot", fake_screenshot)
    monkeypatch.setattr(ui_auto_climb, "score_visual", fake_score_visual)
    monkeypatch.setattr(ui_auto_climb, "generate_edit", fake_generate_edit)

    import hive_conductor.services.ui_hill_climber as climber

    async def fake_score_ui_code(code: str) -> dict[str, Any]:
        assert "Chat" in code
        return {"score": 40, "top_issue": "no error boundary"}

    monkeypatch.setattr(climber, "score_ui_code", fake_score_ui_code)

    result = await ui_auto_climb.auto_climb("Chat.tsx", max_passes=1)

    assert result["best_score"] == 50  # (60 visual + 40 code) // 2
    assert result["history"] == [{"pass": 1, "score": 50, "action": "baseline"}]


# --- credential_store_v2: the module resolves through the package ------------


def test_credential_store_v2_imports_through_the_package() -> None:
    """The v2 store module's `from __future__` line is its migrated first
    statement; nothing else imports this module in-process, so this is the
    executed proof it resolves through the ``hive_conductor`` namespace."""
    from hive_conductor.services import credential_store_v2

    assert credential_store_v2.TABLE == "hive_credentials_v2"
    assert hasattr(credential_store_v2, "AgnosticCredentialStore")
