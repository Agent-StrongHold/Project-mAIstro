"""Shared protocol conformance for built-in and third-party tools (M9-E3).

Pins the acceptance criterion: reference external and built-in tools pass the
shared conformance suite where semantics overlap — and proves the suite has
teeth with negative controls that fail specific checks. Also proves the
out-of-tree criterion end to end with the real ``extensions/reference-greeter``
package: its manifest is parsed, its handler loaded through the host's
import boundary, and its one governed call recorded canonically.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from maistro.capabilities.effect_context import new_in_memory_effect_context
from maistro.capabilities.governed_invocation import InvocationPolicyContext
from maistro.capabilities.invocation import InvocationStatus
from maistro.extensions.tool_skill import (
    ERROR_CODE_APPROVAL,
    ERROR_CODE_CANCELLED,
    ERROR_CODE_DENIAL,
    ERROR_CODE_HANDLER_ERROR,
    EffectClass,
    ExtensionContract,
    ExtensionToolCatalog,
    ExtensionToolOutcome,
    invoke_extension_tool,
    load_entrypoint_handler,
    run_conformance,
)
from maistro.extensions.tool_skill.conformance import (
    DEFAULT_CHECKS,
    CheckResult,
    check_cancellation_is_canonical,
    check_denial_is_attributable,
    check_error_is_canonical,
    check_exposure_is_canonical,
    check_result_is_canonical,
)
from maistro.policy.types import Decision, PolicyVerdict

REPO_ROOT = Path(__file__).resolve().parents[4]
RUN_ID = "run-conf"
NODE_RUN_ID = "node-conf"
ATTEMPT_ID = "attempt-conf"


async def _allow(binding, request, context: InvocationPolicyContext) -> PolicyVerdict:
    del binding, request, context
    return PolicyVerdict(Decision.ALLOW, reason="allow", rule="test.allow")


async def _deny(binding, request, context: InvocationPolicyContext) -> PolicyVerdict:
    del binding, request, context
    return PolicyVerdict(Decision.DENY, reason="denied", rule="test.deny")


def package_manifest(tool_id: str, effects: list[str]) -> dict[str, object]:
    publisher, _, name = tool_id.partition(".")
    return {
        "id": tool_id,
        "publisher": publisher,
        "version": "1.0.0",
        "title": name,
        "description": f"The {tool_id} scenario tool.",
        "contract": ">=1.0.0,<2.0.0",
        "family": "tool",
        "capabilities": [],
        "effects": effects,
        "data": {"scopes": []},
        "entrypoint": {"module": f"{publisher}_{name}.plugin", "object": "PLUGIN"},
    }


async def scenario_handler(
    mode: str = "call",
    target: str = "world",
    boom: bool = False,
) -> Any:
    """One handler, four scenarios the conformance suite drives."""
    if boom:
        raise RuntimeError("scenario failure")
    if mode == "conformance-cancel":
        await asyncio.sleep(30)
    return {"mode": mode, "target": target}


class GovernedToolSubject:
    """A conformant tool surface over one registered tool + one policy.

    This is exactly the shape a host exposes: describe from the catalog,
    invoke through the canonical seam. Built-in and third-party tools share
    it; only the contract's origin differs (code vs extension.json).
    """

    def __init__(self, catalog, tool, *, deny: bool = False) -> None:
        self._catalog = catalog
        self._tool = tool
        self._effects = new_in_memory_effect_context(policy_evaluator=_deny if deny else _allow)
        self._deny_effects = (
            self._effects if deny else new_in_memory_effect_context(policy_evaluator=_deny)
        )
        self._binding = catalog.tool_binding(tool, workspace_id="ws-conf", project_id="pr-conf")

    def describe(self) -> dict[str, Any]:
        return self._tool.describe()

    async def invoke(self, **kwargs: Any) -> ExtensionToolOutcome:
        arguments = dict(kwargs)
        mode = str(arguments.get("mode", "call"))
        if mode == "conformance-error":
            arguments["boom"] = True
        timeout_s = 0.05 if mode == "conformance-cancel" else None
        effects = self._deny_effects if mode == "conformance-deny" else self._effects
        return await self._invoke(
            arguments,
            mode=mode,
            timeout_s=timeout_s,
            effects=effects,
        )

    async def _invoke(self, arguments, *, mode, timeout_s, effects):
        return await invoke_extension_tool(
            effects,
            self._tool,
            self._binding,
            arguments,
            run_id=RUN_ID,
            node_run_id=NODE_RUN_ID,
            attempt_id=ATTEMPT_ID,
            timeout_s=timeout_s,
        )


def registered_scenario_tool(catalog: ExtensionToolCatalog, tool_id: str):
    contract = ExtensionContract.from_manifest(
        package_manifest(tool_id, effects=["read-only"]), digest="cafe"
    )
    entrypoint = {
        "kind": "tool",
        "name": tool_id,
        "version": "1.0.0",
        "capabilities": [],
        "handler": "scenario_handler",
    }
    return catalog.register(contract, entrypoint, handler=scenario_handler)


def crafted_outcome(**overrides: Any) -> ExtensionToolOutcome:
    """One attributable FAILED/refusal-shaped outcome, per-field overridden.

    The negative controls below feed single conformance checks a scripted
    outcome; the defaults are the fully-attributed ``policy_denied`` refusal
    the governed subject itself produces.
    """
    fields: dict[str, Any] = {
        "status": InvocationStatus.FAILED,
        "tool_id": "acme.scenario",
        "run_id": RUN_ID,
        "node_run_id": NODE_RUN_ID,
        "attempt_id": ATTEMPT_ID,
        "error_code": ERROR_CODE_DENIAL,
        "error": "test denies",
        "effect": EffectClass.READ_ONLY,
    }
    fields.update(overrides)
    return ExtensionToolOutcome(**fields)


class ScriptedSubject:
    """A subject whose describe/invoke answers are scripted for one check."""

    def __init__(
        self,
        *,
        described: dict[str, Any] | None = None,
        outcome: ExtensionToolOutcome | None = None,
        raised: BaseException | None = None,
        returns: Any = "__outcome__",
    ) -> None:
        self._described = (
            described if described is not None else {"name": "x", "reversibility": "internal"}
        )
        self._outcome = outcome
        self._raised = raised
        self._returns = returns

    def describe(self) -> dict[str, Any]:
        return self._described

    async def invoke(self, **kwargs: Any) -> Any:
        del kwargs
        if self._raised is not None:
            raise self._raised
        if self._returns != "__outcome__":
            return self._returns
        assert self._outcome is not None
        return self._outcome


@pytest.mark.asyncio
async def test_external_and_builtin_pass_shared_conformance() -> None:
    """The epic AC: the same battery passes an external-style package and a
    built-in surface where semantics overlap."""
    catalog = ExtensionToolCatalog()
    external = registered_scenario_tool(catalog, "acme.scenario")
    # The built-in's contract is defined in code at composition time — same
    # governed structures, no extension manifest involved in *its* origin.
    builtin_contract = ExtensionContract.from_manifest(
        package_manifest("builtin.note", effects=["mutating"]), digest=""
    )
    builtin = catalog.register(
        builtin_contract,
        {
            "kind": "tool",
            "name": "builtin.note",
            "version": "1.0.0",
            "capabilities": [],
            "handler": "scenario_handler",
        },
        handler=scenario_handler,
    )

    external_report = await run_conformance(GovernedToolSubject(catalog, external))
    builtin_report = await run_conformance(GovernedToolSubject(catalog, builtin))

    assert external_report.passed, [(r.name, r.detail) for r in external_report.failures]
    assert builtin_report.passed, [(r.name, r.detail) for r in builtin_report.failures]
    # The overlap is real: both subjects ran the identical check battery.
    assert [c.__name__ for c in DEFAULT_CHECKS] == [
        "check_exposure_is_canonical",
        "check_result_is_canonical",
        "check_error_is_canonical",
        "check_cancellation_is_canonical",
        "check_denial_is_attributable",
    ]


@pytest.mark.asyncio
async def test_denying_policy_fails_result_check_for_the_refused_family() -> None:
    """A subject whose policy denies everything cannot fake a happy path."""
    catalog = ExtensionToolCatalog()
    tool = registered_scenario_tool(catalog, "acme.scenario")
    subject = GovernedToolSubject(catalog, tool, deny=True)
    report = await run_conformance(subject)
    names = {result.name for result in report.results if not result.passed}
    assert "result-is-canonical" in names
    assert "denial-is-attributable" not in names  # the refusal itself conforms
    # The failures projection names exactly the failing results, in order.
    assert [r.name for r in report.failures] == [r.name for r in report.results if not r.passed]
    assert report.failures[0].passed is False


@pytest.mark.asyncio
async def test_exposure_check_rejects_nameless_descriptor() -> None:
    """Negative control: a descriptor with no name is non-conformant."""
    result = await check_exposure_is_canonical(
        ScriptedSubject(described={"reversibility": "internal"})
    )
    assert not result.passed
    assert "no name" in result.detail


@pytest.mark.asyncio
async def test_exposure_check_rejects_reversibility_outside_adr050() -> None:
    """Negative control: a made-up reversibility label is outside the
    ADR-050 taxonomy the exposure check enforces."""
    result = await check_exposure_is_canonical(
        ScriptedSubject(described={"name": "x", "reversibility": "sorta-reversible"})
    )
    assert not result.passed
    assert "outside the ADR-050 taxonomy" in result.detail


@pytest.mark.asyncio
async def test_result_check_rejects_non_completed_outcome() -> None:
    """Negative control: a FAILED outcome cannot pass the result check."""
    result = await check_result_is_canonical(ScriptedSubject(outcome=crafted_outcome()))
    assert not result.passed
    assert "expected completed" in result.detail


@pytest.mark.asyncio
async def test_result_check_rejects_completed_call_with_no_invocation() -> None:
    """Negative control: COMPLETED with no Invocation row is unattributable."""
    result = await check_result_is_canonical(
        ScriptedSubject(
            outcome=crafted_outcome(
                status=InvocationStatus.COMPLETED, result={"ok": 1}, invocation=None
            )
        )
    )
    assert not result.passed
    assert "recorded no Invocation" in result.detail


@pytest.mark.asyncio
async def test_result_check_rejects_missing_execution_correlation() -> None:
    """Negative control: a completed outcome without Run/NodeRun/Attempt
    correlation is not attributable."""
    result = await check_result_is_canonical(
        ScriptedSubject(
            outcome=crafted_outcome(
                status=InvocationStatus.COMPLETED,
                result={"ok": 1},
                invocation=SimpleNamespace(invocation_id="inv-1"),
                run_id="",
                attempt_id="",
            )
        )
    )
    assert not result.passed
    assert "Run/NodeRun/Attempt correlation" in result.detail


@pytest.mark.asyncio
async def test_error_check_rejects_non_failed_outcome() -> None:
    """Negative control: an over-reported COMPLETED outcome for a failing
    call is non-conformant."""
    result = await check_error_is_canonical(
        ScriptedSubject(outcome=crafted_outcome(status=InvocationStatus.COMPLETED, result="fine"))
    )
    assert not result.passed
    assert "expected failed" in result.detail


@pytest.mark.asyncio
async def test_error_check_rejects_unattributed_handler_failure() -> None:
    """Negative control: a handler failure with no Invocation row cannot be
    attributed to the call that produced it."""
    result = await check_error_is_canonical(
        ScriptedSubject(
            outcome=crafted_outcome(
                error_code=ERROR_CODE_HANDLER_ERROR, error="boom", invocation=None
            )
        )
    )
    assert not result.passed
    assert "no attributable Invocation" in result.detail


@pytest.mark.asyncio
async def test_error_check_rejects_silent_handler_failure() -> None:
    """Negative control: a FAILED outcome with no error text is not a
    machine-usable failure."""
    result = await check_error_is_canonical(
        ScriptedSubject(outcome=crafted_outcome(error_code=ERROR_CODE_HANDLER_ERROR, error=""))
    )
    assert not result.passed
    assert "error text" in result.detail


@pytest.mark.asyncio
async def test_cancellation_check_rejects_bare_cancelled_error() -> None:
    """Negative control: an in-flight cancellation that carries no canonical
    outcome fails the suite — cancellation must stay attributable."""
    result = await check_cancellation_is_canonical(ScriptedSubject(raised=asyncio.CancelledError()))
    assert not result.passed
    assert "carried no canonical outcome" in result.detail


@pytest.mark.asyncio
async def test_cancellation_check_accepts_outcome_on_bare_cancelled_error() -> None:
    """The second cancellation spelling: a bare :class:`asyncio.CancelledError`
    with the canonical outcome attached to ``exc.outcome`` passes."""
    outcome = crafted_outcome(
        status=InvocationStatus.UNKNOWN,
        error_code=ERROR_CODE_CANCELLED,
        error="tool invocation cancelled",
    )
    exc = asyncio.CancelledError()
    exc.outcome = outcome  # type: ignore[attr-defined]
    result = await check_cancellation_is_canonical(ScriptedSubject(raised=exc))
    assert result.passed, result.detail


@pytest.mark.asyncio
async def test_cancellation_check_rejects_silent_return() -> None:
    """Negative control: a subject that returns normally over an interrupted
    call fails — the check holds the cancelled disposition, not a value."""
    result = await check_cancellation_is_canonical(ScriptedSubject(returns=None))
    assert not result.passed
    assert "returned normally" in result.detail


@pytest.mark.asyncio
async def test_cancellation_check_rejects_untyped_interruption() -> None:
    """Negative control: an UNKNOWN outcome without a cancellation-family
    error_code hides which interruption happened."""
    result = await check_cancellation_is_canonical(
        ScriptedSubject(
            outcome=crafted_outcome(status=InvocationStatus.UNKNOWN, error_code="mystery")
        )
    )
    assert not result.passed
    assert "interruption family" in result.detail


@pytest.mark.asyncio
async def test_denial_check_rejects_non_failed_outcome() -> None:
    """Negative control: a refusal reported as COMPLETED is non-conformant."""
    result = await check_denial_is_attributable(
        ScriptedSubject(
            outcome=crafted_outcome(status=InvocationStatus.COMPLETED, result="went through")
        )
    )
    assert not result.passed
    assert "must be FAILED" in result.detail


@pytest.mark.asyncio
async def test_denial_check_rejects_untyped_refusal_family() -> None:
    """Negative control: FAILED without a refusal-family error_code does not
    distinguish a policy denial from an ordinary handler failure."""
    result = await check_denial_is_attributable(
        ScriptedSubject(outcome=crafted_outcome(error_code="vibes"))
    )
    assert not result.passed
    assert "refusal family" in result.detail


@pytest.mark.asyncio
async def test_denial_check_requires_execution_scope() -> None:
    """Negative control: a refusal without Run/Attempt correlation cannot be
    attributed to the execution that asked for it."""
    result = await check_denial_is_attributable(
        ScriptedSubject(outcome=crafted_outcome(run_id="", attempt_id=""))
    )
    assert not result.passed
    assert "stay attributable" in result.detail


@pytest.mark.asyncio
async def test_denial_check_requires_effect_classification() -> None:
    """Negative control: the refusal must name the classification the
    decision ran on — otherwise the floor it enforced is unauditable."""
    result = await check_denial_is_attributable(
        ScriptedSubject(outcome=crafted_outcome(effect=None))
    )
    assert not result.passed
    assert "classification" in result.detail


@pytest.mark.asyncio
async def test_denial_check_requires_durable_approval_request_id() -> None:
    """Negative control: approval gating without a durable request id gives a
    human nothing to resolve."""
    result = await check_denial_is_attributable(
        ScriptedSubject(
            outcome=crafted_outcome(error_code=ERROR_CODE_APPROVAL, approval_request_id="")
        )
    )
    assert not result.passed
    assert "durable request id" in result.detail


@pytest.mark.asyncio
async def test_subject_that_swallows_cancellation_fails_the_suite() -> None:
    """Negative control: a tool that reports success over an interrupted call
    is non-conformant, by check name."""

    class LiarSubject(GovernedToolSubject):
        async def invoke(self, **kwargs: Any) -> ExtensionToolOutcome:
            if kwargs.get("mode") == "conformance-cancel":
                return ExtensionToolOutcome(
                    status=InvocationStatus.COMPLETED,
                    tool_id=self._tool.tool_id,
                    run_id=RUN_ID,
                    node_run_id=NODE_RUN_ID,
                    attempt_id=ATTEMPT_ID,
                    result="pretended",
                )
            return await super().invoke(**kwargs)

    catalog = ExtensionToolCatalog()
    tool = registered_scenario_tool(catalog, "acme.scenario")
    report = await run_conformance(LiarSubject(catalog, tool))
    names = {result.name for result in report.results if not result.passed}
    assert "cancellation-is-canonical" in names


@pytest.mark.asyncio
async def test_subject_without_invocation_fails_attribution_check() -> None:
    """Negative control: a fabricated completed outcome with no Invocation
    row cannot pass the canonical-result check."""

    class LiarSubject(GovernedToolSubject):
        async def invoke(self, **kwargs: Any) -> ExtensionToolOutcome:
            outcome = await super().invoke(**kwargs)
            if outcome.success:
                return replace(outcome, invocation=None)
            return outcome

    catalog = ExtensionToolCatalog()
    tool = registered_scenario_tool(catalog, "acme.scenario")
    report = await run_conformance(LiarSubject(catalog, tool))
    failing = {result.name for result in report.results if not result.passed}
    assert "result-is-canonical" in failing


def test_check_results_shape() -> None:
    result = CheckResult(name="x", passed=False, detail="why")
    assert result.passed is False
    assert result.detail == "why"


def test_reference_extension_registers_and_runs_out_of_tree() -> None:
    """AC1 with the real out-of-tree package: manifest parsed from
    ``extensions/reference-greeter/extension.json``, handler loaded through
    the host import boundary, one governed call recorded."""
    import reference_greeter.plugin as plugin_module

    manifest_path = REPO_ROOT / "extensions" / "reference-greeter" / "extension.json"
    body = manifest_path.read_bytes()
    manifest = json.loads(body)
    plugin_object = getattr(plugin_module, manifest["entrypoint"]["object"])

    catalog = ExtensionToolCatalog()
    contract = ExtensionContract.from_manifest(manifest, digest="digest-of-record")
    handler = load_entrypoint_handler(contract, plugin_object)
    tool = catalog.register(contract, plugin_object, handler=handler)

    assert tool.capability == "extension.tool:reference.greeter"
    assert tool.reversibility == "internal"

    async def run() -> ExtensionToolOutcome:
        effects = new_in_memory_effect_context(policy_evaluator=_allow)
        binding = catalog.tool_binding(tool, workspace_id="ws-ref", project_id="pr-ref")
        return await invoke_extension_tool(
            effects,
            tool,
            binding,
            {"target": "M9-E3"},
            run_id=RUN_ID,
            node_run_id=NODE_RUN_ID,
            attempt_id=ATTEMPT_ID,
        )

    outcome = asyncio.run(run())
    assert outcome.success
    assert outcome.result == "Hello, M9-E3!"
    assert outcome.invocation is not None
    assert outcome.invocation.status.value == "completed"
