"""Tests for `maistro.builders.pipeline` spec-store/verifier integration and helpers.

`test_builder_pipeline.py` covers the dispatcher/DAG/skip/gate mechanics; this
file closes the remaining gaps: `build_spec_summary`, the decompose/scaffold
spec on_complete hooks, spec load-or-emit at execute() start, the
verification-wrapping hook, and `_reconcile_stages`'s failed-stage branch.
"""

from __future__ import annotations

import pytest

from maistro.builders.graph import PipelineNode
from maistro.builders.graph_executor import DispatchResult
from maistro.builders.pipeline import BuilderPipeline, StageStatus, build_spec_summary
from maistro.builders.verifier import InvariantVerifier
from maistro.types.spec import Invariant, InvariantKind, Spec


class _InMemorySpecStore:
    def __init__(self) -> None:
        self._specs: dict[int, Spec] = {}
        self.saved: list[Spec] = []

    async def save(self, spec: Spec) -> None:
        self._specs[spec.issue_number] = spec
        self.saved.append(spec)

    async def get(self, issue_number: int) -> Spec | None:
        return self._specs.get(issue_number)

    async def list_active(self) -> list[Spec]:
        return list(self._specs.values())


class ScriptedDispatcher:
    def __init__(self, outputs: dict[str, str]) -> None:
        self._outputs = outputs

    def supports(self, agent_name: str, node_name: str) -> bool:
        return node_name in self._outputs

    async def run(
        self, *, run_id: str, node_name: str, agent_name: str, prompt: str, context: object
    ) -> DispatchResult:
        return DispatchResult(ok=True, output=self._outputs[node_name])


def _spec(issue_number: int = 1, **kwargs: object) -> Spec:
    return Spec(issue_number=issue_number, title="Add caching", **kwargs)  # type: ignore[arg-type]


def test_build_spec_summary_includes_protocols_invariants_and_criteria() -> None:
    spec = _spec(
        protocols_touched=("CacheStore",),
        invariants=(
            Invariant(
                name="no_stale_reads",
                description="cache never returns expired entries",
                kind=InvariantKind.STATE_INVARIANT,
                expression="ttl > 0",
            ),
        ),
        acceptance_criteria=("Cache hits return within 5ms",),
    )
    summary = build_spec_summary(spec)
    assert "Spec: Add caching" in summary
    assert "Protocols: CacheStore" in summary
    assert "no_stale_reads: cache never returns expired entries" in summary
    assert "Cache hits return within 5ms" in summary


def test_build_spec_summary_omits_empty_sections() -> None:
    spec = _spec()
    summary = build_spec_summary(spec)
    assert summary == "Spec: Add caching"


def test_build_spec_summary_truncates_long_output() -> None:
    long_criteria = tuple(f"criterion {i} " + "x" * 50 for i in range(100))
    spec = _spec(acceptance_criteria=long_criteria)
    summary = build_spec_summary(spec)
    assert len(summary) == 2000
    assert summary.endswith("...")


@pytest.mark.asyncio
async def test_execute_loads_existing_spec_from_store_and_skips_emit() -> None:
    store = _InMemorySpecStore()
    existing = _spec(issue_number=42)
    await store.save(existing)
    dispatcher = ScriptedDispatcher({"scaffold": "ok", "implement": "approved"})
    pipeline = BuilderPipeline(dispatcher, spec_store=store)

    await pipeline.execute(issue_number=42, title="Add caching", repo="acme/widget")

    # scaffold's on_complete re-saves the (enriched) spec, but no *new* spec was
    # emitted for issue 42 — the first save is still the originally-stored one.
    assert store.saved[0] is existing


@pytest.mark.asyncio
async def test_execute_emits_spec_immediately_when_skip_decompose_and_no_existing_spec() -> None:
    store = _InMemorySpecStore()
    dispatcher = ScriptedDispatcher({"scaffold": "ok", "implement": "approved"})
    pipeline = BuilderPipeline(dispatcher, spec_store=store)

    run = await pipeline.execute(
        issue_number=7, title="Add caching", repo="acme/widget", skip_decompose=True
    )

    assert len(store.saved) >= 1
    assert store.saved[0].issue_number == 7
    assert "Spec: Add caching" in run.context["spec_summary"]


@pytest.mark.asyncio
async def test_decompose_on_complete_emits_and_persists_spec() -> None:
    store = _InMemorySpecStore()
    dispatcher = ScriptedDispatcher(
        {
            "decompose": "sub-issue breakdown",
            "scaffold": "ok",
            "implement": "approved, all checks pass",
        }
    )
    pipeline = BuilderPipeline(dispatcher, spec_store=store)

    run = await pipeline.execute(
        issue_number=11, title="Add caching", repo="acme/widget", skip_decompose=False
    )

    assert run.context["_spec"].issue_number == 11
    assert run.context["verifications"] == []
    assert any(s.issue_number == 11 for s in store.saved)


@pytest.mark.asyncio
async def test_decompose_on_complete_noop_without_spec_store() -> None:
    dispatcher = ScriptedDispatcher(
        {"decompose": "breakdown", "scaffold": "ok", "implement": "approved, all checks pass"}
    )
    pipeline = BuilderPipeline(dispatcher, spec_store=None)

    run = await pipeline.execute(
        issue_number=12, title="Add caching", repo="acme/widget", skip_decompose=False
    )

    assert "_spec" not in run.context


@pytest.mark.asyncio
async def test_decompose_on_complete_noop_when_spec_already_in_context() -> None:
    store = _InMemorySpecStore()
    await store.save(_spec(issue_number=21))
    dispatcher = ScriptedDispatcher(
        {"decompose": "breakdown", "scaffold": "ok", "implement": "approved, all checks pass"}
    )
    pipeline = BuilderPipeline(dispatcher, spec_store=store)

    await pipeline.execute(
        issue_number=21, title="Add caching", repo="acme/widget", skip_decompose=False
    )

    # The pre-existing spec was loaded before decompose ran; decompose's hook
    # must not overwrite it with a freshly emitted one. scaffold's own
    # on_complete re-saves an enriched copy afterwards, so every save must
    # still carry issue 21, not a fresh emission for a different spec.
    assert store.saved[0].issue_number == 21
    assert all(s.issue_number == 21 for s in store.saved)


@pytest.mark.asyncio
async def test_scaffold_on_complete_enriches_spec_with_property_tests() -> None:
    store = _InMemorySpecStore()
    seeded = Spec(
        issue_number=5,
        title="Add caching",
        invariants=(
            Invariant(
                name="inv1",
                description="d",
                kind=InvariantKind.STATE_INVARIANT,
                expression="e",
            ),
        ),
    )
    await store.save(seeded)
    dispatcher = ScriptedDispatcher({"scaffold": "scaffolded", "implement": "approved"})
    pipeline = BuilderPipeline(dispatcher, spec_store=store)

    run = await pipeline.execute(issue_number=5, title="Add caching", repo="acme/widget")

    enriched = run.context["_spec"]
    assert len(enriched.property_tests) == 1
    assert enriched.property_tests[0].invariant_name == "inv1"


@pytest.mark.asyncio
async def test_scaffold_on_complete_noop_when_no_spec_in_context() -> None:
    dispatcher = ScriptedDispatcher({"scaffold": "scaffolded", "implement": "approved"})
    pipeline = BuilderPipeline(dispatcher, spec_store=None)

    run = await pipeline.execute(issue_number=6, title="Add caching", repo="acme/widget")

    assert "_spec" not in run.context


@pytest.mark.asyncio
async def test_verifier_wraps_on_complete_and_records_verification() -> None:
    store = _InMemorySpecStore()
    seeded = Spec(issue_number=9, title="Add caching")
    await store.save(seeded)
    dispatcher = ScriptedDispatcher({"scaffold": "ok", "implement": "approved, all checks pass"})
    pipeline = BuilderPipeline(dispatcher, spec_store=store, spec_verifier=InvariantVerifier())

    run = await pipeline.execute(issue_number=9, title="Add caching", repo="acme/widget")

    assert len(run.context["verifications"]) >= 1
    assert run.context["verifications"][0]["passed"] is True


@pytest.mark.asyncio
async def test_verifier_hook_noop_when_no_spec_in_context() -> None:
    # spec_verifier is configured but spec_store is not, so no spec ever
    # lands in run.context — the verification hook's early return (spec is
    # None) must skip verification entirely rather than erroring.
    dispatcher = ScriptedDispatcher({"scaffold": "ok", "implement": "approved, all checks pass"})
    pipeline = BuilderPipeline(dispatcher, spec_store=None, spec_verifier=InvariantVerifier())

    run = await pipeline.execute(issue_number=14, title="Add caching", repo="acme/widget")

    assert "_spec" not in run.context
    assert run.context.get("verifications") is None
    assert run.status == "completed"


@pytest.mark.asyncio
async def test_verifier_failure_marks_run_failed_with_spec_violation_message() -> None:
    # Use a single bare node (no enriching on_complete) so the seeded spec's
    # uncovered invariant is still uncovered when the verifier wrapper runs.
    store = _InMemorySpecStore()
    seeded = Spec(
        issue_number=13,
        title="Add caching",
        invariants=(
            Invariant(
                name="uncovered_inv",
                description="d",
                kind=InvariantKind.STATE_INVARIANT,
                expression="e",
            ),
        ),
    )
    await store.save(seeded)
    dispatcher = ScriptedDispatcher({"solo": "done"})
    bare_node = PipelineNode(name="solo", agent_name="mason", prompt_template="go")
    pipeline = BuilderPipeline(
        dispatcher, spec_store=store, spec_verifier=InvariantVerifier(), nodes=[bare_node]
    )

    run = await pipeline.execute(issue_number=13, title="Add caching", repo="acme/widget")

    assert run.status == "failed at solo"
    assert "Spec verification failed" in run.failed_stage_error
    failed_stage = next(s for s in run.stages if s.name == "solo")
    assert failed_stage.status is StageStatus.FAILED
    assert failed_stage.error == run.failed_stage_error
