"""Authorized administrative recovery for the strike ladder (#1172)."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from maistro.security._types import AuditEntry, AuditLog
from maistro.security.sentinel.authz_types import Principal
from maistro.security.sentinel.policy import Sentinel
from maistro.security.strikes import StrikeRecord

logger = logging.getLogger("maistro.strikes.recovery")


class StrikeRecoveryService:
    """M1 product-local projection: Recovery

    Perform strike recovery only for an authorized, different principal.

    The recovery action is checked through Sentinel's capability path rather
    than a private role check. The service also requires the canonical admin
    role as defense in depth: absent permission-table entries intentionally
    mean "allowed" for legacy tool compatibility, and that default must never
    turn an administrative recovery into self-service.
    """

    ACTION = "security.strikes.recover"

    def __init__(
        self,
        *,
        tracker: Any,
        sentinel: Sentinel,
        audit_log: AuditLog | None = None,
    ) -> None:
        self._tracker = tracker
        self._sentinel = sentinel
        self._audit_log = audit_log

    async def unlock(self, acting_principal: Principal, target_user_id: str) -> StrikeRecord | None:
        return await self._mutate("unlock", acting_principal, target_user_id)

    async def enable(self, acting_principal: Principal, target_user_id: str) -> StrikeRecord | None:
        return await self._mutate("enable", acting_principal, target_user_id)

    async def remove_strikes(
        self,
        acting_principal: Principal,
        target_user_id: str,
        count: int | None = None,
    ) -> StrikeRecord | None:
        return await self._mutate("remove_strikes", acting_principal, target_user_id, count=count)

    async def _mutate(
        self,
        operation: str,
        acting_principal: Principal,
        target_user_id: str,
        *,
        count: int | None = None,
    ) -> StrikeRecord | None:
        action = f"{self.ACTION}.{operation}"
        if acting_principal.id == target_user_id:
            await self._audit(
                acting_principal,
                target_user_id,
                action,
                "denied",
                "self-service recovery is not permitted",
            )
            return None

        decision = await self._sentinel.authorize(action, acting_principal)
        # The explicit admin role is required in addition to Sentinel's
        # permission-table decision. This closes the table's intentional
        # absent-entry allow default for this security-sensitive operation.
        if not decision.authorized or "admin" not in acting_principal.roles:
            await self._audit(
                acting_principal,
                target_user_id,
                action,
                "denied",
                decision.reason or "administrative authorization required",
            )
            return None

        method: Callable[..., Awaitable[StrikeRecord | None]] = getattr(self._tracker, operation)
        if operation == "remove_strikes":
            record = await method(target_user_id, count=count)
        else:
            record = await method(target_user_id)
        if record is None:
            await self._audit(
                acting_principal,
                target_user_id,
                action,
                "denied",
                "target principal has no strike record",
            )
            return None

        await self._audit(acting_principal, target_user_id, action, "granted", "recovery applied")
        return record

    async def _audit(
        self,
        actor: Principal,
        target_user_id: str,
        action: str,
        outcome: str,
        detail: str,
    ) -> None:
        if self._audit_log is None:
            return
        await self._audit_log.log(
            AuditEntry(
                boundary="strike_recovery",
                user_id=actor.id,
                tool_name=action,
                verdict=outcome,
                detail=(
                    f"actor_id={actor.id} target_id={target_user_id} "
                    f"action={action} outcome={outcome}: {detail}"
                ),
            )
        )
