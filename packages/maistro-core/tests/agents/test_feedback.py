"""Tests for maistro.agents.feedback — extractor, tracker, loop (RLHF cycle)."""

from __future__ import annotations

import logging
from typing import Any

import pytest

from maistro.agents.feedback.extractor import ReviewFeedbackExtractor
from maistro.agents.feedback.loop import FeedbackLoop
from maistro.agents.feedback.tracker import InMemoryViolationTracker
from maistro.types.feedback import (
    ReviewFinding,
    ReviewResult,
    Severity,
    ViolationCategory,
)
from maistro.types.memory import MemoryScope


def _finding(
    category: ViolationCategory = ViolationCategory.MOCK_USAGE,
    *,
    severity: Severity = Severity.HIGH,
    file_path: str = "foo.py",
    description: str = "uses MagicMock",
    suggestion: str = "use a fake",
) -> ReviewFinding:
    return ReviewFinding(
        category=category,
        severity=severity,
        file_path=file_path,
        description=description,
        suggestion=suggestion,
    )


def _result(
    findings: tuple[ReviewFinding, ...] = (),
    *,
    pr_number: int = 42,
    agent_id: str = "mason",
    approved: bool = True,
    summary: str = "ok",
) -> ReviewResult:
    return ReviewResult(
        pr_number=pr_number,
        agent_id=agent_id,
        findings=findings,
        approved=approved,
        summary=summary,
    )


class TestReviewFeedbackExtractor:
    def test_extract_learnings_empty_findings_returns_empty_list(self) -> None:
        extractor = ReviewFeedbackExtractor()
        assert extractor.extract_learnings(_result()) == []

    def test_extract_learnings_known_category_uses_trigger_keys(self) -> None:
        extractor = ReviewFeedbackExtractor()
        result = _result(findings=(_finding(ViolationCategory.MOCK_USAGE),))

        learnings = extractor.extract_learnings(result)

        assert len(learnings) == 1
        learning = learnings[0]
        assert learning.category == "review_feedback"
        assert "unittest.mock" in learning.trigger_keys
        assert learning.learning == "[mock_usage] uses MagicMock. Fix: use a fake"
        assert learning.tool_name == "auditor"
        assert learning.source_query == "PR #42"
        assert learning.agent_id == "mason"
        assert learning.scope == MemoryScope.AGENT

    def test_extract_learnings_unknown_category_falls_back_to_value(self) -> None:
        extractor = ReviewFeedbackExtractor()
        result = _result(findings=(_finding(ViolationCategory.SPEC_COVERAGE_GAP),))

        learnings = extractor.extract_learnings(result)

        assert learnings[0].trigger_keys == ["spec_coverage_gap"]

    def test_extract_learnings_multiple_findings_preserves_order(self) -> None:
        extractor = ReviewFeedbackExtractor()
        findings = (
            _finding(ViolationCategory.SECURITY, description="sec issue"),
            _finding(ViolationCategory.NAMING_STANDARDS, description="naming issue"),
        )
        result = _result(findings=findings)

        learnings = extractor.extract_learnings(result)

        assert len(learnings) == 2
        assert "sec issue" in learnings[0].learning
        assert "naming issue" in learnings[1].learning


class TestInMemoryViolationTracker:
    def test_get_metrics_creates_empty_metrics_for_new_agent(self) -> None:
        tracker = InMemoryViolationTracker()
        metrics = tracker.get_metrics("agent-1")
        assert metrics.agent_id == "agent-1"
        assert metrics.total_findings == 0
        assert metrics.total_prs_reviewed == 0

    def test_record_finding_increments_counter_and_metrics(self) -> None:
        tracker = InMemoryViolationTracker()
        finding = _finding(ViolationCategory.SECURITY)

        tracker.record_finding(finding, agent_id="agent-1")

        metrics = tracker.get_metrics("agent-1")
        assert metrics.total_findings == 1
        assert metrics.category_counts[ViolationCategory.SECURITY] == 1
        assert tracker.get_top_violations("agent-1") == [(ViolationCategory.SECURITY, 1)]

    def test_record_finding_existing_agent_reuses_counter(self) -> None:
        tracker = InMemoryViolationTracker()
        tracker.record_finding(_finding(ViolationCategory.SECURITY), agent_id="agent-1")
        tracker.record_finding(_finding(ViolationCategory.SECURITY), agent_id="agent-1")

        metrics = tracker.get_metrics("agent-1")
        assert metrics.total_findings == 2
        assert metrics.category_counts[ViolationCategory.SECURITY] == 2

    def test_record_review_updates_pr_count_and_history(self) -> None:
        tracker = InMemoryViolationTracker()
        result = _result(
            findings=(_finding(ViolationCategory.MOCK_USAGE), _finding(ViolationCategory.SECURITY)),
            agent_id="agent-1",
        )

        tracker.record_review(result)

        metrics = tracker.get_metrics("agent-1")
        assert metrics.total_prs_reviewed == 1
        assert metrics.total_findings == 2
        assert metrics.findings_per_pr_history == [2.0]

    def test_get_top_violations_respects_limit(self) -> None:
        tracker = InMemoryViolationTracker()
        for _ in range(3):
            tracker.record_finding(_finding(ViolationCategory.SECURITY), agent_id="agent-1")
        for _ in range(2):
            tracker.record_finding(_finding(ViolationCategory.NAMING_STANDARDS), agent_id="agent-1")
        tracker.record_finding(_finding(ViolationCategory.MOCK_USAGE), agent_id="agent-1")

        top = tracker.get_top_violations("agent-1", limit=2)

        assert top == [
            (ViolationCategory.SECURITY, 3),
            (ViolationCategory.NAMING_STANDARDS, 2),
        ]

    def test_get_top_violations_unknown_agent_returns_empty(self) -> None:
        tracker = InMemoryViolationTracker()
        assert tracker.get_top_violations("nobody") == []


class _FakeExtractor:
    def __init__(self, learnings: list[Any]) -> None:
        self._learnings = learnings
        self.calls: list[ReviewResult] = []

    def extract_learnings(self, result: ReviewResult) -> list[Any]:
        self.calls.append(result)
        return self._learnings


class _FakeLearningStore:
    def __init__(self, ids: list[int]) -> None:
        self._ids = ids
        self.stored: list[Any] = []

    async def store(self, learning: Any) -> int:
        self.stored.append(learning)
        return self._ids[len(self.stored) - 1]


class _FakeViolationStore:
    def __init__(self) -> None:
        self.tracker = InMemoryViolationTracker()
        self.recorded: list[ReviewResult] = []

    def record_review(self, result: ReviewResult) -> None:
        self.recorded.append(result)
        self.tracker.record_review(result)

    def get_metrics(self, agent_id: str) -> Any:
        return self.tracker.get_metrics(agent_id)


class _Learning:
    def __init__(self, text: str) -> None:
        self.learning = text


class TestFeedbackLoop:
    async def test_process_review_records_and_stores_all_learnings(self) -> None:
        extractor = _FakeExtractor([_Learning("a" * 100), _Learning("b")])
        learning_store = _FakeLearningStore([1, 2])
        violation_store = _FakeViolationStore()
        loop = FeedbackLoop(extractor, learning_store, violation_store)  # type: ignore[arg-type]
        result = _result(findings=(_finding(),))

        stored_count = await loop.process_review(result)

        assert stored_count == 2
        assert violation_store.recorded == [result]
        assert extractor.calls == [result]
        assert len(learning_store.stored) == 2

    async def test_process_review_skips_failed_stores(self) -> None:
        extractor = _FakeExtractor([_Learning("a"), _Learning("b")])
        learning_store = _FakeLearningStore([0, 5])
        violation_store = _FakeViolationStore()
        loop = FeedbackLoop(extractor, learning_store, violation_store)  # type: ignore[arg-type]

        stored_count = await loop.process_review(_result())

        assert stored_count == 1

    async def test_process_review_logs_metrics(self, caplog: pytest.LogCaptureFixture) -> None:
        extractor = _FakeExtractor([])
        learning_store = _FakeLearningStore([])
        violation_store = _FakeViolationStore()
        loop = FeedbackLoop(extractor, learning_store, violation_store)  # type: ignore[arg-type]

        with caplog.at_level(logging.INFO, logger="maistro.feedback"):
            await loop.process_review(_result(agent_id="mason", pr_number=7))

        assert "RLHF cycle for PR #7" in caplog.text
