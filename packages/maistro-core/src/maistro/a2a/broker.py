"""A2A delegation broker — ADR-058 / SPEC-182 (Phases 1-2).

One A2A protocol behind an ``A2ABroker`` facade. This module provides the
in-process path (``LocalTransport``) plus the ``DelegationBudget`` capability
envelope and loop guard. The federated transport (SSRF-safe egress, ADR-038
circuit breaking) is Phase 3 follow-up.

DI-clean: the broker depends only on small protocols (a card resolver and an
agent invoker); it never imports the container or conduit.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from maistro.a2a.delegate import A2ATask, DelegationMode, TaskStatus
from maistro.a2a.guest_peers import DelegationResult

if TYPE_CHECKING:
    from maistro.agents.catalog import AgentCard

logger = logging.getLogger("maistro.a2a.broker")


class A2AError(Exception):
    """Base error for the A2A subsystem."""


class DelegationRefused(A2AError):
    """Delegation refused by budget, allow-list, or trust-tier policy."""


@dataclass(frozen=True)
class DelegationBudget:
    """Capability envelope carried (and decremented) across delegation hops.

    ``max_depth`` is the number of hops *remaining*; ``0`` means the holder
    must not delegate further. ``chain`` is the ordered set of agent/peer ids
    already on the path (circular-delegation guard).
    """

    deadline: datetime
    token_budget: int
    trace_id: str
    max_depth: int = 3
    chain: tuple[str, ...] = ()

    def check(self, target: str, *, now: datetime | None = None) -> None:
        """Raise :class:`DelegationRefused` if delegating to ``target`` is not allowed."""
        now = now or datetime.now(UTC)
        if self.max_depth <= 0:
            raise DelegationRefused(
                f"delegation depth exhausted (max_depth=0, trace={self.trace_id})"
            )
        if now >= self.deadline:
            raise DelegationRefused(f"delegation deadline passed (trace={self.trace_id})")
        if self.token_budget <= 0:
            raise DelegationRefused(f"token budget exhausted (trace={self.trace_id})")
        if target in self.chain:
            raise DelegationRefused(
                f"circular delegation: '{target}' already in chain {self.chain} "
                f"(trace={self.trace_id})"
            )

    def spend(self, target: str) -> DelegationBudget:
        """Return the budget the *target* hop receives: depth-1, target appended to chain."""
        return replace(self, max_depth=self.max_depth - 1, chain=(*self.chain, target))


@runtime_checkable
class CardResolver(Protocol):
    """Resolves an agent id to its :class:`AgentCard` (or ``None``)."""

    def resolve(self, agent_id: str, user_id: str = "") -> AgentCard | None: ...


@runtime_checkable
class AgentInvoker(Protocol):
    """Invokes a local agent with a task; injected by the app layer (DI-clean)."""

    async def __call__(self, task: A2ATask, budget: DelegationBudget) -> str: ...


@runtime_checkable
class Transport(Protocol):
    """One delegation transport (local in-process, or federated in Phase 3)."""

    async def run(self, task: A2ATask, budget: DelegationBudget) -> DelegationResult: ...


class LocalTransport:
    """In-process transport: invokes a local agent via an injected callable."""

    def __init__(self, invoker: AgentInvoker) -> None:
        self._invoker = invoker

    async def run(self, task: A2ATask, budget: DelegationBudget) -> DelegationResult:
        try:
            result = await self._invoker(task, budget)
        except Exception as exc:
            logger.error("Local delegation failed: %s (%s -> %s)", task.id, task.from_agent, exc)
            return DelegationResult(
                task_id=task.id,
                peer_name=task.to_agent,
                status=TaskStatus.FAILED,
                error=str(exc),
            )
        return DelegationResult(
            task_id=task.id,
            peer_name=task.to_agent,
            status=TaskStatus.COMPLETED,
            result=result,
        )


def _tier_rank(tier: str) -> int:
    """Numeric rank of a trust tier ('t0' most privileged … 'tN' least)."""
    try:
        return int(tier.lstrip("tT"))
    except ValueError:
        return 99


class A2ABroker:
    """Facade for agent-to-agent delegation (ADR-058, local transport v0)."""

    def __init__(self, *, resolver: CardResolver, local: Transport) -> None:
        self._resolver = resolver
        self._local = local

    async def delegate(
        self,
        *,
        from_agent: str,
        to: str,
        task: str,
        budget: DelegationBudget,
        user_id: str = "",
    ) -> DelegationResult:
        """Delegate ``task`` from ``from_agent`` to local agent ``to``.

        Raises:
            DelegationRefused: budget exhausted, cycle, allow-list, or
                trust-tier escalation.
        """
        budget.check(to)

        caller = self._resolver.resolve(from_agent, user_id)
        if caller is None:
            raise DelegationRefused(f"unknown calling agent '{from_agent}'")
        target = self._resolver.resolve(to, user_id)
        if target is None:
            raise DelegationRefused(f"unknown delegation target '{to}'")

        self._enforce_policy(caller, target)

        hop_budget = budget.spend(to)
        a2a_task = A2ATask(
            id=str(uuid.uuid4()),
            from_agent=from_agent,
            to_agent=to,
            task=task,
            status=TaskStatus.QUEUED,
            created_at=datetime.now(UTC),
            assigned_at=None,
            completed_at=None,
            result=None,
            error=None,
            delegation_mode=DelegationMode(caller.delegation_mode),
        )
        logger.info(
            "Delegating task %s: %s -> %s (depth_left=%d, trace=%s)",
            a2a_task.id,
            from_agent,
            to,
            hop_budget.max_depth,
            hop_budget.trace_id,
        )
        return await self._local.run(a2a_task, hop_budget)

    @staticmethod
    def _enforce_policy(caller: AgentCard, target: AgentCard) -> None:
        """Enforce delegation_mode/sub_agents allow-list and trust-tier ceiling."""
        mode = caller.delegation_mode
        explicitly_listed = target.id in caller.sub_agents

        if mode == DelegationMode.NONE:
            raise DelegationRefused(f"agent '{caller.id}' has delegation_mode=none")
        if mode == DelegationMode.ALLOW_LIST and not explicitly_listed:
            raise DelegationRefused(
                f"agent '{caller.id}' may not delegate to '{target.id}' "
                f"(allow-list: {list(caller.sub_agents)})"
            )
        if mode not in (DelegationMode.ALLOW_ALL, DelegationMode.ALLOW_LIST):
            raise DelegationRefused(f"agent '{caller.id}' has unknown delegation_mode '{mode}'")

        # ADR-058 resolved decision 3: target holds a subset of the caller's
        # authority (t0 is most privileged) unless explicitly allow-listed.
        if not explicitly_listed and _tier_rank(target.trust_tier) < _tier_rank(caller.trust_tier):
            raise DelegationRefused(
                f"trust-tier escalation: '{target.id}' ({target.trust_tier}) is more "
                f"privileged than caller '{caller.id}' ({caller.trust_tier})"
            )
