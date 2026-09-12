"""Sentinel policy enforcement: pre-call and post-call security pipeline.

Pre-call: check permissions and resource limits, validate + repair args, audit log.
Post-call: Warden scan tool result, PII filter, token optimize, audit log.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal

from maistro.observability.metrics import maistro_security_block_total
from maistro.security._types import (
    AuditEntry,
    GateResult,
    SentinelVerdict,
    Violation,
    WardenVerdict,
)
from maistro.security.sentinel.approver_graph import ApproverGraph
from maistro.security.sentinel.argument_limits import ToolArgumentLimits, check_argument_limits
from maistro.security.sentinel.authz_types import AuthzDecision, Principal, Tier
from maistro.security.sentinel.elevation import ElevationStore, hash_args
from maistro.security.sentinel.permission_source import PermissionSource, resolve_live_table
from maistro.security.sentinel.pii_filter import scan_and_redact
from maistro.security.sentinel.rlphd import RlphdModel, RlphdThresholdStore, RlphdVerdict
from maistro.security.sentinel.token_optimizer import optimize_result
from maistro.security.sentinel.validator import validate_and_repair
from maistro.security.warden.sanitizer import strip_terminal_escapes

logger = logging.getLogger("maistro.sentinel")

if TYPE_CHECKING:
    from maistro.security._types import AuditLog, AuthContext, PermissionTable
    from maistro.security.warden.detector import Warden


def check_permission(
    auth_context: AuthContext,
    tool_name: str,
    permission_table: PermissionTable,
    *,
    allow_on_miss: bool = False,
) -> bool:
    """Resolve one tool authorization against ``permission_table``.

    Default is fail-closed (ADR-072726-0d6b, implemented for #1165): a tool
    absent from the table is denied, so an omitted or empty deployment table
    can never authorize every tool. ``allow_on_miss=True`` is the explicit
    compatibility mode for non-production/test/demo wiring that predates the
    fail-closed default; production composition roots must not pass it, and
    no configuration field routes to it.
    """
    if allow_on_miss and tool_name not in permission_table:
        return True
    return auth_context.can_use_tool(tool_name, permission_table)


def _principal_auth_context(principal: Principal) -> AuthContext:
    from maistro.security._types import AuthContext as _AuthContext

    return _AuthContext(user_id=principal.id, roles=frozenset(principal.roles))


class Sentinel:
    """Policy enforcement at every boundary crossing.

    Pre-call: checks permission and argument resource limits, then validates args.
    Post-call: scans result for threats + PII, optimizes tokens, logs audit.
    """

    def __init__(
        self,
        *,
        warden: Warden,
        permission_table: PermissionTable,
        permission_source: PermissionSource | None = None,
        audit_log: AuditLog | None = None,
        tier_policy: dict[tuple[str, str], Tier] | None = None,
        approver_graph: ApproverGraph | None = None,
        elevation_store: ElevationStore | None = None,
        rlphd_model: RlphdModel | None = None,
        rlphd_threshold_store: RlphdThresholdStore | None = None,
        argument_limits: ToolArgumentLimits | None = None,
        allow_on_miss: bool = False,
    ) -> None:
        self._warden = warden
        self._permission_table = permission_table
        # Live permission authority (#1165, ADR-072726-0d6b): wired by
        # production composition roots so a decision consults canonical
        # capability state at the moment it is made, and a runtime capability
        # disable/revoke lands on the very next decision without a restart.
        # When set, it supersedes the static table; when it cannot decide,
        # the decision denies (fail-closed) -- the static table is never used
        # to rescue an unavailable source, because a stale snapshot must not
        # outvote a revoke.
        self._permission_source = permission_source
        self._audit_log = audit_log
        self._tier_policy = tier_policy or {}
        self._approver_graph = approver_graph
        self._elevation_store = elevation_store
        self._rlphd_model = rlphd_model
        self._rlphd_threshold_store = rlphd_threshold_store
        self._argument_limits = argument_limits or ToolArgumentLimits.from_environment()
        # Fail-closed default (ADR-072726-0d6b, #1165): a tool absent from the
        # permission table is DENIED. allow_on_miss=True is the explicit
        # compatibility mode for non-production/test/demo wiring; it is never
        # set by a production composition root and no configuration field can
        # arm it, so the warning below is the loud trace of a permissive
        # construction.
        self._allow_on_miss = allow_on_miss
        if allow_on_miss:
            logger.warning(
                "Sentinel armed in allow-on-miss COMPATIBILITY mode: tools absent "
                "from the permission table are ALLOWED. Non-production/test/demo "
                "use only (ADR-072726-0d6b); production wiring must configure an "
                "explicit permission source instead."
            )

    async def _effective_table(self) -> PermissionTable | None:
        """The permission table for THIS decision, or None when undecidable.

        A wired source is consulted live on every call -- that is the #1165
        runtime-revoke path: canonical capability/binding state changes reach
        the next decision without a process restart. With no source wired,
        the static construction table applies (unchanged legacy shape).
        """
        if self._permission_source is None:
            return self._permission_table
        return await resolve_live_table(self._permission_source)

    async def _permission_denial_reason(self, action: str, principal: Principal) -> str | None:
        """Why this (action, principal) is denied right now, or None when permitted.

        The one fail-closed permission gate every authorize flows through: the
        live permission source (#1165) is resolved here so the decision reads
        canonical state at the moment it is made, an unavailable source denies,
        and a capability miss denies.
        """
        table = await self._effective_table()
        if table is None:
            return f"permission source unavailable for '{action}'; denied fail-closed"
        authorized = check_permission(
            _principal_auth_context(principal),
            action,
            table,
            allow_on_miss=self._allow_on_miss,
        )
        if not authorized:
            return f"principal '{principal.id}' lacks capability for '{action}'"
        return None

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

        denial_reason = await self._permission_denial_reason(action, principal)
        if denial_reason is not None:
            return AuthzDecision(
                tier=tier,
                authorized=False,
                needs="none",
                approver_scope=None,
                within_budget=within_budget,
                rlphd=None,
                reason=denial_reason,
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

        table = await self._effective_table()
        if table is None or not check_permission(
            auth, tool_name, table, allow_on_miss=self._allow_on_miss
        ):
            violations.append(
                Violation(
                    boundary="pre_call",
                    rule="permission_denied",
                    severity="error",
                    detail=(
                        "Permission source unavailable; denied fail-closed"
                        if table is None
                        else f"User '{auth.user_id}' lacks permission for tool '{tool_name}'"
                    ),
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

        limit_violation = check_argument_limits(args, limits=self._argument_limits)
        if limit_violation is not None:
            violations.append(limit_violation)
            verdict = SentinelVerdict(allowed=False, violations=tuple(violations))
            await self._log_audit(
                boundary="pre_call",
                user_id=auth.user_id,
                team_id=auth.team_id,
                tool_name=tool_name,
                verdict="denied",
                violations=tuple(violations),
                detail=limit_violation.detail,
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
        """Return the sanitized tool result, or the established refusal text."""
        outcome = await self.process_output(tool_name, result, auth)
        if outcome.blocked:
            return "[Tool result blocked by Warden -- contained injection attempt]"
        return outcome.sanitized_text

    async def process_output(
        self,
        tool_name: str,
        result: str,
        auth: AuthContext,
    ) -> GateResult:
        """Apply the post-call policy and return its structured security outcome.

        ``post_call`` remains the compatibility API for agent strategies. Output
        projection boundaries use this method so they can distinguish a refusal
        from an allowed, explicitly sanitized value without repeating Warden or
        PII policy logic.
        """
        violations: list[Violation] = []
        processed = strip_terminal_escapes(result)

        # SECURITY-REVIEW: agent/tool output is untrusted until Warden and PII
        # processing complete; do not log or persist ``result`` before this gate.
        warden_verdict = await self._warden.scan(processed, "tool_result")
        if not warden_verdict.clean:
            violations.append(
                Violation(
                    boundary="post_call",
                    rule="warden_tool_result",
                    severity="error",
                    detail="Untrusted output refused by Warden",
                )
            )
            maistro_security_block_total.inc(
                gate="sentinel_output",
                reason="unsafe_output",
            )
            logger.warning("Untrusted output blocked by Sentinel")
            await self._log_audit(
                boundary="post_call",
                user_id=auth.user_id,
                team_id=auth.team_id,
                tool_name=tool_name,
                verdict="flagged",
                violations=tuple(violations),
            )
            return GateResult(
                sanitized_text="",
                warden_verdict=warden_verdict,
                blocked=True,
                block_reason="unsafe_output",
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

        return GateResult(
            sanitized_text=processed,
            warden_verdict=warden_verdict,
        )

    async def record_output_handler_outcome(
        self,
        tool_name: str,
        outcome: Literal["failed", "error", "invalid_result"],
    ) -> None:
        """Record a static, identity-free terminal handler outcome."""
        rules = {
            "failed": "handler_failed",
            "error": "handler_error",
            "invalid_result": "handler_invalid_result",
        }
        await self._log_audit(
            boundary="post_call",
            user_id="",
            team_id="",
            tool_name=tool_name,
            verdict="error",
            violations=(
                Violation(
                    boundary="post_call",
                    rule=rules[outcome],
                    severity="error",
                ),
            ),
        )

    async def record_output_security_error(self, tool_name: str) -> None:
        """Record a static, identity-free fail-closed output-gate outcome."""
        await self._log_audit(
            boundary="post_call",
            user_id="",
            team_id="",
            tool_name=tool_name,
            verdict="error",
            violations=(
                Violation(
                    boundary="post_call",
                    rule="output_security_error",
                    severity="error",
                ),
            ),
        )

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
            logger.error("Security audit log write failed")


def _detection_layer(verdict: WardenVerdict) -> str:
    for flag in verdict.flags:
        if flag.startswith("llm_classification"):
            return "Layer 3 (LLM)"
        if flag.startswith("prescriptive_"):
            return "Layer 2.5 (Semantic)"
        if flag.startswith("high_instruction") or flag.startswith("encoded_"):
            return "Layer 2 (Heuristic)"
    return "Layer 1 (Pattern)"
