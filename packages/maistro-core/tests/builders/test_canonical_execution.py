"""Behavioral and canonical evidence for the Builders execution adapter (#734)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from maistro.builders.graph import PipelineGraph, PipelineNode, RunContext
from maistro.builders.graph_executor import (
    _DEFAULT_EXECUTIONS_PER_NODE,
    CanonicalGraphPipelineExecutor,
    DispatchResult,
    _build_prompt,
    _canonical_graph,
    _derived_max_steps,
    _mark_skipped,
    _project_canonical_record,
    _resolver,
)
from maistro.builders.pipeline import PipelineRun, PipelineStage, StageStatus
from maistro.graph.durable_runs import (
    CanonicalDurableRunStore,
    InMemoryGraphContinuationStore,
)
from maistro.graph.node import IterationBudget
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.model import RunStatus
from maistro.runs.store import InMemoryRunStore

pytestmark = pytest.mark.contract("behavioral")


def test_canonical_adapter_is_public_and_executor_names_are_not_exported() -> None:
    import maistro.builders as builders

    assert not hasattr(builders, "GraphPipelineExecutor")
    assert builders.CanonicalGraphPipelineExecutor is CanonicalGraphPipelineExecutor


def test_build_prompt_falls_back_to_raw_template_on_malformed_format_spec() -> None:
    assert _build_prompt("{0!Z}", {}) == "{0!Z}"


class ScriptedDispatcher:
    """Deterministic stage dispatcher with concurrency and failure instrumentation."""

    def __init__(
        self,
        outputs: dict[str, str | list[str]] | None = None,
        *,
        fail: set[str] | None = None,
        unsupported: set[str] | None = None,
        delay: float = 0.0,
        delays: dict[str, float] | None = None,
    ) -> None:
        self._outputs = outputs or {}
        self._fail = fail or set()
        self._unsupported = unsupported or set()
        self._delay = delay
        self._delays = delays or {}
        self.calls: list[str] = []
        # A snapshot of `context` (copied, since it's a live shared dict) at
        # the moment each dispatch began -- lets a test assert what a stage
        # actually saw, not just what it output.
        self.contexts: dict[str, list[dict[str, Any]]] = {}
        self.in_flight = 0
        self.max_in_flight = 0

    def supports(self, agent_name: str, node_name: str) -> bool:
        return node_name not in self._unsupported

    async def run(
        self,
        *,
        run_id: str,
        node_name: str,
        agent_name: str,
        prompt: str,
        context: RunContext,
    ) -> DispatchResult:
        self.calls.append(node_name)
        self.contexts.setdefault(node_name, []).append(dict(context))
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            delay = self._delays.get(node_name, self._delay)
            if delay:
                await asyncio.sleep(delay)
            if node_name in self._fail:
                return DispatchResult(ok=False, error=f"{node_name} broke")
            scripted = self._outputs.get(node_name, f"{node_name} output")
            if isinstance(scripted, list):
                index = min(self.calls.count(node_name) - 1, len(scripted) - 1)
                output = scripted[index]
            else:
                output = scripted
            return DispatchResult(ok=True, output=output)
        finally:
            self.in_flight -= 1


def _node(name: str, deps: tuple[str, ...] = (), **kwargs: Any) -> PipelineNode:
    return PipelineNode(
        name=name,
        agent_name=f"agent-{name}",
        prompt_template="do {title}",
        depends_on=deps,
        **kwargs,
    )


def _run(graph: PipelineGraph, *, run_id: str) -> PipelineRun:
    nodes = list(graph)
    run = PipelineRun(
        id=run_id,
        issue_number=734,
        title="Converge Builders",
        repo="Agent-StrongHold/Project-mAIstro",
        stages=[
            PipelineStage(
                name=node.name,
                agent_name=node.agent_name,
                prompt_template=node.prompt_template,
            )
            for node in nodes
        ],
    )
    run.context.update(
        {
            "issue_number": run.issue_number,
            "title": run.title,
            "repo": run.repo,
        }
    )
    return run


@dataclass
class _Owner:
    workspace_id: str
    project_id: str
    run_store: InMemoryRunStore
    durable_store: CanonicalDurableRunStore


async def _owner() -> _Owner:
    workspace_id = "workspace-builders"
    project_store = InMemoryProjectScopeStore()
    await project_store.create_root(workspace_id)
    project = await project_store.root_for_workspace(workspace_id)
    run_store = InMemoryRunStore(project_store=project_store)
    continuation = InMemoryGraphContinuationStore()
    return _Owner(
        workspace_id=workspace_id,
        project_id=project.project_id,
        run_store=run_store,
        durable_store=CanonicalDurableRunStore(run_store, continuation),
    )


async def _canonical(
    graph: PipelineGraph,
    dispatcher: ScriptedDispatcher,
    *,
    budget: IterationBudget | None = None,
) -> tuple[PipelineRun, Any, _Owner]:
    owner = await _owner()
    run = _run(graph, run_id="builders-domain-run")
    executor = CanonicalGraphPipelineExecutor(
        dispatcher,
        run_store=owner.run_store,
        durable_store=owner.durable_store,
        workspace_id=owner.workspace_id,
        project_id=owner.project_id,
        budget=budget,
    )
    record = await executor.execute(graph, run)
    return run, record, owner


@pytest.mark.asyncio
async def test_stage_wave_creates_one_canonical_run_node_runs_and_attempts() -> None:
    graph = PipelineGraph(
        [
            _node("spec"),
            _node("tests", ("spec",)),
            _node("code", ("spec",)),
            _node("review", ("tests", "code")),
        ]
    )
    dispatcher = ScriptedDispatcher(delay=0.01)

    canonical_run, record, owner = await _canonical(graph, dispatcher)

    assert canonical_run.status == "completed"
    assert dispatcher.calls == [
        "spec",
        "tests",
        "code",
        "review",
    ]
    assert dispatcher.max_in_flight == 2

    stored = await owner.run_store.get_run(record.run_id)
    assert stored is not None
    assert stored.status is RunStatus.COMPLETED
    assert stored.provenance["admission_source"] == "builders"
    assert stored.provenance["pipeline_id"] == "builders-domain-run"
    assert canonical_run.canonical_run_id == record.run_id

    node_runs = await owner.run_store.list_node_runs(record.run_id)
    assert [item.node_id for item in node_runs] == [
        "builders-stage:spec",
        "builders-stage:tests",
        "builders-stage:code",
        "builders-stage:review",
    ]
    attempts = []
    for node_run in node_runs:
        attempts.extend(await owner.run_store.list_attempts(node_run.node_run_id))
    assert len(attempts) == len(node_runs)
    assert len({attempt.attempt_id for attempt in attempts}) == len(attempts)


@pytest.mark.asyncio
async def test_multiple_root_ready_wave_preserves_concurrency_with_control_frontier() -> None:
    graph = PipelineGraph(
        [
            _node("tests"),
            _node("code"),
            _node("review", ("tests", "code")),
        ]
    )
    dispatcher = ScriptedDispatcher(delay=0.01)

    canonical_run, record, owner = await _canonical(graph, dispatcher)

    assert canonical_run.status == "completed"
    assert dispatcher.max_in_flight == 2
    assert dispatcher.calls == ["tests", "code", "review"]

    node_runs = await owner.run_store.list_node_runs(record.run_id)
    stage_runs = [item for item in node_runs if item.node_id.startswith("builders-stage:")]
    assert [item.node_id for item in stage_runs] == [
        "builders-stage:tests",
        "builders-stage:code",
        "builders-stage:review",
    ]
    assert node_runs[0].node_id == "builders-frontier-start"


@pytest.mark.asyncio
async def test_skip_and_unsupported_stage_domain_projection() -> None:
    graph = PipelineGraph(
        [
            _node("spec", skip_if=lambda ctx: True),
            _node("tests", ("spec",)),
            _node("code", ("tests",)),
        ]
    )
    dispatcher = ScriptedDispatcher(unsupported={"tests"})

    canonical_run, record, owner = await _canonical(graph, dispatcher)

    assert canonical_run.status == "completed"
    assert canonical_run.skipped_stages == ["spec", "tests"]
    assert dispatcher.calls == ["code"]
    assert [stage.status for stage in canonical_run.stages] == [
        StageStatus.SKIPPED,
        StageStatus.SKIPPED,
        StageStatus.COMPLETED,
    ]

    node_runs = await owner.run_store.list_node_runs(record.run_id)
    assert node_runs[0].result["skipped"] is True
    assert node_runs[1].result["skipped"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["failure", "timeout"])
async def test_failure_and_timeout_terminal_behavior(mode: str) -> None:
    """The canonical adapter's externally visible terminal behavior."""
    graph = PipelineGraph([_node("tests", timeout_seconds=0.001 if mode == "timeout" else 600.0)])
    kwargs: dict[str, Any] = {}
    if mode == "failure":
        kwargs["fail"] = {"tests"}
    else:
        kwargs["delay"] = 0.02
    dispatcher = ScriptedDispatcher(**kwargs)

    canonical_run, record, owner = await _canonical(graph, dispatcher)

    assert canonical_run.status == "failed at tests"
    assert dispatcher.calls == ["tests"]
    assert record.run.status is RunStatus.FAILED
    node_runs = await owner.run_store.list_node_runs(record.run_id)
    assert len(node_runs) == 1
    assert node_runs[0].status is RunStatus.FAILED


@pytest.mark.asyncio
async def test_gate_revision_is_new_node_run_and_attempt_evidence_with_feedback() -> None:
    outputs = {"review": ["VIOLATION: missing tests", "APPROVED"]}
    graph = PipelineGraph(
        [
            _node("implement"),
            _node(
                "review",
                ("implement",),
                gate=lambda ctx: "approved" in str(ctx.get("review", "")).lower(),
                revise_target="implement",
                max_revisions=2,
            ),
        ]
    )
    dispatcher = ScriptedDispatcher(outputs=outputs)

    canonical_run, record, owner = await _canonical(graph, dispatcher)

    expected_calls = ["implement", "review", "implement", "review"]
    assert dispatcher.calls == expected_calls
    assert canonical_run.status == "completed"
    assert canonical_run.revisions == {"review": 1}
    assert canonical_run.context["review_feedback"] == "VIOLATION: missing tests"
    assert canonical_run.context["review"] == "APPROVED"

    node_runs = await owner.run_store.list_node_runs(record.run_id)
    assert [item.node_id for item in node_runs] == [
        "builders-stage:implement",
        "builders-stage:review",
        "builders-stage:implement",
        "builders-stage:review",
    ]
    assert node_runs[1].result["route"] == "revise"
    assert node_runs[3].result["route"] == "proceed"
    attempts = []
    for node_run in node_runs:
        attempts.extend(await owner.run_store.list_attempts(node_run.node_run_id))
    assert len(attempts) == 4
    assert len({attempt.attempt_id for attempt in attempts}) == 4


@pytest.mark.asyncio
async def test_revision_dominates_a_concurrent_wave_after_it_settles() -> None:
    """#1067 defect 1: legacy gathers a whole wave, *then* applies gate failures.

    ``plan`` is the revise target. ``gate`` and ``sibling`` are both direct,
    concurrent children of ``plan`` -- one ready wave. ``sibling`` is the
    slower of the two, so its dispatch (and its write into ``run.context``)
    lands after ``gate``'s failed-gate decision would, under the old
    eager/synchronous invalidation, already have cleared ``run.context`` for
    the stale set -- reproducing the exact race the old code lost. Against
    unpatched code this test fails: the stale ``sibling-v1`` write survives
    into ``plan``'s second dispatch, and ``successor`` (which depends only on
    ``sibling``, one hop further out) gets dispatched *twice* -- once
    prematurely, riding on the stale/incomplete wave, and once for real.
    """
    graph = PipelineGraph(
        [
            _node("plan"),
            _node(
                "gate",
                ("plan",),
                gate=lambda ctx: str(ctx.get("gate", "")).startswith("OK"),
                revise_target="plan",
                max_revisions=2,
            ),
            _node("sibling", ("plan",)),
            _node("successor", ("sibling",)),
        ]
    )
    dispatcher = ScriptedDispatcher(
        outputs={
            "gate": ["VIOLATION", "OK"],
            "sibling": ["sibling-v1", "sibling-v2"],
            "successor": "successor output",
        },
        # `gate` also gets a (smaller) delay so its coroutine actually
        # suspends and lets `sibling`'s coroutine start (and begin its own
        # real dispatch) before `gate`'s gate-failure decision fires --
        # otherwise a zero-delay gate can run to completion, decision and
        # all, before `sibling` gets its first turn at all, which changes
        # which race this test is exercising.
        delays={"gate": 0.01, "sibling": 0.03},
    )

    canonical_run, _record, _owner = await _canonical(graph, dispatcher)

    assert canonical_run.status == "completed"
    # `sibling` genuinely re-ran once the revision settled (real dispatch
    # twice). `successor` must have run for real exactly once -- under the
    # old eager-invalidation bug it runs twice: once too early (a premature
    # echo riding on `sibling`'s stale/incomplete wave), once for real.
    assert dispatcher.calls.count("sibling") == 2
    assert dispatcher.calls.count("successor") == 1
    assert canonical_run.context["sibling"] == "sibling-v2"
    assert canonical_run.context["successor"] == "successor output"
    # The only real dispatch of `successor` must have seen the *fresh*
    # sibling output, never the stale or missing one.
    assert dispatcher.contexts["successor"][0].get("sibling") == "sibling-v2"
    # Right after the wave settles (`plan`'s revision redispatch), the stale
    # sibling output must be gone from run.context, not merely overwritten
    # later.
    assert "sibling" not in dispatcher.contexts["plan"][1]


@pytest.mark.asyncio
async def test_revision_dominates_a_concurrent_wave_with_an_immediate_dispatcher() -> None:
    """#1067 follow-up (Codex review, 2026-09-21): flush must be per-frontier, not per-task.

    ``test_revision_dominates_a_concurrent_wave_after_it_settles`` only
    reproduces the wave-ordering race by *delaying* ``gate`` just enough to
    let ``sibling`` start its own real dispatch first. It does not exercise
    the version of the race that matters most: with a fast/immediate
    dispatcher (no artificial delay at all, as here), ``gate`` -- the first
    task ``asyncio.gather`` steps in this wave -- can run to full completion,
    including queuing its own gate failure with ``_RevisionLedger``, before
    ``sibling`` -- its wave-mate in the very same ``asyncio.gather`` batch --
    ever gets its own first turn. A flush applied from inside each stage's
    own ``_execute`` (as an earlier version of the #1067 fix did) would then
    apply that invalidation to ``sibling`` *before* ``sibling`` was ever
    dispatched, failing it out of the stale guard and silently eating its
    legacy-mandated real dispatch instead of giving every member of the
    admitted wave a genuine chance to run -- undoing defect 1's own fix.
    """
    graph = PipelineGraph(
        [
            _node("plan"),
            _node(
                "gate",
                ("plan",),
                gate=lambda ctx: str(ctx.get("gate", "")).startswith("OK"),
                revise_target="plan",
                max_revisions=2,
            ),
            _node("sibling", ("plan",)),
            _node("successor", ("sibling",)),
        ]
    )
    dispatcher = ScriptedDispatcher(
        outputs={
            "gate": ["VIOLATION", "OK"],
            "sibling": ["sibling-v1", "sibling-v2"],
            "successor": "successor output",
        },
        # No delays at all: gate resolves immediately.
    )

    canonical_run, _record, _owner = await _canonical(graph, dispatcher)

    assert canonical_run.status == "completed"
    # `sibling` must be genuinely dispatched twice: once as an ordinary
    # member of the wave that also contained `gate` (before the revision
    # was ever decided), and once for real once the revision settles --
    # never silently skipped out of its first, legitimate dispatch.
    assert dispatcher.calls.count("sibling") == 2
    assert dispatcher.calls.count("successor") == 1
    assert canonical_run.context["sibling"] == "sibling-v2"
    assert canonical_run.context["successor"] == "successor output"
    assert canonical_run.skipped_stages == []


@pytest.mark.asyncio
async def test_stale_guard_defer_does_not_survive_a_genuine_later_failure() -> None:
    """#1067 follow-up (Codex review, 2026-09-21): the transient guard marker must not stick.

    ``successor`` is prematurely routed into a frontier riding on
    ``sibling``'s stale/incomplete wave (the same setup as
    ``test_revision_dominates_a_concurrent_wave_after_it_settles``), so it
    hits ``_stale_guard_output`` and is transiently added to
    ``run.skipped_stages``. Its later, *genuine* redispatch (once `sibling`
    truly re-completes) is made to fail for real. Before this fix, nothing
    ever reached ``_route_stage_result``'s ``_unmark_skipped`` for that real
    failure, so the transient marker outlived it and
    ``_project_stage`` -- which checks ``run.skipped_stages`` before NodeRun
    status -- reported ``successor`` as SKIPPED even though the canonical
    Run and its NodeRun both genuinely FAILED there.
    """
    graph = PipelineGraph(
        [
            _node("plan"),
            _node(
                "gate",
                ("plan",),
                gate=lambda ctx: str(ctx.get("gate", "")).startswith("OK"),
                revise_target="plan",
                max_revisions=2,
            ),
            _node("sibling", ("plan",)),
            _node("successor", ("sibling",)),
        ]
    )
    dispatcher = ScriptedDispatcher(
        outputs={
            "gate": ["VIOLATION", "OK"],
            "sibling": ["sibling-v1", "sibling-v2"],
        },
        fail={"successor"},
        delays={"gate": 0.01, "sibling": 0.03},
    )

    run, record, _owner = await _canonical(graph, dispatcher)

    assert record.run.status is RunStatus.FAILED
    assert run.status == "failed at successor"
    assert run.failed_stage_error == "successor broke"
    # The transient stale-guard defer must not linger once `successor`'s
    # real (failing) dispatch has run.
    assert "successor" not in run.skipped_stages
    successor_stage = next(stage for stage in run.stages if stage.name == "successor")
    assert successor_stage.status is StageStatus.FAILED
    assert successor_stage.error == "successor broke"


@pytest.mark.asyncio
async def test_gate_without_revise_target_reoffers_itself_and_records_new_evidence() -> None:
    graph = PipelineGraph([_node("review", gate=lambda _ctx: False, max_revisions=1)])
    dispatcher = ScriptedDispatcher()

    run, record, owner = await _canonical(graph, dispatcher)

    assert record.run.status is RunStatus.FAILED
    assert run.status == "failed at review"
    assert run.failed_stage_error == "Gate failed after 1 revisions"
    assert dispatcher.calls == ["review", "review"]
    node_runs = await owner.run_store.list_node_runs(record.run_id)
    assert len(node_runs) == 2
    assert node_runs[0].status is RunStatus.COMPLETED
    assert node_runs[1].status is RunStatus.FAILED
    attempts = [
        attempt
        for node_run in node_runs
        for attempt in await owner.run_store.list_attempts(node_run.node_run_id)
    ]
    assert len(attempts) == 2


@pytest.mark.asyncio
async def test_canonical_identity_is_in_the_builders_receipt_projection() -> None:
    graph = PipelineGraph([_node("tests")])

    run, record, _ = await _canonical(graph, ScriptedDispatcher())

    assert run.canonical_run_id == record.run_id
    assert run.to_dict()["canonical_run_id"] == record.run_id


@pytest.mark.asyncio
async def test_dispatch_failure_fails_canonical_run_and_never_starts_downstream() -> None:
    graph = PipelineGraph([_node("tests"), _node("code", ("tests",))])
    dispatcher = ScriptedDispatcher(fail={"tests"})

    run, record, owner = await _canonical(graph, dispatcher)

    assert record.run.status is RunStatus.FAILED
    assert run.status == "failed at tests"
    assert run.failed_stage_error == "tests broke"
    assert dispatcher.calls == ["tests"]
    node_runs = await owner.run_store.list_node_runs(record.run_id)
    assert len(node_runs) == 1
    assert node_runs[0].status is RunStatus.FAILED
    attempts = await owner.run_store.list_attempts(node_runs[0].node_run_id)
    assert len(attempts) == 1


@pytest.mark.asyncio
async def test_two_concurrent_stage_failures_project_one_consistent_authoritative_failure() -> None:
    """#1067 defect 4: the projected stage and its error must come from the same failure.

    ``alpha`` and ``beta`` are independent roots dispatched in the same
    concurrent wave and both fail. Against unpatched code, ``failed_stage``
    (a reversed scan) and ``run.failed_stage_error`` (a shared mutable var
    each concurrent dispatcher writes) can each end up naming a *different*
    one of the two failures. The receipt must instead name one failure and
    carry *its* message -- and it must be the one canonical's own
    ``first_exhausted_failure`` selected (the first in frontier order; every
    Builders stage is ``max_attempts: 1``, so both failures are immediately
    exhausted).
    """
    graph = PipelineGraph([_node("alpha"), _node("beta")])
    # `alpha` is slower, so under the old racy code `beta`'s exception (and
    # its write to the shared `run.failed_stage_error`) lands first and
    # `alpha`'s overwrites it last -- while the old reversed-scan
    # `_failed_stage` names `beta` (last in frontier position) regardless of
    # timing. That mismatch is exactly the bug: two different failures
    # supply the stage name and the error message.
    dispatcher = ScriptedDispatcher(fail={"alpha", "beta"}, delays={"alpha": 0.01})

    run, record, _owner = await _canonical(graph, dispatcher)

    assert record.run.status is RunStatus.FAILED
    assert run.status == "failed at alpha"
    assert run.failed_stage_error == "alpha broke"
    stage_by_name = {stage.name: stage for stage in run.stages}
    assert stage_by_name["alpha"].status is StageStatus.FAILED
    assert stage_by_name["alpha"].error == "alpha broke"
    # beta also failed, but is not the authoritative failure -- it must not
    # be credited with (or blamed for) alpha's message, or vice versa.
    assert stage_by_name["beta"].status is StageStatus.FAILED
    assert stage_by_name["beta"].error != "alpha broke"


@pytest.mark.asyncio
async def test_timeout_never_runs_the_on_complete_hook() -> None:
    hook_outputs: list[str] = []

    async def hook(run: Any, output: str) -> None:
        hook_outputs.append(output)

    graph = PipelineGraph([_node("tests", timeout_seconds=0.001, on_complete=hook)])
    dispatcher = ScriptedDispatcher(delay=0.02)

    run, record, _ = await _canonical(graph, dispatcher)

    assert record.run.status is RunStatus.FAILED
    assert run.status == "failed at tests"
    assert "timed out" in run.failed_stage_error
    assert hook_outputs == []


@pytest.mark.asyncio
async def test_iteration_budget_bounds_revision_loop_before_extra_dispatch() -> None:
    graph = PipelineGraph(
        [
            _node("implement"),
            _node(
                "review",
                ("implement",),
                gate=lambda ctx: False,
                revise_target="implement",
                max_revisions=20,
            ),
        ]
    )
    dispatcher = ScriptedDispatcher(outputs={"review": "VIOLATION"})

    run, record, owner = await _canonical(
        graph,
        dispatcher,
        budget=IterationBudget(max_iterations=3),
    )

    assert record.run.status is RunStatus.FAILED
    assert dispatcher.calls == ["implement", "review", "implement"]
    assert "iteration budget exhausted" in run.failed_stage_error
    node_runs = await owner.run_store.list_node_runs(record.run_id)
    assert [item.node_id for item in node_runs] == [
        "builders-stage:implement",
        "builders-stage:review",
        "builders-stage:implement",
        "builders-stage:review",
    ]
    assert node_runs[-1].status is RunStatus.FAILED


@pytest.mark.asyncio
async def test_gate_exhaustion_halt_fails_the_run_with_domain_error() -> None:
    """The default exhausted-gate policy is a halt, not a silent proceed."""
    graph = PipelineGraph(
        [
            _node("implement"),
            _node(
                "review",
                ("implement",),
                gate=lambda ctx: False,
                revise_target="implement",
                max_revisions=0,
            ),
        ]
    )
    dispatcher = ScriptedDispatcher()

    run, record, owner = await _canonical(graph, dispatcher)

    assert record.run.status is RunStatus.FAILED
    assert run.status == "failed at review"
    assert run.failed_stage_error == "Gate failed after 0 revisions"
    assert run.gate_exhausted == []
    assert dispatcher.calls == ["implement", "review"]
    node_runs = await owner.run_store.list_node_runs(record.run_id)
    failed = [item for item in node_runs if item.status is RunStatus.FAILED]
    assert [item.node_id for item in failed] == ["builders-stage:review"]


@pytest.mark.asyncio
async def test_gate_exhaustion_continue_records_the_stage_once_and_proceeds() -> None:
    """A continue-policy gate stays recorded once across re-exhaustions."""
    graph = PipelineGraph(
        [
            _node("implement"),
            _node(
                "audit",
                ("implement",),
                gate=lambda ctx: False,
                gate_exhausted="continue",
                max_revisions=0,
            ),
            _node(
                "fixup",
                ("audit",),
                gate=lambda ctx: ctx.get("fixup") == "OK",
                revise_target="audit",
                max_revisions=1,
            ),
        ]
    )
    dispatcher = ScriptedDispatcher(outputs={"fixup": ["NO", "OK"]})

    run, record, owner = await _canonical(graph, dispatcher)

    assert run.status == "completed"
    assert record.run.status is RunStatus.COMPLETED
    assert run.gate_exhausted == ["audit"]
    assert dispatcher.calls == ["implement", "audit", "fixup", "audit", "fixup"]
    node_runs = await owner.run_store.list_node_runs(record.run_id)
    assert [item.node_id for item in node_runs] == [
        "builders-stage:implement",
        "builders-stage:audit",
        "builders-stage:fixup",
        "builders-stage:audit",
        "builders-stage:fixup",
    ]


@pytest.mark.asyncio
async def test_on_complete_hook_receives_the_committed_output() -> None:
    hook_outputs: list[str] = []

    async def hook(run: Any, output: str) -> None:
        hook_outputs.append(output)

    graph = PipelineGraph([_node("tests", on_complete=hook)])
    dispatcher = ScriptedDispatcher()

    run, record, _ = await _canonical(graph, dispatcher)

    assert record.run.status is RunStatus.COMPLETED
    assert hook_outputs == ["tests output"]
    assert run.context["tests"] == "tests output"


@pytest.mark.asyncio
async def test_on_complete_hook_that_fails_the_run_fails_the_stage() -> None:
    """A hook marking the run failed must surface as a failed stage, not pass."""

    async def failing_hook(run: Any, output: str) -> None:
        run.status = "failed at tests"

    graph = PipelineGraph([_node("tests", on_complete=failing_hook)])
    dispatcher = ScriptedDispatcher()

    run, record, owner = await _canonical(graph, dispatcher)

    assert record.run.status is RunStatus.FAILED
    assert run.status == "failed at tests"
    node_runs = await owner.run_store.list_node_runs(record.run_id)
    assert [item.node_id for item in node_runs] == ["builders-stage:tests"]
    assert node_runs[0].status is RunStatus.FAILED
    assert "tests failed" in (node_runs[0].error or "")


def test_resolver_rejects_node_ids_outside_the_builders_stage_namespace() -> None:
    graph = PipelineGraph([_node("tests")])
    run = _run(graph, run_id="resolver-run")
    canonical = _canonical_graph(
        graph,
        run=run,
        workspace_id="workspace-builders",
        project_id="project-builders",
    )
    resolve = _resolver(
        graph,
        run=run,
        dispatcher=ScriptedDispatcher(),
        budget=IterationBudget(max_iterations=8),
    )

    assert resolve("builders-stage:tests", canonical).__class__.__name__ == "_StageNode"
    with pytest.raises(KeyError, match="unknown Builders canonical node"):
        resolve("builders-stage:nonexistent", canonical)
    with pytest.raises(KeyError, match="unknown Builders canonical node"):
        resolve("frontier-control", canonical)


def test_mark_skipped_keeps_a_stage_recorded_exactly_once() -> None:
    graph = PipelineGraph([_node("tests")])
    run = _run(graph, run_id="skip-run")

    _mark_skipped(run, "tests")
    _mark_skipped(run, "tests")

    assert run.skipped_stages == ["tests"]


def test_projection_maps_running_queued_and_non_failed_terminal_node_runs() -> None:
    """The receipt projection must not invent terminal states the spine lacks."""
    graph = PipelineGraph(
        [_node("implement"), _node("tests", ("implement",)), _node("review", ("tests",))]
    )

    def _record(
        run_status: RunStatus,
        node_runs: list[tuple[str, RunStatus]],
        errors: dict[str, str] | None = None,
    ) -> Any:
        errors = errors or {}
        return SimpleNamespace(
            run=SimpleNamespace(status=run_status),
            node_runs=tuple(
                SimpleNamespace(
                    node_id=f"builders-stage:{name}", status=status, error=errors.get(name)
                )
                for name, status in node_runs
            ),
        )

    cancelled = _run(graph, run_id="projection-cancelled")
    _project_canonical_record(cancelled, _record(RunStatus.CANCELLED, []))
    assert cancelled.status == "cancelled"

    in_flight = _run(graph, run_id="projection-running")
    _project_canonical_record(
        in_flight,
        _record(
            RunStatus.RUNNING,
            [("implement", RunStatus.COMPLETED), ("tests", RunStatus.RUNNING)],
        ),
    )
    assert in_flight.status == "running"
    assert [stage.status for stage in in_flight.stages] == [
        StageStatus.COMPLETED,
        StageStatus.RUNNING,
        StageStatus.PENDING,
    ]

    queued = _run(graph, run_id="projection-queued")
    _project_canonical_record(
        queued,
        _record(
            RunStatus.RUNNING,
            [("implement", RunStatus.COMPLETED), ("tests", RunStatus.QUEUED)],
        ),
    )
    assert [stage.status for stage in queued.stages] == [
        StageStatus.COMPLETED,
        StageStatus.PENDING,
        StageStatus.PENDING,
    ]

    # Two stages failed in the same concurrent frontier (#1067 defect 4).
    # canonical's own selected failure is the *first* one in frontier order
    # (every Builders stage is max_attempts=1, so any failure is immediately
    # exhausted -- see durable_runs.executor.first_exhausted_failure). The
    # receipt must name that same stage and carry *its* error, never a
    # different stage's -- and must derive it from the NodeRun evidence
    # rather than trust whatever a differently-raced write already left on
    # `failed_stage_error` (deliberately pre-set here to the *other*,
    # non-authoritative stage's message to prove the projection overrides
    # it rather than trusting it).
    failed = _run(graph, run_id="projection-failed")
    failed.failed_stage_error = "review broke"
    _project_canonical_record(
        failed,
        _record(
            RunStatus.FAILED,
            [
                ("implement", RunStatus.COMPLETED),
                ("tests", RunStatus.FAILED),
                ("review", RunStatus.FAILED),
            ],
            errors={
                "tests": "RuntimeError: tests broke",
                "review": "RuntimeError: review broke",
            },
        ),
    )
    assert failed.status == "failed at tests"
    assert failed.failed_stage_error == "tests broke"
    stage_by_name = {stage.name: stage for stage in failed.stages}
    assert stage_by_name["tests"].status is StageStatus.FAILED
    assert stage_by_name["tests"].error == "tests broke"
    assert stage_by_name["review"].status is StageStatus.FAILED
    assert stage_by_name["review"].error == ""


@pytest.mark.asyncio
async def test_execute_rejects_an_invalid_pipeline_graph_before_any_run() -> None:
    graph = PipelineGraph([_node("code", ("nonexistent",))])
    owner = await _owner()
    executor = CanonicalGraphPipelineExecutor(
        ScriptedDispatcher(),
        run_store=owner.run_store,
        durable_store=owner.durable_store,
        workspace_id=owner.workspace_id,
        project_id=owner.project_id,
    )
    run = _run(graph, run_id="invalid-graph-run")

    with pytest.raises(ValueError, match="invalid Builders pipeline graph"):
        await executor.execute(graph, run)


def test_derived_max_steps_covers_a_representative_wide_pipeline() -> None:
    """#1067 defect 3: the derived bound must comfortably exceed the generic default.

    A representative >256-node linear Builders pipeline (cheap to
    *construct* -- see test_execute_derives_and_passes_a_sufficient_max_steps
    for proof that ``execute()`` actually passes this value on, and
    test_public_entry_point_honors_an_explicit_max_steps_override in
    ``test_executor_gaps.py`` for proof the durable walk actually honors it;
    neither runs a real >256-step walk end to end, since the canonical
    durable store's own per-checkpoint cost -- unrelated to this issue --
    makes that impractically slow for a unit test).
    """
    size = 300
    nodes = [_node("stage-0")]
    nodes.extend(_node(f"stage-{i}", (f"stage-{i - 1}",)) for i in range(1, size))
    graph = PipelineGraph(nodes)
    budget = IterationBudget(max_iterations=_DEFAULT_EXECUTIONS_PER_NODE * len(graph))

    bound = _derived_max_steps(graph, budget)

    assert bound > 256
    # Every real dispatch consumes exactly one unit of `budget`
    # (_reserve_iteration), so the bound must cover the whole budget too.
    assert bound >= budget.max_iterations


def test_derived_max_steps_covers_repeated_revision_driven_free_frontiers() -> None:
    """#1067 follow-up (Codex review, 2026-09-21): one free step per node isn't enough.

    Concrete counterexample from the review: a 100-node graph with one
    always-skipped root, one always-failing gated child that revises that
    root, and 98 other unrelated always-skipped roots. The prior formula
    (``budget.max_iterations + len(graph) + 1``) assumed a skip-only
    frontier happens at most once per node for the whole run, but a
    revision can replay an already-skipped node's frontier once per failed
    attempt: the walker alternates one free skipped-root frontier with one
    budget-consuming gate frontier, so legitimately exhausting the default
    300-iteration budget needs roughly ``2 * 300`` steps, not the ``401``
    the old formula derived -- it used to hit ``StepBudgetExhausted`` after
    only ~200 real executions.

    This does not run the walk end to end (see
    ``test_derived_max_steps_covers_a_representative_wide_pipeline`` for why
    that is impractically slow); it proves the derived bound itself now
    comfortably covers the steps such a run would legitimately need.
    """
    size = 100
    nodes = [_node("root", skip_if=lambda _ctx: True)]
    nodes.append(
        _node(
            "gate",
            ("root",),
            gate=lambda _ctx: False,
            revise_target="root",
            max_revisions=1000,
        )
    )
    nodes.extend(_node(f"padding-{i}", skip_if=lambda _ctx: True) for i in range(size - 2))
    graph = PipelineGraph(nodes)
    budget = IterationBudget(max_iterations=300)

    bound = _derived_max_steps(graph, budget)
    old_formula_bound = budget.max_iterations + len(graph) + 1

    # The walker alternates one free `root`-settle frontier with one
    # budget-consuming `gate` frontier, so it needs roughly 2 steps per
    # allowed real dispatch (plus a small constant for the initial control
    # frontier) to legitimately exhaust the budget.
    required = 2 * budget.max_iterations + 2
    assert old_formula_bound < required, "counterexample must actually defeat the old formula"
    assert bound >= required


@pytest.mark.asyncio
async def test_execute_derives_and_passes_a_sufficient_max_steps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#1067 defect 3: ``execute()`` must derive, not hardcode, the walk's step bound.

    Against unpatched code, ``execute()`` calls ``run_durable_graph`` with no
    ``max_steps`` at all, so the durable walk silently falls back to its
    generic 256-step default regardless of the admitted pipeline's own size
    -- this spy captures exactly what ``execute()`` passes, without paying
    for the (slow -- see test_derived_max_steps_covers_a_representative_wide_pipeline)
    cost of a real 300-step walk.
    """
    size = 300
    nodes = [_node("stage-0")]
    nodes.extend(_node(f"stage-{i}", (f"stage-{i - 1}",)) for i in range(1, size))
    graph = PipelineGraph(nodes)

    captured: dict[str, Any] = {}

    class _Captured(Exception):
        pass

    async def _spy(*_args: Any, **kwargs: Any) -> Any:
        captured.update(kwargs)
        raise _Captured

    monkeypatch.setattr("maistro.builders.graph_executor.run_durable_graph", _spy)

    owner = await _owner()
    executor = CanonicalGraphPipelineExecutor(
        ScriptedDispatcher(),
        run_store=owner.run_store,
        durable_store=owner.durable_store,
        workspace_id=owner.workspace_id,
        project_id=owner.project_id,
    )
    run = _run(graph, run_id="wide-pipeline-run")

    with pytest.raises(_Captured):
        await executor.execute(graph, run)

    assert captured["max_steps"] > 256
