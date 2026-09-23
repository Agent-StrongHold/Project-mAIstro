"""Every parked Graph pause reason names a reachable production waker (#1192).

`PAUSE_RESUME_CONDITIONS` says what each pause waits *for*; nothing said who
delivers it. `awaiting_remote_delegation` is answer-gated, parks WAITING, and
the only production answer path (`answer_record` behind Hive HITL) accepts
PAUSED alone -- so a dispatched delegation can wait forever and no test fails.

`PAUSE_REASON_WAKERS` below is the missing statement, kept test-local on
purpose: a production registry nobody imports would itself be unreachable
code. Each waker is checked mechanically rather than trusted, within limits:

* the entrypoint exists and has a production caller (a registered route for a
  person's answer or cancel; a call from a non-test tree for anything that must
  fire on its own), so a waker only tests reach does not count. Callers are
  matched by name, one hop deep: a tick loop that is itself never started would
  still pass;
* the entrypoint calls the canonical API it claims to go through, and that
  API's accepted parked status -- pinned behaviourally at the end of this file
  -- matches the status the executor parks the reason in. That is the
  WAITING/PAUSED mismatch expressed as a failing assertion.

`UNWOKEN` is the known-gap ledger. It is strict both ways against the map: a
reason missing from both fails, and a ledgered reason given a waker entry
fails until it leaves the ledger.

Scope: the mapped ticks own only Runs admitted by the legacy Hive DAG adapter
and by Evolve. Runs from other admission sources (scheduled registered DAGs,
the orchestrator, synthesized DAGs) have no production drain for an answered
or elapsed pause until `Container.resume_parked_runs` gets its #62 cadence and
#837 lands registered-DAG recovery.
"""

from __future__ import annotations

import ast
import pathlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from functools import cache

import pytest

import maistro.graph.nodes.base as base
from maistro.graph.durable_runs import recovery
from maistro.graph.durable_runs.executor import _is_human_pause
from maistro.graph.durable_runs.stores import answer_record, settle_hitl_record
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
from maistro.runs.model import RunStatus

from .._canonical_helpers import durable_record

pytestmark = [pytest.mark.contract("behavioral")]

REPO_ROOT = pathlib.Path(base.__file__).resolve().parents[6]

_HITL_ROUTES = "packages/hive-conductor/backend/routes/hitl.py"
_DAG_RUNNER = "packages/hive-conductor/backend/services/canonical_dag_runner.py"
_EVOLUTION = "packages/hive-conductor/backend/services/evolution_graph.py"


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


#: The parked status each canonical API accepts. The HITL rows are pinned by
#: the behavioural tests at the bottom; `resume_due_graph_runs` by equality
#: with its own eligibility set. An answer settles PAUSED -> QUEUED, which is what the
#: queued-recovery seam drains.
VIA_ACCEPTS: dict[str, frozenset[RunStatus]] = {
    "submit_hitl_answer": frozenset({RunStatus.PAUSED}),
    "cancel_hitl": frozenset({RunStatus.PAUSED}),
    "expire_hitl_pauses": frozenset({RunStatus.PAUSED}),
    "resume_due_graph_runs": frozenset({RunStatus.WAITING, RunStatus.RUNNING}),
    "recover_queued_graph_runs": frozenset({RunStatus.QUEUED}),
}

_QUEUED_RECOVERY = (
    Entry(_DAG_RUNNER, "recover_stranded_dag_runs", "recover_queued_graph_runs"),
    Entry(_EVOLUTION, "recover_stranded_evolution_runs", "recover_queued_graph_runs"),
)
_HUMAN_WAKERS = (
    Waker(
        "answer",
        Entry(_HITL_ROUTES, "answer_human_work", "submit_hitl_answer"),
        resumed_by=_QUEUED_RECOVERY,
    ),
    Waker("cancel", Entry(_HITL_ROUTES, "cancel_human_work", "cancel_hitl")),
)
# `expire_human_work` is not listed: it expires HITL deadlines only when
# someone calls `POST /v1/hitl/expire`, and a deadline nobody ticks is not a
# waker (`test_a_deadline_only_a_route_reaches_is_not_a_waker`).
#
# `Container.resume_parked_runs` also re-enters these for consumer-executed
# Runs, but has no production caller until the #62 cadence ticks it.
_TIMER_WAKERS = (
    Waker("timer", Entry(_DAG_RUNNER, "wake_due_dag_runs", "resume_due_graph_runs")),
    Waker("timer", Entry(_EVOLUTION, "wake_due_evolution_runs", "resume_due_graph_runs")),
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


def parked_status(reason: str) -> RunStatus:
    """The status the durable executor parks a Run in for `reason`."""
    human = _is_human_pause(NodeResult(success=True, metadata={"paused_reason": reason}))
    return RunStatus.PAUSED if human else RunStatus.WAITING


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


@cache
def _call_sites(root: pathlib.Path) -> dict[str, tuple[tuple[pathlib.Path, int], ...]]:
    """Callee name -> where it is called. Kept instead of the ASTs themselves,
    which would pin a few hundred MB for the rest of the suite."""
    sites: dict[str, list[tuple[pathlib.Path, int]]] = {}
    for path in _production_files(root):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for call in ast.walk(tree):
            if isinstance(call, ast.Call) and (name := _callee(call)) is not None:
                sites.setdefault(name, []).append((path.resolve(), call.lineno))
    return {name: tuple(where) for name, where in sites.items()}


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
    """A call by name anywhere in a production tree, except inside `fn` itself."""
    own_file = (root / entry.path).resolve()
    first, last = getattr(fn, "lineno", 0), getattr(fn, "end_lineno", 0)
    return any(
        not (path == own_file and first <= line <= (last or first))
        for path, line in _call_sites(root).get(entry.name, ())
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


def waker_problems(root: pathlib.Path, wakers: Mapping[str, tuple[Waker, ...]]) -> list[str]:
    problems: list[str] = []
    route_counts: dict[Entry, bool] = {}
    for reason, specs in wakers.items():
        for waker in specs:
            problems.extend(kind_problems(reason, waker))
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
    problems = kind_problems(PAUSE_AWAITING_REMOTE_DELEGATION, _HUMAN_WAKERS[0])

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

    assert entry_problems(root, _HUMAN_WAKERS[0].entry) == [
        f"{_HITL_ROUTES}:answer_human_work: no module-level function of that name"
    ]


def test_an_unregistered_route_is_unreachable(tmp_path: pathlib.Path) -> None:
    source = (REPO_ROOT / _HITL_ROUTES).read_text(encoding="utf-8")
    root = _tree(
        tmp_path,
        {_HITL_ROUTES: source, "packages/hive-conductor/backend/main.py": "app = None\n"},
    )

    assert entry_problems(root, _HUMAN_WAKERS[0].entry) == [
        f"{_HITL_ROUTES}:answer_human_work: no reachable production caller outside tests"
    ]


def test_a_deadline_only_a_route_reaches_is_not_a_waker() -> None:
    deadline = Waker("deadline", Entry(_HITL_ROUTES, "expire_human_work", "expire_hitl_pauses"))

    problems = waker_problems(REPO_ROOT, {PAUSE_AWAITING_HUMAN_ANSWER: (deadline,)})

    assert problems == [
        f"{_HITL_ROUTES}:expire_human_work: no reachable production caller outside tests"
    ]


def test_an_entrypoint_that_skips_its_canonical_api_fails() -> None:
    entry = replace(_HUMAN_WAKERS[0].entry, via="resume_due_graph_runs")

    assert entry_problems(REPO_ROOT, entry) == [
        f"{_HITL_ROUTES}:answer_human_work: does not call resume_due_graph_runs"
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
