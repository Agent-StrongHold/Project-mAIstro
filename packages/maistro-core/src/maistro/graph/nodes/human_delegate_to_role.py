"""`human.delegate_to_role` — pause for whoever currently holds role X.

Unlike `human.approve_draft`/`human.ask_question`, the reviewer isn't a
hardcoded user_id — it's "whoever currently holds role X" (e.g. "on-call
PM", "current approver"). The role-holder lookup happens at *resume* time
(when the runtime actually needs to know who to notify / whose answer to
accept), not at graph-build time, so role reassignments mid-run are picked
up correctly.

No role->holder registry exists elsewhere in maistro-core, so this node
takes an injected resolver rather than inventing a new identity subsystem.
The resolved holder is represented as an `AuthContext`-shaped identity
(user_id + roles), matching the rest of the security subsystem's identity
model (`maistro.security._types.AuthContext`).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, ClassVar, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from . import register_node
from .base import (
    PAUSE_AWAITING_ROLE_DELEGATE,
    BaseNode,
    NodeContext,
    now_utc,
    pause_until,
)


@runtime_checkable
class RoleHolderResolver(Protocol):
    """Resolves a role name to the user_id currently holding it.

    Implementations live outside maistro-core (org-chart lookup, on-call
    schedule, etc.); this node only depends on the shape.
    """

    def resolve(self, role: str) -> str | None: ...


class DelegateToRoleIn(BaseModel):
    role: str = Field(description="Role to delegate to, e.g. 'on_call_pm'")
    payload: dict[str, Any] = Field(
        default_factory=dict, description="The task/contract handed to the role holder"
    )
    title: str = Field(default="", description="Short label shown to the resolved holder")
    timeout_seconds: int = Field(default=86_400)


class DelegateToRoleOut(BaseModel):
    verdict: Literal["approved", "rejected", "modified", "timed_out", "no_holder"] = "approved"
    resolved_user_id: str | None = None
    modified_payload: dict[str, Any] | None = None
    reviewer_note: str = ""
    timed_out: bool = False


@register_node
class HumanDelegateToRoleNode(BaseNode[DelegateToRoleIn, DelegateToRoleOut]):
    kind: ClassVar[str] = "human.delegate_to_role"
    kind_category: ClassVar = "hitl"
    input_schema: ClassVar[type[BaseModel]] = DelegateToRoleIn
    output_schema: ClassVar[type[BaseModel]] = DelegateToRoleOut
    cost_hint: ClassVar[float] = 0.0
    idempotent: ClassVar[bool] = True
    external_io: ClassVar[bool] = False
    display_name: ClassVar[str] = "Human: delegate to role"
    description: ClassVar[str] = (
        "Pause and delegate to whoever currently holds a role, resolved at "
        "resume time rather than graph-build time."
    )

    def __init__(self, *, role_resolver: RoleHolderResolver | None = None) -> None:
        self._role_resolver = role_resolver

    async def _execute(self, inputs: DelegateToRoleIn, ctx: NodeContext) -> DelegateToRoleOut:
        answers = (ctx.metadata or {}).get("hitl_answers") or {}
        resumed = answers.get(ctx.node_id)
        if resumed is not None:
            resolved_user_id = (
                self._role_resolver.resolve(inputs.role) if self._role_resolver else None
            )
            if resolved_user_id is None:
                return DelegateToRoleOut(verdict="no_holder", resolved_user_id=None)
            return DelegateToRoleOut(
                verdict=resumed.get("verdict", "approved"),
                resolved_user_id=resolved_user_id,
                modified_payload=resumed.get("modified_payload"),
                reviewer_note=str(resumed.get("reviewer_note") or ""),
                timed_out=bool(resumed.get("timed_out", False)),
            )

        resume_at = now_utc() + timedelta(seconds=inputs.timeout_seconds)
        pause_until(
            PAUSE_AWAITING_ROLE_DELEGATE,
            resume_at=resume_at,
            metadata={
                "role": inputs.role,
                "payload": inputs.payload,
                "title": inputs.title,
                "timeout_seconds": inputs.timeout_seconds,
            },
        )
        return DelegateToRoleOut()  # unreachable
