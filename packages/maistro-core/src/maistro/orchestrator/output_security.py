"""Production output-security gate for MasterOrchestrator projections."""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING, Literal

from maistro.observability.metrics import maistro_security_block_total
from maistro.security._types import AuthContext, IdentityKind
from maistro.security.sentinel.policy import Sentinel
from maistro.security.warden.detector import Warden

if TYPE_CHECKING:
    from maistro.orchestrator.master import StageHandler, WorkItem
    from maistro.security._types import AuditLog

logger = logging.getLogger("maistro.orchestrator.output_security")

OUTPUT_SECURITY_OUTCOME_KEY = "security_outcome"
OUTPUT_SECURITY_ALLOWED = "allowed"
OUTPUT_SECURITY_BLOCKED = "blocked"
OUTPUT_SECURITY_ERROR = "error"
OUTPUT_SECURITY_BLOCKED_RESULT = "Output blocked by security policy."
OUTPUT_SECURITY_ERROR_RESULT = "Output security check unavailable."
HANDLER_OUTCOME_KEY = "handler_outcome"
HANDLER_OUTCOME_FAILED: Literal["failed"] = "failed"
HANDLER_OUTCOME_ERROR: Literal["error"] = "error"
HANDLER_OUTCOME_INVALID: Literal["invalid_result"] = "invalid_result"
HANDLER_ERROR_RESULT = "Work item handler failed."
HANDLER_INVALID_RESULT = "Work item handler returned an invalid result."
MIN_PROJECTED_XP = 0
MAX_PROJECTED_XP = 100

_OUTPUT_TOOL_NAME = "master_orchestrator_work_item"
_OUTPUT_AUTH = AuthContext(
    kind=IdentityKind.SYSTEM,
    auth_method="master_orchestrator",
)
_SAFE_HANDLER_OUTCOMES = frozenset(
    {
        HANDLER_OUTCOME_FAILED,
        HANDLER_OUTCOME_ERROR,
        HANDLER_OUTCOME_INVALID,
    }
)


def _allowed_metadata(item: WorkItem) -> dict[str, object]:
    """Project only bounded, non-text metadata from untrusted handler output."""
    metadata: dict[str, object] = {
        OUTPUT_SECURITY_OUTCOME_KEY: OUTPUT_SECURITY_ALLOWED,
    }
    xp_earned = item.metadata.get("xp_earned")
    if type(xp_earned) is int and MIN_PROJECTED_XP <= xp_earned <= MAX_PROJECTED_XP:
        metadata["xp_earned"] = xp_earned
    handler_outcome = item.metadata.get(HANDLER_OUTCOME_KEY)
    if handler_outcome in _SAFE_HANDLER_OUTCOMES:
        metadata[HANDLER_OUTCOME_KEY] = handler_outcome
    return metadata


def build_output_security_gate(
    *,
    warden: Warden | None = None,
    sentinel: Sentinel | None = None,
    audit_log: AuditLog | None = None,
) -> StageHandler:
    """Build the fail-closed Warden+Sentinel gate used by production planners.

    Passing an already-wired Sentinel preserves a Container's Warden and audit
    dependencies. Otherwise this factory assembles the same output pipeline from
    a Warden and optional audit log. The returned handler is the existing
    MasterOrchestrator injection seam; it does not create another execution
    lifecycle.
    """
    # Strict runtime cycle: master imports this factory to establish its safe
    # default, while this adapter needs master's canonical status vocabulary.
    from maistro.orchestrator.master import WorkItemStatus

    if sentinel is not None and (warden is not None or audit_log is not None):
        raise ValueError("warden and audit_log cannot be combined with an injected sentinel")

    output_sentinel = sentinel or Sentinel(
        warden=warden or Warden(),
        permission_table={},
        audit_log=audit_log,
    )

    async def secure_output(item: WorkItem) -> WorkItem:
        try:
            # SECURITY-REVIEW: WorkItem result and metadata are untrusted handler
            # output. Only Sentinel's sanitized text and allowlisted metadata may
            # cross into the canonical Run projection.
            outcome = await output_sentinel.process_output(
                _OUTPUT_TOOL_NAME,
                item.result,
                _OUTPUT_AUTH,
            )
            handler_outcome = item.metadata.get(HANDLER_OUTCOME_KEY)
            if handler_outcome == HANDLER_OUTCOME_FAILED:
                await output_sentinel.record_output_handler_outcome(
                    _OUTPUT_TOOL_NAME,
                    HANDLER_OUTCOME_FAILED,
                )
            elif handler_outcome == HANDLER_OUTCOME_ERROR:
                await output_sentinel.record_output_handler_outcome(
                    _OUTPUT_TOOL_NAME,
                    HANDLER_OUTCOME_ERROR,
                )
            elif handler_outcome == HANDLER_OUTCOME_INVALID:
                await output_sentinel.record_output_handler_outcome(
                    _OUTPUT_TOOL_NAME,
                    HANDLER_OUTCOME_INVALID,
                )
        except Exception:
            try:
                await output_sentinel.record_output_security_error(_OUTPUT_TOOL_NAME)
            except Exception:
                logger.error("Master Orchestrator security audit recording failed")
            maistro_security_block_total.inc(
                gate="master_orchestrator_output",
                reason="processing_error",
            )
            logger.error("Master Orchestrator output security check failed closed")
            return replace(
                item,
                status=WorkItemStatus.FAILED,
                result=OUTPUT_SECURITY_ERROR_RESULT,
                metadata={OUTPUT_SECURITY_OUTCOME_KEY: OUTPUT_SECURITY_ERROR},
            )

        if outcome.blocked:
            return replace(
                item,
                status=WorkItemStatus.FAILED,
                result=OUTPUT_SECURITY_BLOCKED_RESULT,
                metadata={OUTPUT_SECURITY_OUTCOME_KEY: OUTPUT_SECURITY_BLOCKED},
            )

        return replace(
            item,
            result=outcome.sanitized_text,
            metadata=_allowed_metadata(item),
        )

    return secure_output
