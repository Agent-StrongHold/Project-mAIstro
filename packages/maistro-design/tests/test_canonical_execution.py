"""Design Studio operations converge on the canonical execution spine (#52)."""

from __future__ import annotations

import base64
import json
from typing import Any

import pytest

from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.model import AttemptStatus, RunStatus
from maistro.runs.store import InMemoryRunStore, RunIntegrityError
from maistro_design.canonical_execution import DesignCanonicalExecution
from maistro_design.types import (
    ArtifactKind,
    ArtifactNode,
    DesignOutput,
    DesignProject,
    DiscoveryResult,
    OutputFormat,
    TrustTier,
)

pytestmark = pytest.mark.asyncio


async def _execution() -> tuple[DesignCanonicalExecution, InMemoryRunStore]:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("workspace-design")
    runs = InMemoryRunStore(project_store=projects)
    return (
        DesignCanonicalExecution(
            runs,
            workspace_id=root.workspace_id,
            project_id=root.project_id,
        ),
        runs,
    )


async def test_design_operation_persists_run_noderun_and_attempt() -> None:
    canonical, runs = await _execution()
    discovery = DiscoveryResult(
        skill_slug="login-flow",
        responses={"auth_methods": "email"},
        design_system_slug="default",
    )
    run_id = await canonical.admit(discovery=discovery, actor_principal_id="principal-1")
    result = await canonical.execute(
        run_id,
        lambda: _value({"project_id": "design-project-1"}),
    )

    assert result == {"project_id": "design-project-1"}
    run = await runs.get_run(run_id)
    assert run is not None
    assert run.workspace_id == "workspace-design"
    assert run.project_id != "workspace-design"
    assert run.actor_principal_id == "principal-1"
    assert run.status is RunStatus.COMPLETED
    node_runs = await runs.list_node_runs(run.run_id)
    assert len(node_runs) == 1
    assert node_runs[0].status is RunStatus.COMPLETED
    attempts = await runs.list_attempts(node_runs[0].node_run_id)
    assert [attempt.status for attempt in attempts] == [AttemptStatus.COMPLETED]
    assert attempts[0].result == {"project_id": "design-project-1"}


async def test_adapter_rejects_a_run_outside_its_bound_scope() -> None:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("workspace-design")
    child = await projects.create(
        workspace_id=root.workspace_id,
        parent_project_id=root.project_id,
        name="other-scope",
    )
    runs = InMemoryRunStore(project_store=projects)
    bound = DesignCanonicalExecution(
        runs,
        workspace_id=root.workspace_id,
        project_id=root.project_id,
    )
    other = DesignCanonicalExecution(
        runs,
        workspace_id=child.workspace_id,
        project_id=child.project_id,
    )
    discovery = DiscoveryResult(
        skill_slug="login-flow",
        responses={"auth_methods": "email"},
        design_system_slug="default",
    )
    run_id = await other.admit(discovery=discovery, actor_principal_id="principal-1")

    async def _must_not_execute() -> Any:
        raise AssertionError("an out-of-scope operation must not reach the provider")

    with pytest.raises(RunIntegrityError, match="outside its bound"):
        await bound.execute(run_id, _must_not_execute)


async def test_replay_rebuilds_design_project_from_durable_attempt_evidence() -> None:
    """A replayed completed Run returns a DesignProject, not a JSON-hydrated dict."""
    canonical, runs = await _execution()
    discovery = DiscoveryResult(
        skill_slug="login-flow",
        responses={"auth_methods": "email"},
        design_system_slug="default",
    )
    png = b"\x89PNG-not-utf8"
    project = DesignProject(
        id="design-project-1",
        name="Login Flow (Default)",
        skill_slug="login-flow",
        design_system_slug="default",
        org_id="default-org",
        trust_tier=TrustTier.T2,
        canvas_id=None,
        outputs=[
            DesignOutput(
                root=ArtifactNode(
                    key="png",
                    kind=ArtifactKind.BLOB,
                    format=OutputFormat.PNG,
                    value=png,
                ),
                trust_tier=TrustTier.T2,
            )
        ],
        discovery=discovery,
    )
    run_id = await canonical.admit(discovery=discovery, actor_principal_id="principal-1")
    generated = await canonical.execute(run_id, lambda: _value(project))
    assert generated is project

    async def _must_not_execute() -> Any:
        raise AssertionError("a completed Design Run must not reach the provider again")

    replayed = await canonical.execute(run_id, _must_not_execute)
    assert isinstance(replayed, DesignProject)
    assert replayed == project
    assert replayed.outputs[0].root.value == png

    # The Attempt carries the JSON-stable DTO the durable stores hydrate.
    node_run = (await runs.list_node_runs(run_id))[0]
    (attempt,) = await runs.list_attempts(node_run.node_run_id)
    hydrated = json.loads(json.dumps(attempt.result))
    assert DesignProject.from_payload(hydrated["project"]) == project
    assert base64.b64decode(hydrated["project"]["outputs"][0]["root"]["value"]["__bytes_b64__"])


async def test_design_failure_is_a_failed_attempt_and_failed_run() -> None:
    canonical, runs = await _execution()
    discovery = DiscoveryResult(
        skill_slug="login-flow",
        responses={"auth_methods": "email"},
        design_system_slug="default",
    )

    async def _fail() -> Any:
        raise RuntimeError("design provider unavailable")

    with pytest.raises(RuntimeError, match="design provider unavailable"):
        run_id = await canonical.admit(discovery=discovery, actor_principal_id="principal-1")
        await canonical.execute(run_id, _fail)

    run = await runs.get_run(run_id)
    assert run is not None
    assert run.status is RunStatus.FAILED
    node_run = (await runs.list_node_runs(run.run_id))[0]
    assert node_run.status is RunStatus.FAILED
    attempts = await runs.list_attempts(node_run.node_run_id)
    assert len(attempts) == 1
    assert attempts[0].status is AttemptStatus.FAILED
    assert attempts[0].error == "design provider unavailable"


async def test_generate_admits_and_executes_in_one_call() -> None:
    canonical, runs = await _execution()
    discovery = DiscoveryResult(
        skill_slug="login-flow",
        responses={"auth_methods": "email"},
        design_system_slug="default",
    )
    result = await canonical.generate(
        discovery=discovery,
        operation=lambda: _value({"ok": True}),
        actor_principal_id="principal-1",
    )
    assert result == {"ok": True}
    stored = list(runs._runs.values())
    assert len(stored) == 1
    assert stored[0].status is RunStatus.COMPLETED


async def test_blank_scope_bindings_are_refused() -> None:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("workspace-design")
    runs = InMemoryRunStore(project_store=projects)
    with pytest.raises(ValueError, match="workspace_id"):
        DesignCanonicalExecution(runs, workspace_id="  ", project_id=root.project_id)
    with pytest.raises(ValueError, match="project_id"):
        DesignCanonicalExecution(runs, workspace_id=root.workspace_id, project_id="")


async def test_admit_rolls_back_when_queue_transition_fails() -> None:
    canonical, runs = await _execution()
    discovery = DiscoveryResult(
        skill_slug="login-flow",
        responses={"auth_methods": "email"},
        design_system_slug="default",
    )
    original = runs.transition_run

    async def _fail_queue(run_id: str, status: RunStatus, **kwargs: Any) -> Any:
        if status is RunStatus.QUEUED:
            raise RuntimeError("queue full")
        return await original(run_id, status, **kwargs)

    runs.transition_run = _fail_queue  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="queue full"):
        await canonical.admit(discovery=discovery, actor_principal_id="principal-1")
    assert list(runs._runs.values()) == []


async def test_replay_refuses_a_completed_noderun_without_a_completed_attempt() -> None:
    canonical, runs = await _execution()
    discovery = DiscoveryResult(
        skill_slug="login-flow",
        responses={"auth_methods": "email"},
        design_system_slug="default",
    )
    run_id = await canonical.admit(discovery=discovery, actor_principal_id="principal-1")
    await canonical.execute(run_id, lambda: _value({"project_id": "p-1"}))
    node_run = (await runs.list_node_runs(run_id))[0]
    for attempt_id, attempt in list(runs._attempts.items()):
        if attempt.node_run_id == node_run.node_run_id:
            runs._attempts[attempt_id] = attempt.model_copy(
                update={"status": AttemptStatus.FAILED}
            )

    with pytest.raises(RunIntegrityError, match="no completed Attempt"):
        await canonical.execute(run_id, lambda: _value({"must": "not run"}))


async def test_execute_rebuilds_from_attempt_when_capture_is_empty() -> None:
    """Durable stores may complete the Attempt without a process-local capture."""
    from maistro_design import canonical_execution as mod

    canonical, _runs = await _execution()
    discovery = DiscoveryResult(
        skill_slug="login-flow",
        responses={"auth_methods": "email"},
        design_system_slug="default",
    )
    project = DesignProject(
        id="design-project-2",
        name="Login Flow (Default)",
        skill_slug="login-flow",
        design_system_slug="default",
        org_id="default-org",
        trust_tier=TrustTier.T2,
        outputs=[
            DesignOutput(
                root=ArtifactNode(
                    key="prompt",
                    kind=ArtifactKind.FILE,
                    format=OutputFormat.MARKDOWN,
                    value="# hello",
                ),
                trust_tier=TrustTier.T2,
            )
        ],
        discovery=discovery,
    )
    run_id = await canonical.admit(discovery=discovery, actor_principal_id="principal-1")
    original_execute = canonical._service.execute_node

    async def _execute_node(*args: Any, executor: Any = None, **kwargs: Any) -> Any:
        async def _wrapper(_work_item: object, _context: object) -> Any:
            # Intentionally skip the outer `captured.append` so execute must
            # rebuild from Attempt evidence (the durable-store replay shape).
            return mod._result_as_evidence(project)

        return await original_execute(*args, executor=_wrapper, **kwargs)

    canonical._service.execute_node = _execute_node  # type: ignore[method-assign]
    rebuilt = await canonical.execute(run_id, lambda: _value(project))
    assert isinstance(rebuilt, DesignProject)
    assert rebuilt == project
    assert rebuilt.outputs[0].root.value == "# hello"


async def test_fail_is_a_noop_on_an_already_terminal_run() -> None:
    canonical, runs = await _execution()
    discovery = DiscoveryResult(
        skill_slug="login-flow",
        responses={"auth_methods": "email"},
        design_system_slug="default",
    )

    async def _fail() -> Any:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        run_id = await canonical.admit(discovery=discovery, actor_principal_id="principal-1")
        await canonical.execute(run_id, _fail)

    await canonical.fail(run_id, "ignored")
    run = await runs.get_run(run_id)
    assert run is not None
    assert run.status is RunStatus.FAILED


async def test_fail_resumes_created_and_queued_runs() -> None:
    canonical, runs = await _execution()
    discovery = DiscoveryResult(
        skill_slug="login-flow",
        responses={"auth_methods": "email"},
        design_system_slug="default",
    )
    queued_id = await canonical.admit(discovery=discovery, actor_principal_id="principal-1")
    await canonical.fail(queued_id, "provider down")
    queued = await runs.get_run(queued_id)
    assert queued is not None
    assert queued.status is RunStatus.FAILED
    assert queued.error == "provider down"

    created_id = await canonical.admit(discovery=discovery, actor_principal_id="principal-1")
    created = await runs.get_run(created_id)
    assert created is not None
    runs._runs[created_id] = created.model_copy(update={"status": RunStatus.CREATED})
    await canonical.fail(created_id, "never started")
    resumed = await runs.get_run(created_id)
    assert resumed is not None
    assert resumed.status is RunStatus.FAILED


async def test_fail_refuses_a_run_that_cannot_resume() -> None:
    canonical, runs = await _execution()
    discovery = DiscoveryResult(
        skill_slug="login-flow",
        responses={"auth_methods": "email"},
        design_system_slug="default",
    )
    run_id = await canonical.admit(discovery=discovery, actor_principal_id="principal-1")
    run = await runs.get_run(run_id)
    assert run is not None
    runs._runs[run_id] = run.model_copy(update={"status": RunStatus.PAUSED})
    with pytest.raises(RunIntegrityError, match="cannot execute from"):
        await canonical.fail(run_id, "stuck")


async def test_fail_skips_already_terminal_node_runs() -> None:
    canonical, runs = await _execution()
    discovery = DiscoveryResult(
        skill_slug="login-flow",
        responses={"auth_methods": "email"},
        design_system_slug="default",
    )
    run_id = await canonical.admit(discovery=discovery, actor_principal_id="principal-1")
    await canonical.execute(run_id, lambda: _value({"ok": True}))
    # Re-open the Run while leaving the NodeRun terminal so fail() walks the
    # continue branch for finished nodes before failing the Run itself.
    run = await runs.get_run(run_id)
    assert run is not None
    runs._runs[run_id] = run.model_copy(update={"status": RunStatus.RUNNING, "error": None})
    await canonical.fail(run_id, "late failure")
    failed = await runs.get_run(run_id)
    assert failed is not None
    assert failed.status is RunStatus.FAILED


async def test_execute_rejects_a_missing_run() -> None:
    canonical, _runs = await _execution()

    async def _must_not_run() -> Any:
        raise AssertionError("missing run must not execute")

    with pytest.raises(RunIntegrityError, match="does not exist"):
        await canonical.execute("missing-run", _must_not_run)


async def test_multiple_noderuns_for_the_same_node_are_integrity_errors() -> None:
    canonical, runs = await _execution()
    discovery = DiscoveryResult(
        skill_slug="login-flow",
        responses={"auth_methods": "email"},
        design_system_slug="default",
    )
    run_id = await canonical.admit(discovery=discovery, actor_principal_id="principal-1")
    await canonical.execute(run_id, lambda: _value({"once": True}))
    node_runs = await runs.list_node_runs(run_id)
    assert len(node_runs) == 1
    duplicate = node_runs[0]
    # Plant a second NodeRun with the same node_id so the lookup refuses.
    runs._node_runs[f"dup-{duplicate.node_run_id}"] = duplicate.model_copy(
        update={"node_run_id": f"dup-{duplicate.node_run_id}"}
    )
    with pytest.raises(RunIntegrityError, match="multiple NodeRuns"):
        await canonical.execute(run_id, lambda: _value({"twice": True}))


async def test_text_artifact_payload_round_trips_without_bytes_tag() -> None:
    """Non-BLOB leaves stay plain strings through the durable Attempt DTO."""
    project = DesignProject(
        id="design-project-text",
        name="Text",
        skill_slug="login-flow",
        design_system_slug="default",
        org_id="default-org",
        outputs=[
            DesignOutput(
                root=ArtifactNode(
                    key="prompt",
                    kind=ArtifactKind.FILE,
                    format=OutputFormat.MARKDOWN,
                    value="plain text",
                ),
                trust_tier=TrustTier.T2,
            )
        ],
    )
    payload = project.to_payload()
    assert payload["outputs"][0]["root"]["value"] == "plain text"
    rebuilt = DesignProject.from_payload(payload)
    assert rebuilt.outputs[0].root.value == "plain text"

    with pytest.raises(TypeError, match="str, bytes, or None"):
        DesignProject.from_payload(
            {
                **payload,
                "outputs": [
                    {
                        **payload["outputs"][0],
                        "root": {**payload["outputs"][0]["root"], "value": 123},
                    }
                ],
            }
        )


async def test_untagged_attempt_evidence_passes_through() -> None:
    """Non-project Attempt results (and malformed envelopes) are returned as-is."""
    from maistro_design.canonical_execution import _result_from_evidence

    assert _result_from_evidence({"plain": True}) == {"plain": True}
    assert _result_from_evidence({"design_result": "design.project.v1", "project": "nope"}) == {
        "design_result": "design.project.v1",
        "project": "nope",
    }


async def _value(value: Any) -> Any:
    return value
