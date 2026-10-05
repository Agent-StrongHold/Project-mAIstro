"""Canonical binding of one external Agent delegation (issue #959, M9-D2).

Every external Agent call must be attributable to the canonical caller, the
delegating Workspace/Project scope, the delegated Goal/Subgoal context, the
canonical Run/NodeRun/Attempt that admitted it, and the effect identity the
transport keyed. :class:`DelegationContext` is that binding: one validated,
frozen record that rides the outbound request, is recorded on the delegated
child Run's provenance, and is filed as inbound evidence by the receiving
admission endpoint.

The context is *evidence and attenuation*, not a second authorization path.
Scope authority on the receiving side remains the receiver's own admission
guards; the sending side's ceiling is the peer's declared trust policy
(``PeerTrust.allowed_scopes``). A delegation claiming more authority than the
ceiling allows is refused before anything is dispatched, and a remote peer's
generated ids are carried as receipts only — they never replace the canonical
Goal/Run/Invocation identity (ADR-081226-6b46, ADR-082526-7f02).
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationInfo


class DelegationContextError(ValueError):
    """An external delegation lacks the canonical caller/scope it must carry."""


class DelegationScopeExceeded(DelegationContextError):
    """The delegation claims capability scopes beyond its declared ceiling."""


def _refuse_blank(value: str, info: ValidationInfo) -> str:
    """Refuse a whitespace-only canonical identity value.

    A blank identity is no attribution at all, so it must fail construction
    rather than ride to a peer as if it were evidence. Referenced through
    ``Annotated`` below (the same shape as ``scheduling.model``), so the
    validator is applied where each identity field is declared.
    """
    if not value.strip():
        raise ValueError(f"{info.field_name} must not be blank")
    return value


#: A canonical identity/context string: non-blank, never whitespace-only.
_IdentityStr = Annotated[str, AfterValidator(_refuse_blank)]


def validate_goal_binding(context: DelegationContext) -> None:
    """Refuse an incoherent Goal/Subgoal binding.

    A bound Goal names its revision (canonical Goal identity carries one), a
    parent Goal only rides on a bound Goal, and a revision is meaningless
    without its Goal. Admission paths call this before dispatching so a
    malformed binding fails the delegation instead of being recorded as if
    it were evidence. The receiving side deliberately does not call it: it
    files the sender's binding verbatim as provenance.
    """
    if not context.goal_id:
        if context.goal_revision is not None:
            raise DelegationContextError("goal_revision requires goal_id")
        if context.subgoal_of:
            raise DelegationContextError("subgoal_of requires goal_id")
        return
    if context.goal_revision is None:
        raise DelegationContextError("a bound Goal names its revision (goal_revision)")


def attenuate_scopes(requested: tuple[str, ...], ceiling: tuple[str, ...]) -> tuple[str, ...]:
    """Narrow the requested scopes to the authority the ceiling actually allows.

    The result preserves the caller's order and drops duplicates. A requested
    scope the ceiling does not list is a refusal, not a silent narrowing: an
    operator that never granted a scope must see the delegation refused rather
    than watch it proceed with the remainder.
    """
    if not requested:
        return ()
    ceiling_set = set(ceiling)
    exceeded = [scope for scope in requested if scope not in ceiling_set]
    if exceeded:
        raise DelegationScopeExceeded(
            "delegated authority exceeds the peer's allowed scopes: "
            + ", ".join(sorted(set(exceeded)))
        )
    narrowed: list[str] = []
    for scope in requested:
        if scope not in narrowed:
            narrowed.append(scope)
    return tuple(narrowed)


class DelegationContext(BaseModel):
    """The canonical identity/context binding for one external delegation.

    Every field is a fact about the delegating side. ``delegation_key`` is the
    canonical effect identity the transport and the child Run already share;
    the remote task id received in return is a receipt of the transport, never
    a replacement for it.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    # The canonical identity fields refuse whitespace-only values: a blank
    # identity is no attribution at all, so it must fail construction rather
    # than ride to a peer as if it were evidence. Optional fields (attempt_id,
    # the Goal/Subgoal context) stay verbatim — absent stays absent.
    caller_principal_id: _IdentityStr = Field(min_length=1)
    delegating_agent: _IdentityStr = Field(min_length=1)
    workspace_id: _IdentityStr = Field(min_length=1)
    project_id: _IdentityStr = Field(min_length=1)
    run_id: _IdentityStr = Field(min_length=1)
    node_run_id: _IdentityStr = Field(min_length=1)
    # A dispatching Attempt exists in production execution; it stays optional
    # so transport-level constructions that have not entered an Attempt yet
    # can still carry the rest of the binding truthfully.
    attempt_id: str = ""
    # Delegated Goal/Subgoal context (interop ``goal_subgoal``): the Goal this
    # delegation advances, its revision, and the parent Goal when the bound
    # Goal is a subgoal. Absent stays absent — no placeholder identities. The
    # cross-field coherence (a bound Goal names its revision; a parent only
    # with a Goal) is enforced by :func:`validate_goal_binding`, which
    # admission paths call — the model itself stays a plain record so the
    # receiving side can deserialize and file sender-authored evidence
    # without re-judging it.
    goal_id: str = ""
    goal_revision: int | None = Field(default=None, ge=1)
    subgoal_of: str = ""
    # The attenuated capability envelope the delegatee may exercise. Empty
    # means no caller authority is delegated at all, which is the safe default.
    delegated_scopes: tuple[str, ...] = ()
    delegation_key: _IdentityStr = Field(min_length=1)

    def as_payload(self) -> dict[str, Any]:
        """The wire/provenance form: explicit, JSON-ready, no absent facts."""
        return self.model_dump(exclude_none=True, mode="json")

    def narrowed(self, ceiling: tuple[str, ...]) -> DelegationContext:
        """Re-issue the context with scopes attenuated to the given ceiling."""
        narrowed = attenuate_scopes(self.delegated_scopes, ceiling)
        if narrowed == self.delegated_scopes:
            return self
        return self.model_copy(update={"delegated_scopes": narrowed})


__all__ = [
    "DelegationContext",
    "DelegationContextError",
    "DelegationScopeExceeded",
    "attenuate_scopes",
    "validate_goal_binding",
]
