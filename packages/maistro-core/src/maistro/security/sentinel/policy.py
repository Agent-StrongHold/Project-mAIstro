"""Sentinel policy enforcement: pre-call and post-call security pipeline.

Pre-call: validate + repair args, check permissions, audit log.
Post-call: Warden scan tool result, PII filter, token optimize, audit log.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal

from maistro.security._types import AuditEntry, SentinelVerdict, Violation, WardenVerdict
from maistro.security.sentinel.approver_graph import ApproverGraph
from maistro.security.sentinel.authz_types import AuthzDecision, Principal, Tier
from maistro.security.sentinel.elevation import ElevationStore, hash_args
from maistro.security.sentinel.pii_filter import scan_and_redact
from maistro.security.sentinel.rlphd import RlphdModel, RlphdThresholdStore, RlphdVerdict
from maistro.security.sentinel.token_optimizer import optimize_result
from maistro.security.sentinel.validator import validate_and_repair

logger = logging.getLogger("maistro.sentinel")

if TYPE_CHECKING:
    from maistro.security._types import AuditLog, AuthContext, PermissionTable
    from maistro.security.warden.detector import Warden


def check_permission(
    auth_context: AuthContext,
    tool_name: str,
    permission_table: PermissionTable,
) -> bool:
    return auth_context.can_use_tool(tool_name, permission_table)


def _principal_auth_context(principal: Principal) -> AuthContext:
    from maistro.security._types import AuthContext as _AuthContext

    return _AuthContext(user_id=principal.id, roles=frozenset(principal.roles))


class Sentinel:
    """Policy enforcement at every boundary crossing.

    Pre-call: validates args, checks permissions, logs audit.
    Post-call: scans result for threats + PII, optimizes tokens, logs audit.
    """

    def __init__(
        self,
        *,
        warden: Warden,
        permission_table: PermissionTable,
        audit_log: AuditLog | None = None,
        tier_policy: dict[tuple[str, str], Tier] | None = None,
        approver_graph: ApproverGraph | None = None,
        elevation_store: ElevationStore | None = None,
        rlphd_model: RlphdModel | None = None,
        rlphd_threshold_store: RlphdThresholdStore | None = None,
    ) -> None:
        self._warden = warden
        self._permission_table = permission_table
        self._audit_log = audit_log
        self._tier_policy = tier_policy or {}
        self._approver_graph = approver_graph
        self._elevation_store = elevation_store
        self._rlphd_model = rlphd_model
        self._rlphd_threshold_store = rlphd_threshold_store

    def resolve_tier(
        self,
        action: str,
        principal: Principal,
        *,
        reversibility: str = "reversible",
    ) -> Tier:
        """Most-specific static policy entry for (action, principal scope/role); else
        falls back to the ADR-050 reversibility default (SPEC-245 §Decision)."""
        for scope in (*principal.scopes, *principal.roles):
            tier = self._tier_policy.get((action, scope))
            if tier is not None:
                return tier
        if reversibility == "irreversible":
            return Tier.SELF_ELEVATION
        return Tier.OPEN

    async def authorize(
        self,
        action: str,
        principal: Principal,
        *,
        reversibility: str = "reversible",
        within_budget: bool = True,
        args: dict[str, Any] | None = None,
        rlphd_features: dict[str, float] | None = None,
    ) -> AuthzDecision:
        """ADR-068 §F steps 1-4, short-circuiting on first deny."""
        tier = self.resolve_tier(action, principal, reversibility=reversibility)

        authorized = check_permission(
            _principal_auth_context(principal), action, self._permission_table
        )
        if not authorized:
            return AuthzDecision(
                tier=tier,
                authorized=False,
                needs="none",
                approver_scope=None,
                within_budget=within_budget,
                rlphd=None,
                reason=f"principal '{principal.id}' lacks capability for '{action}'",
            )

        if not within_budget:
            return AuthzDecision(
                tier=tier,
                authorized=False,
                needs="none",
                approver_scope=None,
                within_budget=False,
                rlphd=None,
                reason="over budget",
            )

        if tier == Tier.BLOCKED:
            return AuthzDecision(
                tier=tier,
                authorized=False,
                needs="none",
                approver_scope=None,
                within_budget=True,
                rlphd=None,
                reason="action is blocked",
            )

        needs = self._resolve_needs(tier, principal)
        if tier == Tier.SELF_ELEVATION:
            cleared = await self._check_elevation_grant(action, principal, needs, args)
            if cleared is not None:
                return cleared

        approver_scope: str | None = None
        if tier == Tier.DELEGATED and self._approver_graph is not None:
            requester_scope = principal.scopes[0] if principal.scopes else principal.id
            approver_scope = self._approver_graph.resolve(action, requester_scope)

        rlphd_verdict: RlphdVerdict | None = None
        if tier == Tier.DELEGATED:
            rlphd_verdict, auto_acted_decision = await self._try_rlphd(
                action, principal, approver_scope, rlphd_features
            )
            if auto_acted_decision is not None:
                return auto_acted_decision

        return AuthzDecision(
            tier=tier,
            authorized=True,
            needs=needs,
            approver_scope=approver_scope,
            within_budget=True,
            rlphd=rlphd_verdict,
            reason="",
        )

    def _resolve_needs(
        self, tier: Tier, principal: Principal
    ) -> Literal["none", "self_elevation", "scoped_2fa", "delegated", "admin"]:
        if tier in (Tier.OPEN, Tier.ROLE_AUTO):
            return "none"
        if tier == Tier.SELF_ELEVATION:
            return "scoped_2fa" if principal.kind == "agent" else "self_elevation"
        if tier == Tier.DELEGATED:
            return "delegated"
        return "admin"  # Tier.ADMIN

    async def _check_elevation_grant(
        self,
        action: str,
        principal: Principal,
        needs: Literal["none", "self_elevation", "scoped_2fa", "delegated", "admin"],
        args: dict[str, Any] | None,
    ) -> AuthzDecision | None:
        """Return a cleared AuthzDecision if a prior elevation grant covers this call, else None."""
        if self._elevation_store is None:
            return None
        args_hash = hash_args(args) if needs == "scoped_2fa" and args else None
        grant = await self._elevation_store.find_valid(principal.id, action, args_hash)
        if grant is None:
            return None
        return AuthzDecision(
            tier=Tier.SELF_ELEVATION,
            authorized=True,
            needs="none",
            approver_scope=None,
            within_budget=True,
            rlphd=None,
            reason="cleared by a prior elevation grant",
        )

    async def _try_rlphd(
        self,
        action: str,
        principal: Principal,
        approver_scope: str | None,
        rlphd_features: dict[str, float] | None,
    ) -> tuple[RlphdVerdict | None, AuthzDecision | None]:
        """Predict and maybe auto-act at the DELEGATED tier; returns (verdict, auto_acted_decision)."""
        if self._rlphd_model is None or self._rlphd_threshold_store is None:
            return None, None
        opted_in = await self._rlphd_threshold_store.opted_in(principal.id, action)
        if not opted_in:
            return None, None
        theta = await self._rlphd_threshold_store.get_theta(principal.id, action, "delegated")
        p = self._rlphd_model.predict(rlphd_features or {})
        auto_acted = p >= theta
        verdict = RlphdVerdict(p=p, theta=theta, auto_acted=auto_acted)
        if not auto_acted:
            return verdict, None
        decision = AuthzDecision(
            tier=Tier.DELEGATED,
            authorized=True,
            needs="none",
            approver_scope=approver_scope,
            within_budget=True,
            rlphd=verdict,
            reason="auto-acted by RLPHD prediction",
        )
        return verdict, decision

    async def pre_call(
        self,
        tool_name: str,
        args: dict[str, Any],
        auth: AuthContext,
        schema: dict[str, Any],
    ) -> SentinelVerdict:
        violations: list[Violation] = []

        if not check_permission(auth, tool_name, self._permission_table):
            violations.append(
                Violation(
                    boundary="pre_call",
                    rule="permission_denied",
                    severity="error",
                    detail=f"User '{auth.user_id}' lacks permission for tool '{tool_name}'",
                )
            )
            verdict = SentinelVerdict(
                allowed=False,
                violations=tuple(violations),
            )
            await self._log_audit(
                boundary="pre_call",
                user_id=auth.user_id,
                team_id=auth.team_id,
                tool_name=tool_name,
                verdict="denied",
                violations=tuple(violations),
            )
            return verdict

        schema_verdict = validate_and_repair(args, schema)
        if schema_verdict.violations:
            violations.extend(schema_verdict.violations)

        verdict = SentinelVerdict(
            allowed=schema_verdict.allowed,
            repaired=schema_verdict.repaired,
            repaired_data=schema_verdict.repaired_data,
            violations=tuple(violations),
        )

        await self._log_audit(
            boundary="pre_call",
            user_id=auth.user_id,
            team_id=auth.team_id,
            tool_name=tool_name,
            verdict="allowed" if verdict.allowed else "denied",
            violations=tuple(violations),
            detail=f"repaired={schema_verdict.repaired}" if schema_verdict.repaired else "",
            repaired_data=schema_verdict.repaired_data if schema_verdict.repaired else None,
        )

        return verdict

    async def post_call(
        self,
        tool_name: str,
        result: str,
        auth: AuthContext,
    ) -> str:
        violations: list[Violation] = []
        processed = result

        warden_verdict = await self._warden.scan(processed, "tool_result")
        if not warden_verdict.clean:
            violations.append(
                Violation(
                    boundary="post_call",
                    rule="warden_tool_result",
                    severity="error",
                    detail=f"Warden flags: {', '.join(warden_verdict.flags)}",
                )
            )
            # Fix #3: tool results (egress) use the SAME threshold as user input (ingress).
            # Any flag blocks — tool results are the higher-risk boundary (injected content arrives here).
            processed = "[Tool result blocked by Warden -- contained injection attempt]"
            logger.warning(
                "Tool result BLOCKED: tool=%s, user=%s, flags=%s",
                tool_name,
                auth.user_id,
                warden_verdict.flags,
            )

        processed, pii_matches = scan_and_redact(processed)
        if pii_matches:
            violations.append(
                Violation(
                    boundary="post_call",
                    rule="pii_detected",
                    severity="warning",
                    detail=f"Redacted {len(pii_matches)} PII pattern(s): "
                    + ", ".join(m.pii_type for m in pii_matches),
                )
            )

        processed = optimize_result(processed, tool_name)

        await self._log_audit(
            boundary="post_call",
            user_id=auth.user_id,
            team_id=auth.team_id,
            tool_name=tool_name,
            verdict="clean" if not violations else "flagged",
            violations=tuple(violations),
        )

        return processed

    async def _log_audit(
        self,
        *,
        boundary: str,
        user_id: str,
        team_id: str = "",
        tool_name: str,
        verdict: str,
        violations: tuple[Violation, ...] = (),
        detail: str = "",
        repaired_data: dict[str, Any] | None = None,
    ) -> None:
        if self._audit_log is None:
            return
        if repaired_data and not detail:
            detail = f"repaired_data_keys={list(repaired_data.keys())}"
        try:
            await self._audit_log.log(
                AuditEntry(
                    boundary=boundary,
                    user_id=user_id,
                    team_id=team_id,
                    tool_name=tool_name,
                    verdict=verdict,
                    violations=violations,
                    detail=detail,
                )
            )
        except Exception:
            logger.exception("Audit log write failed (boundary=%s, tool=%s)", boundary, tool_name)


def _detection_layer(verdict: WardenVerdict) -> str:
    for flag in verdict.flags:
        if flag.startswith("llm_classification"):
            return "Layer 3 (LLM)"
        if flag.startswith("prescriptive_"):
            return "Layer 2.5 (Semantic)"
        if flag.startswith("high_instruction") or flag.startswith("encoded_"):
            return "Layer 2 (Heuristic)"
    return "Layer 1 (Pattern)"
