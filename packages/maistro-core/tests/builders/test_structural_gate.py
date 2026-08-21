"""Behavioral tests for the structural-awareness gate on the `review` node.

Proves the review gate hard-fails on a deterministic (EXTRACTED, CRITICAL)
structural finding even when the LLM auditor's own review text says
"APPROVED" — the core behavior this whole change exists to prove — while
staying a no-op, not an error, for callers who don't opt into `code_index`.
"""

from __future__ import annotations

import pytest

from maistro.builders.graph_executor import DispatchResult
from maistro.builders.pipeline import BuilderPipeline
from maistro.codebase.types import CodeClass, CodeImport, CodeModule, CodeStructureReport


class ScriptedDispatcher:
    """Pipeline dispatcher returning scripted outputs keyed by node name."""

    def __init__(self, outputs: dict[str, str]) -> None:
        self._outputs = outputs
        self.prompts: dict[str, list[str]] = {}

    def supports(self, agent_name: str, node_name: str) -> bool:
        return node_name in self._outputs

    async def run(
        self, *, run_id: str, node_name: str, agent_name: str, prompt: str, context: object
    ) -> DispatchResult:
        self.prompts.setdefault(node_name, []).append(prompt)
        return DispatchResult(ok=True, output=self._outputs[node_name])


class _FakeCodeIndex:
    """A code_index stub that returns a canned report rather than walking a real tree."""

    def __init__(self, report: CodeStructureReport) -> None:
        self._report = report
        self.build_calls: list[str] = []

    async def build(self, root_path: str) -> CodeStructureReport:
        self.build_calls.append(root_path)
        return self._report


class _BombCodeIndex:
    """A code_index stub whose build() must never be called."""

    async def build(self, root_path: str) -> CodeStructureReport:
        raise AssertionError("build() should not be called when workspace_path is empty")


def _clean_report() -> CodeStructureReport:
    return CodeStructureReport(root_path="/fake", modules=())


def _violating_report() -> CodeStructureReport:
    protocol_mod = CodeModule(
        module_path="protocols.storage",
        file_path="protocols/storage.py",
        classes=(CodeClass(name="Store", bases=("Protocol",), is_protocol=True),),
    )
    concrete_mod = CodeModule(
        module_path="impls.concrete_store",
        file_path="impls/concrete_store.py",
        classes=(CodeClass(name="Store", bases=(), is_protocol=False),),
    )
    bad_mod = CodeModule(
        module_path="impls.bad_impl",
        file_path="impls/bad_impl.py",
        imports=(CodeImport(module="impls.concrete_store", names=("Store",), line_number=3),),
    )
    return CodeStructureReport(root_path="/fake", modules=(protocol_mod, concrete_mod, bad_mod))


@pytest.mark.asyncio
async def test_gate_passes_clean_when_code_index_finds_nothing_wrong() -> None:
    dispatcher = ScriptedDispatcher(
        {"scaffold": "scaffolded", "implement": "PR created", "review": "APPROVED"}
    )
    code_index = _FakeCodeIndex(_clean_report())
    pipeline = BuilderPipeline(dispatcher, code_index=code_index)

    run = await pipeline.execute(
        issue_number=1, title="t", repo="acme/widget", skip_decompose=True, workspace_path="/repo"
    )

    assert run.status == "completed"
    assert run.gate_exhausted == []
    assert run.context["structural_findings"] == []
    assert code_index.build_calls == ["/repo"]


@pytest.mark.asyncio
async def test_gate_hard_fails_on_critical_extracted_finding_despite_approved_review() -> None:
    dispatcher = ScriptedDispatcher(
        {"scaffold": "scaffolded", "implement": "PR created with changes", "review": "APPROVED"}
    )
    code_index = _FakeCodeIndex(_violating_report())
    pipeline = BuilderPipeline(dispatcher, code_index=code_index)

    run = await pipeline.execute(
        issue_number=2, title="t", repo="acme/widget", skip_decompose=True, workspace_path="/repo"
    )

    # The LLM review text says APPROVED on every pass, but the deterministic
    # structural finding keeps failing the gate until revisions are exhausted
    # — at which point gate_exhausted="continue" lets the run finish rather
    # than halt forever.
    assert run.gate_exhausted == ["review"]
    assert run.status == "completed"
    assert len(dispatcher.prompts["implement"]) == 3


@pytest.mark.asyncio
async def test_gate_failure_feeds_finding_back_into_next_implement_prompt() -> None:
    dispatcher = ScriptedDispatcher(
        {"scaffold": "scaffolded", "implement": "PR created with changes", "review": "APPROVED"}
    )
    code_index = _FakeCodeIndex(_violating_report())
    pipeline = BuilderPipeline(dispatcher, code_index=code_index)

    await pipeline.execute(
        issue_number=3, title="t", repo="acme/widget", skip_decompose=True, workspace_path="/repo"
    )

    revised_prompt = dispatcher.prompts["implement"][1]
    assert "bypassing the 'Store' Protocol" in revised_prompt


@pytest.mark.asyncio
async def test_no_code_index_reproduces_today_behavior() -> None:
    dispatcher = ScriptedDispatcher(
        {"scaffold": "scaffolded", "implement": "PR created", "review": "APPROVED"}
    )
    pipeline = BuilderPipeline(dispatcher)

    run = await pipeline.execute(issue_number=4, title="t", repo="acme/widget", skip_decompose=True)

    assert run.status == "completed"
    assert run.gate_exhausted == []
    assert run.context["structural_findings"] == []


@pytest.mark.asyncio
async def test_code_index_set_without_workspace_path_is_a_noop() -> None:
    dispatcher = ScriptedDispatcher(
        {"scaffold": "scaffolded", "implement": "PR created", "review": "APPROVED"}
    )
    pipeline = BuilderPipeline(dispatcher, code_index=_BombCodeIndex())

    run = await pipeline.execute(issue_number=5, title="t", repo="acme/widget", skip_decompose=True)

    assert run.status == "completed"
    assert run.context["structural_findings"] == []
