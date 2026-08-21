"""Coverage for skills/canary.py."""

from __future__ import annotations

from maistro.skills.canary import CanaryDeployment, CanaryManager, CanaryStage


def test_error_rate_zero_when_no_requests() -> None:
    deployment = CanaryDeployment(skill_name="s")
    assert deployment.error_rate == 0.0


def test_error_rate_computed_from_errors_and_requests() -> None:
    deployment = CanaryDeployment(skill_name="s", total_requests=4, errors=1)
    assert deployment.error_rate == 0.25


def test_traffic_pct_matches_stage_table() -> None:
    assert CanaryDeployment(skill_name="s", stage=CanaryStage.CANARY).traffic_pct == 0.05
    assert CanaryDeployment(skill_name="s", stage=CanaryStage.PARTIAL).traffic_pct == 0.25
    assert CanaryDeployment(skill_name="s", stage=CanaryStage.MAJORITY).traffic_pct == 0.75
    assert CanaryDeployment(skill_name="s", stage=CanaryStage.FULL).traffic_pct == 1.0


def test_start_canary_creates_deployment_at_canary_stage() -> None:
    manager = CanaryManager()
    deployment = manager.start_canary("my_skill", old_version=1, new_version=2)
    assert deployment.skill_name == "my_skill"
    assert deployment.old_version == 1
    assert deployment.new_version == 2
    assert deployment.stage == CanaryStage.CANARY
    assert manager.get_deployment("my_skill") is deployment


def test_get_deployment_returns_none_when_absent() -> None:
    manager = CanaryManager()
    assert manager.get_deployment("ghost") is None


def test_should_use_new_version_false_when_no_deployment() -> None:
    manager = CanaryManager()
    assert manager.should_use_new_version("ghost") is False


def test_should_use_new_version_true_when_random_below_traffic_pct(monkeypatch) -> None:
    manager = CanaryManager()
    manager.start_canary("s", 1, 2)
    monkeypatch.setattr("maistro.skills.canary.random.random", lambda: 0.01)
    assert manager.should_use_new_version("s") is True


def test_should_use_new_version_false_when_random_above_traffic_pct(monkeypatch) -> None:
    manager = CanaryManager()
    manager.start_canary("s", 1, 2)
    monkeypatch.setattr("maistro.skills.canary.random.random", lambda: 0.99)
    assert manager.should_use_new_version("s") is False


def test_record_result_noop_when_no_deployment() -> None:
    manager = CanaryManager()
    manager.record_result("ghost", success=True)
    assert manager.get_deployment("ghost") is None


def test_record_result_increments_total_and_errors_on_failure() -> None:
    manager = CanaryManager()
    deployment = manager.start_canary("s", 1, 2)
    manager.record_result("s", success=False)
    assert deployment.total_requests == 1
    assert deployment.errors == 1


def test_record_result_increments_total_only_on_success() -> None:
    manager = CanaryManager()
    deployment = manager.start_canary("s", 1, 2)
    manager.record_result("s", success=True)
    assert deployment.total_requests == 1
    assert deployment.errors == 0


def test_check_promotion_or_rollback_holds_when_no_deployment() -> None:
    manager = CanaryManager()
    assert manager.check_promotion_or_rollback("ghost") == "hold"


def test_check_promotion_or_rollback_holds_when_insufficient_requests_and_time() -> None:
    manager = CanaryManager(min_requests_per_stage=20, stage_duration_secs=300.0)
    manager.start_canary("s", 1, 2)
    assert manager.check_promotion_or_rollback("s") == "hold"


def test_check_promotion_or_rollback_rolls_back_on_high_error_rate() -> None:
    manager = CanaryManager(error_threshold=0.1, min_requests_per_stage=2)
    manager.start_canary("s", 1, 2)
    manager.record_result("s", success=False)
    manager.record_result("s", success=False)
    result = manager.check_promotion_or_rollback("s")
    assert result == "rollback"
    assert manager.get_deployment("s") is None
    rollbacks = manager.list_rollbacks()
    assert len(rollbacks) == 1
    assert rollbacks[0]["skill_name"] == "s"
    assert rollbacks[0]["new_version"] == 2
    assert rollbacks[0]["total_requests"] == 2
    assert rollbacks[0]["stage"] == "canary"


def test_check_promotion_or_rollback_advances_when_time_elapsed_and_error_rate_ok(
    monkeypatch,
) -> None:
    manager = CanaryManager(error_threshold=0.5, min_requests_per_stage=1, stage_duration_secs=10.0)
    deployment = manager.start_canary("s", 1, 2)
    manager.record_result("s", success=True)
    monkeypatch.setattr(
        "maistro.skills.canary.time.time", lambda: deployment.stage_started_at + 20.0
    )
    result = manager.check_promotion_or_rollback("s")
    assert result == "advance"
    assert deployment.stage == CanaryStage.PARTIAL
    assert deployment.total_requests == 0
    assert deployment.errors == 0


def test_check_promotion_or_rollback_holds_when_time_elapsed_but_not_enough_requests(
    monkeypatch,
) -> None:
    manager = CanaryManager(error_threshold=0.5, min_requests_per_stage=5, stage_duration_secs=10.0)
    deployment = manager.start_canary("s", 1, 2)
    monkeypatch.setattr(
        "maistro.skills.canary.time.time", lambda: deployment.stage_started_at + 20.0
    )
    assert manager.check_promotion_or_rollback("s") == "hold"


def test_advance_progresses_through_all_stages_then_completes() -> None:
    manager = CanaryManager()
    deployment = manager.start_canary("s", 1, 2)
    assert manager._advance(deployment) == "advance"
    assert deployment.stage == CanaryStage.PARTIAL
    assert manager._advance(deployment) == "advance"
    assert deployment.stage == CanaryStage.MAJORITY
    assert manager._advance(deployment) == "advance"
    assert deployment.stage == CanaryStage.FULL
    assert manager._advance(deployment) == "complete"
    assert manager.get_deployment("s") is None


def test_rollback_truncates_history_when_exceeding_200_entries() -> None:
    manager = CanaryManager()
    manager._rollbacks = [{"skill_name": f"old{i}"} for i in range(200)]
    deployment = manager.start_canary("s", 1, 2)
    manager._rollback(deployment)
    assert len(manager._rollbacks) == 100
    assert manager._rollbacks[-1]["skill_name"] == "s"


def test_list_active_returns_summary_for_each_deployment() -> None:
    manager = CanaryManager()
    manager.start_canary("s1", 1, 2)
    manager.record_result("s1", success=False)
    summaries = manager.list_active()
    assert len(summaries) == 1
    summary = summaries[0]
    assert summary["skill_name"] == "s1"
    assert summary["old_version"] == 1
    assert summary["new_version"] == 2
    assert summary["stage"] == "canary"
    assert summary["traffic_pct"] == 5
    assert summary["total_requests"] == 1
    assert summary["errors"] == 1
    assert summary["error_rate"] == 1.0


def test_list_rollbacks_applies_limit() -> None:
    manager = CanaryManager()
    for i in range(5):
        deployment = manager.start_canary(f"s{i}", 1, 2)
        manager._rollback(deployment)
    limited = manager.list_rollbacks(limit=2)
    assert len(limited) == 2
    assert [r["skill_name"] for r in limited] == ["s3", "s4"]


class TestCheckPromotionBoundaryMatrix:
    """Boundary-focused cross-product over (requests met, error_rate vs
    threshold, elapsed vs stage_duration) — representative threshold-adjacent
    values per axis rather than a full Cartesian explosion (mirrors the
    self-repair governor matrix's approach)."""

    def _manager_with_deployment(
        self, *, error_threshold: float, min_requests: int, stage_duration: float
    ) -> tuple[CanaryManager, CanaryDeployment]:
        manager = CanaryManager(
            error_threshold=error_threshold,
            min_requests_per_stage=min_requests,
            stage_duration_secs=stage_duration,
        )
        deployment = manager.start_canary("s", 1, 2)
        return manager, deployment

    def test_error_rate_exactly_at_threshold_is_ok_not_rollback(self) -> None:
        manager, deployment = self._manager_with_deployment(
            error_threshold=0.5, min_requests=2, stage_duration=300.0
        )
        manager.record_result("s", success=False)
        manager.record_result("s", success=True)
        assert deployment.error_rate == 0.5
        assert manager.check_promotion_or_rollback("s") != "rollback"

    def test_error_rate_just_above_threshold_rolls_back(self) -> None:
        manager, deployment = self._manager_with_deployment(
            error_threshold=0.4, min_requests=5, stage_duration=300.0
        )
        for _ in range(3):
            manager.record_result("s", success=False)
        for _ in range(2):
            manager.record_result("s", success=True)
        assert deployment.error_rate == 0.6
        assert manager.check_promotion_or_rollback("s") == "rollback"

    def test_requests_one_below_minimum_never_rolls_back_even_at_100pct_errors(self) -> None:
        manager, deployment = self._manager_with_deployment(
            error_threshold=0.1, min_requests=5, stage_duration=300.0
        )
        for _ in range(4):
            manager.record_result("s", success=False)
        assert deployment.total_requests == 4
        assert manager.check_promotion_or_rollback("s") == "hold"

    def test_requests_exactly_at_minimum_with_high_errors_rolls_back(self) -> None:
        manager, deployment = self._manager_with_deployment(
            error_threshold=0.1, min_requests=5, stage_duration=300.0
        )
        for _ in range(5):
            manager.record_result("s", success=False)
        assert deployment.total_requests == 5
        assert manager.check_promotion_or_rollback("s") == "rollback"

    def test_elapsed_one_second_below_duration_holds_even_with_good_error_rate(
        self, monkeypatch
    ) -> None:
        manager, deployment = self._manager_with_deployment(
            error_threshold=0.5, min_requests=1, stage_duration=300.0
        )
        manager.record_result("s", success=True)
        monkeypatch.setattr(
            "maistro.skills.canary.time.time", lambda: deployment.stage_started_at + 299.0
        )
        assert manager.check_promotion_or_rollback("s") == "hold"

    def test_elapsed_exactly_at_duration_advances(self, monkeypatch) -> None:
        manager, deployment = self._manager_with_deployment(
            error_threshold=0.5, min_requests=1, stage_duration=300.0
        )
        manager.record_result("s", success=True)
        monkeypatch.setattr(
            "maistro.skills.canary.time.time", lambda: deployment.stage_started_at + 300.0
        )
        assert manager.check_promotion_or_rollback("s") == "advance"

    def test_rollback_takes_priority_over_advance_when_both_conditions_met(
        self, monkeypatch
    ) -> None:
        """If time has elapsed AND requests are sufficient AND error_rate
        exceeds threshold, rollback must win — the function checks rollback
        before advance, so a stale/high-error canary can't sneak through
        on stage-duration alone."""
        manager, deployment = self._manager_with_deployment(
            error_threshold=0.1, min_requests=1, stage_duration=10.0
        )
        manager.record_result("s", success=False)
        monkeypatch.setattr(
            "maistro.skills.canary.time.time", lambda: deployment.stage_started_at + 20.0
        )
        assert manager.check_promotion_or_rollback("s") == "rollback"
