"""Delegability evaluator built on Sentinel authorization."""

from __future__ import annotations

from maistro.security.delegability.types import (
    DelegabilityContext,
    DelegabilityDecision,
    DelegabilityStatus,
    ProposedAction,
)
from maistro.security.sentinel.authz_types import AuthzDecision, Principal, Tier
from maistro.security.sentinel.policy import Sentinel


async def evaluate_delegability(
    action: ProposedAction,
    principal: Principal,
    sentinel: Sentinel,
    *,
    context: DelegabilityContext | None = None,
) -> DelegabilityDecision:
    """Evaluate what authority exists now and what would unlock more.

    Sentinel remains the policy decision point. This function translates its
    answer into a shape that an agent can use for planning: execute, continue
    with safe subactions, request approval, or stop.
    """

    ctx = context or DelegabilityContext()
    authz = await sentinel.authorize(
        action.name,
        principal,
        reversibility=action.reversibility,
        within_budget=ctx.within_budget,
        args=action.args,
        rlphd_features=ctx.rlphd_features,
    )

    reasons = _reasons(action, authz)
    unlock_requirements = _unlock_requirements(action, authz)
    status = _status(action, authz, unlock_requirements)
    confidence = authz.rlphd.p if authz.rlphd is not None else None

    return DelegabilityDecision(
        action=action.name,
        status=status,
        authz=authz,
        reasons=tuple(reasons),
        missing_policy=action.missing_policy,
        unlock_requirements=tuple(unlock_requirements),
        safe_subactions=action.safe_subactions,
        reversibility=action.reversibility,
        confidence=confidence,
    )


def _status(
    action: ProposedAction,
    authz: AuthzDecision,
    unlock_requirements: list[str],
) -> DelegabilityStatus:
    if authz.tier == Tier.BLOCKED:
        return "blocked"
    if not authz.authorized:
        return "not_yet_delegable"
    if not unlock_requirements:
        return "delegable"
    if action.safe_subactions:
        return "partially_delegable"
    return "not_yet_delegable"


def _reasons(action: ProposedAction, authz: AuthzDecision) -> list[str]:
    reasons: list[str] = []
    if authz.reason:
        reasons.append(authz.reason)
    if authz.tier == Tier.BLOCKED:
        reasons.append("action is blocked by policy")
    if not authz.within_budget:
        reasons.append("budget has not been delegated for this action")
    if authz.needs != "none":
        reasons.append(f"action requires {authz.needs}")
    if action.reversibility == "irreversible":
        reasons.append("action is irreversible")
    reasons.extend(action.impacts)
    return _dedupe(reasons)


def _unlock_requirements(action: ProposedAction, authz: AuthzDecision) -> list[str]:
    requirements: list[str] = []
    if not authz.authorized and authz.reason:
        requirements.append(authz.reason)
    if not authz.within_budget:
        requirements.append("grant or raise the budget for this action")
    if authz.needs == "self_elevation":
        requirements.append("principal must complete self-elevation")
    elif authz.needs == "scoped_2fa":
        requirements.append("owning human must approve this scoped action")
    elif authz.needs == "delegated":
        approver = authz.approver_scope or "configured approver"
        requirements.append(f"{approver} must approve this action")
    elif authz.needs == "admin":
        requirements.append("admin must approve this action")
    requirements.extend(action.missing_policy)
    return _dedupe(requirements)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
