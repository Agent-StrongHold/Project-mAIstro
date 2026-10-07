"""Tests for `scripts/model_check_consumer_claim.py` (issue #884, M8-A4).

The root suite is the coverage producer for `scripts/` (quality.yml runs
`--source=scripts`), so an untested research checker would red the
diff-coverage gate — same reason `test_bench_outcome_routing.py` exists.
Beyond coverage, these tests pin the evidence the research record's
disposition rests on:

* the modeled transition legality is the shipped lifecycle's (the checker
  imports `maistro.runs.lifecycle`, it does not restate it), and the lease
  predicates derive time exactly as the shipped ones do;
* the GUARDED protocol — every shipped fence in place — survives exhaustive
  exploration of its bounded state space with zero violations and settles
  without a person under the stated fairness assumptions;
* the UNGUARDED protocol violates exactly the two invariants whose guards
  were removed, and the counterexample traces are the shipped races:
  ADR-082426-e3ff's stale acceptance and #1335's completion landing inside
  the read/commit window. A checker that never fires is not evidence
  (formal/INVARIANTS.md #410), so each remaining invariant is also
  demonstrated to fire against a realistic mutant;
* effect-once holds exactly under `once` replay semantics — under
  `retryable`, a crashed in-flight effect legitimately re-runs (the
  at-least-once contract), which the model must allow, not flag as a bug;
* exploration is deterministic (same states, same first counterexample).

Everything is offline, stdlib-only and small (the full both-variant run is
~2s), well inside the suite's `--timeout=30` producer budget.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "model_check_consumer_claim.py"

spec = importlib.util.spec_from_file_location("model_check_consumer_claim", SCRIPT)
assert spec and spec.loader
checker = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = checker
spec.loader.exec_module(checker)


def _explore(**kwargs: object) -> checker.Report:
    """Safety-only exploration (mutation probes and determinism checks do not
    need the fairness graph; the full runs get their own test)."""
    return checker.explore(with_progress=False, **kwargs)


def _index(trace: tuple[str, ...], prefix: str) -> int:
    """Position of the first step whose label starts with `prefix` (labels
    carry their consumer, e.g. `land_commit(c0)`)."""
    return next(i for i, step in enumerate(trace) if step.startswith(prefix))


def _contains(trace: tuple[str, ...], prefix: str) -> bool:
    return any(step.startswith(prefix) for step in trace)


# ---------------------------------------------------------------------------
# Conformance with the shipped protocol, not a parallel universe.
# ---------------------------------------------------------------------------


class TestConformanceWithShippedCode:
    def test_modeled_moves_are_legal_in_the_shipped_lifecycle(self) -> None:
        """Every Run/Attempt move the model makes must exist in
        `maistro.runs.lifecycle` — imported, not restated."""
        assert checker.conformance_with_shipped_tables() == []

    def test_lease_expiry_predicate_matches_the_shipped_one(self) -> None:
        """The model's `lease_is_expired` derives time exactly as
        `maistro.runs.lifecycle.lease_is_expired`: unexpired leases are live,
        lapsed leases are expired, terminal Attempts never expire, and a
        lease-less Attempt is never reclaimable (the additive opt-in)."""
        from maistro.runs.lifecycle import lease_is_expired as shipped
        from maistro.runs.model import Attempt, AttemptStatus, ExecutionLease

        now = datetime.now(UTC)
        holder = "worker-a"

        def lease(attempt_id: str, expires_at: datetime | None) -> ExecutionLease:
            return ExecutionLease(
                node_run_id="n1",
                attempt_id=attempt_id,
                lease_epoch=1,
                holder=holder,
                issued_at=now - timedelta(seconds=30),
                expires_at=expires_at,
            )

        cases = [
            # (shipped attempt, model attempt, model clock)
            (
                Attempt(
                    attempt_id="a1",
                    node_run_id="n1",
                    ordinal=1,
                    status=AttemptStatus.RUNNING,
                    execution_lease=lease("a1", now + timedelta(seconds=5)),
                ),
                checker.Attempt(
                    ordinal=1,
                    status=checker.ATT_RUNNING,
                    holder=0,
                    token=1,
                    expires=10,
                ),
                5,
            ),
            (
                Attempt(
                    attempt_id="a2",
                    node_run_id="n1",
                    ordinal=1,
                    status=AttemptStatus.RUNNING,
                    execution_lease=lease("a2", now - timedelta(seconds=5)),
                ),
                checker.Attempt(
                    ordinal=1,
                    status=checker.ATT_RUNNING,
                    holder=0,
                    token=1,
                    expires=5,
                ),
                10,
            ),
            (
                Attempt(
                    attempt_id="a3",
                    node_run_id="n1",
                    ordinal=1,
                    status=AttemptStatus.COMPLETED,
                    finished_at=now,
                    execution_lease=lease("a3", now - timedelta(seconds=5)),
                ),
                checker.Attempt(
                    ordinal=1,
                    status=checker.ATT_COMPLETED,
                    holder=0,
                    token=1,
                    expires=5,
                ),
                10,
            ),
            (
                Attempt(
                    attempt_id="a4",
                    node_run_id="n1",
                    ordinal=1,
                    status=AttemptStatus.RUNNING,
                    execution_lease=None,
                ),
                checker.Attempt(
                    ordinal=1,
                    status=checker.ATT_RUNNING,
                    holder=0,
                    token=None,
                    expires=None,
                ),
                10,
            ),
        ]
        for real, modeled, clock in cases:
            assert shipped(real, now) is checker.lease_is_expired(modeled, clock), (
                f"model disagrees with the shipped predicate for {real.attempt_id}"
            )


# ---------------------------------------------------------------------------
# The guarded protocol is clean; the unguarded one fires exactly as claimed.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def guarded_full_run() -> checker.Report:
    return checker.explore(checker.Spec())  # includes the fairness graph


@pytest.fixture(scope="module")
def unguarded_run() -> checker.Report:
    return checker.explore(
        checker.Spec(fenced_acceptance=False, terminal_run_refusal=False),
        with_progress=False,
    )


class TestGuardedProtocol:
    def test_no_violations_exhaustively(self, guarded_full_run: checker.Report) -> None:
        assert guarded_full_run.variant == "guarded"
        assert guarded_full_run.findings == ()
        assert guarded_full_run.states > 1000  # the space is real, not degenerate

    def test_no_deadlock_short_of_the_declared_ceilings(
        self, guarded_full_run: checker.Report
    ) -> None:
        """Non-terminal states whose only move is a person's cancel exist —
        but only at a declared modeling ceiling (tick horizon or attempt
        bound). A protocol deadlock short of those ceilings would show in
        `stuck_beyond_ceilings`, and must not."""
        assert guarded_full_run.stuck_beyond_ceilings == 0

    def test_progress_without_a_person(self, guarded_full_run: checker.Report) -> None:
        """Crash + tick + recover + spawn suffice to return every
        safety-reachable state to settled-or-owned; settlement never needs a
        cancel."""
        assert guarded_full_run.settlement_without_cancel is True


class TestUnguardedProtocol:
    def test_violates_exactly_s3_and_s4(self, unguarded_run: checker.Report) -> None:
        """Removing exactly two shipped guards fires exactly their two
        invariants — and nothing else (S1/S2/S5 hold by construction)."""
        assert unguarded_run.violated == (
            "S3_acceptance_is_current",
            "S4_no_completion_under_terminal_run",
        )

    def test_s3_trace_is_the_stale_acceptance_race(self, unguarded_run: checker.Report) -> None:
        """ADR-082426-e3ff's reproduced interleaving: worker completes, its
        node is parked for retry, a successor attempt goes live, and the
        stale acceptance lands — acceptance not from the latest Attempt."""
        trace = next(
            f.trace for f in unguarded_run.findings if f.invariant == "S3_acceptance_is_current"
        )
        assert trace[0].startswith("claim(")
        assert _contains(trace, "land_commit")
        assert _index(trace, "land_commit") < _index(trace, "retry")
        assert trace[-1].startswith("accept(")
        assert _index(trace, "retry") < _index(trace, "accept")

    def test_s4_trace_runs_cancel_inside_the_commit_window(
        self, unguarded_run: checker.Report
    ) -> None:
        """#1335's window: the Run lands CANCELLED between the read
        (`begin_commit`) and the write (`land_commit`), and the stale success
        lands as COMPLETED underneath it."""
        trace = next(
            f.trace
            for f in unguarded_run.findings
            if f.invariant == "S4_no_completion_under_terminal_run"
        )
        assert (
            _index(trace, "begin_commit") < _index(trace, "cancel") < _index(trace, "land_commit")
        )
        assert trace[-1].startswith("land_commit(")


class TestInvariantsThatHoldEverywhere:
    @pytest.mark.parametrize(
        "spec",
        [
            checker.Spec(),
            checker.Spec(fenced_acceptance=False, terminal_run_refusal=False),
        ],
        ids=["guarded", "unguarded"],
    )
    def test_single_owner_and_terminal_absorption_hold(self, spec: checker.Spec) -> None:
        run = _explore(spec=spec)
        assert "S1_single_owner" not in run.violated
        assert "S5_terminal_no_regress" not in run.violated


class TestEffectOnceAgainstReplaySemantics:
    def test_once_semantics_never_repeats_the_effect(self) -> None:
        run = _explore(spec=checker.Spec(semantics="once"))
        assert "S2_effect_once" not in run.violated

    def test_retryable_semantics_legitimately_repeats_a_crashed_effect(self) -> None:
        """At-least-once: under `retryable`, a crashed in-flight effect MAY
        re-run through recovery. The model must allow it (no invariant
        claims otherwise) — and the re-dispatch trace must go through
        reclaim/retry, never through a completed Attempt (a completed effect
        is never re-dispatched; guarded retry requires the RECOVERED
        cause)."""
        run = _explore(spec=checker.Spec(semantics="retryable"))
        assert "S2_effect_once" in run.violated
        trace = next(f.trace for f in run.findings if f.invariant == "S2_effect_once")
        assert "recover" in trace, "re-dispatch must ride crash recovery"
        assert trace.index("recover") < len(trace) - 1

    def test_guarded_retry_never_rides_a_completed_attempt(self) -> None:
        """A completed Attempt's node is not re-driven: guarded `retry`
        demands the RECOVERED cause. Force a completed attempt and check no
        retry successor exists."""
        spec = checker.Spec(semantics="retryable")
        claim = checker.act_claim(spec, checker.initial_state(2), 0)
        assert claim is not None
        _label, claimed = claim
        dispatch = checker.act_dispatch(spec, claimed, 0)
        assert dispatch is not None
        _label, dispatched = dispatch
        begin = checker.act_begin_commit(spec, dispatched, 0)
        assert begin is not None
        _label, begun = begin
        land = checker.act_land_commit(spec, begun, 0)
        assert land is not None
        _label, landed = land
        assert landed.attempts[-1].status == checker.ATT_COMPLETED
        assert checker.act_retry(spec, landed, 1) is None
        assert checker.act_retry(spec, landed, 0) is None


# ---------------------------------------------------------------------------
# Mutation probes: each counted invariant must be able to fail (#410).
# ---------------------------------------------------------------------------


class TestEveryInvariantCanFail:
    def test_resume_over_a_live_owner_fires_single_owner(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Mutant: recovery resumes a Run whose Attempt is still live — the
        exact hazard `LiveAttemptOwned` refuses. Two attempts end up owning
        the node at once."""
        original = checker.act_retry

        def mutant(spec: checker.Spec, state: checker.State, consumer: int):
            step = original(spec, state, consumer)
            if step is None:
                # Drop the open-attempt guard only: retry over a live owner.
                if state.run != checker.RUN_RUNNING or not state.attempts:
                    return None
                if len(state.attempts) >= spec.max_attempts:
                    return None
                if any(checker.live_lease(a, state.clock) for a in state.attempts):
                    return None
                attempt = checker.Attempt(
                    ordinal=len(state.attempts) + 1,
                    status=checker.ATT_RUNNING,
                    holder=consumer,
                    token=state.fence + 1,
                    expires=min(state.clock + spec.ttl, spec.horizon),
                )
                return (
                    f"retry!(c{consumer})",
                    dataclasses.replace(
                        state, attempts=(*state.attempts, attempt), fence=state.fence + 1
                    ),
                )
            return step

        monkeypatch.setattr(checker, "act_retry", mutant)
        run = _explore(spec=checker.Spec())
        assert "S1_single_owner" in run.violated

    def test_dropped_replay_refusal_fires_effect_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Mutant: the `once` node's ReplayRefused discipline is gone, so the
        retried Attempt re-executes an effect that already ran (#1194)."""
        original = checker.act_dispatch

        def mutant(spec: checker.Spec, state: checker.State, consumer: int):
            if spec.semantics == "once":
                spec = dataclasses.replace(spec, semantics="retryable")
            return original(spec, state, consumer)

        monkeypatch.setattr(checker, "act_dispatch", mutant)
        run = _explore(spec=checker.Spec(semantics="once"))
        assert "S2_effect_once" in run.violated

    def test_accept_over_a_terminal_run_fires_terminal_no_regress(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Mutant: acceptance ignores the Run's terminality — the Run regresses
        out of CANCELLED, which nothing in the shipped spine may do."""
        original = checker.act_accept

        def mutant(spec: checker.Spec, state: checker.State, consumer: int):
            if state.run in checker.RUN_TERMINAL:
                state = dataclasses.replace(state, run=checker.RUN_RUNNING)
            return original(spec, state, consumer)

        monkeypatch.setattr(checker, "act_accept", mutant)
        run = _explore(spec=checker.Spec())
        assert "S5_terminal_no_regress" in run.violated

    def test_writing_over_a_reclaimed_attempt_fires_terminal_no_regress(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Mutant: a store drops the Attempt transition-table guard, so a
        landing write overwrites an Attempt recovery already settled — the
        Attempt leaves a terminal status, and the pairwise monitor catches
        what the (removed) landing guard used to refuse."""

        def mutant(spec: checker.Spec, state: checker.State, consumer: int):
            if state.pending is None:
                return None
            ordinal, holder, _token, _observed = state.pending
            if holder != consumer:
                return None
            if checker._refuse_under_cancelled_run(spec, state):
                return None
            attempt = next(
                (a for a in state.attempts if a.ordinal == ordinal and a.holder == consumer), None
            )
            if attempt is None:
                return None
            landed = dataclasses.replace(attempt, status=checker.ATT_COMPLETED)
            attempts = tuple(landed if a.ordinal == ordinal else a for a in state.attempts)
            run = state.run if state.run in checker.RUN_TERMINAL else checker.RUN_RUNNING
            return (
                f"land_commit!(c{consumer})",
                dataclasses.replace(state, attempts=attempts, run=run, pending=None),
            )

        monkeypatch.setattr(checker, "act_land_commit", mutant)
        run = _explore(spec=checker.Spec())
        assert "S5_terminal_no_regress" in run.violated

    def test_a_clockless_world_is_detected_as_stuck(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Mutant: time never advances. A crashed holder's lease can never
        lapse, so nothing can reclaim or finish it — the stuck-state detector
        must count that state, not silently explore an infinite-looking
        freeze. (A monitor that never fired could not be trusted on the real
        protocol either.)"""
        monkeypatch.setattr(checker, "act_tick", lambda spec, state: None)
        run = _explore(spec=checker.Spec())
        assert run.stuck_beyond_ceilings > 0


# ---------------------------------------------------------------------------
# The named windows behave as the source docstrings claim.
# ---------------------------------------------------------------------------


class TestNamedWindows:
    def _dispatched_and_begun(self, spec: checker.Spec) -> checker.State:
        claim = checker.act_claim(spec, checker.initial_state(2), 0)
        assert claim is not None
        dispatch = checker.act_dispatch(spec, claim[1], 0)
        assert dispatch is not None
        begin = checker.act_begin_commit(spec, dispatch[1], 0)
        assert begin is not None
        return begin[1]

    def test_landing_write_is_refused_after_reclamation(self) -> None:
        """A commit window left open across recovery cannot land: the
        Attempt is terminal, and the transition table refuses the write —
        the worker's outcome dies with its lease."""
        spec = checker.Spec()
        state = self._dispatched_and_begun(spec)
        # Let the lease (ttl=2, expiring at clock 2) lapse, then sweep.
        ticked = state
        for _ in range(2):
            step = checker.act_tick(spec, ticked)
            assert step is not None
            ticked = step[1]
        recovered = checker.act_recover(spec, ticked)
        assert recovered is not None
        _label, reclaimed = recovered
        assert reclaimed.attempts[0].status == checker.ATT_CANCELLED
        assert checker.act_land_commit(spec, reclaimed, 0) is None

    def test_guarded_landing_converts_under_a_cancelled_run(self) -> None:
        """#1335's shipped behavior: a stale success meeting the terminal-Run
        fence lands as a CANCELLED Attempt, never COMPLETED under CANCELLED."""
        spec = checker.Spec()
        state = self._dispatched_and_begun(spec)
        cancelled = checker.act_cancel(spec, state)
        assert cancelled is not None
        _label, cancelled_state = cancelled
        assert cancelled_state.run == checker.RUN_CANCELLED
        landing = checker.act_land_commit(spec, cancelled_state, 0)
        assert landing is not None
        label, landed = landing
        assert landed.attempts[0].status == checker.ATT_CANCELLED
        assert landed.run == checker.RUN_CANCELLED
        assert "cancelled" in label

    def test_unguarded_landing_lands_completed_under_a_cancelled_run(self) -> None:
        """The pre-#1335 world: the same window lands COMPLETED underneath the
        CANCELLED Run — the contradiction the fence refuses."""
        spec = checker.Spec(terminal_run_refusal=False)
        state = self._dispatched_and_begun(spec)
        cancelled = checker.act_cancel(spec, state)
        assert cancelled is not None
        landing = checker.act_land_commit(spec, cancelled[1], 0)
        assert landing is not None
        _label, landed = landing
        assert landed.attempts[0].status == checker.ATT_COMPLETED
        assert landed.run == checker.RUN_CANCELLED

    def test_fenced_acceptance_refuses_a_superseded_holder(self) -> None:
        """ADR-082426-e3ff: the acceptance carries the live token; attempt 1's
        holder may not accept once attempt 2 exists. The pre-fix era — which
        parked completed-but-unaccepted nodes for retry — is what creates the
        successor attempt; the fence is what discharges the stale acceptance."""
        era = checker.Spec(fenced_acceptance=False)  # retry over parked nodes
        state = self._dispatched_and_begun(era)
        landed = checker.act_land_commit(era, state, 0)
        assert landed is not None
        completed = landed[1]
        assert completed.attempts[0].status == checker.ATT_COMPLETED
        retried = checker.act_retry(era, completed, 1)
        assert retried is not None
        _label, successor = retried
        assert successor.attempts[-1].ordinal == 2
        assert checker.act_accept(checker.Spec(), successor, 0) is None, (
            "the superseded holder's acceptance must be refused under the fence"
        )
        assert checker.act_accept(era, successor, 0) is not None, (
            "without the fence, the stale acceptance lands"
        )


# ---------------------------------------------------------------------------
# Machinery: determinism, CLI, validation.
# ---------------------------------------------------------------------------


class TestMachinery:
    def test_exploration_is_deterministic(self) -> None:
        first = _explore(spec=checker.Spec(fenced_acceptance=False, terminal_run_refusal=False))
        second = _explore(spec=checker.Spec(fenced_acceptance=False, terminal_run_refusal=False))
        assert first.states == second.states
        assert first.edges == second.edges
        assert first.findings == second.findings

    def test_spec_rejects_degenerate_bounds(self) -> None:
        with pytest.raises(ValueError, match="ttl"):
            checker.Spec(ttl=0)
        with pytest.raises(ValueError, match="horizon"):
            checker.Spec(ttl=4, horizon=4)
        with pytest.raises(ValueError, match="max_attempts"):
            checker.Spec(max_attempts=0)
        with pytest.raises(ValueError, match="semantics"):
            checker.Spec(semantics="sometimes")

    def test_cli_json_reports_both_variants_and_exit_zero(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert checker.main(["--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        by_variant = {entry["variant"]: entry for entry in payload}
        assert by_variant["guarded"]["violated"] == []
        assert by_variant["guarded"]["states"] > 1000
        assert by_variant["guarded"]["settlement_without_cancel"] is True
        assert set(by_variant["unguarded"]["violated"]) == {
            "S3_acceptance_is_current",
            "S4_no_completion_under_terminal_run",
        }
        for entry in payload:
            assert entry["stuck_beyond_ceilings"] == 0
            for finding in entry["findings"]:
                assert finding["trace"], "every reported violation carries its trace"

    def test_cli_exit_one_when_the_guarded_variant_fires(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The guarded variant is clean by construction, so the failure exit
        is exercised by injecting a violating guarded-labeled report."""
        violating = checker.Report(
            variant="guarded",
            spec=checker.Spec(),
            states=10,
            edges=12,
            findings=(checker.Finding("S1_single_owner", ("claim(c0)",)),),
            stuck_states=0,
            stuck_beyond_ceilings=0,
            settlement_without_cancel=True,
        )
        monkeypatch.setattr(
            checker,
            "explore",
            lambda spec, consumers=2, with_progress=True: violating,
        )
        assert checker.main(["--variant", "guarded"]) == 1
        capsys.readouterr()

    def test_cli_human_output_names_traces(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert checker.main(["--variant", "unguarded"]) == 0
        out = capsys.readouterr().out
        assert "unguarded" in out
        assert "S3_acceptance_is_current" in out
        assert "claim(c0)" in out  # counterexample traces are printed, not just counted
