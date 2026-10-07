"""M8-A research harness — concurrency/model checking (TLA+/Apalache or equivalent).

Issue #918 (leaf of epic #880, initiative #879). Hypothesis under study: lightweight
concurrency bugs in MAIstro's core can be detected early with model checking, focusing
on race conditions in state management, task admission, or extension lifecycle that
existing testing misses.

This module is a RESEARCH ARTIFACT, not product code. The leaf's title says
"TLA+/Apalache **or equivalent**": no TLA+/Apalache toolchain exists in this
repository's deterministic CI and none was run, so this harness implements the
*equivalent in miniature* — an explicit-state model checker of the kind TLC
executes (exhaustive reachability over a fingerprint set, safety invariants
with shortest counterexample traces, leads-to liveness via sticky-cycle
detection, bounded exploration with honest truncation, and state abstraction
with counterexample spuriousness replay). That makes the technique's mechanics
reproducible today and the real experiment's procedure concrete, without
claiming any Apalache run or any finding about real MAIstro code: every model
below is a hand-written abstraction validated by hand-checked fixtures.

Canonical seam modeled: the exactly-once occurrence-claim contract of task
admission (``packages/maistro-core/src/maistro/scheduling/admission.py``):
``(schedule_id, scheduled_for)`` is the identity of a firing; the Run store
refuses a second Run for an occurrence that already has one; a duplicate claim
is consumed rather than fatal; and the cursor advances only after the Runs
exist (a tick that stamped first and then failed to create the Run would skip
that occurrence permanently). The harness rediscovers both documented defect
shapes when the abstract model drops each guard — evidence the technique catches
this failure class, on a hand-checked model; it is never a claim about the real
implementation, which carries the guards.

Trust boundary (the epic contract, enforced by construction):

- Every result produced here is ADVISORY EVIDENCE. Nothing in this module reads
  or writes a Goal, a Run authority, a routing decision, or a
  Warden/HITL/delegation control. It imports nothing from ``maistro`` at all,
  so it cannot become an authority by accident (M8 guardrails 1-2).
- Results are frozen records; they cannot be mutated into authorization after
  the fact. A truncated exploration is flagged in the result and must never be
  read as a pass — incompleteness is reported, not hidden (M8 guardrail 3).
- ``formal/`` remains the canonical in-tree model authority (Hypothesis stateful
  models against the real code). This harness complements it with *exhaustive*
  checking of *hand-written abstract* models and deliberately does not touch it
  (epic non-goal: no competing ``formal/`` authority).

The experiment record and terminal disposition (WATCH) live in
``docs/research/918-concurrency-model-checking-tla-apalache.md``.
"""

from __future__ import annotations

import ast
import dataclasses
from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

#: Explicit evidence-only contract marker. Asserted by a test so it cannot
#: silently rot; nothing outside this module may treat M8-A output as
#: authorization. No adoption here routes anything: production ownership of
#: admission/concurrency semantics stays with maistro-core scheduling and the
#: execution runtime contract (ADR-081426-1f7c).
ADVISORY_ONLY = True

#: Terminal disposition recorded in the research note. WATCH: the harness
#: demonstrates the technique on hand-checked abstract models; no run against
#: a real TLA+/Apalache toolchain or a real MAIstro subsystem abstraction has
#: happened, so nothing graduates.
RESEARCH_DISPOSITION = "WATCH"

#: A state is any hashable tuple; models are total over their own states.
State = tuple

#: An action maps a state to its labelled successors (empty = not enabled).
#: Nondeterminism (interleavings) is expressed as multiple actions and/or
#: multiple successors per action — the same shape as a TLA+ next-state relation.
Action = Callable[[State], list[tuple[str, State]]]

# ---------------------------------------------------------------------------
# Checking results — frozen records, advisory evidence only
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SafetyViolation:
    """A reachable state that breaks a safety invariant, with the shortest
    witnessing trace. ``path`` holds ``(action_label, state_after)`` steps from
    ``initial`` to ``final``; a violation *at* an initial state has an empty
    path."""

    invariant: str
    initial: State
    path: tuple[tuple[str, State], ...]
    final: State


@dataclass(frozen=True)
class LivenessViolation:
    """A sticky bad cycle: a reachable cycle (or terminal state, which stutters
    forever) on which the ``eventually`` target never holds, plus a shortest
    path from an initial state to the cycle. This is the standard finite-graph
    counterexample to ``<>Q`` — an execution may loop in the cycle forever."""

    property: str
    initial: State
    path: tuple[tuple[str, State], ...]
    cycle: tuple[State, ...]


@dataclass(frozen=True)
class SafetyResult:
    """Outcome of a bounded safety check. ``truncated=True`` means the state
    budget ran out before the frontier drained: ``violation is None`` is then
    INCONCLUSIVE, not a pass."""

    explored: int
    truncated: bool
    fingerprints: tuple[State, ...]
    violation: SafetyViolation | None


@dataclass(frozen=True)
class LivenessResult:
    """Outcome of a bounded liveness check, with the same honesty contract as
    :class:`SafetyResult`."""

    explored: int
    truncated: bool
    violation: LivenessViolation | None


# ---------------------------------------------------------------------------
# The checker — explicit-state exploration, the "or equivalent" of the leaf
# ---------------------------------------------------------------------------


def _successors(state: State, actions: tuple[Action, ...]) -> list[tuple[str, State]]:
    out: list[tuple[str, State]] = []
    for action in actions:
        out.extend(action(state))
    return out


def _path_to(
    parents: dict[State, tuple[State, str] | None], state: State
) -> tuple[tuple[str, State], ...]:
    steps: list[tuple[str, State]] = []
    cur: State = state
    while parents[cur] is not None:
        prev, label = parents[cur]
        steps.append((label, cur))
        cur = prev
    steps.reverse()
    return tuple(steps)


def _reach(
    initials: tuple[State, ...] | list[State],
    actions: tuple[Action, ...] | list[Action],
    max_states: int | None,
) -> tuple[dict[State, tuple[State, str] | None], bool]:
    """BFS over the reachable state space with first-wins parent pointers.
    Returns the parent map and whether the ``max_states`` budget stopped the
    search with frontier remaining (incompleteness the caller must report)."""
    parents: dict[State, tuple[State, str] | None] = {}
    queue: deque[State] = deque()
    for initial in initials:
        if initial not in parents:
            parents[initial] = None
            queue.append(initial)
    truncated = False
    while queue:
        if max_states is not None and len(parents) >= max_states:
            truncated = True
            break
        current = queue.popleft()
        for label, successor in _successors(current, actions):
            if successor in parents:
                continue
            parents[successor] = (current, label)
            queue.append(successor)
    return parents, truncated


def check_safety(
    initials: tuple[State, ...] | list[State],
    actions: tuple[Action, ...] | list[Action],
    invariant: Callable[[State], bool],
    *,
    invariant_name: str = "",
    max_states: int | None = None,
) -> SafetyResult:
    """Exhaustive BFS reachability with an invariant checked on every state
    (initial states included). Returns the shortest counterexample when the
    invariant is violated, or ``violation=None`` with an honest ``truncated``
    flag when the ``max_states`` budget stops exploration early."""
    name = invariant_name or getattr(invariant, "__name__", "<invariant>")
    parents: dict[State, tuple[State, str] | None] = {}
    queue: deque[State] = deque()
    violation: SafetyViolation | None = None
    for initial in initials:
        if initial in parents:
            continue
        parents[initial] = None
        if not invariant(initial):
            violation = SafetyViolation(invariant=name, initial=initial, path=(), final=initial)
            break
        queue.append(initial)
    truncated = False
    while queue and violation is None:
        if max_states is not None and len(parents) >= max_states:
            # Budget exhausted with frontier remaining: what we did not explore
            # could violate the invariant, so incompleteness is recorded.
            truncated = True
            break
        current = queue.popleft()
        for label, successor in _successors(current, actions):
            if successor in parents:
                continue
            parents[successor] = (current, label)
            if not invariant(successor):
                violation = SafetyViolation(
                    invariant=name,
                    initial=initial_state_of(parents, successor),
                    path=_path_to(parents, successor),
                    final=successor,
                )
                break
            queue.append(successor)
    return SafetyResult(
        explored=len(parents),
        truncated=truncated,
        fingerprints=tuple(sorted(parents)),
        violation=violation,
    )


def check_eventually(
    initials: tuple[State, ...] | list[State],
    actions: tuple[Action, ...] | list[Action],
    target: Callable[[State], bool],
    *,
    property_name: str = "",
    max_states: int | None = None,
) -> LivenessResult:
    """Check ``<>target`` ("eventually") over the reachable graph: the finite
    form of a leads-to liveness property. Violated iff some reachable state can
    stutter/cycle forever without reaching ``target`` — a reachable bad cycle,
    or a reachable terminal state (stuttering semantics, as in TLA+). Terminal
    bad states are reported first (deterministically, sorted), then bad cycles
    via a deterministic depth-first search."""
    name = property_name or getattr(target, "__name__", "<property>")
    parents, truncated = _reach(initials, actions, max_states)
    graph = {state: _successors(state, actions) for state in parents}

    def succ(state: State) -> list[State]:
        return sorted({nxt for _, nxt in graph[state]})

    violation: LivenessViolation | None = None
    if truncated:
        return LivenessResult(explored=len(parents), truncated=True, violation=None)
    bad = sorted(state for state in parents if not target(state))
    # A terminal bad state stutters forever without reaching the target.
    for state in bad:
        if not succ(state):
            violation = LivenessViolation(
                property=name,
                initial=initial_state_of(parents, state),
                path=_path_to(parents, state),
                cycle=(state,),
            )
            break
    if violation is None:
        cycle = _find_bad_cycle(bad, succ)
        if cycle is not None:
            entry = cycle[0]
            violation = LivenessViolation(
                property=name,
                initial=initial_state_of(parents, entry),
                path=_path_to(parents, entry),
                cycle=cycle,
            )
    return LivenessResult(explored=len(parents), truncated=truncated, violation=violation)


def initial_state_of(parents: dict[State, tuple[State, str] | None], state: State) -> State:
    """The initial state at the head of ``state``'s BFS parent chain."""
    cur: State = state
    while parents[cur] is not None:
        cur = parents[cur][0]  # type: ignore[index]
    return cur


def _find_bad_cycle(
    bad: list[State], succ: Callable[[State], list[State]]
) -> tuple[State, ...] | None:
    """Deterministic DFS over the bad subgraph; a gray re-encounter (back edge)
    yields the cycle currently on the stack. ``bad`` must be sorted and ``succ``
    deterministic for reproducible counterexamples."""
    color: dict[State, int] = {}  # 1 = gray (on stack), 2 = black (done)
    for root in bad:
        if color.get(root) == 2:
            continue
        nodes: list[State] = [root]
        iters: list[Iterator[State]] = [iter(succ(root))]
        color[root] = 1
        while nodes:
            nxt = next(iters[-1], None)
            if nxt is None:
                color[nodes[-1]] = 2
                nodes.pop()
                iters.pop()
                continue
            if nxt not in bad:
                continue
            seen = color.get(nxt)
            if seen is None:
                color[nxt] = 1
                nodes.append(nxt)
                iters.append(iter(succ(nxt)))
            elif seen == 1:
                return tuple(nodes[nodes.index(nxt) :])
    return None


# ---------------------------------------------------------------------------
# Abstraction and counterexample validation (benchmark-procedure step 5)
# ---------------------------------------------------------------------------


def abstract_state(model_state: State, abstraction: Callable[[State], State]) -> State:
    """Project a concrete state through an abstraction map."""
    return abstraction(model_state)


def abstract_model(
    initials: tuple[State, ...] | list[State],
    actions: tuple[Action, ...] | list[Action],
    abstraction: Callable[[State], State],
) -> tuple[tuple[State, ...], tuple[Action, ...]]:
    """Lift a model through an abstraction map: initials and every successor are
    projected, duplicate projected successors collapse (order-preserved). A
    sound abstraction never invents new behaviour; a coarse one can — which is
    exactly what :func:`counterexample_spuriousness` is for."""
    projected_initials = tuple(dict.fromkeys(abstraction(s) for s in initials))

    def lift(action: Action) -> Action:
        def step(state: State) -> list[tuple[str, State]]:
            out: list[tuple[str, State]] = []
            seen: set[State] = set()
            for label, successor in action(state):
                projected = abstraction(successor)
                if projected not in seen:
                    seen.add(projected)
                    out.append((label, projected))
            return out

        return step

    return projected_initials, tuple(lift(action) for action in actions)


def replay_steps(
    initial: State,
    path: tuple[tuple[str, State], ...],
    initials: tuple[State, ...] | list[State],
    actions: tuple[Action, ...] | list[Action],
) -> tuple[bool, str]:
    """Validate a counterexample trace against a (concrete) model: the start
    state must be an initial state and every step must be an enabled, labelled
    transition of the model. Used to test whether an abstract counterexample is
    concretizable or spurious."""
    if initial not in initials:
        return False, f"start state {initial!r} is not an initial state"
    current = initial
    for label, expected in path:
        enabled = {nxt for lbl, nxt in _successors(current, actions) if lbl == label}
        if expected not in enabled:
            return False, f"step {label!r} to {expected!r} not enabled at {current!r}"
        current = expected
    return True, "every step is an enabled transition of the model"


def counterexample_spuriousness(
    violation: SafetyViolation | LivenessViolation,
    initials: tuple[State, ...] | list[State],
    actions: tuple[Action, ...] | list[Action],
) -> tuple[bool, str]:
    """Is a counterexample produced against an abstract model concretizable on
    the concrete model? ``False`` means the abstraction is too coarse — the
    counterexample is spurious and must not be reported as a real finding."""
    return replay_steps(violation.initial, violation.path, initials, actions)


# ---------------------------------------------------------------------------
# The MAIstro seam: exactly-once occurrence claiming (scheduling/admission.py)
# ---------------------------------------------------------------------------

#: Per-ticker program counters: enumerated the due window, holds the claim,
#: created the Run, done, or crashed (absorbing — the bounded model has no
#: retry tick; see the liveness test that surfaces this modelling limit).
_ENUMERATED = "enumerated"
_CLAIMED = "claimed"
_CREATED = "created"
_DONE = "done"
_CRASHED = "crashed"


def _ticker_actions(
    ticker: int,
    tickers: int,
    *,
    guard_claims: bool,
    stamp_before_create: bool,
    allow_crash: bool,
) -> list[Action]:
    """One ticker's moves over the shared occurrence (see the contract
    invariants in :func:`occurrence_claim_model`)."""

    def claim(state: State) -> list[tuple[str, State]]:
        if state[ticker] != _ENUMERATED:
            return []
        nxt = list(state)
        if state[tickers] and guard_claims:
            # A duplicate claim is not a failure: the occurrence did fire,
            # so this ticker consumes it and moves on without a new Run.
            nxt[ticker] = _DONE
            return [(f"t{ticker}.claim:duplicate-consumed", tuple(nxt))]
        nxt[ticker] = _CLAIMED
        nxt[tickers] = True
        return [(f"t{ticker}.claim", tuple(nxt))]

    def create_run(state: State) -> list[tuple[str, State]]:
        if state[ticker] != _CLAIMED:
            return []
        nxt = list(state)
        nxt[ticker] = _CREATED
        nxt[tickers + 1] += 1
        return [(f"t{ticker}.create_run", tuple(nxt))]

    def stamp_cursor(state: State) -> list[tuple[str, State]]:
        ready = _CLAIMED if stamp_before_create else _CREATED
        if state[ticker] != ready:
            return []
        nxt = list(state)
        nxt[ticker] = _DONE
        nxt[tickers + 2] = True
        return [(f"t{ticker}.stamp_cursor", tuple(nxt))]

    def crash(state: State) -> list[tuple[str, State]]:
        if not allow_crash or state[ticker] not in (_ENUMERATED, _CLAIMED, _CREATED):
            return []
        nxt = list(state)
        nxt[ticker] = _CRASHED
        return [(f"t{ticker}.crash", tuple(nxt))]

    return [claim, create_run, stamp_cursor, crash]


def occurrence_claim_model(
    *,
    tickers: int = 1,
    guard_claims: bool = True,
    stamp_before_create: bool = False,
    allow_crash: bool = True,
) -> tuple[tuple[State, ...], tuple[Action, ...]]:
    """Abstract model of concurrent schedule admission.

    State layout: ``(pc_0 .. pc_{n-1}, occurrence_claimed, runs, cursor_stamped)``.
    Two concurrent tickers enumerate the same due window (the race setup the
    occurrence identity exists to close). Invariants of the real contract:

    - ``one_run_per_occurrence``: at most one Run is created for the occurrence
      (the store refuses a second Run for an occurrence that already has one);
    - ``cursor_implies_run``: the cursor is stamped only after a Run exists
      (stamping first would skip the occurrence permanently).

    ``guard_claims=False`` drops the duplicate-claim guard; ``stamp_before_create=True``
    stamps the cursor at ``claimed`` instead of ``created``. Each drop is a
    documented defect shape the checker must rediscover.
    """
    initials = (tuple([_ENUMERATED] * tickers + [False, 0, False]),)
    actions = tuple(
        action
        for i in range(tickers)
        for action in _ticker_actions(
            i,
            tickers,
            guard_claims=guard_claims,
            stamp_before_create=stamp_before_create,
            allow_crash=allow_crash,
        )
    )
    return initials, actions


def one_run_per_occurrence(state: State) -> bool:
    """Safety invariant: at most one Run for the occurrence."""
    return state[-2] <= 1


def cursor_implies_run(state: State) -> bool:
    """Safety invariant: a stamped cursor means the Run exists."""
    return (not state[-1]) or state[-2] >= 1


# ---------------------------------------------------------------------------
# Generic fixtures — hand-checked mechanics of the checker itself
# ---------------------------------------------------------------------------


def grid_model() -> tuple[tuple[State, ...], tuple[Action, ...]]:
    """Two counters capped at 2: exactly 9 reachable states (hand-checked)."""

    def incr_a(state: State) -> list[tuple[str, State]]:
        return [] if state[0] >= 2 else [("incr_a", (state[0] + 1, state[1]))]

    def incr_b(state: State) -> list[tuple[str, State]]:
        return [] if state[1] >= 2 else [("incr_b", (state[0], state[1] + 1))]

    return ((0, 0),), (incr_a, incr_b)


def sequence_model(*, guarded: bool) -> tuple[tuple[State, ...], tuple[Action, ...]]:
    """Two finishing steps; ``b`` must not finish before ``a``. The guarded
    model disables ``finish_b`` until ``a`` finished; the unguarded one exposes
    the reorder."""

    def finish_a(state: State) -> list[tuple[str, State]]:
        return [] if state[0] else [("finish_a", (True, state[1]))]

    def finish_b(state: State) -> list[tuple[str, State]]:
        if state[1] or (guarded and not state[0]):
            return []
        return [("finish_b", (state[0], True))]

    def settle(state: State) -> list[tuple[str, State]]:
        return [("settle", state)] if state == (True, True) else []

    return ((False, False),), (finish_a, finish_b, settle)


def chain_model() -> tuple[tuple[State, ...], tuple[Action, ...]]:
    """A single forward step into the target state."""

    def go(state: State) -> list[tuple[str, State]]:
        return [("go", ("s1",))] if state == ("s0",) else []

    return (("s0",),), (go,)


def trap_model() -> tuple[tuple[State, ...], tuple[Action, ...]]:
    """A self-loop that never reaches the target."""

    def loop(state: State) -> list[tuple[str, State]]:
        return [("loop", state)] if state == ("s0",) else []

    return (("s0",),), (loop,)


def ring_model() -> tuple[tuple[State, ...], tuple[Action, ...]]:
    """Three states whose last two form a cycle avoiding the target."""

    def go(state: State) -> list[tuple[str, State]]:
        edges = {
            ("a",): ("b",),
            ("b",): ("c",),
            ("c",): ("b",),
        }
        nxt = edges.get(state)
        return [("go", nxt)] if nxt else []

    return (("a",),), (go,)


def coarse_abstract_chain() -> tuple[tuple[State, ...], tuple[Action, ...]]:
    """Hand-written OVER-coarse abstraction used to demonstrate spuriousness.

    Concrete chain (``concrete_eventual_model``) reaches the target from every
    state; this abstract version adds an unguarded ``retry`` self-loop on the
    middle phase — an abstraction artifact that liveness checking must flag,
    and that replay then identifies as spurious.
    """

    def work(state: State) -> list[tuple[str, State]]:
        steps = {("p0",): ("p1",), ("p1",): ("p2",)}
        nxt = steps.get(state)
        return [("work", nxt)] if nxt else []

    def retry(state: State) -> list[tuple[str, State]]:
        # Abstraction artifact: the concrete model's retry leaves p1; this
        # projection forgot that, inventing a forever-loop.
        return [("retry", ("p1",))] if state == ("p1",) else []

    return (("p0",),), (work, retry)


def concrete_eventual_model() -> tuple[tuple[State, ...], tuple[Action, ...]]:
    """Every state can reach the target: ``<>p2`` genuinely holds."""

    def step(state: State) -> list[tuple[str, State]]:
        edges = {
            ("p0", 0): ("p1", 0),
            ("p1", 0): ("p1", 1),
            ("p1", 1): ("p2", 0),
        }
        nxt = edges.get(state)
        return [("advance", nxt)] if nxt else []

    return (("p0", 0),), (step,)


# ---------------------------------------------------------------------------
# Tests — checker mechanics on hand-checked fixtures
# ---------------------------------------------------------------------------


def test_advisory_only_marker_is_set() -> None:
    assert ADVISORY_ONLY is True
    assert RESEARCH_DISPOSITION == "WATCH"


def test_harness_imports_no_maistro_module() -> None:
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    assert imported, "sanity: the module imports something"
    assert not [name for name in imported if name.split(".")[0] == "maistro"], (
        "research harness must not import maistro: it cannot become an authority"
    )


def test_results_are_frozen_records() -> None:
    result = check_safety(((0, 0),), grid_model()[1], lambda s: True)
    assert dataclasses.is_dataclass(result)
    assert result.explored == 9
    violation = SafetyViolation(invariant="x", initial=(0,), path=(), final=(0,))
    try:
        violation.invariant = "y"  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        pass
    else:
        raise AssertionError("violations must be frozen: records cannot be mutated")
    try:
        result.explored = 0  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        pass
    else:
        raise AssertionError("results must be frozen: records cannot be mutated")


def test_grid_model_explores_exactly_nine_states() -> None:
    initials, actions = grid_model()
    result = check_safety(initials, actions, lambda s: True)
    assert result.explored == 9
    assert result.truncated is False
    assert result.violation is None
    assert result.fingerprints == tuple(sorted(result.fingerprints))


def test_grid_checking_is_deterministic() -> None:
    initials, actions = grid_model()
    first = check_safety(initials, actions, lambda s: True)
    second = check_safety(initials, actions, lambda s: True)
    assert first == second


def test_safety_violation_yields_hand_checked_shortest_trace() -> None:
    initials, actions = grid_model()

    def a_within_one(state: State) -> bool:
        return state[0] <= 1

    result = check_safety(initials, actions, a_within_one, invariant_name="a<=1")
    assert result.violation is not None
    violation = result.violation
    assert violation.invariant == "a<=1"
    assert violation.initial == (0, 0)
    assert [label for label, _ in violation.path] == ["incr_a", "incr_a"]
    assert violation.path[0][1] == (1, 0)
    assert violation.final == (2, 0)
    ok, reason = replay_steps(violation.initial, violation.path, initials, actions)
    assert ok, reason


def test_held_invariant_yields_no_violation() -> None:
    initials, actions = grid_model()
    result = check_safety(initials, actions, lambda s: s[0] <= 2 and s[1] <= 2)
    assert result.violation is None
    assert result.truncated is False


def test_violation_at_an_initial_state_has_empty_path() -> None:
    initials, actions = grid_model()
    result = check_safety(initials, actions, lambda s: s[0] > 0, invariant_name="started")
    assert result.violation is not None
    assert result.violation.initial == (0, 0)
    assert result.violation.path == ()
    assert result.violation.final == (0, 0)


def test_state_budget_truncates_honestly() -> None:
    initials, actions = grid_model()
    result = check_safety(initials, actions, lambda s: True, max_states=3)
    assert result.explored == 3
    assert result.truncated is True
    assert result.violation is None  # inconclusive — never a pass


def test_generous_budget_completes() -> None:
    initials, actions = grid_model()
    result = check_safety(initials, actions, lambda s: True, max_states=50)
    assert result.explored == 9
    assert result.truncated is False


def test_zero_budget_still_saw_the_initial_state() -> None:
    initials, actions = grid_model()
    result = check_safety(initials, actions, lambda s: True, max_states=0)
    assert result.explored == 1
    assert result.truncated is True


def test_empty_initial_set_explores_nothing() -> None:
    _, actions = grid_model()
    result = check_safety((), actions, lambda s: False)
    assert result.explored == 0
    assert result.truncated is False
    assert result.violation is None


def test_guarded_sequence_holds_and_explores_three_states() -> None:
    initials, actions = sequence_model(guarded=True)

    def b_not_before_a(state: State) -> bool:
        return not (state[1] and not state[0])

    result = check_safety(initials, actions, b_not_before_a)
    assert result.explored == 3
    assert result.violation is None


def test_unguarded_sequence_is_caught_at_the_first_reorder() -> None:
    initials, actions = sequence_model(guarded=False)

    def b_not_before_a(state: State) -> bool:
        return not (state[1] and not state[0])

    result = check_safety(initials, actions, b_not_before_a)
    assert result.violation is not None
    violation = result.violation
    assert violation.initial == (False, False)
    assert [label for label, _ in violation.path] == ["finish_b"]
    assert violation.final == (False, True)


def test_disabled_action_produces_no_successors() -> None:
    _, actions = sequence_model(guarded=True)
    assert actions[1]((False, False)) == []  # finish_b disabled before a
    assert actions[1]((False, True)) == []  # already finished
    assert actions[1]((True, False)) == [("finish_b", (True, True))]


def test_eventually_holds_on_a_simple_chain() -> None:
    initials, actions = chain_model()
    result = check_eventually(initials, actions, lambda s: s == ("s1",), property_name="reaches_s1")
    assert result.truncated is False
    assert result.violation is None
    assert result.explored == 2


def test_eventually_flags_a_self_loop_trap() -> None:
    initials, actions = trap_model()
    result = check_eventually(initials, actions, lambda s: s == ("s1",), property_name="reaches_s1")
    assert result.violation is not None
    violation = result.violation
    assert violation.property == "reaches_s1"
    assert violation.path == ()
    assert violation.cycle == (("s0",),)
    assert violation.initial == ("s0",)


def test_eventually_finds_the_bad_cycle_in_a_ring() -> None:
    initials, actions = ring_model()
    result = check_eventually(initials, actions, lambda s: s == ("z",))
    assert result.violation is not None
    violation = result.violation
    assert violation.cycle == (("b",), ("c",))
    assert [label for label, _ in violation.path] == ["go"]
    ok, reason = replay_steps(violation.initial, violation.path, initials, actions)
    assert ok, reason


def test_terminal_states_stutter_so_incompleteness_is_a_violation() -> None:
    # TLA+ stuttering semantics: a stopped execution repeats its last state
    # forever, so a dead end short of the target is a liveness violation.
    initials, actions = chain_model()
    result = check_eventually(initials, actions, lambda s: s == ("s9",))
    assert result.violation is not None
    assert result.violation.cycle == (("s1",),)


# ---------------------------------------------------------------------------
# Tests — the occurrence-claim seam model
# ---------------------------------------------------------------------------


def test_single_ticker_correct_model_hand_checked_state_count() -> None:
    initials, actions = occurrence_claim_model(tickers=1)
    result = check_safety(initials, actions, one_run_per_occurrence)
    # (E,F,0,F) (C,T,0,F) (R,T,1,F) (D,T,1,T) (X,F,0,F) (X,T,0,F) (X,T,1,F)
    assert result.explored == 7
    assert result.truncated is False
    assert result.violation is None
    assert set(result.fingerprints) == {
        (_ENUMERATED, False, 0, False),
        (_CLAIMED, True, 0, False),
        (_CREATED, True, 1, False),
        (_DONE, True, 1, True),
        (_CRASHED, False, 0, False),
        (_CRASHED, True, 0, False),
        (_CRASHED, True, 1, False),
    }


def test_single_ticker_model_satisfies_both_contract_invariants() -> None:
    initials, actions = occurrence_claim_model(tickers=1)
    for invariant in (one_run_per_occurrence, cursor_implies_run):
        result = check_safety(initials, actions, invariant)
        assert result.violation is None, invariant.__name__


def test_duplicate_claim_is_consumed_without_a_second_run() -> None:
    initials, actions = occurrence_claim_model(tickers=1)
    result = check_safety(initials, actions, one_run_per_occurrence)
    done_states = [s for s in result.fingerprints if s[0] == _DONE]
    assert done_states == [(_DONE, True, 1, True)]


def test_two_tickers_racing_still_produces_one_run() -> None:
    initials, actions = occurrence_claim_model(tickers=2)
    for invariant in (one_run_per_occurrence, cursor_implies_run):
        result = check_safety(initials, actions, invariant)
        assert result.violation is None, invariant.__name__
        assert result.truncated is False
        assert result.explored > 7  # the interleaving space, not just one ticker


def test_two_ticker_race_reaches_the_duplicate_consume_interleaving() -> None:
    initials, actions = occurrence_claim_model(tickers=2)
    result = check_safety(initials, actions, one_run_per_occurrence)
    # t0 claims and creates while t1's claim is consumed as a duplicate.
    assert (_DONE, _CREATED, True, 1, False) in set(result.fingerprints)
    assert (_DONE, _DONE, True, 1, True) in set(result.fingerprints)


def test_dropped_claim_guard_produces_a_second_run() -> None:
    initials, actions = occurrence_claim_model(tickers=2, guard_claims=False)
    result = check_safety(initials, actions, one_run_per_occurrence)
    assert result.violation is not None
    violation = result.violation
    assert [label for label, _ in violation.path] == [
        "t0.claim",
        "t0.create_run",
        "t1.claim",
        "t1.create_run",
    ]
    assert violation.final[-2] == 2  # two Runs for one occurrence
    ok, reason = replay_steps(violation.initial, violation.path, initials, actions)
    assert ok, reason


def test_stamping_cursor_before_creating_skips_the_occurrence() -> None:
    initials, actions = occurrence_claim_model(tickers=1, stamp_before_create=True)
    result = check_safety(initials, actions, cursor_implies_run)
    assert result.violation is not None
    violation = result.violation
    assert [label for label, _ in violation.path] == ["t0.claim", "t0.stamp_cursor"]
    assert violation.final == (_DONE, True, 0, True)
    ok, reason = replay_steps(violation.initial, violation.path, initials, actions)
    assert ok, reason


def test_crash_short_of_the_run_is_a_liveness_violation_in_this_model() -> None:
    # The bounded model has no retry tick, so a crash before create_run leaves
    # the occurrence claimed forever: the checker must surface exactly that
    # modelling limit rather than paper over it.
    initials, actions = occurrence_claim_model(tickers=1)
    result = check_eventually(initials, actions, lambda s: s[-2] >= 1, property_name="run_exists")
    assert result.violation is not None
    violation = result.violation
    assert violation.cycle == ((_CRASHED, False, 0, False),)
    assert [label for label, _ in violation.path] == ["t0.crash"]


def test_without_crashes_every_enumeration_eventually_creates_the_run() -> None:
    initials, actions = occurrence_claim_model(tickers=1, allow_crash=False)
    result = check_eventually(initials, actions, lambda s: s[-2] >= 1, property_name="run_exists")
    assert result.violation is None
    assert result.truncated is False


def test_full_seam_check_is_reproducible() -> None:
    initials, actions = occurrence_claim_model(tickers=2)
    first = check_safety(initials, actions, one_run_per_occurrence)
    second = check_safety(initials, actions, one_run_per_occurrence)
    assert first == second


# ---------------------------------------------------------------------------
# Tests — abstraction and spuriousness (benchmark-procedure step 5)
# ---------------------------------------------------------------------------


def test_cap_abstraction_shrinks_the_state_space_without_false_alarms() -> None:
    initials, actions = grid_model()

    def cap_at_one(state: State) -> State:
        return (min(state[0], 1), min(state[1], 1))

    abstract_initials, abstract_actions = abstract_model(initials, actions, cap_at_one)
    concrete = check_safety(initials, actions, lambda s: True)
    abstract = check_safety(abstract_initials, abstract_actions, lambda s: s[0] <= 1 and s[1] <= 1)
    assert abstract.explored == 4
    assert concrete.explored == 9
    assert abstract.violation is None  # sound abstraction: no invented failure


def test_coarse_abstraction_invents_a_liveness_violation() -> None:
    abstract_initials, abstract_actions = coarse_abstract_chain()
    result = check_eventually(abstract_initials, abstract_actions, lambda s: s == ("p2",))
    assert result.violation is not None
    assert result.violation.cycle == (("p1",),)


def test_concrete_model_of_the_same_system_has_no_violation() -> None:
    initials, actions = concrete_eventual_model()
    result = check_eventually(initials, actions, lambda s: s[0] == "p2")
    assert result.violation is None
    assert result.truncated is False


def test_spurious_abstract_counterexample_is_flagged_by_replay() -> None:
    abstract_initials, abstract_actions = coarse_abstract_chain()
    concrete_initials, concrete_actions = concrete_eventual_model()
    result = check_eventually(abstract_initials, abstract_actions, lambda s: s == ("p2",))
    assert result.violation is not None
    concretizable, reason = counterexample_spuriousness(
        result.violation, concrete_initials, concrete_actions
    )
    assert concretizable is False
    assert "not enabled" in reason or "not an initial state" in reason


def test_real_counterexample_replays_concretely() -> None:
    initials, actions = occurrence_claim_model(tickers=2, guard_claims=False)
    result = check_safety(initials, actions, one_run_per_occurrence)
    assert result.violation is not None
    concretizable, reason = counterexample_spuriousness(result.violation, initials, actions)
    assert concretizable is True, reason


def test_replay_rejects_a_fabricated_trace() -> None:
    initials, actions = grid_model()
    fabricated = SafetyViolation(
        invariant="a<=1",
        initial=(0, 0),
        path=(("incr_b", (1, 0)),),  # incr_b cannot change the first coordinate
        final=(1, 0),
    )
    concretizable, reason = counterexample_spuriousness(fabricated, initials, actions)
    assert concretizable is False
    assert "not enabled" in reason


def test_replay_rejects_a_trace_not_starting_at_an_initial_state() -> None:
    initials, actions = grid_model()
    misplaced = SafetyViolation(
        invariant="a<=1",
        initial=(1, 1),  # reachable, but not an initial state
        path=(("incr_a", (2, 1)),),
        final=(2, 1),
    )
    concretizable, reason = counterexample_spuriousness(misplaced, initials, actions)
    assert concretizable is False
    assert "not an initial state" in reason


def test_abstract_projection_helper_matches_manual_projection() -> None:
    assert abstract_state((2, 3), lambda s: (min(s[0], 1), min(s[1], 1))) == (1, 1)
