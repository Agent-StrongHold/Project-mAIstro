"""Unit tests for the canonical external-delegation binding (issue #959, M9-D2).

`DelegationContext` is the record that makes an external Agent call
attributable: canonical caller, Workspace/Project scope, Goal/Subgoal context,
Run/NodeRun/Attempt linkage, and the effect identity. `attenuate_scopes` is
the authority ceiling. These pin the contract the transport and the node rely
on; the end-to-end wiring lives in
`tests/graph/nodes/test_agent_delegate_remote_governance.py`.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from maistro.a2a.delegation_context import (
    DelegationContext,
    DelegationContextError,
    DelegationScopeExceeded,
    attenuate_scopes,
    validate_goal_binding,
)


def _context(**overrides: object) -> DelegationContext:
    values: dict[str, object] = {
        "caller_principal_id": "actor-1",
        "delegating_agent": "planner",
        "workspace_id": "workspace-1",
        "project_id": "project-1",
        "run_id": "run-1",
        "node_run_id": "node-run-1",
        "delegation_key": "effect-1",
    }
    values.update(overrides)
    return DelegationContext(**values)  # type: ignore[arg-type]


class TestDelegationContextValidation:
    def test_a_context_without_a_canonical_caller_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            _context(caller_principal_id="")

    def test_a_context_without_workspace_or_project_scope_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            _context(workspace_id="")
        with pytest.raises(ValidationError):
            _context(project_id="")

    def test_a_context_without_the_delegating_agent_or_key_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            _context(delegating_agent="")
        with pytest.raises(ValidationError):
            _context(delegation_key="")

    def test_goal_coherence_is_enforced_by_validate_goal_binding(self) -> None:
        with pytest.raises(DelegationContextError):
            validate_goal_binding(_context(goal_id="goal-1"))
        context = _context(goal_id="goal-1", goal_revision=3)
        validate_goal_binding(context)
        assert context.goal_revision == 3

    def test_goal_revision_and_parent_are_meaningless_without_a_goal(self) -> None:
        with pytest.raises(DelegationContextError):
            validate_goal_binding(_context(goal_revision=2))
        with pytest.raises(DelegationContextError):
            validate_goal_binding(_context(subgoal_of="goal-parent"))
        validate_goal_binding(_context())  # no Goal claimed: coherent

    def test_subgoal_binding_carries_both_goals(self) -> None:
        context = _context(goal_id="goal-child", goal_revision=1, subgoal_of="goal-parent")
        validate_goal_binding(context)
        assert context.subgoal_of == "goal-parent"

    def test_unknown_fields_are_refused(self) -> None:
        with pytest.raises(ValidationError):
            _context(actor_id="someone")  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "field",
        [
            "caller_principal_id",
            "delegating_agent",
            "workspace_id",
            "project_id",
            "run_id",
            "node_run_id",
            "delegation_key",
        ],
    )
    def test_whitespace_only_identity_fields_are_refused(self, field: str) -> None:
        with pytest.raises(ValidationError, match="must not be blank"):
            _context(**{field: "   "})


class TestAttenuation:
    def test_the_ceiling_narrows_claims_and_preserves_order(self) -> None:
        assert attenuate_scopes(("b", "a", "b"), ("a", "b", "c")) == ("b", "a")

    def test_an_empty_claim_stays_empty_under_any_ceiling(self) -> None:
        assert attenuate_scopes((), ("a",)) == ()
        assert attenuate_scopes((), ()) == ()

    def test_a_claim_beyond_the_ceiling_is_refused_not_narrowed(self) -> None:
        with pytest.raises(DelegationScopeExceeded) as excinfo:
            attenuate_scopes(("web.read", "shell.exec"), ("web.read",))
        assert "shell.exec" in str(excinfo.value)

    def test_any_claim_against_an_empty_ceiling_is_refused(self) -> None:
        with pytest.raises(DelegationScopeExceeded):
            attenuate_scopes(("web.read",), ())

    def test_narrowed_reissues_the_context_with_attenuated_scopes(self) -> None:
        context = _context(delegated_scopes=("web.read", "mail.send", "web.read"))
        narrowed = context.narrowed(("mail.send", "web.read"))
        assert narrowed is not context
        # Deduplication changes the tuple, so a new context is issued; the
        # caller's own order is what survives.
        assert narrowed.delegated_scopes == ("web.read", "mail.send")
        assert narrowed.caller_principal_id == context.caller_principal_id

    def test_narrowed_returns_the_same_context_when_nothing_is_dropped(self) -> None:
        context = _context(delegated_scopes=("web.read",))
        assert context.narrowed(("web.read", "more")) is context


class TestPayload:
    def test_as_payload_carries_every_fact_and_drops_absent_ones(self) -> None:
        payload = _context(goal_id="goal-1", goal_revision=2).as_payload()
        assert payload["caller_principal_id"] == "actor-1"
        assert payload["workspace_id"] == "workspace-1"
        assert payload["project_id"] == "project-1"
        assert payload["run_id"] == "run-1"
        assert payload["node_run_id"] == "node-run-1"
        assert payload["delegation_key"] == "effect-1"
        assert payload["goal_id"] == "goal-1"
        assert payload["goal_revision"] == 2
        assert "attempt_id" not in payload or payload["attempt_id"] == ""
        # An empty parent stays an explicit empty: no placeholder identities,
        # but no omitted facts either.
        assert payload["subgoal_of"] == ""

    def test_the_payload_round_trips_through_the_model(self) -> None:
        context = _context(attempt_id="attempt-9", delegated_scopes=("web.read",))
        revived = DelegationContext.model_validate(context.as_payload())
        assert revived == context


def test_delegation_scope_error_is_a_context_error() -> None:
    """Callers catching the family catch the scope refusal too."""
    assert issubclass(DelegationScopeExceeded, DelegationContextError)
