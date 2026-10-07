#!/usr/bin/env python3
"""Exhaustive bounded model checker for the consumer-claim execution spine (#884).

Research deliverable for RESEARCH M8-A4: a bounded, exhaustive exploration of
the claim -> dispatch -> commit -> accept -> cancel -> crash -> recover ->
retry protocol implemented by `maistro.runs.consumer_claim`,
`maistro.runs.execution` and `maistro.runs.lifecycle`, checking the safety
invariants the issue names over *every* interleaving up to the bound, rather
than the interleavings a randomized state machine (`formal/models/
test_run_lease_fence.py`) or a hand-written race
(`packages/maistro-core/tests/runs/test_spine_conformance.py`) happens to
schedule.

The transition relation is an independent encoding of the shipped protocol.
The checker imports only the shipped lifecycle tables (see
`conformance_with_shipped_tables`) so modeled transition legality cannot
silently diverge from `maistro.runs.lifecycle`; every guard is spelled here
and kept honest against the source docstrings. Two named multi-await windows
are modeled as explicit split actions, so the exploration covers the
interleavings *inside* the window and can prove the shipped guard closes all
of them:

* `_settle_provider_success` reads the Run, then writes the Attempt
  (#1335): modeled as `begin_commit` (the read) followed by `land_commit`
  (the write). The shipped guard converts the landing write to CANCELLED
  when the Run terminalized inside the window.
* the `accept_outcome` projection (ADR-082426-e3ff): modeled as `accept`,
  which in the shipped protocol carries the live fencing token and is
  refused for a superseded holder.

Variants: `guarded` models every shipped fence; `unguarded` removes exactly
two (the fenced acceptance and the terminal-run refusal) — the pre-fix world
those two changes repaired. The unguarded variant *must* violate S3/S4,
proving the checker can fire (formal/INVARIANTS.md #410 discipline).

Tooling justification: TLC/Apalache need a JVM this repo's CI does not
carry; this explorer is the "justified equivalent" the issue allows — a
deterministic, dependency-free, exhaustive bounded checker over the same
transition relation, reviewable by the same engineers as the protocol. The
portable TLA+ rendering of the same relation ships beside the research
record under `docs/research/models/884-execution-lease/`.

No product code changes; no ledgers touched.
"""

from __future__ import annotations

import argparse
import json
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, replace

# ---------------------------------------------------------------------------
# Model vocabulary. Status spellings follow the shipped lifecycle tables.
# ---------------------------------------------------------------------------

RUN_QUEUED = "queued"
RUN_RUNNING = "running"
RUN_COMPLETED = "completed"
RUN_CANCELLED = "cancelled"
RUN_TERMINAL = frozenset({RUN_COMPLETED, RUN_CANCELLED})

ATT_RUNNING = "running"
ATT_COMPLETED = "completed"
ATT_CANCELLED = "cancelled"

CAUSE_REQUESTED = "requested"
CAUSE_RECOVERED = "recovered"

#: Node replay semantics (durable_runs ReplaySemantics): `retryable` nodes may
#: be re-executed after crash recovery (duplicate effect tolerated downstream);
#: `once` nodes refuse a second physical try (ReplayRefused, #1194).
SEMANTICS = ("retryable", "once")


@dataclass(frozen=True, slots=True)
class Spec:
    """Bounded parameters and the guarded/unguarded switch.

    `ttl` is the lease in ticks; `horizon` bounds the clock. Renewals cap the
    expiry at `horizon` (standard max-expiry abstraction): time is coarsened,
    leases can only lapse *earlier* than real, so every safety trace of the
    real protocol has a model trace — the explored behaviors are a superset.
    """

    ttl: int = 2
    horizon: int = 6
    max_attempts: int = 2
    semantics: str = "once"
    #: ADR-082426-e3ff: acceptance carries the live fencing token.
    fenced_acceptance: bool = True
    #: #1335: the landing commit re-reads the Run and refuses/converts.
    terminal_run_refusal: bool = True

    def __post_init__(self) -> None:
        if self.ttl < 1:
            raise ValueError("ttl must be >= 1")
        if self.horizon < self.ttl + 3:
            raise ValueError("horizon must leave room for expiry and recovery")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if self.semantics not in SEMANTICS:
            raise ValueError(f"semantics must be one of {SEMANTICS}")

    @property
    def guarded(self) -> bool:
        return self.fenced_acceptance and self.terminal_run_refusal


@dataclass(frozen=True, slots=True)
class Attempt:
    """One ordinal Attempt: status, holder, fencing token, lease expiry."""

    ordinal: int
    status: str
    holder: int | None
    token: int | None
    expires: int | None
    #: Why CANCELLED: `requested` (a person) or `recovered` (crash reclamation)
    #: — the CancellationCause distinction the spine keeps for retry decisions.
    cause: str | None = None
    #: Whether this Attempt dispatched the physical effect.
    dispatched: bool = False


@dataclass(frozen=True, slots=True)
class State:
    """One protocol state; frozen so the frontier can hash it."""

    run: str
    attempts: tuple[Attempt, ...]
    alive: tuple[bool, ...]
    clock: int
    fence: int
    #: Ordinals whose physical effect has been dispatched ("once" witness).
    dispatched: tuple[int, ...]
    #: #1335 window: a commit has READ the Run and not yet landed its write,
    #: as (ordinal, holder, token, observed_run).
    pending: tuple[int, int, int, str] | None

    def key(self) -> tuple:
        return (
            self.run,
            self.attempts,
            self.alive,
            self.clock,
            self.fence,
            self.dispatched,
            self.pending,
        )


def initial_state(consumers: int) -> State:
    """Admission has committed: one Run QUEUED, no Attempts, no effect."""
    return State(
        run=RUN_QUEUED,
        attempts=(),
        alive=tuple(True for _ in range(consumers)),
        clock=0,
        fence=0,
        dispatched=(),
        pending=None,
    )


# ---------------------------------------------------------------------------
# Shipped-guard helpers, each named for the source it encodes.
# ---------------------------------------------------------------------------


def lease_is_expired(attempt: Attempt, clock: int) -> bool:
    """`maistro.runs.lifecycle.lease_is_expired`: expires_at <= now; an open
    Attempt with no lease never expires (the additive opt-in stance)."""
    if attempt.status != ATT_RUNNING:
        return False
    if attempt.expires is None:
        return False
    return attempt.expires <= clock


def live_lease(attempt: Attempt, clock: int) -> bool:
    """`has_live_execution_lease` for one Attempt: open + unexpired."""
    return attempt.status == ATT_RUNNING and attempt.expires is not None and attempt.expires > clock


def open_attempt(state: State) -> Attempt | None:
    """The single open Attempt, if any (the spine allows at most one)."""
    for attempt in state.attempts:
        if attempt.status == ATT_RUNNING:
            return attempt
    return None


def _cap(expires: int, horizon: int) -> int:
    return min(expires, horizon)


def _refuse_under_cancelled_run(spec: Spec, state: State) -> bool:
    """#1335: the landing write re-reads the Run inside its transaction."""
    return spec.terminal_run_refusal and state.run == RUN_CANCELLED


# ---------------------------------------------------------------------------
# Transition relation. Each action returns a labelled successor or None.
# ---------------------------------------------------------------------------


def act_claim(spec: Spec, state: State, consumer: int) -> tuple[str, State] | None:
    """consumer_claim.claim_consumer_run: one atomic write that moves the Run
    QUEUED -> RUNNING and mints Attempt 1 RUNNING under a fresh lease."""
    if state.run != RUN_QUEUED or state.attempts:
        return None
    attempt = Attempt(
        ordinal=1,
        status=ATT_RUNNING,
        holder=consumer,
        token=1,
        expires=_cap(state.clock + spec.ttl, spec.horizon),
    )
    return f"claim(c{consumer})", replace(state, run=RUN_RUNNING, attempts=(attempt,), fence=1)


def act_renew(spec: Spec, state: State, consumer: int) -> tuple[str, State] | None:
    """renew_attempt_lease: the live holder extends; an expired lease cannot
    be resurrected, and the token is unchanged (renewal is not a new claim)."""
    attempt = open_attempt(state)
    if attempt is None or attempt.holder != consumer or not state.alive[consumer]:
        return None
    if attempt.expires is None or attempt.expires <= state.clock:
        return None
    renewed = replace(attempt, expires=_cap(state.clock + spec.ttl, spec.horizon))
    attempts = tuple(renewed if a.ordinal == attempt.ordinal else a for a in state.attempts)
    return f"renew(c{consumer})", replace(state, attempts=attempts)


def act_tick(spec: Spec, state: State) -> tuple[str, State] | None:
    if state.clock >= spec.horizon:
        return None
    return "tick", replace(state, clock=state.clock + 1)


def act_crash(spec: Spec, state: State, consumer: int) -> tuple[str, State] | None:
    """The process dies: renewals stop with it; durable state stands."""
    if not state.alive[consumer]:
        return None
    alive = tuple(False if i == consumer else a for i, a in enumerate(state.alive))
    return f"crash(c{consumer})", replace(state, alive=alive)


def act_spawn(spec: Spec, state: State, consumer: int) -> tuple[str, State] | None:
    """Worker replacement: the orchestrator re-arms a dead slot.

    A fairness action for the progress graph only — the safety graph omits
    it because a revived worker can only take lease/fence-guarded actions,
    so its behaviors are already covered by never-crashed workers. Without
    replacement a fleet that crashed wholesale could never finish anything,
    and 'eventual progress' would fail for want of a successor — a fairness
    assumption of the world, not a guarantee of the protocol."""
    if state.alive[consumer]:
        return None
    alive = tuple(True if i == consumer else a for i, a in enumerate(state.alive))
    return f"spawn(c{consumer})", replace(state, alive=alive)


def act_dispatch(spec: Spec, state: State, consumer: int) -> tuple[str, State] | None:
    """The physical effect starts. The live-lease + fence guard is the
    ADR-081626-f383 / ADR-082426-e3ff discipline: a stale worker may not start
    work either. A `once` node never dispatches twice (ReplayRefused, #1194)."""
    attempt = open_attempt(state)
    if attempt is None or attempt.holder != consumer or attempt.dispatched:
        return None
    if not state.alive[consumer]:
        return None
    if attempt.token != state.fence or attempt.expires is None or attempt.expires <= state.clock:
        return None
    if spec.semantics == "once" and state.dispatched:
        return None
    return f"dispatch(c{consumer})", replace(
        state,
        attempts=tuple(
            replace(a, dispatched=True) if a.ordinal == attempt.ordinal else a
            for a in state.attempts
        ),
        dispatched=(*state.dispatched, attempt.ordinal),
    )


def act_begin_commit(spec: Spec, state: State, consumer: int) -> tuple[str, State] | None:
    """`_settle_provider_success` step 1: read the Run. The window this read
    opens is exactly #1335's; the model keeps it open as explicit state so a
    concurrent cancel can land inside it."""
    attempt = open_attempt(state)
    if attempt is None or attempt.holder != consumer or not attempt.dispatched:
        return None
    if state.pending is not None:
        return None
    return f"begin_commit(c{consumer})", replace(
        state,
        pending=(attempt.ordinal, consumer, attempt.token or 0, state.run),
    )


def act_land_commit(spec: Spec, state: State, consumer: int) -> tuple[str, State] | None:
    """`_settle_provider_success` step 2: write the Attempt.

    Shipped (#1335): the write re-checks the Run inside the same transaction.
    A Run that terminalized inside the window converts the stale success into
    a CANCELLED Attempt; a Run still RUNNING accepts COMPLETED. Unguarded
    (pre-fix): whatever the window observed or suffered, the success lands.
    The write itself still obeys the Attempt transition table — a landing
    against an Attempt recovery already settled is refused outright.
    """
    if state.pending is None:
        return None
    ordinal, holder, _token, _observed = state.pending
    if holder != consumer:
        return None
    attempt = next((a for a in state.attempts if a.ordinal == ordinal), None)
    if attempt is None or attempt.status != ATT_RUNNING:
        return None
    if _refuse_under_cancelled_run(spec, state):
        landed = replace(attempt, status=ATT_CANCELLED, cause=CAUSE_REQUESTED)
        label = f"land_commit->cancelled(c{consumer})"
    else:
        landed = replace(attempt, status=ATT_COMPLETED)
        label = f"land_commit(c{consumer})"
    attempts = tuple(landed if a.ordinal == ordinal else a for a in state.attempts)
    run = state.run if state.run in RUN_TERMINAL else RUN_RUNNING
    return label, replace(state, attempts=attempts, run=run, pending=None)


def act_accept(spec: Spec, state: State, consumer: int) -> tuple[str, State] | None:
    """accept_outcome: the worker-authored write that projects the outcome and
    terminalizes the Run. Shipped (ADR-082426-e3ff): the acceptance carries
    the fencing token and is refused unless its Attempt is still the live
    latest. Unguarded (pre-fix): a holder that once completed lands its
    acceptance regardless of who owns the node now."""
    attempt = next(
        (a for a in state.attempts if a.holder == consumer and a.status == ATT_COMPLETED),
        None,
    )
    if attempt is None or state.run in RUN_TERMINAL:
        return None
    if spec.fenced_acceptance:
        latest = state.attempts[-1]
        if attempt.ordinal != latest.ordinal or attempt.token != state.fence:
            return None
    return f"accept(c{consumer})", replace(state, run=RUN_COMPLETED)


def act_cancel(spec: Spec, state: State) -> tuple[str, State] | None:
    """Run-level cancellation: QUEUED/RUNNING -> CANCELLED, open Attempts
    settled CANCELLED (requested). A commit holding the #1335 window is
    mid-write: the Run lands first; the pending write lands afterwards and
    meets the shipped refusal (or, unguarded, does not)."""
    if state.run in RUN_TERMINAL:
        return None
    attempts = tuple(
        replace(a, status=ATT_CANCELLED, cause=CAUSE_REQUESTED)
        if a.status == ATT_RUNNING and (state.pending is None or state.pending[0] != a.ordinal)
        else a
        for a in state.attempts
    )
    return "cancel", replace(state, run=RUN_CANCELLED, attempts=attempts)


def act_recover(spec: Spec, state: State) -> tuple[str, State] | None:
    """reclaim_expired_attempts: settle open Attempts whose lease lapsed,
    naming the quiet holder. CancellationCause.RECOVERED — the node is still
    owed, so retry may re-drive it."""
    if not any(lease_is_expired(a, state.clock) for a in state.attempts):
        return None
    attempts = tuple(
        replace(a, status=ATT_CANCELLED, cause=CAUSE_RECOVERED)
        if lease_is_expired(a, state.clock)
        else a
        for a in state.attempts
    )
    return "recover", replace(state, attempts=attempts)


def act_retry(spec: Spec, state: State, consumer: int) -> tuple[str, State] | None:
    """A fresh Attempt for the still-owed node under the RUNNING Run
    (resume_due_graph_runs). Guards: every Attempt terminal (LiveAttemptOwned
    is subsumed — an open Attempt blocks here via `open_attempt`, and a
    terminal Attempt never holds a live lease, exactly as the shipped sweep
    consults only {CREATED, RUNNING} attempts), and the last Attempt's cause
    authorizes the retry — RECOVERED, or (pre-fix era) a completed-but-
    unaccepted Attempt whose node recovery had parked. A `once` node whose
    effect already ran never re-executes it: the fresh Attempt may exist, but
    `dispatch` refuses it (ReplayRefused), which is why that guard lives in
    dispatch."""
    if state.run != RUN_RUNNING or not state.attempts:
        return None
    if len(state.attempts) >= spec.max_attempts:
        return None
    if open_attempt(state) is not None:
        return None
    last = state.attempts[-1]
    authorized = last.cause == CAUSE_RECOVERED or (
        last.status == ATT_COMPLETED and not spec.fenced_acceptance
    )
    if not authorized:
        return None
    attempt = Attempt(
        ordinal=len(state.attempts) + 1,
        status=ATT_RUNNING,
        holder=consumer,
        token=state.fence + 1,
        expires=_cap(state.clock + spec.ttl, spec.horizon),
    )
    return (
        f"retry(c{consumer})",
        replace(state, attempts=(*state.attempts, attempt), fence=state.fence + 1),
    )


# ---------------------------------------------------------------------------
# Successor enumeration, invariant checking, exploration.
# ---------------------------------------------------------------------------


def successors(spec: Spec, state: State) -> list[tuple[str, State]]:
    """All labelled successors, in a fixed order (deterministic exploration)."""
    out: list[tuple[str, State]] = []
    consumers = range(len(state.alive))
    per_consumer = (
        act_claim,
        act_renew,
        act_crash,
        act_dispatch,
        act_begin_commit,
        act_accept,
        act_retry,
        act_land_commit,
    )
    for action in per_consumer:
        for consumer in consumers:
            step = action(spec, state, consumer)
            if step is not None:
                out.append(step)
    for action in (act_tick, act_cancel, act_recover):
        step = action(spec, state)
        if step is not None:
            out.append(step)
    return out


def check_invariants(state: State) -> list[str]:
    """The issue's candidate invariants, as state predicates.

    S1_single_owner — at most one active Attempt owns the node.
    S2_effect_once  — a `once` node's physical effect runs at most once.
    S3_acceptance_is_current — the acceptance that terminalized the Run came
        from the latest Attempt (ADR-082426-e3ff's stale acceptance).

    S4 and S5 are transition (edge) properties, checked in `edge_violations`:
    they are about *writes landing*, not states coexisting. In particular,
    run CANCELLED with an attempt COMPLETED is a legal shipped state (the
    work finished, then the run was cancelled — cancellation settles open
    Attempts and leaves terminal ones alone); what #1335 refuses is the
    COMPLETED write landing *after* the Run terminalized.
    """
    violations: list[str] = []
    running = [a for a in state.attempts if a.status == ATT_RUNNING]
    if len(running) > 1:
        violations.append("S1_single_owner")
    if len(state.dispatched) > 1:
        violations.append("S2_effect_once")
    if state.run == RUN_COMPLETED and state.attempts[-1].status != ATT_COMPLETED:
        violations.append("S3_acceptance_is_current")
    return violations


def edge_violations(prev: State, nxt: State) -> list[str]:
    """Transition properties, checked on every edge (they need both ends).

    S4_no_completion_under_terminal_run — a COMPLETED Attempt write never
        lands once the Run is terminal (#1335's refusal; the guarded
        landing converts instead).
    S5_terminal_no_regress — terminal statuses are absorbing.
    """
    violations: list[str] = []
    before = {a.ordinal: a.status for a in prev.attempts}
    if prev.run in RUN_TERMINAL:
        for attempt in nxt.attempts:
            if before.get(attempt.ordinal) == ATT_RUNNING and attempt.status == ATT_COMPLETED:
                violations.append("S4_no_completion_under_terminal_run")
        if nxt.run != prev.run:
            violations.append("S5_terminal_no_regress")
    for attempt in nxt.attempts:
        was = before.get(attempt.ordinal)
        if was in (ATT_COMPLETED, ATT_CANCELLED) and attempt.status != was:
            violations.append("S5_terminal_no_regress")
    return violations


@dataclass(frozen=True, slots=True)
class Finding:
    invariant: str
    trace: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Report:
    variant: str
    spec: Spec
    states: int
    edges: int
    findings: tuple[Finding, ...]
    stuck_states: int
    #: stuck states that are NOT explained by a declared modeling ceiling —
    #: a genuine protocol deadlock would show up here.
    stuck_beyond_ceilings: int
    settlement_without_cancel: bool

    @property
    def violated(self) -> tuple[str, ...]:
        return tuple(sorted({f.invariant for f in self.findings}))


def explore(spec: Spec, consumers: int = 2, *, with_progress: bool = True) -> Report:
    """Deterministic BFS over the full bounded state space.

    Safety invariants are checked on every discovered state; S4/S5 on every
    edge. The first violation per invariant keeps its BFS-minimal trace.
    Progress is checked by `check_progress` on its own fairness graph unless
    `with_progress` is false (mutation probes skip it: they exist to fire
    safety invariants).
    """
    start = initial_state(consumers)
    seen: dict[tuple, int] = {start.key(): 0}
    parent: dict[tuple, tuple[tuple, str]] = {}
    order: list[State] = [start]
    frontier: deque[State] = deque([start])
    edges = 0
    stuck = 0
    stuck_beyond_ceilings = 0
    findings: dict[str, Finding] = {}

    while frontier:
        current = frontier.popleft()
        steps = successors(spec, current)
        # 'Stuck' means the machinery has no move of its own — `cancel` is a
        # person's action and always available, so raw successor counts are
        # vacuous. A non-terminal state left with only a cancel is counted;
        # if it is also short of both declared modeling ceilings (the tick
        # horizon and the attempt bound), it is a genuine protocol deadlock
        # and reported separately.
        if current.run not in RUN_TERMINAL and all(label == "cancel" for label, _ in steps):
            stuck += 1
            ceiling_reached = (
                current.clock >= spec.horizon or len(current.attempts) >= spec.max_attempts
            )
            if not ceiling_reached:
                stuck_beyond_ceilings += 1
        for label, nxt in steps:
            edges += 1
            for violation in edge_violations(current, nxt):
                findings.setdefault(
                    violation, Finding(violation, (*_trace(parent, current.key()), label))
                )
            key = nxt.key()
            if key not in seen:
                seen[key] = len(order)
                parent[key] = (current.key(), label)
                order.append(nxt)
                for violation in check_invariants(nxt):
                    findings.setdefault(violation, Finding(violation, _trace(parent, key)))
                frontier.append(nxt)

    settlement = check_progress(spec, safety_keys=set(seen)) if with_progress else True
    return Report(
        variant="guarded" if spec.guarded else "unguarded",
        spec=spec,
        states=len(order),
        edges=edges,
        findings=tuple(findings[k] for k in sorted(findings)),
        stuck_states=stuck,
        stuck_beyond_ceilings=stuck_beyond_ceilings,
        settlement_without_cancel=settlement,
    )


def _trace(parent: dict[tuple, tuple[tuple, str]], key: tuple) -> tuple[str, ...]:
    """Rebuild the BFS-minimal action trace that reached `key`."""
    steps: list[str] = []
    while key in parent:
        prev_key, step = parent[key]
        steps.append(step)
        key = prev_key
    steps.reverse()
    return tuple(steps)


def check_progress(spec: Spec, safety_keys: set[tuple], consumers: int = 2) -> bool:
    """Eventual progress under the stated fairness assumptions.

    Claim quantified: every *safety-reachable* state (`safety_keys`) with
    tick budget remaining (clock < horizon) reaches — without any `cancel`
    and without assuming any current holder keeps running — either a
    terminal Run or live ownership (an open Attempt whose lease is unexpired
    and whose holder is alive). Fairness assumptions carried by the graph:
    the clock advances (`tick`), the sweep eventually runs (`recover`), and
    crashed workers are eventually replaced (`spawn`). Cancellation is a
    person's action, not a fairness assumption, so its edges carry no
    progress witness.

    The exploration allows one retry beyond the safety bound (the modeling
    ceiling, not protocol behavior); paths from safety-reachable states need
    at most that. States at clock == horizon are outside the claim — the
    model's time budget is exhausted and even a fresh lease cannot outlive
    it; a finite-clock TLC run has the same boundary, and the research
    record states it as such.
    """
    progress_spec = replace(spec, max_attempts=spec.max_attempts + 1)
    order, edge_list = _fairness_graph(progress_spec, consumers)

    def owned_or_terminal(state: State) -> bool:
        if state.run in RUN_TERMINAL:
            return True
        attempt = open_attempt(state)
        return (
            attempt is not None
            and live_lease(attempt, state.clock)
            and attempt.holder is not None
            and state.alive[attempt.holder]
        )

    return _reachable_from_all(order, edge_list, safety_keys, spec.horizon, owned_or_terminal)


def _fairness_graph(
    progress_spec: Spec, consumers: int
) -> tuple[list[State], list[tuple[tuple, str, tuple]]]:
    """Explore the transition relation with `spawn` added; returns states and
    edges. Cancel edges are kept (states behind them exist and are quantified
    over) but carry no progress witness (see `_reachable_from_all`)."""
    start = initial_state(consumers)
    seen: dict[tuple, int] = {start.key(): 0}
    order: list[State] = [start]
    frontier: deque[State] = deque([start])
    edge_list: list[tuple[tuple, str, tuple]] = []
    while frontier:
        current = frontier.popleft()
        steps = successors(progress_spec, current)
        for consumer in range(consumers):
            spawn = act_spawn(progress_spec, current, consumer)
            if spawn is not None:
                steps.append(spawn)
        for label, nxt in steps:
            edge_list.append((current.key(), label, nxt.key()))
            key = nxt.key()
            if key not in seen:
                seen[key] = len(order)
                order.append(nxt)
                frontier.append(nxt)
    return order, edge_list


def _reachable_from_all(
    order: list[State],
    edge_list: list[tuple[tuple, str, tuple]],
    quantified: set[tuple],
    horizon: int,
    target: Callable[[State], bool],
) -> bool:
    """Exact backward reachability from target states over non-cancel edges;
    True iff every quantified state with tick budget left can reach one."""
    key_index = {s.key(): i for i, s in enumerate(order)}
    reach = [target(s) for s in order]
    rev: dict[int, list[int]] = {}
    for src, label, dst in edge_list:
        if label == "cancel":
            continue  # a person's action carries no progress witness
        rev.setdefault(key_index[dst], []).append(key_index[src])
    changed = True
    while changed:
        changed = False
        for dst_i, srcs in rev.items():
            if reach[dst_i]:
                for src_i in srcs:
                    if not reach[src_i]:
                        reach[src_i] = True
                        changed = True
    return all(
        reach[key_index[key]]
        for key in quantified
        if key[3] < horizon  # key = (run, attempts, alive, clock, ...)
    )


def conformance_with_shipped_tables() -> list[str]:
    """Model-vs-shipped lifecycle conformance.

    Every move the model makes must be legal per `maistro.runs.lifecycle` —
    the shipped tables are imported, not restated, so a table change the
    model contradicts is reported instead of silently diverging. The model
    deliberately omits shipped moves outside its scope (WAITING/PAUSED/YIELD
    paths); omissions are not disagreements.
    """
    from maistro.runs.lifecycle import ATTEMPT_TRANSITIONS, RUN_TRANSITIONS

    model_run_moves = {
        (RUN_QUEUED, RUN_RUNNING),
        (RUN_RUNNING, RUN_COMPLETED),
        (RUN_QUEUED, RUN_CANCELLED),
        (RUN_RUNNING, RUN_CANCELLED),
    }
    model_attempt_moves = {
        (ATT_RUNNING, ATT_COMPLETED),
        (ATT_RUNNING, ATT_CANCELLED),
    }
    shipped_run_moves = {
        (source.value, target.value)
        for source, targets in RUN_TRANSITIONS.items()
        for target in targets
    }
    shipped_attempt_moves = {
        (source.value, target.value)
        for source, targets in ATTEMPT_TRANSITIONS.items()
        for target in targets
    }
    disagreements = [
        f"modeled Run move {move} is illegal in RUN_TRANSITIONS"
        for move in sorted(model_run_moves - shipped_run_moves)
    ]
    disagreements += [
        f"modeled Attempt move {move} is illegal in ATTEMPT_TRANSITIONS"
        for move in sorted(model_attempt_moves - shipped_attempt_moves)
    ]
    return disagreements


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

VARIANTS: dict[str, Spec] = {
    "guarded": Spec(),
    "unguarded": Spec(fenced_acceptance=False, terminal_run_refusal=False),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--variant", choices=(*VARIANTS, "all"), default="all")
    parser.add_argument("--semantics", choices=SEMANTICS, default="once")
    parser.add_argument("--json", action="store_true", help="machine-readable report")
    args = parser.parse_args(argv)

    names = list(VARIANTS) if args.variant == "all" else [args.variant]
    reports = [explore(replace(VARIANTS[name], semantics=args.semantics)) for name in names]

    if args.json:
        print(
            json.dumps(
                [
                    {
                        "variant": r.variant,
                        "spec": {
                            "ttl": r.spec.ttl,
                            "horizon": r.spec.horizon,
                            "max_attempts": r.spec.max_attempts,
                            "semantics": r.spec.semantics,
                            "fenced_acceptance": r.spec.fenced_acceptance,
                            "terminal_run_refusal": r.spec.terminal_run_refusal,
                        },
                        "states": r.states,
                        "edges": r.edges,
                        "stuck_states": r.stuck_states,
                        "stuck_beyond_ceilings": r.stuck_beyond_ceilings,
                        "violated": list(r.violated),
                        "findings": [
                            {"invariant": f.invariant, "trace": list(f.trace)} for f in r.findings
                        ],
                        "settlement_without_cancel": r.settlement_without_cancel,
                    }
                    for r in reports
                ],
                indent=2,
            )
        )
    else:
        for r in reports:
            print(
                f"{r.variant} [{r.spec.semantics}]: {r.states} states, {r.edges} edges, "
                f"{r.stuck_states} stuck ({r.stuck_beyond_ceilings} beyond ceilings), "
                f"settlement-without-cancel: "
                f"{r.settlement_without_cancel}, violations: {list(r.violated)}"
            )
            for finding in r.findings:
                print(f"  {finding.invariant}")
                for step in finding.trace:
                    print(f"    {step}")

    guarded = [r for r in reports if r.variant == "guarded"]
    return 1 if guarded and guarded[0].findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
