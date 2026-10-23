"""Execution lifecycle state machine — Hypothesis property-based tests."""

from __future__ import annotations

import pytest
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, rule, invariant

from maistro.graph.definitions import Graph, Node
from maistro.runs.lifecycle import (
    RUN_TRANSITIONS,
    InvalidLifecycleTransition,
    transition_run,
)
from maistro.runs.model import (
    GraphSnapshot,
    Run,
    RunStatus,
    TERMINAL_RUN_STATUSES,
)


class ExecutionLifecycleMachine(RuleBasedStateMachine):
    """State machine over the *real* Run lifecycle transition table.

    Unlike a hand-rolled mirror, every step calls the production
    ``transition_run`` helper from ``maistro.runs.lifecycle`` and the
    machine's model is derived from the same ``RUN_TRANSITIONS`` table the
    helper enforces. A divergence between the two — a transition the table
    permits but the helper rejects, or one the helper allows that the table
    forbids — surfaces as a failed property here rather than as a silent
    agreement between two copies of the same bug.
    """

    def __init__(self):
        super().__init__()
        graph = Graph(
            name="test-gcd",
            workspace_id="test-workspace",
            project_id="test-project",
            nodes=[Node(node_id="test-node", node_type="task", name="Test Task")],
        )
        graph_snapshot = GraphSnapshot.from_graph(graph)
        self.run = Run(
            workspace_id="test-workspace",
            project_id="test-project",
            graph=graph_snapshot,
            actor_principal_id="test-actor",
        )
        self.model_status = RunStatus.CREATED

    @rule(target_status=st.sampled_from(list(RunStatus)))
    def attempt_transition(self, target_status: RunStatus) -> None:
        current = self.model_status
        legal = target_status in RUN_TRANSITIONS[current]
        if legal:
            self.run = transition_run(self.run, target_status)
            self.model_status = target_status
        else:
            with pytest.raises(InvalidLifecycleTransition):
                transition_run(self.run, target_status)
            # An illegal attempt must not mutate either side.
            assert self.run.status == current

    @invariant()
    def model_matches_run(self) -> None:
        assert self.run.status == self.model_status

    @invariant()
    def terminal_statuses_have_no_outgoing_transitions(self) -> None:
        if self.model_status in TERMINAL_RUN_STATUSES:
            for candidate in RunStatus:
                assert candidate not in RUN_TRANSITIONS[self.model_status]

    @invariant()
    def run_validator_agrees_with_table(self) -> None:
        # The Run's persisted status must always be a member of the table's
        # domain; guards against a future status added to the enum but not
        # to RUN_TRANSITIONS.
        assert self.run.status in RUN_TRANSITIONS


TestExecutionLifecycleMachine = ExecutionLifecycleMachine.TestCase


def test_execution_lifecycle_placeholder() -> None:
    """Placeholder test to ensure the module is not empty."""
    pass
