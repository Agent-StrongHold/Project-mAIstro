"""Tests for maistro.memory.learnings.approval — learning promotion approval gate."""

from __future__ import annotations

from maistro.memory.learnings.approval import LearningApprovalGate


class TestRequestApproval:
    def test_creates_new_approval_with_defaults(self) -> None:
        gate = LearningApprovalGate()
        approval = gate.request_approval(1)
        assert approval.learning_id == 1
        assert approval.org_id == ""
        assert approval.status == "pending"
        assert approval.learning_preview == ""
        assert approval.tool_name == ""
        assert approval.hit_count == 0

    def test_creates_new_approval_with_all_fields(self) -> None:
        gate = LearningApprovalGate()
        approval = gate.request_approval(
            2, org_id="org1", learning_preview="preview", tool_name="tool", hit_count=5
        )
        assert approval.org_id == "org1"
        assert approval.learning_preview == "preview"
        assert approval.tool_name == "tool"
        assert approval.hit_count == 5

    def test_duplicate_request_returns_existing(self) -> None:
        gate = LearningApprovalGate()
        first = gate.request_approval(1, learning_preview="first")
        second = gate.request_approval(1, learning_preview="second")
        assert second is first
        assert second.learning_preview == "first"


class TestApprove:
    def test_approve_pending_succeeds(self) -> None:
        gate = LearningApprovalGate()
        gate.request_approval(1)
        approval = gate.approve(1, reviewer="alice", notes="looks good")
        assert approval is not None
        assert approval.status == "approved"
        assert approval.reviewed_by == "alice"
        assert approval.review_notes == "looks good"
        assert approval.reviewed_at > 0

    def test_approve_missing_returns_none(self) -> None:
        gate = LearningApprovalGate()
        assert gate.approve(999, reviewer="alice") is None

    def test_approve_non_pending_returns_none(self) -> None:
        gate = LearningApprovalGate()
        gate.request_approval(1)
        gate.approve(1, reviewer="alice")
        assert gate.approve(1, reviewer="bob") is None


class TestReject:
    def test_reject_pending_succeeds(self) -> None:
        gate = LearningApprovalGate()
        gate.request_approval(1)
        approval = gate.reject(1, reviewer="alice", reason="bad data")
        assert approval is not None
        assert approval.status == "rejected"
        assert approval.reviewed_by == "alice"
        assert approval.review_notes == "bad data"
        assert approval.reviewed_at > 0

    def test_reject_missing_returns_none(self) -> None:
        gate = LearningApprovalGate()
        assert gate.reject(999, reviewer="alice") is None

    def test_reject_non_pending_returns_none(self) -> None:
        gate = LearningApprovalGate()
        gate.request_approval(1)
        gate.reject(1, reviewer="alice")
        assert gate.reject(1, reviewer="bob") is None


class TestGetPending:
    def test_filters_to_pending_only(self) -> None:
        gate = LearningApprovalGate()
        gate.request_approval(1)
        gate.request_approval(2)
        gate.approve(2, reviewer="alice")
        pending = gate.get_pending()
        assert [a.learning_id for a in pending] == [1]

    def test_filters_by_org_id(self) -> None:
        gate = LearningApprovalGate()
        gate.request_approval(1, org_id="org1")
        gate.request_approval(2, org_id="org2")
        pending = gate.get_pending(org_id="org1")
        assert [a.learning_id for a in pending] == [1]

    def test_no_org_id_returns_all_pending(self) -> None:
        gate = LearningApprovalGate()
        gate.request_approval(1, org_id="org1")
        gate.request_approval(2, org_id="org2")
        pending = gate.get_pending()
        assert {a.learning_id for a in pending} == {1, 2}

    def test_sorted_most_recent_first(self) -> None:
        gate = LearningApprovalGate()
        first = gate.request_approval(1)
        second = gate.request_approval(2)
        second.requested_at = first.requested_at + 100
        pending = gate.get_pending()
        assert [a.learning_id for a in pending] == [2, 1]


class TestGetApprovedIds:
    def test_returns_only_approved(self) -> None:
        gate = LearningApprovalGate()
        gate.request_approval(1)
        gate.request_approval(2)
        gate.approve(1, reviewer="alice")
        assert gate.get_approved_ids() == [1]

    def test_empty_when_none_approved(self) -> None:
        gate = LearningApprovalGate()
        gate.request_approval(1)
        assert gate.get_approved_ids() == []


class TestMarkPromoted:
    def test_marks_approved_as_promoted(self) -> None:
        gate = LearningApprovalGate()
        gate.request_approval(1)
        gate.approve(1, reviewer="alice")
        gate.mark_promoted(1)
        assert gate._approvals[1].status == "promoted"

    def test_noop_for_missing_learning(self) -> None:
        gate = LearningApprovalGate()
        gate.mark_promoted(999)

        assert gate._approvals == {}

    def test_noop_for_non_approved_learning(self) -> None:
        gate = LearningApprovalGate()
        gate.request_approval(1)
        gate.mark_promoted(1)
        assert gate._approvals[1].status == "pending"


class TestGetAll:
    def test_returns_dict_representations(self) -> None:
        gate = LearningApprovalGate()
        gate.request_approval(
            1, org_id="org1", learning_preview="prev", tool_name="tool", hit_count=3
        )
        results = gate.get_all()
        assert results == [
            {
                "learning_id": 1,
                "org_id": "org1",
                "status": "pending",
                "requested_at": results[0]["requested_at"],
                "reviewed_by": "",
                "review_notes": "",
                "learning_preview": "prev",
                "tool_name": "tool",
                "hit_count": 3,
            }
        ]

    def test_filters_by_org_id(self) -> None:
        gate = LearningApprovalGate()
        gate.request_approval(1, org_id="org1")
        gate.request_approval(2, org_id="org2")
        results = gate.get_all(org_id="org1")
        assert [r["learning_id"] for r in results] == [1]

    def test_respects_limit(self) -> None:
        gate = LearningApprovalGate()
        for i in range(5):
            gate.request_approval(i)
        results = gate.get_all(limit=2)
        assert len(results) == 2

    def test_sorted_most_recent_first(self) -> None:
        gate = LearningApprovalGate()
        first = gate.request_approval(1)
        gate.request_approval(2)
        first.requested_at -= 100
        results = gate.get_all()
        assert [r["learning_id"] for r in results] == [2, 1]
