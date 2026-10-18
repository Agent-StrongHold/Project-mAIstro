"""Shared protocol conformance for tools, built-in and third-party alike.

The epic acceptance criterion: "external and built-in implementations pass
the same protocol conformance suites where semantically equivalent." This
module is that suite for the tool contract: one battery of checks over the
:class:`ConformantTool` protocol — exposure, canonical results, attributable
errors, denial and cancellation handling, declared classification — that any
tool surface runs, whichever side of the extension boundary it lives on.

The checks are semantic, not stylistic: they hold the *observable behavior*
of a tool call to the canonical contract (one Invocation per call, correlation
ids attached, dispositions in the closed vocabulary). Where semantics do not
overlap — an out-of-tree package's packaging, for instance — the suite stays
silent; that is the isolation fixture's job (M9-A3).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from maistro.capabilities.invocation import InvocationStatus
from maistro.extensions.tool_skill.execution import (
    ERROR_CODE_APPROVAL,
    ERROR_CODE_CANCELLED,
    ERROR_CODE_DENIAL,
    ERROR_CODE_HANDLER_ERROR,
    ERROR_CODE_TIMEOUT,
    ExtensionToolCancellation,
    ExtensionToolOutcome,
)


@runtime_checkable
class ConformantTool(Protocol):
    """The tool surface the shared conformance suite holds every tool to."""

    def describe(self) -> Mapping[str, Any]:
        """The model-facing exposure descriptor."""
        ...

    async def invoke(self, **kwargs: Any) -> ExtensionToolOutcome:
        """One canonical, attributable tool call."""
        ...


@dataclass(frozen=True)
class CheckResult:
    """One conformance check's outcome."""

    name: str
    passed: bool
    detail: str = ""


@dataclass(frozen=True)
class ConformanceReport:
    """The full report for one tool subject."""

    subject: str
    results: tuple[CheckResult, ...] = ()

    @property
    def passed(self) -> bool:
        """Whether every check passed."""
        return all(result.passed for result in self.results)

    @property
    def failures(self) -> tuple[CheckResult, ...]:
        """The failing checks, in run order."""
        return tuple(result for result in self.results if not result.passed)


CheckFn = Callable[[ConformantTool], Awaitable[CheckResult]]


def _result(name: str, passed: bool, detail: str = "") -> CheckResult:
    return CheckResult(name=name, passed=passed, detail=detail)


async def check_exposure_is_canonical(tool: ConformantTool) -> CheckResult:
    """The descriptor names the tool and carries a canonical classification."""
    described = tool.describe()
    name = str(described.get("name", "") or described.get("tool_id", ""))
    if not name:
        return _result("exposure-is-canonical", False, "descriptor has no name")
    reversibility = described.get("reversibility", "")
    if reversibility not in {"internal", "reversible", "irreversible"}:
        return _result(
            "exposure-is-canonical",
            False,
            f"reversibility {reversibility!r} is outside the ADR-050 taxonomy",
        )
    return _result("exposure-is-canonical", True)


async def check_result_is_canonical(tool: ConformantTool) -> CheckResult:
    """The happy path completes with an attributable canonical outcome."""
    outcome = await tool.invoke(mode="conformance-result")
    if outcome.status is not InvocationStatus.COMPLETED:
        # ``success`` is derived from this same status; the status check is
        # the whole test.
        return _result(
            "result-is-canonical",
            False,
            f"expected completed, got {outcome.status.value}: {outcome.error}",
        )
    if not outcome.invocation_id:
        return _result("result-is-canonical", False, "completed call recorded no Invocation")
    if not (outcome.run_id and outcome.node_run_id and outcome.attempt_id):
        return _result(
            "result-is-canonical",
            False,
            "completed call is missing Run/NodeRun/Attempt correlation",
        )
    return _result("result-is-canonical", True)


async def check_error_is_canonical(tool: ConformantTool) -> CheckResult:
    """A failing call is a FAILED outcome with a typed error and correlation."""
    outcome = await tool.invoke(mode="conformance-error")
    if outcome.status is not InvocationStatus.FAILED:
        return _result(
            "error-is-canonical",
            False,
            f"expected failed, got {outcome.status.value}: {outcome.error}",
        )
    if outcome.error_code != ERROR_CODE_HANDLER_ERROR:
        return _result(
            "error-is-canonical",
            False,
            f"a handler failure must carry error_code {ERROR_CODE_HANDLER_ERROR!r}, "
            f"got {outcome.error_code!r}",
        )
    if not outcome.error:
        return _result(
            "error-is-canonical",
            False,
            "failed outcome must carry error text",
        )
    if not outcome.invocation_id:
        return _result(
            "error-is-canonical",
            False,
            "failed call created no attributable Invocation",
        )
    return _result("error-is-canonical", True)


async def check_cancellation_is_canonical(tool: ConformantTool) -> CheckResult:
    """A cancelled call is the canonical cancelled disposition, never success.

    Both cancellation spellings are held: deadline expiry surfaces as
    :class:`ExtensionToolCancellation` (carrying the outcome), and an in-flight
    task cancellation re-raises :class:`asyncio.CancelledError` with the
    outcome attached to ``exc.outcome``. Success over an interruption is
    structurally impossible once the status is pinned to the ledger's
    ``UNKNOWN`` row — the status and family checks above are the whole
    contract.
    """
    outcome: ExtensionToolOutcome | None
    try:
        outcome = await tool.invoke(mode="conformance-cancel")
    except ExtensionToolCancellation as exc:
        outcome = exc.outcome
    except asyncio.CancelledError as exc:
        candidate = getattr(exc, "outcome", None)
        if not isinstance(candidate, ExtensionToolOutcome):
            return _result(
                "cancellation-is-canonical",
                False,
                "cancellation carried no canonical outcome",
            )
        outcome = candidate
    if outcome is None:
        return _result("cancellation-is-canonical", False, "cancelled call returned normally")
    if outcome.status is not InvocationStatus.UNKNOWN:
        return _result(
            "cancellation-is-canonical",
            False,
            f"an interrupted call must report the ledger's UNKNOWN row, got {outcome.status.value}",
        )
    if outcome.error_code not in {ERROR_CODE_CANCELLED, ERROR_CODE_TIMEOUT}:
        return _result(
            "cancellation-is-canonical",
            False,
            f"interruption family must be named in error_code, got {outcome.error_code!r}",
        )
    return _result("cancellation-is-canonical", True)


async def check_denial_is_attributable(tool: ConformantTool) -> CheckResult:
    """A refused call is the canonical refusal family, fully attributed.

    The refused family is policy denial (``policy_denied``) and approval
    gating (``approval_required``): both refuse execution without creating an
    Invocation, and both must stay attributable — execution-scope correlation,
    the classification the decision ran on, and for an approval gate the
    durable request id a human resolves later. The family is typed by
    ``error_code`` on a ``FAILED`` status, not by a second status vocabulary.
    """
    outcome = await tool.invoke(mode="conformance-deny")
    if outcome.status is not InvocationStatus.FAILED:
        return _result(
            "denial-is-attributable",
            False,
            f"a refused call must be FAILED, got {outcome.status.value}",
        )
    if outcome.error_code not in {ERROR_CODE_DENIAL, ERROR_CODE_APPROVAL}:
        return _result(
            "denial-is-attributable",
            False,
            f"expected refusal family in error_code, got {outcome.error_code!r}: {outcome.error}",
        )
    if not (outcome.run_id and outcome.attempt_id):
        return _result(
            "denial-is-attributable",
            False,
            "refused outcome must stay attributable to its execution scope",
        )
    if outcome.effect is None:
        return _result(
            "denial-is-attributable",
            False,
            "refused outcome does not name the classification the decision ran on",
        )
    if outcome.error_code == ERROR_CODE_APPROVAL and not outcome.approval_request_id:
        return _result(
            "denial-is-attributable",
            False,
            "approval_required outcome carries no durable request id",
        )
    return _result("denial-is-attributable", True)


DEFAULT_CHECKS: tuple[CheckFn, ...] = (
    check_exposure_is_canonical,
    check_result_is_canonical,
    check_error_is_canonical,
    check_cancellation_is_canonical,
    check_denial_is_attributable,
)


async def run_conformance(
    subject: ConformantTool,
    *,
    checks: Sequence[CheckFn] = DEFAULT_CHECKS,
    name: str = "",
) -> ConformanceReport:
    """Run the shared battery over one tool subject.

    Every check runs against the same subject instance; the subject's own
    ``invoke`` maps the suite's ``mode`` hints onto the scenarios it can
    exhibit. A tool that cannot produce a scenario fails that check — the
    suite does not let a subject grade its own homework.
    """
    described = subject.describe()
    subject_name = str(name or described.get("name") or described.get("tool_id") or "tool")
    collected: list[CheckResult] = []
    for check in checks:
        collected.append(await check(subject))
    return ConformanceReport(subject=subject_name, results=tuple(collected))
