"""Every parked Graph pause reason names a reachable production waker (#1192).

`PAUSE_RESUME_CONDITIONS` says what each pause waits *for*; nothing said who
delivers it. `awaiting_remote_delegation` is answer-gated, parks WAITING, and
the only production answer path (`answer_record` behind Hive HITL) accepts
PAUSED alone -- so a dispatched delegation can wait forever and no test fails.

`PAUSE_REASON_WAKERS` below is the missing statement, kept test-local on
purpose: a production registry nobody imports would itself be unreachable
code. Each waker is checked mechanically rather than trusted, within limits:

* the entrypoint exists and has a production caller (a registered route for a
  person's answer or cancel; a call from, or a hand-off as an argument in, a
  non-test tree for anything that must fire on its own), so a waker only tests
  reach does not count. Callers are matched by name, one hop deep: a tick loop
  that is itself never started would still pass;
* the entrypoint calls the canonical API it claims to go through, and that
  API's accepted parked status -- pinned behaviourally at the end of this file
  -- matches the status the executor parks the reason in. That is the
  WAITING/PAUSED mismatch expressed as a failing assertion. A reason parked
  beside a human pause parks PAUSED with it, so every such pair must also be
  released by one of its members' wakers;
* whatever finally runs the Run again -- the tick itself, or for an answer the
  drain that picks up the QUEUED Run -- must be able to select a Run that
  carries the reason. A tick that filters to one admission source owns only
  the node kinds that source builds Graphs from (its module's `node_type=`
  arguments), and one of those kinds must be a node that can emit the reason
  (its defining module names it). A filtered tick whose module builds no Graph
  runs registered definitions, so it owns any registered kind. A tick over Runs
  that can never pause this way is not a waker, however reachable it is.

`UNWOKEN` is the known-gap ledger. It is strict both ways against the map: a
reason missing from both fails, and a ledgered reason given a waker entry
fails until it leaves the ledger.

Scope: the legacy Hive DAG (every node `hive.legacy_node`) and Evolve
(`evolve.*`) ticks own Runs that never pause, so the Runs these wakers actually
reach are schedule-admitted registered DAGs, via #837's recovery halves. A
registered DAG run by hand, the orchestrator's, or a synthesized one has no
production drain for an answered or elapsed pause until
`Container.resume_parked_runs` gets its #62 cadence.
"""

from __future__ import annotations

import ast
import asyncio
import pathlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from functools import cache
from types import SimpleNamespace
from typing import Any

import pytest

import maistro.graph.nodes.base as base
from maistro.graph.durable_runs import recovery
from maistro.graph.durable_runs.executor import _checkpoint_paused_frontier
from maistro.graph.durable_runs.hitl import expire_hitl_pauses
from maistro.graph.durable_runs.stores import (
    InMemoryDurableRunStore,
    answer_record,
    settle_hitl_record,
)
from maistro.graph.durable_runs.types import DurableRunRecord
from maistro.graph.nodes.base import (
    PAUSE_AWAITING_DELEGATION_RECONCILIATION,
    PAUSE_AWAITING_HARNESS,
    PAUSE_AWAITING_HUMAN_ANSWER,
    PAUSE_AWAITING_HUMAN_APPROVAL,
    PAUSE_AWAITING_HUMAN_REVIEW,
    PAUSE_AWAITING_REMOTE_DELEGATION,
    PAUSE_AWAITING_ROLE_DELEGATE,
    PAUSE_REASON_OWNERS,
    PAUSE_RESUME_CONDITIONS,
    PAUSE_WAITING_ON_JIRA_SUBTASKS,
    TIMER_RESUMABLE_PAUSE_REASONS,
    NodeResult,
)
from maistro.runs.lifecycle import transition_node_run
from maistro.runs.model import NodeRun, Run, RunStatus

from .._canonical_helpers import durable_record, graph_from_dag, run_at_status

pytestmark = [pytest.mark.contract("behavioral")]

REPO_ROOT = pathlib.Path(base.__file__).resolve().parents[6]

_HITL_ROUTES = "packages/hive-conductor/backend/routes/hitl.py"
_DAG_RUNNER = "packages/hive-conductor/backend/services/canonical_dag_runner.py"
_EVOLUTION = "packages/hive-conductor/backend/services/evolution_graph.py"
_EVOLVE_KINDS = frozenset(
    {
        "evolve.evaluate_genome",
        "evolve.plan_tournament_pairs",
        "evolve.tournament_pair",
        "evolve.finalize_cycle",
    }
)


@dataclass(frozen=True)
class Entry:
    """A production function and the canonical API it must call."""

    path: str
    name: str
    via: str


@dataclass(frozen=True)
class Waker:
    #: answer | deadline | cancel | timer | event
    kind: str
    entry: Entry
    #: What picks the Run up once `entry` has left it QUEUED. An answer that
    #: queues a Run nothing drains is not a waker.
    resumed_by: tuple[Entry, ...] = ()


#: The parked status each canonical API accepts. Every row is pinned by
#: equality against the shipped API at the bottom of this file, so a literal
#: here cannot drift from what production accepts. An answer settles
#: PAUSED -> QUEUED, which is what the queued-recovery seam drains.
VIA_ACCEPTS: dict[str, frozenset[RunStatus]] = {
    "submit_hitl_answer": frozenset({RunStatus.PAUSED}),
    "cancel_hitl": frozenset({RunStatus.PAUSED}),
    "expire_hitl_pauses": frozenset({RunStatus.PAUSED}),
    "resume_due_graph_runs": frozenset({RunStatus.WAITING, RunStatus.RUNNING}),
    "recover_queued_graph_runs": frozenset({RunStatus.QUEUED}),
}

_REGISTERED = "packages/hive-conductor/backend/services/registered_dag_recovery.py"

#: Drain QUEUED Runs of their own admissions only, whose nodes never pause.
_LEGACY_QUEUED_RECOVERY = (
    Entry(_DAG_RUNNER, "recover_stranded_dag_runs", "recover_queued_graph_runs"),
    Entry(_EVOLUTION, "recover_stranded_evolution_runs", "recover_queued_graph_runs"),
)
_QUEUED_RECOVERY = (
    *_LEGACY_QUEUED_RECOVERY,
    Entry(_REGISTERED, "recover_stranded_registered_dag_runs", "recover_queued_graph_runs"),
)
_HITL_ANSWER = Waker(
    "answer",
    Entry(_HITL_ROUTES, "answer_human_work", "submit_hitl_answer"),
    resumed_by=_QUEUED_RECOVERY,
)
_HITL_CANCEL = Waker("cancel", Entry(_HITL_ROUTES, "cancel_human_work", "cancel_hitl"))
_HUMAN_WAKERS = (_HITL_ANSWER, _HITL_CANCEL)
# `expire_human_work` is not listed: it expires HITL deadlines only when
# someone calls `POST /v1/hitl/expire`, and a deadline nobody ticks is not a
# waker (`test_a_deadline_only_a_route_reaches_is_not_a_waker`).
#
# `Container.resume_parked_runs` also re-enters these for consumer-executed
# Runs, but has no production caller until the #62 cadence ticks it.

#: Reachable, and `resume_due_graph_runs` accepts WAITING, but each owns only
#: its own admission's Runs, none of which can hold a Jira or delegation node
#: (`test_the_legacy_due_ticks_own_no_run_that_can_emit_a_timer_reason`).
_LEGACY_TIMER_WAKERS = (
    Waker("timer", Entry(_DAG_RUNNER, "wake_due_dag_runs", "resume_due_graph_runs")),
    Waker("timer", Entry(_EVOLUTION, "wake_due_evolution_runs", "resume_due_graph_runs")),
)
_TIMER_WAKERS = (
    Waker("timer", Entry(_REGISTERED, "wake_due_registered_dag_runs", "resume_due_graph_runs")),
)

PAUSE_REASON_WAKERS: dict[str, tuple[Waker, ...]] = {
    PAUSE_AWAITING_HUMAN_ANSWER: _HUMAN_WAKERS,
    PAUSE_AWAITING_HUMAN_APPROVAL: _HUMAN_WAKERS,
    PAUSE_AWAITING_HUMAN_REVIEW: _HUMAN_WAKERS,
    PAUSE_AWAITING_ROLE_DELEGATE: _HUMAN_WAKERS,
    PAUSE_WAITING_ON_JIRA_SUBTASKS: _TIMER_WAKERS,
    PAUSE_AWAITING_DELEGATION_RECONCILIATION: _TIMER_WAKERS,
}

#: Known gaps: answer-gated reasons that park WAITING, which no production
#: path delivers an answer to. Removing an entry is how #1192 closes.
UNWOKEN: dict[str, str] = {
    PAUSE_AWAITING_REMOTE_DELEGATION: "#1192",
    PAUSE_AWAITING_HARNESS: "#1192",
}


# -- checks ------------------------------------------------------------------


def frontier_status(reasons: Sequence[str]) -> RunStatus:
    """The status the durable executor parks a frontier of these pauses in.

    Asked of the executor's own checkpoint rather than re-derived, so a
    sibling's pause changing the parent's status is whatever the executor does.
    """
    ids = [f"n{index}" for index in range(len(reasons))]
    record = durable_record(
        {"id": "frontier", "nodes": [{"id": i, "kind": "test.pause"} for i in ids], "edges": []},
        run_id="frontier",
    )
    paused: Any = tuple(
        SimpleNamespace(node_id=i, result=NodeResult(success=True, metadata={"paused_reason": r}))
        for i, r in zip(ids, reasons, strict=True)
    )

    async def _park() -> DurableRunRecord:
        store = InMemoryDurableRunStore()
        await store.create(record)
        return await _checkpoint_paused_frontier(record, paused, (), (), store=store)

    return asyncio.run(_park()).run.status


def parked_status(reason: str) -> RunStatus:
    """The status the durable executor parks a Run in for `reason` alone."""
    return frontier_status((reason,))


def coverage_problems(
    conditions: Iterable[str],
    wakers: Mapping[str, object],
    ledger: Mapping[str, str],
) -> list[str]:
    problems: list[str] = []
    for reason in sorted(set(conditions) - set(wakers) - set(ledger)):
        problems.append(f"{reason}: no reachable production waker and not in the UNWOKEN ledger")
    for reason in sorted(set(wakers) & set(ledger)):
        problems.append(f"{reason}: has a waker, so remove it from the UNWOKEN ledger")
    for reason in sorted((set(wakers) | set(ledger)) - set(conditions)):
        problems.append(f"{reason}: not a PAUSE_RESUME_CONDITIONS reason")
    for reason, specs in wakers.items():
        if not specs:
            problems.append(f"{reason}: no reachable production waker (empty waker list)")
    return problems


def _production_files(root: pathlib.Path) -> list[pathlib.Path]:
    trees = [*sorted((root / "packages").glob("*/src"))]
    trees.append(root / "packages" / "hive-conductor" / "backend")
    files: list[pathlib.Path] = []
    for tree in trees:
        for path in sorted(tree.rglob("*.py")):
            parts = path.relative_to(root).parts
            if "tests" in parts or path.name.startswith("test_"):
                continue
            files.append(path)
    return files


@dataclass(frozen=True)
class _Index:
    #: Function name -> where it is called, or handed to a call as an argument.
    call_sites: dict[str, tuple[tuple[pathlib.Path, int], ...]]
    #: Node kind -> the modules defining a node class of that kind.
    kind_modules: dict[str, tuple[pathlib.Path, ...]]


@cache
def _index(root: pathlib.Path) -> _Index:
    """One pass over production. Kept instead of the ASTs themselves, which
    would pin a few hundred MB for the rest of the suite."""
    sites: dict[str, list[tuple[pathlib.Path, int]]] = {}
    kinds: dict[str, list[pathlib.Path]] = {}
    for path in _production_files(root):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        strings = _module_strings(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                handed = [*node.args, *(keyword.value for keyword in node.keywords)]
                names = [_callee(node), *(a.id for a in handed if isinstance(a, ast.Name))]
                for name in filter(None, names):
                    sites.setdefault(name, []).append((path.resolve(), node.lineno))
            elif isinstance(node, ast.ClassDef):
                for kind in _class_kinds(node, strings):
                    kinds.setdefault(kind, []).append(path.resolve())
    return _Index(
        call_sites={name: tuple(where) for name, where in sites.items()},
        kind_modules={kind: tuple(where) for kind, where in kinds.items()},
    )


def _module_strings(tree: ast.Module) -> dict[str, str]:
    """Module-level `NAME = "literal"` bindings, to resolve `kind = _KIND`."""
    strings: dict[str, str] = {}
    for node in tree.body:
        target = value = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        if (
            isinstance(target, ast.Name)
            and isinstance(value, ast.Constant)
            and isinstance(value.value, str)
        ):
            strings[target.id] = value.value
    return strings


def _string(node: ast.AST | None, strings: Mapping[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return strings.get(node.id)
    return None


def _class_kinds(cls: ast.ClassDef, strings: Mapping[str, str]) -> list[str]:
    return [
        kind
        for stmt in cls.body
        if isinstance(stmt, ast.AnnAssign)
        and isinstance(stmt.target, ast.Name)
        and stmt.target.id == "kind"
        and (kind := _string(stmt.value, strings))
    ]


def _callee(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _called_names(node: ast.AST) -> set[str]:
    return {
        name
        for call in ast.walk(node)
        if isinstance(call, ast.Call) and (name := _callee(call)) is not None
    }


def _module_function(tree: ast.Module, name: str) -> ast.AST | None:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name:
            return node
    return None


def _is_registered_route(root: pathlib.Path, path: str, fn: ast.AST) -> bool:
    """A `@router.<verb>` handler whose module's router the Hive app includes."""
    decorators = getattr(fn, "decorator_list", [])
    routed = any(
        isinstance(d, ast.Call)
        and isinstance(d.func, ast.Attribute)
        and isinstance(d.func.value, ast.Name)
        and d.func.value.id == "router"
        for d in decorators
    )
    if not routed:
        return False
    main = root / "packages" / "hive-conductor" / "backend" / "main.py"
    if not main.exists():
        return False
    module = pathlib.Path(path).stem
    for call in ast.walk(ast.parse(main.read_text(encoding="utf-8"))):
        if (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "include_router"
            and call.args
            and isinstance(call.args[0], ast.Attribute)
            and isinstance(call.args[0].value, ast.Name)
            and call.args[0].value.id == module
            and call.args[0].attr == "router"
        ):
            return True
    return False


def _has_production_caller(root: pathlib.Path, entry: Entry, fn: ast.AST) -> bool:
    """A call or hand-off by name anywhere in a production tree, except inside `fn`."""
    own_file = (root / entry.path).resolve()
    first, last = getattr(fn, "lineno", 0), getattr(fn, "end_lineno", 0)
    return any(
        not (path == own_file and first <= line <= (last or first))
        for path, line in _index(root).call_sites.get(entry.name, ())
    )


#: Kinds that must fire without anyone asking. A registered route is how a
#: person answers or cancels; it is not how a deadline or a timer elapses.
TICK_KINDS = frozenset({"deadline", "timer"})


def entry_problems(root: pathlib.Path, entry: Entry, *, route_counts: bool = True) -> list[str]:
    where = f"{entry.path}:{entry.name}"
    source = root / entry.path
    if not source.exists():
        return [f"{where}: file does not exist"]
    fn = _module_function(ast.parse(source.read_text(encoding="utf-8")), entry.name)
    if fn is None:
        return [f"{where}: no module-level function of that name"]
    problems: list[str] = []
    if entry.via not in _called_names(fn):
        problems.append(f"{where}: does not call {entry.via}")
    routed = route_counts and _is_registered_route(root, entry.path, fn)
    if not (routed or _has_production_caller(root, entry, fn)):
        problems.append(f"{where}: no reachable production caller outside tests")
    return problems


def kind_problems(reason: str, waker: Waker) -> list[str]:
    where = f"{reason} <- {waker.kind} {waker.entry.name}"
    problems: list[str] = []
    status = parked_status(reason)
    accepts = VIA_ACCEPTS.get(waker.entry.via)
    if accepts is None:
        problems.append(f"{where}: {waker.entry.via} has no declared accepted status")
    elif status not in accepts:
        problems.append(
            f"{where}: parks {status.value} but {waker.entry.via} accepts "
            f"{sorted(s.value for s in accepts)}"
        )
    if waker.kind == "answer" and PAUSE_REASON_OWNERS.get(reason) != "human":
        problems.append(f"{where}: answer wakers serve human-owned reasons only")
    if waker.kind == "answer" and not waker.resumed_by:
        problems.append(f"{where}: an answer queues the Run; name what resumes it")
    if waker.kind == "timer" and reason not in TIMER_RESUMABLE_PAUSE_REASONS:
        problems.append(f"{where}: timer wakers serve RESUME_ON_ELAPSED reasons only")
    for follow in waker.resumed_by:
        if RunStatus.QUEUED not in VIA_ACCEPTS.get(follow.via, frozenset()):
            problems.append(f"{where}: {follow.name} does not drain QUEUED Runs")
    return problems


def admitted_kinds(root: pathlib.Path, entry: Entry) -> frozenset[str] | None:
    """The node kinds a Run `entry` selects can hold; None if it takes any Run.

    An entry that hands its canonical API an `eligible=` filter owns only its
    own admission's Runs, whose Graphs that same module builds -- so their
    kinds are the module's `node_type=` arguments. One that acts on a Run by id
    (a route) takes whatever Run it is given, and so does a filtered one whose
    module builds no Graph: it runs registered definitions, whose resolver
    serves every registered kind.
    """
    tree = ast.parse((root / entry.path).read_text(encoding="utf-8"))
    fn = _module_function(tree, entry.name)
    filtered = fn is not None and any(
        isinstance(call, ast.Call)
        and _callee(call) == entry.via
        and any(keyword.arg == "eligible" for keyword in call.keywords)
        for call in ast.walk(fn)
    )
    if not filtered:
        return None
    strings = _module_strings(tree)
    built = frozenset(
        kind
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        for keyword in call.keywords
        if keyword.arg == "node_type" and (kind := _string(keyword.value, strings))
    )
    return built or None


def _reason_names(reason: str) -> frozenset[str]:
    """The reason's value and every `PAUSE_*` constant spelling it."""
    names = {n for n, v in vars(base).items() if n.startswith("PAUSE_") and v == reason}
    return frozenset({reason, *names})


def can_emit(root: pathlib.Path, kind: str, reason: str) -> bool:
    """Whether a module defining a `kind` node names `reason` at all.

    Deliberately coarse: a node that pauses through a helper in another module
    reads as unable to, which fails closed -- the reason stays ledgered until
    someone looks.
    """
    names = _reason_names(reason)
    for path in _index(root).kind_modules.get(kind, ()):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                (isinstance(node, ast.Name) and node.id in names)
                or (isinstance(node, ast.Attribute) and node.attr in names)
                or (isinstance(node, ast.Constant) and node.value == reason)
            ):
                return True
    return False


def admission_problems(root: pathlib.Path, reason: str, waker: Waker) -> list[str]:
    """Whatever runs the Run again must be able to select one holding `reason`."""
    runners = waker.resumed_by or (waker.entry,)
    owned: set[str] = set()
    for runner in runners:
        kinds = admitted_kinds(root, runner)
        if kinds is None or any(can_emit(root, kind, reason) for kind in kinds):
            return []
        owned |= kinds
    names = ", ".join(runner.name for runner in runners)
    return [
        f"{reason} <- {waker.kind} {waker.entry.name}: {names} own only "
        f"{sorted(owned)} Runs, none of which can pause on {reason}"
    ]


def mixed_frontier_problems(wakers: Mapping[str, tuple[Waker, ...]]) -> list[str]:
    """A mapped reason parked beside a human pause must still be released.

    The executor parks the whole frontier PAUSED if any member is human, so a
    timer sibling's own tick (WAITING/RUNNING only) cannot reach it; one of the
    pair's wakers must accept the status the frontier actually parks in.
    """
    humans = sorted(r for r in PAUSE_RESUME_CONDITIONS if parked_status(r) is RunStatus.PAUSED)
    problems: list[str] = []
    for reason in sorted(wakers):
        for human in humans:
            if human == reason:
                continue
            status = frontier_status((reason, human))
            specs = (*wakers[reason], *wakers.get(human, ()))
            if not any(status in VIA_ACCEPTS.get(w.entry.via, frozenset()) for w in specs):
                problems.append(
                    f"{reason} beside {human}: parks {status.value}, "
                    "which no waker of either accepts"
                )
    return problems


def waker_problems(root: pathlib.Path, wakers: Mapping[str, tuple[Waker, ...]]) -> list[str]:
    problems: list[str] = []
    route_counts: dict[Entry, bool] = {}
    for reason, specs in wakers.items():
        for waker in specs:
            problems.extend(kind_problems(reason, waker))
            problems.extend(admission_problems(root, reason, waker))
            ticked = waker.kind in TICK_KINDS
            route_counts[waker.entry] = route_counts.get(waker.entry, True) and not ticked
            for follow in waker.resumed_by:
                route_counts[follow] = False
    for entry in sorted(route_counts, key=lambda e: (e.path, e.name)):
        problems.extend(entry_problems(root, entry, route_counts=route_counts[entry]))
    return problems


# -- the architecture test ---------------------------------------------------


def test_every_pause_reason_has_a_waker_or_a_ledgered_gap() -> None:
    assert coverage_problems(PAUSE_RESUME_CONDITIONS, PAUSE_REASON_WAKERS, UNWOKEN) == []


def test_every_waker_is_reachable_and_accepts_the_parked_status() -> None:
    assert waker_problems(REPO_ROOT, PAUSE_REASON_WAKERS) == []


def test_every_mixed_human_frontier_is_released() -> None:
    assert mixed_frontier_problems(PAUSE_REASON_WAKERS) == []


def test_every_ledgered_gap_cites_its_issue() -> None:
    assert all(issue.startswith("#") for issue in UNWOKEN.values())


# -- the checks fail when they should ------------------------------------------


def test_a_reason_without_a_waker_or_ledger_entry_fails() -> None:
    ledger = {k: v for k, v in UNWOKEN.items() if k != PAUSE_AWAITING_REMOTE_DELEGATION}

    problems = coverage_problems(PAUSE_RESUME_CONDITIONS, PAUSE_REASON_WAKERS, ledger)

    assert problems == [
        f"{PAUSE_AWAITING_REMOTE_DELEGATION}: no reachable production waker "
        "and not in the UNWOKEN ledger"
    ]


def test_a_new_resumable_reason_fails_until_it_is_mapped() -> None:
    conditions = {**PAUSE_RESUME_CONDITIONS, "awaiting_new_thing": base.RESUME_ON_ANSWER}

    problems = coverage_problems(conditions, PAUSE_REASON_WAKERS, UNWOKEN)

    assert any("awaiting_new_thing: no reachable production waker" in p for p in problems)


def test_a_deleted_waker_entry_fails() -> None:
    wakers = {k: v for k, v in PAUSE_REASON_WAKERS.items() if k != PAUSE_AWAITING_HUMAN_REVIEW}

    assert coverage_problems(PAUSE_RESUME_CONDITIONS, wakers, UNWOKEN)


def test_a_ledgered_reason_that_gains_a_waker_fails() -> None:
    wakers = {**PAUSE_REASON_WAKERS, PAUSE_AWAITING_HARNESS: _TIMER_WAKERS}

    problems = coverage_problems(PAUSE_RESUME_CONDITIONS, wakers, UNWOKEN)

    assert f"{PAUSE_AWAITING_HARNESS}: has a waker, so remove it from the UNWOKEN ledger" in (
        problems
    )


def test_the_hitl_answer_path_cannot_wake_a_waiting_delegation() -> None:
    problems = kind_problems(PAUSE_AWAITING_REMOTE_DELEGATION, _HITL_ANSWER)

    assert any("parks waiting but submit_hitl_answer accepts ['paused']" in p for p in problems)
    assert any("human-owned reasons only" in p for p in problems)


def test_a_timer_cannot_wake_an_answer_gated_reason() -> None:
    problems = kind_problems(PAUSE_AWAITING_HUMAN_ANSWER, _TIMER_WAKERS[0])

    assert any("RESUME_ON_ELAPSED reasons only" in p for p in problems)
    assert any("parks paused" in p for p in problems)


def _tree(tmp_path: pathlib.Path, files: Mapping[str, str]) -> pathlib.Path:
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path


def test_a_waker_only_tests_call_is_unreachable(tmp_path: pathlib.Path) -> None:
    root = _tree(
        tmp_path / "unwired",
        {
            "packages/pkg/src/pkg/waker.py": "def wake():\n    resume_due_graph_runs()\n",
            "packages/pkg/tests/test_waker.py": "from pkg.waker import wake\nwake()\n",
            "packages/hive-conductor/backend/tests/test_x.py": "wake()\n",
        },
    )
    entry = Entry("packages/pkg/src/pkg/waker.py", "wake", "resume_due_graph_runs")

    assert entry_problems(root, entry) == [
        "packages/pkg/src/pkg/waker.py:wake: no reachable production caller outside tests"
    ]

    wired = _tree(
        tmp_path / "wired",
        {
            "packages/pkg/src/pkg/waker.py": "def wake():\n    resume_due_graph_runs()\n",
            "packages/pkg/src/pkg/tick.py": "async def tick():\n    await wake()\n",
        },
    )
    assert entry_problems(wired, entry) == []


def test_a_renamed_entrypoint_fails(tmp_path: pathlib.Path) -> None:
    source = (REPO_ROOT / _HITL_ROUTES).read_text(encoding="utf-8")
    root = _tree(
        tmp_path,
        {_HITL_ROUTES: source.replace("def answer_human_work(", "def answer_human_work_v2(")},
    )

    assert entry_problems(root, _HITL_ANSWER.entry) == [
        f"{_HITL_ROUTES}:answer_human_work: no module-level function of that name"
    ]


def test_an_unregistered_route_is_unreachable(tmp_path: pathlib.Path) -> None:
    source = (REPO_ROOT / _HITL_ROUTES).read_text(encoding="utf-8")
    root = _tree(
        tmp_path,
        {_HITL_ROUTES: source, "packages/hive-conductor/backend/main.py": "app = None\n"},
    )

    assert entry_problems(root, _HITL_ANSWER.entry) == [
        f"{_HITL_ROUTES}:answer_human_work: no reachable production caller outside tests"
    ]


def test_a_deadline_only_a_route_reaches_is_not_a_waker() -> None:
    deadline = Waker("deadline", Entry(_HITL_ROUTES, "expire_human_work", "expire_hitl_pauses"))

    problems = waker_problems(REPO_ROOT, {PAUSE_AWAITING_HUMAN_ANSWER: (deadline,)})

    assert problems == [
        f"{_HITL_ROUTES}:expire_human_work: no reachable production caller outside tests"
    ]


def test_an_entrypoint_that_skips_its_canonical_api_fails() -> None:
    entry = replace(_HITL_ANSWER.entry, via="resume_due_graph_runs")

    assert entry_problems(REPO_ROOT, entry) == [
        f"{_HITL_ROUTES}:answer_human_work: does not call resume_due_graph_runs"
    ]


def test_the_legacy_due_ticks_own_no_run_that_can_emit_a_timer_reason() -> None:
    wakers = {PAUSE_WAITING_ON_JIRA_SUBTASKS: _LEGACY_TIMER_WAKERS}

    assert waker_problems(REPO_ROOT, wakers) == [
        f"{PAUSE_WAITING_ON_JIRA_SUBTASKS} <- timer wake_due_dag_runs: wake_due_dag_runs "
        f"own only ['hive.legacy_node'] Runs, none of which can pause on "
        f"{PAUSE_WAITING_ON_JIRA_SUBTASKS}",
        f"{PAUSE_WAITING_ON_JIRA_SUBTASKS} <- timer wake_due_evolution_runs: "
        f"wake_due_evolution_runs own only {sorted(_EVOLVE_KINDS)} Runs, none of which "
        f"can pause on {PAUSE_WAITING_ON_JIRA_SUBTASKS}",
    ]


def test_an_answer_only_legacy_drains_resume_is_not_a_waker() -> None:
    """Reachable, calls its API, accepts PAUSED -- and still not a waker."""
    answer = replace(_HITL_ANSWER, resumed_by=_LEGACY_QUEUED_RECOVERY)

    problems = waker_problems(REPO_ROOT, {PAUSE_AWAITING_HUMAN_ANSWER: (answer,)})

    assert problems == [
        f"{PAUSE_AWAITING_HUMAN_ANSWER} <- answer answer_human_work: "
        "recover_stranded_dag_runs, recover_stranded_evolution_runs own only "
        f"{sorted({'hive.legacy_node', *_EVOLVE_KINDS})} Runs, none of which can pause "
        f"on {PAUSE_AWAITING_HUMAN_ANSWER}"
    ]


def test_a_tick_owning_a_node_that_emits_the_reason_is_a_waker(tmp_path: pathlib.Path) -> None:
    root = _tree(
        tmp_path,
        {
            "packages/pkg/src/pkg/tick.py": (
                '_KIND = "pkg.wait"\n'
                "def build():\n"
                "    return Node(node_type=_KIND)\n"
                "def wake():\n"
                "    resume_due_graph_runs(eligible=lambda run: True)\n"
                "def loop():\n"
                "    wake()\n"
            ),
            "packages/pkg/src/pkg/wait.py": (
                "class Wait:\n"
                '    kind: ClassVar[str] = "pkg.wait"\n'
                "    def run(self):\n"
                "        pause_until(PAUSE_WAITING_ON_JIRA_SUBTASKS)\n"
            ),
            "packages/pkg/src/pkg/other.py": (
                'class Other:\n    kind: ClassVar[str] = "pkg.other"\n'
            ),
        },
    )
    waker = Waker("timer", Entry("packages/pkg/src/pkg/tick.py", "wake", "resume_due_graph_runs"))

    assert admitted_kinds(root, waker.entry) == {"pkg.wait"}
    assert waker_problems(root, {PAUSE_WAITING_ON_JIRA_SUBTASKS: (waker,)}) == []
    assert not can_emit(root, "pkg.other", PAUSE_WAITING_ON_JIRA_SUBTASKS)


def test_a_route_acting_by_run_id_takes_any_admission() -> None:
    assert admitted_kinds(REPO_ROOT, _HITL_CANCEL.entry) is None
    assert admitted_kinds(REPO_ROOT, _HITL_ANSWER.entry) is None


def test_a_tick_handed_to_its_loop_by_reference_is_reachable(tmp_path: pathlib.Path) -> None:
    root = _tree(
        tmp_path,
        {
            "packages/pkg/src/pkg/waker.py": "def wake():\n    resume_due_graph_runs()\n",
            "packages/pkg/src/pkg/loop.py": "async def run():\n    await tick('w', half=wake)\n",
        },
    )
    entry = Entry("packages/pkg/src/pkg/waker.py", "wake", "resume_due_graph_runs")

    assert entry_problems(root, entry, route_counts=False) == []


def test_a_mixed_frontier_only_its_timer_could_wake_fails() -> None:
    wakers = {PAUSE_WAITING_ON_JIRA_SUBTASKS: _TIMER_WAKERS}

    problems = mixed_frontier_problems(wakers)

    assert (
        f"{PAUSE_WAITING_ON_JIRA_SUBTASKS} beside {PAUSE_AWAITING_HUMAN_ANSWER}: parks paused, "
        "which no waker of either accepts"
    ) in problems
    assert mixed_frontier_problems({**wakers, PAUSE_AWAITING_HUMAN_ANSWER: _HUMAN_WAKERS}) == [
        p for p in problems if PAUSE_AWAITING_HUMAN_ANSWER not in p
    ]


# -- VIA_ACCEPTS is pinned to the shipped APIs, not asserted -------------------


def _waiting_delegation_record() -> DurableRunRecord:
    return durable_record(
        {"id": "delegate", "nodes": [{"id": "d", "kind": "agent.delegate_remote"}], "edges": []},
        run_id="run-1192",
        status=RunStatus.WAITING,
        active_node_id="d",
    )


def test_the_hitl_answer_api_refuses_a_waiting_run() -> None:
    with pytest.raises(ValueError, match="not paused"):
        answer_record(_waiting_delegation_record(), "d", {"ok": True})


def test_hitl_timeout_refuses_a_waiting_run() -> None:
    with pytest.raises(ValueError, match="not paused"):
        settle_hitl_record(_waiting_delegation_record(), "d", "timed_out")


def test_hitl_cancel_refuses_a_waiting_run() -> None:
    with pytest.raises(ValueError, match="not paused"):
        settle_hitl_record(_waiting_delegation_record(), "d", "cancelled")


def test_timed_resume_accepts_exactly_its_declared_statuses() -> None:
    assert VIA_ACCEPTS["resume_due_graph_runs"] == recovery._RESUME_ELIGIBLE_STATUSES
    assert RunStatus.PAUSED not in recovery._RESUME_ELIGIBLE_STATUSES


def test_parked_status_follows_the_executor() -> None:
    assert parked_status(PAUSE_AWAITING_HUMAN_ANSWER) is RunStatus.PAUSED
    assert parked_status(PAUSE_AWAITING_REMOTE_DELEGATION) is RunStatus.WAITING


def test_the_due_ticks_admit_exactly_their_own_node_kinds() -> None:
    """Pins what `admitted_kinds` reads from the shipped ticks' modules."""
    legacy = ({"hive.legacy_node"}, _EVOLVE_KINDS)
    for tick, kinds in zip(_LEGACY_TIMER_WAKERS, legacy, strict=True):
        assert admitted_kinds(REPO_ROOT, tick.entry) == kinds
    for drain, kinds in zip(_LEGACY_QUEUED_RECOVERY, legacy, strict=True):
        assert admitted_kinds(REPO_ROOT, drain) == kinds
    # Registered-DAG recovery builds no Graph: it runs registered definitions.
    assert admitted_kinds(REPO_ROOT, _TIMER_WAKERS[0].entry) is None
    assert admitted_kinds(REPO_ROOT, _QUEUED_RECOVERY[-1]) is None


def test_can_emit_finds_the_shipped_emitters() -> None:
    assert can_emit(REPO_ROOT, "jira.wait_for_subtasks", PAUSE_WAITING_ON_JIRA_SUBTASKS)
    assert can_emit(REPO_ROOT, "agent.delegate_remote", PAUSE_AWAITING_DELEGATION_RECONCILIATION)
    assert can_emit(REPO_ROOT, "human.ask_question", PAUSE_AWAITING_HUMAN_ANSWER)
    assert not can_emit(REPO_ROOT, "hive.legacy_node", PAUSE_AWAITING_HUMAN_ANSWER)


def test_a_timer_beside_a_human_pause_parks_paused() -> None:
    assert frontier_status((PAUSE_WAITING_ON_JIRA_SUBTASKS,)) is RunStatus.WAITING
    assert (
        frontier_status((PAUSE_WAITING_ON_JIRA_SUBTASKS, PAUSE_AWAITING_HUMAN_ANSWER))
        is RunStatus.PAUSED
    )


_DEADLINE = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _hitl_record(status: RunStatus, *, run_id: str = "hitl") -> DurableRunRecord:
    """A Run at `status` whose only frontier node holds a human pause."""
    node_run = NodeRun(run_id=run_id, node_id="ask", ordinal=1)
    for step in (RunStatus.QUEUED, RunStatus.RUNNING, RunStatus.PAUSED):
        node_run = transition_node_run(node_run, step, at=_DEADLINE - timedelta(hours=1))
    pause = {
        "kind": "hitl",
        "metadata": {"paused_reason": PAUSE_AWAITING_HUMAN_ANSWER, "question": "Ship it?"},
        "resume_at": _DEADLINE.isoformat(),
    }
    return durable_record(
        {"id": "ask", "nodes": [{"id": "ask", "kind": "human.ask_question"}], "edges": []},
        run_id=run_id,
        status=status,
        active_node_id="ask",
        node_runs=(node_run,),
        metadata={
            "initial_inputs": {},
            "hitl_answers": {},
            "pauses": {"ask": pause},
            "pause": pause,
        },
        resume_at=_DEADLINE,
    )


_STATUSES = tuple(RunStatus)


def _accepted_by(settle: Any) -> frozenset[RunStatus]:
    """Statuses whose record gets past `settle`'s parked-status gate."""
    accepted: set[RunStatus] = set()
    for status in _STATUSES:
        try:
            settle(_hitl_record(status))
        except ValueError as exc:
            if "not paused" in str(exc):
                continue
            raise
        accepted.add(status)
    return frozenset(accepted)


def test_the_hitl_answer_api_accepts_exactly_its_declared_statuses() -> None:
    before = _DEADLINE - timedelta(minutes=1)

    accepted = _accepted_by(lambda r: answer_record(r, "ask", {"answer": "yes"}, at=before))

    assert accepted == VIA_ACCEPTS["submit_hitl_answer"]
    answered = answer_record(_hitl_record(RunStatus.PAUSED), "ask", {"answer": "yes"}, at=before)
    assert answered.run.status is RunStatus.QUEUED


def test_hitl_cancel_accepts_exactly_its_declared_statuses() -> None:
    before = _DEADLINE - timedelta(minutes=1)

    accepted = _accepted_by(lambda r: settle_hitl_record(r, "ask", "cancelled", at=before))

    assert accepted == VIA_ACCEPTS["cancel_hitl"]
    cancelled = settle_hitl_record(_hitl_record(RunStatus.PAUSED), "ask", "cancelled", at=before)
    assert cancelled.run.status is RunStatus.CANCELLED


@pytest.mark.asyncio
async def test_hitl_expiry_settles_exactly_its_declared_statuses() -> None:
    store = InMemoryDurableRunStore()
    for status in _STATUSES:
        await store.create(_hitl_record(status, run_id=f"hitl-{status.value}"))

    settled = await expire_hitl_pauses(store, now=_DEADLINE + timedelta(minutes=1))

    assert {r.run_id for r in settled} == {
        f"hitl-{s.value}" for s in VIA_ACCEPTS["expire_hitl_pauses"]
    }
    assert all(r.run.status is RunStatus.TIMED_OUT for r in settled)


class _RunsByStatus:
    """A Run store holding one Run per status, answering status queries."""

    def __init__(self) -> None:
        graph = graph_from_dag(
            {"id": "g", "nodes": [{"id": "n", "kind": "test.node"}], "edges": []},
            workspace_id="test-workspace",
            project_id="test-project",
        )
        self.runs = [run_at_status(graph, run_id=f"run-{s.value}", status=s) for s in _STATUSES]

    async def list_by_status(
        self, status: RunStatus, *, after: object = None, **_: object
    ) -> list[Run]:
        return [] if after is not None else [r for r in self.runs if r.status is status]


@pytest.mark.asyncio
async def test_queued_recovery_drains_exactly_its_declared_statuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resumed: list[str] = []

    async def _resume(run_id: str, **_: object) -> None:
        resumed.append(run_id)

    monkeypatch.setattr(recovery, "resume_durable_graph", _resume)
    run_store: Any = _RunsByStatus()

    await recovery.recover_queued_graph_runs(
        store=InMemoryDurableRunStore(),
        run_store=run_store,
        node_resolver_factory=lambda _run: lambda _node_id, _graph: None,
        eligible=lambda _run: True,
    )

    assert set(resumed) == {f"run-{s.value}" for s in VIA_ACCEPTS["recover_queued_graph_runs"]}
