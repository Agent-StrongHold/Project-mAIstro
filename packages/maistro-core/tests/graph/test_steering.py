from __future__ import annotations

import pytest

from maistro.graph.steering import SteeringQueue


class TestSteer:
    @pytest.mark.ac("ADR-066/AC-16")
    def test_adds_guidance(self):
        q = SteeringQueue()
        q.steer("Focus on database schema")
        assert q.pending_count == 1
        entries = q.get_all()
        assert entries == ["Focus on database schema"]

    @pytest.mark.ac("ADR-066/AC-18")
    def test_multiple_steer_calls(self):
        q = SteeringQueue()
        q.steer("Use Python 3.12 features")
        q.steer("Prefer async/await over threads")
        q.steer("Add type hints everywhere")
        assert q.pending_count == 3
        entries = q.get_all()
        assert entries == [
            "Use Python 3.12 features",
            "Prefer async/await over threads",
            "Add type hints everywhere",
        ]


class TestDrain:
    @pytest.mark.ac("ADR-066/AC-18")
    def test_drain_returns_and_clears(self):
        q = SteeringQueue()
        q.steer("Guidance A")
        q.steer("Guidance B")
        entries = q.drain()
        assert entries == ["Guidance A", "Guidance B"]
        assert q.pending_count == 0

    def test_drain_empty_returns_empty(self):
        q = SteeringQueue()
        entries = q.drain()
        assert entries == []
        assert q.pending_count == 0

    def test_drain_twice(self):
        q = SteeringQueue()
        q.steer("First")
        first = q.drain()
        assert first == ["First"]
        second = q.drain()
        assert second == []

    def test_drain_then_steer(self):
        q = SteeringQueue()
        q.steer("A")
        q.drain()
        q.steer("B")
        entries = q.drain()
        assert entries == ["B"]


class TestGetAll:
    def test_returns_without_clearing(self):
        q = SteeringQueue()
        q.steer("Keep this")
        entries = q.get_all()
        assert entries == ["Keep this"]
        assert q.pending_count == 1
        entries2 = q.get_all()
        assert entries2 == ["Keep this"]


class TestClear:
    def test_clear_empties_queue(self):
        q = SteeringQueue()
        q.steer("A")
        q.steer("B")
        assert q.pending_count == 2
        q.clear()
        assert q.pending_count == 0

    def test_clear_empty_queue(self):
        q = SteeringQueue()
        q.clear()
        assert q.pending_count == 0


class TestPendingCount:
    def test_starts_at_zero(self):
        q = SteeringQueue()
        assert q.pending_count == 0

    def test_increments_with_steer(self):
        q = SteeringQueue()
        q.steer("A")
        assert q.pending_count == 1
        q.steer("B")
        assert q.pending_count == 2

    def test_decrements_with_drain(self):
        q = SteeringQueue()
        q.steer("A")
        q.steer("B")
        q.drain()
        assert q.pending_count == 0
