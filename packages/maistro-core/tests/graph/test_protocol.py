"""Algorithm-only coverage for retired graph node helpers.

These tests do not execute a physical Graph or claim lifecycle authority. The
canonical durable Graph suites own Run/NodeRun/Attempt execution evidence.
"""

from __future__ import annotations

from maistro.graph.node import IterationBudget


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
