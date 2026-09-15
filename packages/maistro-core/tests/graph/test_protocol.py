"""Algorithm-only coverage for retired graph node helpers.

These tests do not execute a physical Graph or claim lifecycle authority. The
canonical durable Graph suites own Run/NodeRun/Attempt execution evidence.
"""

from __future__ import annotations

from maistro.graph.node import IterationBudget
from maistro.graph.phases import (
    TERMINAL_GRAPH_PHASES,
    TERMINAL_NODE_PHASES,
    GraphPhase,
    NodePhase,
)


class TestPhases:
    def test_node_phase_values(self):
        assert NodePhase.PENDING == "pending"
        assert NodePhase.SUCCEEDED == "succeeded"
        assert NodePhase.FAILED == "failed"
        assert NodePhase.CANCELLED == "cancelled"

    def test_graph_phase_values(self):
        assert GraphPhase.IDLE == "idle"
        assert GraphPhase.RUNNING == "running"
        assert GraphPhase.COMPLETED == "completed"
        assert GraphPhase.FAILED == "failed"

    def test_terminal_node_phases(self):
        assert NodePhase.SUCCEEDED in TERMINAL_NODE_PHASES
        assert NodePhase.FAILED in TERMINAL_NODE_PHASES
        assert NodePhase.PENDING not in TERMINAL_NODE_PHASES

    def test_terminal_graph_phases(self):
        assert GraphPhase.COMPLETED in TERMINAL_GRAPH_PHASES
        assert GraphPhase.FAILED in TERMINAL_GRAPH_PHASES
        assert GraphPhase.IDLE not in TERMINAL_GRAPH_PHASES


class TestIterationBudget:
    def test_consume_within_budget(self):
        budget = IterationBudget(5)
        assert budget.consume() is True
        assert budget.remaining == 4

    def test_consume_exhausts_budget(self):
        budget = IterationBudget(2)
        budget.consume()
        budget.consume()
        assert budget.exhausted is True
        assert budget.consume() is False

    def test_consume_multi(self):
        budget = IterationBudget(10)
        assert budget.consume(5) is True
        assert budget.remaining == 5

    def test_consume_over_budget(self):
        budget = IterationBudget(3)
        assert budget.consume(5) is False
