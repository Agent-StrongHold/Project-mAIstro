"""Safety governor — keeps the autonomous loop self-limiting (SPEC-188)."""

from __future__ import annotations

from maistro.capabilities.self_repair_governor import GovernorReason, SafetyGovernor


class _Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, secs: float) -> None:
        self.t += secs


def test_allows_first_attempt() -> None:
    gov = SafetyGovernor(clock=_Clock())
    d = gov.allow("docker:a")
    assert d.allowed is True
    assert d.reason is GovernorReason.OK


def test_in_flight_guard_blocks_second_dispatch() -> None:
    gov = SafetyGovernor(clock=_Clock())
    gov.record_dispatch("docker:a")
    d = gov.allow("docker:a")
    assert d.allowed is False
    assert d.reason is GovernorReason.IN_FLIGHT


def test_cooldown_blocks_immediate_redispatch() -> None:
    clock = _Clock()
    gov = SafetyGovernor(clock=clock, cooldown_s=60)
    gov.record_dispatch("docker:a")
    gov.record_result("docker:a", recovered=True)
    assert gov.allow("docker:a").reason is GovernorReason.COOLDOWN
    clock.advance(61)
    assert gov.allow("docker:a").allowed is True


def test_attempt_budget_exhausted_within_window() -> None:
    clock = _Clock()
    # high flap threshold so only the budget rule fires
    gov = SafetyGovernor(clock=clock, budget=3, window_s=1800, cooldown_s=10, flap_threshold=99)
    for _ in range(3):
        assert gov.allow("docker:a").allowed is True
        gov.record_dispatch("docker:a")
        gov.record_result("docker:a", recovered=True)
        clock.advance(11)  # past cooldown, within window
    d = gov.allow("docker:a")
    assert d.allowed is False
    assert d.reason is GovernorReason.BUDGET


def test_budget_resets_after_window() -> None:
    clock = _Clock()
    gov = SafetyGovernor(clock=clock, budget=2, window_s=600, cooldown_s=10, flap_threshold=99)
    for _ in range(2):
        gov.record_dispatch("docker:a")
        gov.record_result("docker:a", recovered=True)
        clock.advance(11)
    assert gov.allow("docker:a").reason is GovernorReason.BUDGET
    clock.advance(601)  # window elapsed → attempts pruned
    assert gov.allow("docker:a").allowed is True


def test_flap_detection_stops_oscillating_resource() -> None:
    clock = _Clock()
    # high budget so only the flap rule fires
    gov = SafetyGovernor(clock=clock, budget=99, window_s=99999, cooldown_s=10, flap_threshold=2)
    for _ in range(3):  # fix → recover → break, three times
        assert gov.allow("docker:a").allowed is True
        gov.record_dispatch("docker:a")
        gov.record_result("docker:a", recovered=True)
        clock.advance(11)
    d = gov.allow("docker:a")
    assert d.allowed is False
    assert d.reason is GovernorReason.FLAP


def test_resources_are_tracked_independently() -> None:
    gov = SafetyGovernor(clock=_Clock())
    gov.record_dispatch("docker:a")
    assert gov.allow("docker:a").reason is GovernorReason.IN_FLIGHT
    assert gov.allow("docker:b").allowed is True


def test_record_result_clears_in_flight() -> None:
    clock = _Clock()
    gov = SafetyGovernor(clock=clock, cooldown_s=0)
    gov.record_dispatch("docker:a")
    gov.record_result("docker:a", recovered=True)
    assert gov.allow("docker:a").allowed is True


def _build_flap_count(gov: SafetyGovernor, resource: str, count: int) -> None:
    """count+1 dispatch/recovered cycles -> flap_count == count.

    record_dispatch only increments flap_count when recovered_flag was already
    True from a prior cycle, so the first cycle establishes the flag without
    incrementing.
    """
    for _ in range(count + 1):
        gov.record_dispatch(resource)
        gov.record_result(resource, recovered=True)


def _build_attempts(gov: SafetyGovernor, resource: str, count: int) -> None:
    """count dispatch/failed cycles -> attempts_in_window == count, flap untouched.

    recovered=False never sets recovered_flag, so record_dispatch never bumps
    flap_count here.
    """
    for _ in range(count):
        gov.record_dispatch(resource)
        gov.record_result(resource, recovered=False)


class TestFlapCountBoundary:
    """flap_count vs flap_threshold at representative values 0, t-1, t, t+1.

    Budget/window are set generous so only the flap axis can block.
    """

    def test_zero_does_not_block(self) -> None:
        gov = SafetyGovernor(
            clock=_Clock(), budget=99, window_s=99999, cooldown_s=0, flap_threshold=3
        )
        _build_flap_count(gov, "docker:a", 0)
        assert gov.allow("docker:a").allowed is True

    def test_threshold_minus_one_does_not_block(self) -> None:
        gov = SafetyGovernor(
            clock=_Clock(), budget=99, window_s=99999, cooldown_s=0, flap_threshold=3
        )
        _build_flap_count(gov, "docker:a", 2)  # threshold - 1
        assert gov.allow("docker:a").allowed is True

    def test_at_threshold_blocks(self) -> None:
        gov = SafetyGovernor(
            clock=_Clock(), budget=99, window_s=99999, cooldown_s=0, flap_threshold=3
        )
        _build_flap_count(gov, "docker:a", 3)  # == threshold
        d = gov.allow("docker:a")
        assert d.allowed is False
        assert d.reason is GovernorReason.FLAP

    def test_above_threshold_still_blocks(self) -> None:
        gov = SafetyGovernor(
            clock=_Clock(), budget=99, window_s=99999, cooldown_s=0, flap_threshold=3
        )
        _build_flap_count(gov, "docker:a", 4)  # threshold + 1
        d = gov.allow("docker:a")
        assert d.allowed is False
        assert d.reason is GovernorReason.FLAP


class TestAttemptBudgetBoundary:
    """attempts_in_window vs budget at representative values 0, b-1, b, b+1.

    Flap/cooldown are set permissive so only the budget axis can block.
    record_dispatch never checks allow() internally, so attempts can be driven
    past budget directly — confirming allow() still recomputes correctly from
    an over-budget attempts list rather than only matching the exact boundary.
    """

    def test_zero_does_not_block(self) -> None:
        gov = SafetyGovernor(
            clock=_Clock(), budget=3, window_s=1800, cooldown_s=0, flap_threshold=99
        )
        _build_attempts(gov, "docker:a", 0)
        assert gov.allow("docker:a").allowed is True

    def test_budget_minus_one_does_not_block(self) -> None:
        gov = SafetyGovernor(
            clock=_Clock(), budget=3, window_s=1800, cooldown_s=0, flap_threshold=99
        )
        _build_attempts(gov, "docker:a", 2)  # budget - 1
        assert gov.allow("docker:a").allowed is True

    def test_at_budget_blocks(self) -> None:
        gov = SafetyGovernor(
            clock=_Clock(), budget=3, window_s=1800, cooldown_s=0, flap_threshold=99
        )
        _build_attempts(gov, "docker:a", 3)  # == budget
        d = gov.allow("docker:a")
        assert d.allowed is False
        assert d.reason is GovernorReason.BUDGET

    def test_above_budget_still_blocks(self) -> None:
        gov = SafetyGovernor(
            clock=_Clock(), budget=3, window_s=1800, cooldown_s=0, flap_threshold=99
        )
        _build_attempts(gov, "docker:a", 4)  # budget + 1, bypassing allow()'s own gate
        d = gov.allow("docker:a")
        assert d.allowed is False
        assert d.reason is GovernorReason.BUDGET


class TestCooldownElapsedBoundary:
    """cooldown_elapsed vs effective_cooldown at 0, c-eps, c (exact), c+eps.

    consecutive_failures is held at 0 (single recovered dispatch) so
    effective_cooldown == cooldown_s exactly, with no backoff multiplier
    muddying the boundary. The check is strict '<', so elapsed == cooldown_s
    must NOT block — that asymmetry vs. the budget axis's '>=' is the point
    of this boundary test.
    """

    def _seed(self) -> tuple[SafetyGovernor, _Clock]:
        clock = _Clock()
        gov = SafetyGovernor(
            clock=clock, budget=99, window_s=99999, cooldown_s=60, flap_threshold=99
        )
        gov.record_dispatch("docker:a")
        gov.record_result("docker:a", recovered=True)
        return gov, clock

    def test_zero_elapsed_blocks(self) -> None:
        gov, _clock = self._seed()
        d = gov.allow("docker:a")
        assert d.allowed is False
        assert d.reason is GovernorReason.COOLDOWN

    def test_just_under_cooldown_blocks(self) -> None:
        gov, clock = self._seed()
        clock.advance(59.999)
        d = gov.allow("docker:a")
        assert d.allowed is False
        assert d.reason is GovernorReason.COOLDOWN

    def test_exactly_at_cooldown_allows(self) -> None:
        gov, clock = self._seed()
        clock.advance(60.0)
        assert gov.allow("docker:a").allowed is True

    def test_just_over_cooldown_allows(self) -> None:
        gov, clock = self._seed()
        clock.advance(60.001)
        assert gov.allow("docker:a").allowed is True


class TestGateCheckPriorityOrder:
    """When multiple axes are simultaneously blocking, allow()'s actual check
    order — read directly from the source, not assumed from the module
    docstring's bullet order (which lists in-flight, budget, cooldown, flap)
    — is: in_flight > flap > budget > cooldown. Each case below stacks every
    higher-priority axis into its blocking state and confirms the reason
    matches the highest-priority one, not a lower one that's also blocking.
    """

    def test_in_flight_outranks_everything(self) -> None:
        gov = SafetyGovernor(
            clock=_Clock(), budget=1, window_s=1800, cooldown_s=60, flap_threshold=1
        )
        _build_flap_count(gov, "docker:a", 1)  # at flap threshold too
        gov.record_dispatch("docker:a")  # leaves in_flight True, also exhausts budget
        d = gov.allow("docker:a")
        assert d.allowed is False
        assert d.reason is GovernorReason.IN_FLIGHT

    def test_flap_outranks_budget_and_cooldown(self) -> None:
        gov = SafetyGovernor(
            clock=_Clock(), budget=1, window_s=1800, cooldown_s=60, flap_threshold=1
        )
        _build_flap_count(gov, "docker:a", 1)  # at threshold; also leaves budget/cooldown blocking
        d = gov.allow("docker:a")
        assert d.allowed is False
        assert d.reason is GovernorReason.FLAP

    def test_budget_outranks_cooldown(self) -> None:
        gov = SafetyGovernor(
            clock=_Clock(), budget=1, window_s=1800, cooldown_s=60, flap_threshold=99
        )
        _build_attempts(gov, "docker:a", 1)  # at budget; last dispatch also starts cooldown
        d = gov.allow("docker:a")
        assert d.allowed is False
        assert d.reason is GovernorReason.BUDGET

    def test_all_axes_clear_allows(self) -> None:
        gov = SafetyGovernor(
            clock=_Clock(), budget=3, window_s=1800, cooldown_s=60, flap_threshold=3
        )
        d = gov.allow("docker:a")
        assert d.allowed is True
        assert d.reason is GovernorReason.OK
