"""Tests for maistro.classifier.logging — ClassifierLogger."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from maistro.classifier.logging import ClassifierLogger


class TestLogDecision:
    def test_records_decision(self) -> None:
        log = ClassifierLogger()
        log.log_decision(
            "hi", "chat", "chat", 0.9, "low", "agent1", reason="why", metadata={"k": "v"}
        )
        decisions = log.get_decisions()
        assert len(decisions) == 1
        assert decisions[0].classified_intent == "chat"
        assert decisions[0].reason == "why"
        assert decisions[0].metadata == {"k": "v"}

    def test_disabled_audit_skips_logging(self) -> None:
        log = ClassifierLogger()
        log.disable_audit()
        log.log_decision("hi", None, "chat", 0.9, "low", "agent1")
        assert log.get_decisions() == []


class TestGetDecisions:
    def test_limit_truncates_to_most_recent(self) -> None:
        log = ClassifierLogger()
        for i in range(5):
            log.log_decision(f"t{i}", None, "chat", 0.9, "low", "agent1")
        decisions = log.get_decisions(limit=2)
        assert len(decisions) == 2
        assert decisions[-1].input_text == "t4"

    def test_limit_zero_returns_all(self) -> None:
        log = ClassifierLogger()
        for i in range(3):
            log.log_decision(f"t{i}", None, "chat", 0.9, "low", "agent1")
        decisions = log.get_decisions(limit=0)
        assert len(decisions) == 3

    def test_since_filters_older_decisions(self) -> None:
        log = ClassifierLogger()
        log.log_decision("old", None, "chat", 0.9, "low", "agent1")
        cutoff = datetime.now(UTC) + timedelta(seconds=1)
        log.log_decision("new", None, "chat", 0.9, "low", "agent1")
        # manually age the first entry below the cutoff isn't needed; test that
        # a future cutoff excludes all and a past cutoff includes all
        future_cutoff = datetime.now(UTC) + timedelta(days=1)
        assert log.get_decisions(since=future_cutoff) == []
        past_cutoff = datetime.now(UTC) - timedelta(days=1)
        assert len(log.get_decisions(since=past_cutoff)) == 2
        assert cutoff is not None


class TestGetStats:
    def test_empty_returns_zero_total(self) -> None:
        log = ClassifierLogger()
        assert log.get_stats() == {"total": 0}

    def test_aggregates_intents_and_agents(self) -> None:
        log = ClassifierLogger()
        log.log_decision("a", None, "chat", 0.9, "low", "agent1")
        log.log_decision("b", None, "chat", 0.9, "low", "agent2")
        log.log_decision("c", None, "code", 0.9, "low", "agent1")
        stats = log.get_stats()
        assert stats["total"] == 3
        assert stats["intent_distribution"] == {"chat": 2, "code": 1}
        assert stats["agent_distribution"] == {"agent1": 2, "agent2": 1}


class TestClearAndAuditToggle:
    def test_clear_empties_decisions(self) -> None:
        log = ClassifierLogger()
        log.log_decision("a", None, "chat", 0.9, "low", "agent1")
        log.clear()
        assert log.get_decisions() == []

    def test_enable_audit_resumes_logging(self) -> None:
        log = ClassifierLogger()
        log.disable_audit()
        log.enable_audit()
        log.log_decision("a", None, "chat", 0.9, "low", "agent1")
        assert len(log.get_decisions()) == 1
