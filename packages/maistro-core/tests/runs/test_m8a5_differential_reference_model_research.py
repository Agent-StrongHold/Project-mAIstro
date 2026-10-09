"""M8-A5 research harness — differential reference-model testing for the
canonical Run/NodeRun/Attempt state machines.

Issue #885 (leaf of epic #880, initiative #879). Hypothesis under study: a
deliberately simple, independent reference model can act as an oracle for a
complex production state machine and expose semantic drift that ordinary
assertions miss.

This module is a RESEARCH ARTIFACT, not product code. Unlike the other M8
harnesses it DOES import ``maistro`` — driving the real implementation is the
experiment; a differential oracle that never touches the implementation under
test would be vacuous. The guardrail reconciliation (M8 guardrails 1-2) is
recorded in ``docs/research/885-differential-reference-model-testing.md``:
the harness is test-side only, is imported by no product module, computes
nothing any authority reads, and its only outputs are assertions inside this
file. Run/NodeRun/Attempt remains the one execution identity
(``scripts/check-execution-lifecycles.py``); this module introduces no second
lifecycle enum, no store, and no scheduler.

Architecture (the experiment the issue prescribes):

- ``ReferenceModel`` is a deliberately simple, synchronous, in-memory oracle
  for the Run/NodeRun/Attempt lifecycle. Its transition tables and
  stamping/cascade/acceptance/lease rules are transcribed from the contract
  prose (``maistro.runs.lifecycle`` docstrings, ADR-082426-a47f/e3ff/f170,
  #43/#48/#230/#233/#241/#1335), not read off the implementation, so semantic
  drift in the implementation diverges from the model instead of being
  reproduced by construction. The transcription judgment calls are recorded
  in the research note — that burden is exactly the maintenance-cost evidence
  question the issue asks.
- ``Executor`` drives the real implementation (``transition_run``,
  ``transition_node_run``, ``transition_attempt``, ``settle_open_node_run``,
  ``check_completion_is_earned``, ``refuse_completion_under_terminal_run``,
  the lease/reclaim helpers) over the same generated operation stream. The
  ``Drift*`` subclasses inject ten hand-written semantic drifts (mutants) to
  measure defect yield against an ordinary-assertion baseline.
- ``run_stream`` is the differential driver: every operation is applied to
  both sides, refusal agreement (including refusal *category*) is compared,
  and after every accepted step the full normalized observable state —
  statuses, driver-clocked timestamps, acceptance projections, lease
  expiries — must match exactly.

The experiment record, measured defect-yield table, and the terminal
GRADUATE / INCUBATE / REJECT / WATCH disposition live in
``docs/research/885-differential-reference-model-testing.md``.
"""

from __future__ import annotations

import ast
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from hypothesis import find, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from maistro.graph import Graph, Node
from maistro.runs import (
    AcceptedNodeOutcome,
    Attempt,
    AttemptResult,
    AttemptStatus,
    ExecutionLease,
    GraphSnapshot,
    InvalidLifecycleTransition,
    NodeRun,
    Run,
    RunStatus,
    transition_attempt,
    transition_node_run,
    transition_run,
)
from maistro.runs.lifecycle import (
    StaleLeaseRenewal,
    UnearnedRunCompletion,
    check_completion_is_earned,
    lease_is_expired,
    reclaim_attempt,
    refuse_completion_under_terminal_run,
    renew_attempt_lease,
    renewed_lease,
    settle_open_node_run,
)
from maistro.runs.model import TERMINAL_ATTEMPT_STATUSES, TERMINAL_RUN_STATUSES
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID

#: Explicit evidence-only contract marker. Asserted by a test so it cannot
#: silently rot; nothing outside this module may treat M8-A5 output as
#: authorization or as a lifecycle definition.
ADVISORY_ONLY = True

T0 = datetime(2026, 10, 7, 12, 0, 0, tzinfo=UTC)

RUN_STATUS_VALUES = (
    "created",
    "queued",
    "running",
    "waiting",
    "paused",
    "completed",
    "failed",
    "cancelled",
    "timed_out",
)
ATTEMPT_STATUS_VALUES = (
    "created",
    "running",
    "completed",
    "failed",
    "cancelled",
    "timed_out",
    "yielded",
)
TERMINAL_RUN_STRINGS = frozenset({"completed", "failed", "cancelled", "timed_out"})
TERMINAL_ATTEMPT_STRINGS = frozenset({"completed", "failed", "cancelled", "timed_out", "yielded"})
ACCEPTABLE_LOGICAL_STRINGS = frozenset({"waiting", "paused", "completed", "failed"})
SUPERSEDING_TARGETS = frozenset({"queued", "running", "cancelled", "timed_out"})
NODE_IDS = ("n0", "n1", "n2", "n3")

LEASE_TTL = timedelta(seconds=5)


# ---------------------------------------------------------------------------
# The reference model — deliberately simple, maistro-free, prose-transcribed
# ---------------------------------------------------------------------------


class ModelRefusal(Exception):
    """The model predicts this operation is illegal."""

    def __init__(self, category: str, node_id: str | None = None) -> None:
        self.category = category
        self.node_id = node_id
        super().__init__(category)


@dataclass
class ModelAttempt:
    ordinal: int
    status: str = "created"
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result: Any = None
    error: str | None = None
    lease_expires_at: datetime | None = None
    lease_holder: str | None = None
    lease_token: str | None = None


@dataclass
class ModelNodeRun:
    node_id: str
    ordinal: int
    status: str = "created"
    started_at: datetime | None = None
    finished_at: datetime | None = None
    updated_at: datetime | None = None
    result: Any = None
    error: str | None = None
    accepted: dict[str, Any] | None = None  # {logical_status, result, error}
    attempts: list[ModelAttempt] = field(default_factory=list)


@dataclass
class ReferenceModel:
    """The oracle: one Run, its NodeRuns, and their Attempts.

    Every rule below was transcribed from the contract prose, not read off
    the implementation. Where the prose is silent the model encodes the
    narrowest defensible reading, and each judgment call is recorded in the
    research note.
    """

    status: str = "created"
    started_at: datetime | None = None
    finished_at: datetime | None = None
    updated_at: datetime | None = None
    result: Any = None
    error: str | None = None
    nodes: dict[str, list[ModelNodeRun]] = field(default_factory=dict)

    # Terminal states are absorbing (a lifecycle table that let a finished
    # record move would stop meaning anything).
    RUN_TABLE: dict[str, frozenset[str]] = field(
        default_factory=lambda: {
            "created": frozenset({"queued", "cancelled"}),
            "queued": frozenset({"running", "cancelled", "timed_out"}),
            "running": frozenset(
                {"waiting", "paused", "completed", "failed", "cancelled", "timed_out"}
            ),
            "waiting": frozenset({"queued", "running", "paused", "cancelled", "timed_out"}),
            "paused": frozenset({"queued", "cancelled", "timed_out"}),
            "completed": frozenset(),
            "failed": frozenset(),
            "cancelled": frozenset(),
            "timed_out": frozenset(),
        }
    )

    ATTEMPT_TABLE: dict[str, frozenset[str]] = field(
        default_factory=lambda: {
            "created": frozenset({"running", "cancelled"}),
            "running": frozenset({"completed", "failed", "cancelled", "timed_out", "yielded"}),
            "completed": frozenset(),
            "failed": frozenset(),
            "cancelled": frozenset(),
            "timed_out": frozenset(),
            "yielded": frozenset(),
        }
    )

    # -- helpers --

    def latest_node_run(self, node_id: str) -> ModelNodeRun | None:
        """The newest NodeRun for a node, by ordinal — the one that counts."""
        runs = self.nodes.get(node_id)
        if not runs:
            return None
        return max(runs, key=lambda item: item.ordinal)

    def latest_attempt(self, node_id: str) -> ModelAttempt | None:
        node_run = self.latest_node_run(node_id)
        if node_run is None or not node_run.attempts:
            return None
        return node_run.attempts[-1]

    # -- operations; each raises ModelRefusal on a predicted-illegal op --

    def add_node(self, node_id: str, at: datetime) -> None:
        runs = self.nodes.setdefault(node_id, [])
        ordinal = max((item.ordinal for item in runs), default=0) + 1
        runs.append(ModelNodeRun(node_id=node_id, ordinal=ordinal, updated_at=at))

    def run_move(self, target: str, *, at: datetime, result: Any = None) -> None:
        if target not in self.RUN_TABLE[self.status]:
            raise ModelRefusal("illegal")
        self.status = target
        self.updated_at = at
        self.result = result
        if target == "running" and self.started_at is None:
            self.started_at = at
        if target in TERMINAL_RUN_STRINGS:
            self.finished_at = at

    def node_move(
        self,
        node_id: str,
        target: str,
        *,
        at: datetime,
        acceptance: bool,
        result: Any = None,
        error: str | None = None,
    ) -> None:
        node_run = self.latest_node_run(node_id)
        if node_run is None:
            raise ModelRefusal("illegal")
        if target not in self.RUN_TABLE[node_run.status]:
            raise ModelRefusal("illegal")
        # A newly successful logical node must name accepted evidence from a
        # physically completed Attempt; absence of acceptance is not evidence.
        if target == "completed" and not acceptance:
            raise ModelRefusal("illegal")
        if acceptance:
            attempt = node_run.attempts[-1] if node_run.attempts else None
            if attempt is None or attempt.status != "completed":
                raise ModelRefusal("illegal")  # nothing physical to accept
            node_run.accepted = {
                "logical_status": target,  # precondition: target acceptable
                "result": attempt.result,
                "error": attempt.error,
            }
            result = attempt.result
            error = attempt.error
        elif (
            node_run.accepted is not None
            and node_run.status in {"waiting", "paused"}
            and target in SUPERSEDING_TARGETS
        ):
            # Superseding a stale acceptance: the record may not claim both.
            node_run.accepted = None
        if node_run.accepted is not None and node_run.accepted["logical_status"] != target:
            # A NodeRun whose status is not its accepted logical disposition
            # is unrepresentable, not merely illegal.
            raise ModelRefusal("unrepresentable")
        node_run.status = target
        node_run.updated_at = at
        node_run.result = result
        node_run.error = error
        if target == "running" and node_run.started_at is None:
            node_run.started_at = at
        if target in TERMINAL_RUN_STRINGS:
            node_run.finished_at = at

    def attempt_new(self, node_id: str, at: datetime) -> None:
        node_run = self.latest_node_run(node_id)
        if node_run is None:
            raise ModelRefusal("illegal")
        node_run.attempts.append(ModelAttempt(ordinal=len(node_run.attempts) + 1))

    def attempt_move(
        self,
        node_id: str,
        target: str,
        *,
        at: datetime,
        result: Any = None,
        error: str | None = None,
    ) -> None:
        attempt = self.latest_attempt(node_id)
        if attempt is None:
            raise ModelRefusal("illegal")
        if target not in self.ATTEMPT_TABLE[attempt.status]:
            raise ModelRefusal("illegal")
        if target == "completed" and self.status in TERMINAL_RUN_STRINGS:
            raise ModelRefusal("illegal")  # no success lands under a terminal Run
        attempt.status = target
        attempt.result = result
        attempt.error = error
        if target == "running" and attempt.started_at is None:
            attempt.started_at = at
        if target in TERMINAL_ATTEMPT_STRINGS:
            attempt.finished_at = at

    def settle_open(self, node_id: str, run_target: str, *, at: datetime) -> None:
        node_run = self.latest_node_run(node_id)
        if node_run is None or run_target not in TERMINAL_RUN_STRINGS:
            raise ModelRefusal("illegal")
        if node_run.status in TERMINAL_RUN_STRINGS:
            raise ModelRefusal("illegal")
        # Every non-terminal status has an edge to cancelled; the cascade
        # names the Run's own outcome in the error.
        self.node_move(
            node_id,
            "cancelled",
            at=at,
            acceptance=False,
            result=None,
            error=f"cancelled because its Run terminalized as {run_target}",
        )

    def check_complete(self) -> None:
        """Success must be earned: only COMPLETED is checked, and a paused
        human wait blocks completion rather than being cascaded away."""
        for node_id in sorted(self.nodes):
            newest = self.latest_node_run(node_id)
            assert newest is not None
            if newest.status == "completed":
                continue
            if newest.status in TERMINAL_RUN_STRINGS or newest.status == "paused":
                raise ModelRefusal("unearned", node_id)

    def lease_new(self, node_id: str, *, at: datetime, holder: str) -> None:
        attempt = self.latest_attempt(node_id)
        if attempt is None:
            raise ModelRefusal("illegal")
        attempt.lease_holder = holder
        attempt.lease_token = f"tok-{attempt.ordinal}"
        attempt.lease_expires_at = at + LEASE_TTL

    def lease_renew(self, node_id: str, *, token: str, at: datetime) -> None:
        attempt = self.latest_attempt(node_id)
        if attempt is None or attempt.lease_token is None:
            raise ModelRefusal("lease")
        if token != attempt.lease_token:
            raise ModelRefusal("lease")
        if attempt.status in TERMINAL_ATTEMPT_STRINGS:
            raise ModelRefusal("illegal")
        if attempt.lease_expires_at is not None and attempt.lease_expires_at <= at:
            raise ModelRefusal("illegal")  # expiry surrenders the lease
        attempt.lease_expires_at = at + LEASE_TTL

    def attempt_lease_expired(self, attempt: ModelAttempt, now: datetime) -> bool:
        if attempt.status in TERMINAL_ATTEMPT_STRINGS:
            return False
        if attempt.lease_expires_at is None:
            return False
        return attempt.lease_expires_at <= now

    def reclaim(self, node_id: str, *, at: datetime) -> None:
        attempt = self.latest_attempt(node_id)
        if attempt is None:
            raise ModelRefusal("illegal")
        if attempt.status in TERMINAL_ATTEMPT_STRINGS:
            raise ModelRefusal("illegal")
        holder = attempt.lease_holder if attempt.lease_holder is not None else "unknown"
        attempt.status = "cancelled"
        attempt.error = (
            f"lease expired; holder {holder!r} stopped renewing before the Attempt finished"
        )
        attempt.finished_at = at

    # -- observation --

    def snapshot(self, now: datetime) -> dict[str, Any]:
        """Normalized observable state, mirroring the real side's shape."""
        return {
            "run": {
                "status": self.status,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "updated_at": self.updated_at,
                "result": self.result,
                "error": self.error,
            },
            "nodes": {
                node_id: [
                    {
                        "ordinal": item.ordinal,
                        "status": item.status,
                        "started_at": item.started_at,
                        "finished_at": item.finished_at,
                        "updated_at": item.updated_at,
                        "result": item.result,
                        "error": item.error,
                        "accepted": None if item.accepted is None else dict(item.accepted),
                        "attempts": [
                            {
                                "ordinal": att.ordinal,
                                "status": att.status,
                                "started_at": att.started_at,
                                "finished_at": att.finished_at,
                                "result": att.result,
                                "error": att.error,
                                "lease_expires_at": att.lease_expires_at,
                                "lease_expired": self.attempt_lease_expired(att, now),
                            }
                            for att in item.attempts
                        ],
                    }
                    for item in sorted(runs, key=lambda item: item.ordinal)
                ]
                for node_id, runs in sorted(self.nodes.items())
            },
        }


# ---------------------------------------------------------------------------
# The real side — one Executor drives maistro.runs.lifecycle
# ---------------------------------------------------------------------------


def _graph() -> Graph:
    return Graph(
        graph_id="graph-1",
        workspace_id="ws",
        project_id="pj",
        name="M8-A5 differential fixture",
        nodes=[Node(node_id=node_id, node_type="agent") for node_id in NODE_IDS],
    )


def _payload(at: datetime) -> dict[str, int]:
    return {"step": at.second + 60 * at.minute}


class Executor:
    """Drives the real lifecycle functions over a generated op stream.

    Every ``op_*`` method touches ONLY the real side; the model is driven
    separately by ``_apply_model`` so the two can disagree. All overridable
    behavior lives on methods, which is what the ``Drift*`` mutants override.
    """

    def __init__(self) -> None:
        self.run = Run(
            workspace_id="ws",
            project_id="pj",
            graph=GraphSnapshot.from_graph(_graph()),
            created_at=T0,
            updated_at=T0,
            actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
        )
        self.node_runs: dict[str, list[NodeRun]] = {}
        self.attempts: dict[str, list[Attempt]] = {}  # by node_run_id
        self.model = ReferenceModel(updated_at=T0)

    # -- state access --

    def latest_node_run(self, node_id: str) -> NodeRun | None:
        runs = self.node_runs.get(node_id)
        if not runs:
            return None
        return max(runs, key=lambda item: item.ordinal)

    def latest_attempt(self, node_id: str) -> Attempt | None:
        node_run = self.latest_node_run(node_id)
        if node_run is None:
            return None
        found = self.attempts.get(node_run.node_run_id, [])
        return found[-1] if found else None

    def _replace_node_run(self, old: NodeRun, new: NodeRun) -> None:
        self.node_runs[old.node_id] = [
            item if item.ordinal != old.ordinal else new for item in self.node_runs[old.node_id]
        ]

    def _replace_attempt(self, old: Attempt, new: Attempt) -> None:
        self.attempts[old.node_run_id] = [
            item if item.ordinal != old.ordinal else new for item in self.attempts[old.node_run_id]
        ]

    # -- the lease-expiry seam (DriftLeaseBoundaryOffByOne overrides this) --

    def lease_expired(self, attempt: Attempt, now: datetime) -> bool:
        return lease_is_expired(attempt, now)

    # -- operations --

    def op_run_move(self, target: str, with_result: bool, at: datetime) -> None:
        payload = _payload(at) if with_result else None
        self.run = transition_run(self.run, RunStatus(target), at=at, result=payload)

    def op_add_node(self, node_id: str, at: datetime) -> None:
        node_run = NodeRun(
            run_id=self.run.run_id,
            node_id=node_id,
            ordinal=max((item.ordinal for item in self.node_runs.get(node_id, [])), default=0) + 1,
            created_at=at,
            updated_at=at,
        )
        self.node_runs.setdefault(node_id, []).append(node_run)

    def op_node_move(self, node_id: str, target: str, acceptance: bool, at: datetime) -> None:
        node_run = self.latest_node_run(node_id)
        assert node_run is not None  # driver precondition
        result: Any = None
        error: str | None = None
        accepted_outcome: AcceptedNodeOutcome | None = None
        if acceptance:
            attempt = self.latest_attempt(node_id)
            assert attempt is not None  # driver precondition
            assert attempt.status is AttemptStatus.COMPLETED
            accepted_outcome = AcceptedNodeOutcome(
                node_run_id=node_run.node_run_id,
                attempt_result=AttemptResult.from_attempt(attempt),
                logical_status=RunStatus(target),
                accepted_at=at,
            )
            result = attempt.result
            error = attempt.error
        moved = transition_node_run(
            node_run,
            RunStatus(target),
            at=at,
            result=result,
            error=error,
            accepted_outcome=accepted_outcome,
        )
        self._replace_node_run(node_run, moved)

    def op_attempt_new(self, node_id: str, at: datetime) -> None:
        node_run = self.latest_node_run(node_id)
        assert node_run is not None
        attempt = Attempt(
            node_run_id=node_run.node_run_id,
            ordinal=len(self.attempts.get(node_run.node_run_id, [])) + 1,
            created_at=at,
        )
        self.attempts.setdefault(node_run.node_run_id, []).append(attempt)

    def op_attempt_move(self, node_id: str, target: str, at: datetime) -> None:
        attempt = self.latest_attempt(node_id)
        assert attempt is not None
        result: Any = None
        if target == "completed":
            # The executor's durable Run fence precedes the success write.
            refuse_completion_under_terminal_run(self.run.status, attempt.attempt_id)
            result = _payload(at)
        moved = transition_attempt(attempt, AttemptStatus(target), at=at, result=result)
        self._replace_attempt(attempt, moved)

    def op_settle_open(self, node_id: str, run_target: str, at: datetime) -> None:
        node_run = self.latest_node_run(node_id)
        assert node_run is not None
        moved = settle_open_node_run(node_run, RunStatus(run_target), at=at)
        self._replace_node_run(node_run, moved)

    def op_check_complete(self, at: datetime) -> None:
        check_completion_is_earned(
            RunStatus.COMPLETED,
            [item for runs in self.node_runs.values() for item in runs],
        )

    def op_lease_new(self, node_id: str, at: datetime) -> None:
        attempt = self.latest_attempt(node_id)
        assert attempt is not None
        assert attempt.execution_lease is None  # driver precondition
        lease = ExecutionLease(
            node_run_id=attempt.node_run_id,
            attempt_id=attempt.attempt_id,
            lease_epoch=1,
            holder=f"worker-{attempt.ordinal}",
            fencing_token=f"tok-{attempt.ordinal}",
            issued_at=at,
            expires_at=at + LEASE_TTL,
        )
        self._replace_attempt(attempt, attempt.model_copy(update={"execution_lease": lease}))

    def op_lease_renew(self, node_id: str, wrong_token: bool, at: datetime) -> None:
        attempt = self.latest_attempt(node_id)
        assert attempt is not None
        token = "intruder"
        if not wrong_token and attempt.execution_lease is not None:
            token = attempt.execution_lease.fencing_token
        renewed = renew_attempt_lease(attempt, fencing_token=token, ttl=LEASE_TTL, at=at)
        self._replace_attempt(attempt, renewed)

    def op_reclaim(self, node_id: str, at: datetime) -> None:
        attempt = self.latest_attempt(node_id)
        assert attempt is not None
        self._replace_attempt(attempt, reclaim_attempt(attempt, at=at))

    # -- observation --

    def snapshot(self, now: datetime) -> dict[str, Any]:
        nodes: dict[str, Any] = {}
        for node_id, runs in self.node_runs.items():
            nodes[node_id] = []
            for item in sorted(runs, key=lambda item: item.ordinal):
                found = self.attempts.get(item.node_run_id, [])
                nodes[node_id].append(
                    {
                        "ordinal": item.ordinal,
                        "status": item.status.value,
                        "started_at": item.started_at,
                        "finished_at": item.finished_at,
                        "updated_at": item.updated_at,
                        "result": item.result,
                        "error": item.error,
                        "accepted": None
                        if item.accepted_outcome is None
                        else {
                            "logical_status": item.accepted_outcome.logical_status.value,
                            "result": item.accepted_outcome.result,
                            "error": item.accepted_outcome.error,
                        },
                        "attempts": [
                            {
                                "ordinal": att.ordinal,
                                "status": att.status.value,
                                "started_at": att.started_at,
                                "finished_at": att.finished_at,
                                "result": att.result,
                                "error": att.error,
                                "lease_expires_at": (
                                    att.execution_lease.expires_at
                                    if att.execution_lease is not None
                                    else None
                                ),
                                "lease_expired": self.lease_expired(att, now),
                            }
                            for att in sorted(found, key=lambda item: item.ordinal)
                        ],
                    }
                )
        return {
            "run": {
                "status": self.run.status.value,
                "started_at": self.run.started_at,
                "finished_at": self.run.finished_at,
                "updated_at": self.run.updated_at,
                "result": self.run.result,
                "error": self.run.error,
            },
            "nodes": {node_id: nodes[node_id] for node_id in sorted(nodes)},
        }


# ---------------------------------------------------------------------------
# The differential driver — one op stream, both sides, compared every step
# ---------------------------------------------------------------------------


def _node_move_applicable(model: ReferenceModel, op: tuple[Any, ...]) -> bool:
    node_run = model.latest_node_run(op[1])
    if node_run is None or node_run.status == "completed":
        return False  # legacy hydration path is out of scope
    if op[3]:  # acceptance requested
        if op[2] not in ACCEPTABLE_LOGICAL_STRINGS:
            return False
        attempt = model.latest_attempt(op[1])
        if attempt is None or attempt.status != "completed":
            return False
    return True


def _model_holder(model: ReferenceModel, node_id: str) -> str:
    attempt = model.latest_attempt(node_id)
    assert attempt is not None
    return f"worker-{attempt.ordinal}"


def _model_token(model: ReferenceModel, node_id: str, wrong_token: bool) -> str:
    if wrong_token:
        return "intruder"
    attempt = model.latest_attempt(node_id)
    assert attempt is not None
    return attempt.lease_token if attempt.lease_token is not None else ""


_APPLICABILITY: dict[str, Callable[[ReferenceModel, tuple[Any, ...]], bool]] = {
    "node_move": _node_move_applicable,
    "attempt_new": lambda model, op: model.latest_node_run(op[1]) is not None,
    "attempt_move": lambda model, op: model.latest_attempt(op[1]) is not None,
    "settle_open": lambda model, op: model.latest_node_run(op[1]) is not None,
    "lease_new": lambda model, op: (
        (attempt := model.latest_attempt(op[1])) is not None and attempt.lease_token is None
    ),
    "lease_renew": lambda model, op: model.latest_attempt(op[1]) is not None,
    "reclaim": lambda model, op: model.latest_attempt(op[1]) is not None,
}


def applicable(model: ReferenceModel, op: tuple[Any, ...]) -> bool:
    """Driver preconditions, evaluated on the model's state only.

    These are construction constraints of the *driver* (an acceptance can
    only be built from a physically completed Attempt), not lifecycle rules:
    lifecycle rules are exactly what the differential comparison tests, so
    they must never be smuggled in here.
    """
    predicate = _APPLICABILITY.get(op[0])
    return predicate(model, op) if predicate is not None else True


_REAL_DISPATCH: dict[str, Callable[[Executor, tuple[Any, ...], datetime], None]] = {
    "run_move": lambda executor, op, at: executor.op_run_move(op[1], op[2], at),
    "add_node": lambda executor, op, at: executor.op_add_node(op[1], at),
    "node_move": lambda executor, op, at: executor.op_node_move(op[1], op[2], op[3], at),
    "attempt_new": lambda executor, op, at: executor.op_attempt_new(op[1], at),
    "attempt_move": lambda executor, op, at: executor.op_attempt_move(op[1], op[2], at),
    "settle_open": lambda executor, op, at: executor.op_settle_open(op[1], op[2], at),
    "check_complete": lambda executor, op, at: executor.op_check_complete(at),
    "lease_new": lambda executor, op, at: executor.op_lease_new(op[1], at),
    "lease_renew": lambda executor, op, at: executor.op_lease_renew(op[1], op[2], at),
    "reclaim": lambda executor, op, at: executor.op_reclaim(op[1], at),
}

_MODEL_DISPATCH: dict[str, Callable[[ReferenceModel, tuple[Any, ...], datetime], None]] = {
    "run_move": lambda model, op, at: model.run_move(
        op[1], at=at, result=_payload(at) if op[2] else None
    ),
    "add_node": lambda model, op, at: model.add_node(op[1], at=at),
    "node_move": lambda model, op, at: model.node_move(op[1], op[2], at=at, acceptance=op[3]),
    "attempt_new": lambda model, op, at: model.attempt_new(op[1], at=at),
    "attempt_move": lambda model, op, at: model.attempt_move(
        op[1], op[2], at=at, result=_payload(at) if op[2] == "completed" else None
    ),
    "settle_open": lambda model, op, at: model.settle_open(op[1], op[2], at=at),
    "check_complete": lambda model, op, at: model.check_complete(),
    "lease_new": lambda model, op, at: model.lease_new(
        op[1], at=at, holder=_model_holder(model, op[1])
    ),
    "lease_renew": lambda model, op, at: model.lease_renew(
        op[1], token=_model_token(model, op[1], op[2]), at=at
    ),
    "reclaim": lambda model, op, at: model.reclaim(op[1], at=at),
}


def _apply_real(executor: Executor, op: tuple[Any, ...], at: datetime) -> None:
    _REAL_DISPATCH[op[0]](executor, op, at)


def _apply_model(model: ReferenceModel, op: tuple[Any, ...], at: datetime) -> None:
    _MODEL_DISPATCH[op[0]](model, op, at)


def _exception_category(exc: BaseException) -> str:
    if isinstance(exc, ModelRefusal):
        return exc.category
    if isinstance(exc, UnearnedRunCompletion):
        return "unearned"
    if isinstance(exc, StaleLeaseRenewal):
        return "lease"
    if isinstance(exc, InvalidLifecycleTransition):
        return "illegal"
    if isinstance(exc, ValidationError):
        return "unrepresentable"
    return "other"


def run_stream(ops: list[tuple[Any, ...]], executor: Executor | None = None) -> list[str]:
    """Drive one op stream against both sides; return divergence records.

    Agreement per step is: both accept (and then the full normalized
    snapshots must match exactly), or both refuse with the same category.
    The driver owns one logical clock so timestamps compare exactly — the
    first normalization boundary recorded in the research note.
    """
    executor = executor if executor is not None else Executor()
    divergences: list[str] = []
    clock = T0
    for index, op in enumerate(ops):
        real_error: BaseException | None = None
        model_error: BaseException | None = None
        if op[0] != "tick":
            if not applicable(executor.model, op):
                continue
            try:
                _apply_real(executor, op, clock)
            except Exception as exc:  # the refusal IS the observation
                real_error = exc
            try:
                _apply_model(executor.model, op, clock)
            except Exception as exc:  # the refusal IS the observation
                model_error = exc
            if (real_error is None) != (model_error is None):
                refused = "real" if real_error is not None else "model"
                category = _exception_category(real_error or model_error)
                divergences.append(
                    f"step {index} op {op!r}: {refused} refused ({category}), "
                    f"{'model' if refused == 'real' else 'real'} accepted"
                )
                continue
            if real_error is not None:
                real_category = _exception_category(real_error)
                model_category = _exception_category(model_error)
                assert model_error is not None
                if real_category != model_category:
                    divergences.append(
                        f"step {index} op {op!r}: refusal categories differ: "
                        f"real={real_category} model={model_category}"
                    )
                continue
        else:
            clock = clock + timedelta(seconds=op[1])
        expected = executor.model.snapshot(clock)
        actual = executor.snapshot(clock)
        if expected != actual:
            divergences.append(f"step {index} op {op!r}: normalized state diverged")
    return divergences


# ---------------------------------------------------------------------------
# Operation-stream generation: one Hypothesis strategy, one seeded corpus
# ---------------------------------------------------------------------------

_NODE = st.sampled_from(NODE_IDS)
_TERMINAL_RUN_TARGETS = [s for s in RUN_STATUS_VALUES if s in TERMINAL_RUN_STRINGS]

OP = st.one_of(
    st.tuples(st.just("run_move"), st.sampled_from(RUN_STATUS_VALUES), st.booleans()),
    st.tuples(st.just("add_node"), _NODE),
    st.tuples(st.just("node_move"), _NODE, st.sampled_from(RUN_STATUS_VALUES), st.booleans()),
    st.tuples(st.just("attempt_new"), _NODE),
    st.tuples(st.just("attempt_move"), _NODE, st.sampled_from(ATTEMPT_STATUS_VALUES)),
    st.tuples(st.just("settle_open"), _NODE, st.sampled_from(_TERMINAL_RUN_TARGETS)),
    st.just(("check_complete",)),
    st.tuples(st.just("lease_new"), _NODE),
    st.tuples(st.just("lease_renew"), _NODE, st.booleans()),
    st.tuples(st.just("reclaim"), _NODE),
    st.tuples(st.just("tick"), st.integers(min_value=1, max_value=3)),
)

OP_STREAMS = st.lists(OP, max_size=16)


def corpus_stream(seed: int, length: int = 18) -> list[tuple[Any, ...]]:
    """The deterministic corpus the defect-yield comparison replays."""
    rng = random.Random(seed)
    factories: tuple[Callable[[], tuple[Any, ...]], ...] = (
        lambda: ("add_node", rng.choice(NODE_IDS)),
        lambda: ("run_move", rng.choice(RUN_STATUS_VALUES), rng.random() < 0.3),
        lambda: (
            "node_move",
            rng.choice(NODE_IDS),
            rng.choice(RUN_STATUS_VALUES),
            rng.random() < 0.5,
        ),
        lambda: ("attempt_new", rng.choice(NODE_IDS)),
        lambda: ("attempt_move", rng.choice(NODE_IDS), rng.choice(ATTEMPT_STATUS_VALUES)),
        lambda: ("settle_open", rng.choice(NODE_IDS), rng.choice(_TERMINAL_RUN_TARGETS)),
        lambda: ("check_complete",),
        lambda: ("lease_new", rng.choice(NODE_IDS)),
        lambda: ("lease_renew", rng.choice(NODE_IDS), rng.random() < 0.3),
        lambda: ("reclaim", rng.choice(NODE_IDS)),
        lambda: ("tick", rng.randint(1, 3)),
    )
    weights = (14, 10, 20, 10, 10, 6, 8, 6, 6, 6, 4)
    return [rng.choices(factories, weights)[0]() for _ in range(length)]


CORPUS: list[list[tuple[Any, ...]]] = [corpus_stream(seed) for seed in range(32)]


# ---------------------------------------------------------------------------
# Injected drift — ten hand-written semantic mutants of the real seam
# ---------------------------------------------------------------------------
#
# Each mutant emulates one plausible implementation drift by overriding the
# Executor seam it would live behind. Each has a minimal probe stream where
# the unmutated implementation agrees with the model and the mutant does not
# (asserted non-vacuously by the tests below).


def _force_run_move(run: Run, target: str, *, at: datetime, result: Any) -> Run:
    update: dict[str, Any] = {"status": RunStatus(target), "updated_at": at, "result": result}
    if target == "running" and run.started_at is None:
        update["started_at"] = at
    if target in TERMINAL_RUN_STATUSES:
        update["finished_at"] = at
    return run.model_copy(update=update)


def _force_node_move(
    node_run: NodeRun, target: str, *, at: datetime, result: Any, error: str | None
) -> NodeRun:
    update: dict[str, Any] = {
        "status": RunStatus(target),
        "updated_at": at,
        "result": result,
        "error": error,
    }
    if target == "running" and node_run.started_at is None:
        update["started_at"] = at
    if target in TERMINAL_RUN_STATUSES:
        update["finished_at"] = at
    return node_run.model_copy(update=update)


class DriftTerminalPermissive(Executor):
    """M1: terminal states lost their absorbing edges."""

    id = "M1-terminal-absorbing-edges-lost"

    def op_run_move(self, target: str, with_result: bool, at: datetime) -> None:
        try:
            super().op_run_move(target, with_result, at)
        except InvalidLifecycleTransition:
            self.run = _force_run_move(
                self.run, target, at=at, result=_payload(at) if with_result else None
            )

    def op_node_move(self, node_id: str, target: str, acceptance: bool, at: datetime) -> None:
        node_run = self.latest_node_run(node_id)
        assert node_run is not None
        try:
            super().op_node_move(node_id, target, acceptance, at)
        except InvalidLifecycleTransition:
            self._replace_node_run(
                node_run, _force_node_move(node_run, target, at=at, result=None, error=None)
            )

    def op_attempt_move(self, node_id: str, target: str, at: datetime) -> None:
        attempt = self.latest_attempt(node_id)
        assert attempt is not None
        try:
            super().op_attempt_move(node_id, target, at)
        except InvalidLifecycleTransition:
            self._replace_attempt(
                attempt,
                attempt.model_copy(update={"status": AttemptStatus(target), "finished_at": at}),
            )


class DriftEvidencelessCompletion(Executor):
    """M2: a Run/NodeRun can complete without accepted evidence."""

    id = "M2-completion-without-acceptance"

    def op_node_move(self, node_id: str, target: str, acceptance: bool, at: datetime) -> None:
        if target == "completed" and not acceptance:
            node_run = self.latest_node_run(node_id)
            assert node_run is not None
            self._replace_node_run(
                node_run, _force_node_move(node_run, target, at=at, result=None, error=None)
            )
            return
        super().op_node_move(node_id, target, acceptance, at)


class DriftStaleAcceptanceKept(Executor):
    """M3: superseded acceptance survives a resumption."""

    id = "M3-stale-acceptance-not-superseded"

    def op_node_move(self, node_id: str, target: str, acceptance: bool, at: datetime) -> None:
        node_run = self.latest_node_run(node_id)
        assert node_run is not None
        kept = node_run.accepted_outcome
        super().op_node_move(node_id, target, acceptance, at)
        moved = self.latest_node_run(node_id)
        assert moved is not None
        if (
            kept is not None
            and moved.accepted_outcome is None
            and kept.logical_status.value in {"waiting", "paused"}
            and target in SUPERSEDING_TARGETS
        ):
            self._replace_node_run(moved, moved.model_copy(update={"accepted_outcome": kept}))


class DriftOldestNodeRunWins(Executor):
    """M4: completion consults the oldest NodeRun per node, not the newest."""

    id = "M4-oldest-node-run-counts"

    def op_check_complete(self, at: datetime) -> None:
        oldest: dict[str, NodeRun] = {}
        for item in (r for runs in self.node_runs.values() for r in runs):
            current = oldest.get(item.node_id)
            if current is None or item.ordinal < current.ordinal:
                oldest[item.node_id] = item
        check_completion_is_earned(RunStatus.COMPLETED, list(oldest.values()))


class DriftPausedCascadeAllowed(Executor):
    """M5: a paused human wait no longer blocks completion (#48 regression)."""

    id = "M5-paused-node-cascadable"

    def op_check_complete(self, at: datetime) -> None:
        try:
            super().op_check_complete(at)
        except UnearnedRunCompletion as exc:
            latest = self.latest_node_run(exc.node_id)
            if latest is not None and latest.status is RunStatus.PAUSED:
                return  # drift: paused treated like an open, cascadable node
            raise


class DriftLeaseBoundaryOffByOne(Executor):
    """M6: lease expiry compares strictly instead of at the boundary."""

    id = "M6-lease-expiry-off-by-one"

    def lease_expired(self, attempt: Attempt, now: datetime) -> bool:
        lease = attempt.execution_lease
        if attempt.status in TERMINAL_ATTEMPT_STATUSES:
            return False
        if lease is None or lease.expires_at is None:
            return False
        return lease.expires_at < now


class DriftExpiredLeaseRenewable(Executor):
    """M7: an expired lease can be resurrected with its old token."""

    id = "M7-expired-lease-renewable"

    def op_lease_renew(self, node_id: str, wrong_token: bool, at: datetime) -> None:
        attempt = self.latest_attempt(node_id)
        assert attempt is not None
        lease = attempt.execution_lease
        if (
            not wrong_token
            and lease is not None
            and lease.expires_at is not None
            and lease.expires_at <= at
            and attempt.status not in TERMINAL_ATTEMPT_STATUSES
        ):
            self._replace_attempt(
                attempt,
                attempt.model_copy(
                    update={"execution_lease": renewed_lease(lease, at=at, ttl=LEASE_TTL)}
                ),
            )
            return
        super().op_lease_renew(node_id, wrong_token, at)


class DriftStartRestampedOnResume(Executor):
    """M8: re-entering RUNNING overwrites the original start timestamp."""

    id = "M8-started-at-overwritten-on-resume"

    def op_run_move(self, target: str, with_result: bool, at: datetime) -> None:
        super().op_run_move(target, with_result, at)
        if target == "running":
            self.run = self.run.model_copy(update={"started_at": at})

    def op_node_move(self, node_id: str, target: str, acceptance: bool, at: datetime) -> None:
        super().op_node_move(node_id, target, acceptance, at)
        if target == "running":
            node_run = self.latest_node_run(node_id)
            assert node_run is not None
            self._replace_node_run(node_run, node_run.model_copy(update={"started_at": at}))

    def op_attempt_move(self, node_id: str, target: str, at: datetime) -> None:
        super().op_attempt_move(node_id, target, at)
        if target == "running":
            attempt = self.latest_attempt(node_id)
            assert attempt is not None
            self._replace_attempt(attempt, attempt.model_copy(update={"started_at": at}))


class DriftReclaimAnonymized(Executor):
    """M9: a reclaimed Attempt no longer names the holder that went quiet."""

    id = "M9-reclaim-error-anonymized"

    def op_reclaim(self, node_id: str, at: datetime) -> None:
        attempt = self.latest_attempt(node_id)
        assert attempt is not None
        self._replace_attempt(
            attempt,
            transition_attempt(
                attempt, AttemptStatus.CANCELLED, at=at, error="cancelled by recovery"
            ),
        )


class DriftCascadeAnonymized(Executor):
    """M10: a cascaded NodeRun no longer names the Run's own outcome."""

    id = "M10-cascade-error-anonymized"

    def op_settle_open(self, node_id: str, run_target: str, at: datetime) -> None:
        node_run = self.latest_node_run(node_id)
        assert node_run is not None
        self._replace_node_run(
            node_run,
            transition_node_run(node_run, RunStatus.CANCELLED, at=at, error="cancelled"),
        )


MUTANTS: list[type[Executor]] = [
    DriftTerminalPermissive,
    DriftEvidencelessCompletion,
    DriftStaleAcceptanceKept,
    DriftOldestNodeRunWins,
    DriftPausedCascadeAllowed,
    DriftLeaseBoundaryOffByOne,
    DriftExpiredLeaseRenewable,
    DriftStartRestampedOnResume,
    DriftReclaimAnonymized,
    DriftCascadeAnonymized,
]


PROBES: dict[str, list[tuple[Any, ...]]] = {
    "M1-terminal-absorbing-edges-lost": [
        ("tick", 1),
        ("run_move", "queued", False),
        ("tick", 1),
        ("run_move", "running", False),
        ("tick", 1),
        ("run_move", "completed", True),
        ("run_move", "failed", False),
    ],
    "M2-completion-without-acceptance": [
        ("add_node", "n0"),
        ("node_move", "n0", "queued", False),
        ("attempt_new", "n0"),
        ("attempt_move", "n0", "running"),
        ("attempt_move", "n0", "completed"),
        ("node_move", "n0", "completed", False),
    ],
    "M3-stale-acceptance-not-superseded": [
        ("add_node", "n0"),
        ("node_move", "n0", "queued", False),
        ("node_move", "n0", "running", False),
        ("attempt_new", "n0"),
        ("attempt_move", "n0", "running"),
        ("attempt_move", "n0", "completed"),
        ("node_move", "n0", "waiting", True),
        ("node_move", "n0", "queued", False),
    ],
    "M4-oldest-node-run-counts": [
        ("add_node", "n0"),
        ("node_move", "n0", "queued", False),
        ("node_move", "n0", "running", False),
        ("node_move", "n0", "failed", False),
        ("add_node", "n0"),
        ("node_move", "n0", "queued", False),
        ("node_move", "n0", "running", False),
        ("attempt_new", "n0"),
        ("attempt_move", "n0", "running"),
        ("attempt_move", "n0", "completed"),
        ("node_move", "n0", "completed", True),
        ("check_complete",),
    ],
    "M5-paused-node-cascadable": [
        ("add_node", "n0"),
        ("node_move", "n0", "queued", False),
        ("node_move", "n0", "running", False),
        ("node_move", "n0", "paused", False),
        ("check_complete",),
    ],
    "M6-lease-expiry-off-by-one": [
        ("add_node", "n0"),
        ("node_move", "n0", "queued", False),
        ("attempt_new", "n0"),
        ("attempt_move", "n0", "running"),
        ("lease_new", "n0"),
        ("tick", 5),
    ],
    "M7-expired-lease-renewable": [
        ("add_node", "n0"),
        ("node_move", "n0", "queued", False),
        ("attempt_new", "n0"),
        ("attempt_move", "n0", "running"),
        ("lease_new", "n0"),
        ("tick", 6),
        ("lease_renew", "n0", False),
    ],
    "M8-started-at-overwritten-on-resume": [
        ("add_node", "n0"),
        ("node_move", "n0", "queued", False),
        ("tick", 1),
        ("node_move", "n0", "running", False),
        ("tick", 1),
        ("node_move", "n0", "waiting", False),
        ("tick", 1),
        ("node_move", "n0", "running", False),
    ],
    "M9-reclaim-error-anonymized": [
        ("add_node", "n0"),
        ("node_move", "n0", "queued", False),
        ("attempt_new", "n0"),
        ("attempt_move", "n0", "running"),
        ("reclaim", "n0"),
    ],
    "M10-cascade-error-anonymized": [
        ("add_node", "n0"),
        ("node_move", "n0", "queued", False),
        ("settle_open", "n0", "failed"),
    ],
}

assert set(PROBES) == {mutant.id for mutant in MUTANTS}


# ---------------------------------------------------------------------------
# The ordinary-assertion baseline — existing-suite-style point assertions
# ---------------------------------------------------------------------------
#
# Deliberately written the way ``test_lifecycle.py`` and its neighbours are
# written: fixed mini-scenarios, one asserted outcome each, sampled from the
# behavior space the way an example-based suite samples it. This is the
# control group of the defect-yield comparison; its coverage was matched
# against the real suite at this head (first-start stamping, refusal edges,
# acceptance requirement, supersession, earned completion, cascade and
# reclaim error text, lease expiry after the fact, wrong-token renewal).


def _advance(at: datetime, seconds: int = 1) -> datetime:
    return at + timedelta(seconds=seconds)


def ordinary_run_first_start_stamps(make: type[Executor]) -> None:
    executor = make()
    at = T0
    executor.op_run_move("queued", False, at)
    at = _advance(at)
    executor.op_run_move("running", False, at)
    assert executor.run.status is RunStatus.RUNNING
    assert executor.run.started_at == at


def ordinary_run_terminal_refuses(make: type[Executor]) -> None:
    executor = make()
    at = T0
    executor.op_run_move("queued", False, at)
    at = _advance(at)
    executor.op_run_move("running", False, at)
    at = _advance(at)
    executor.op_run_move("completed", True, at)
    at = _advance(at)
    try:
        executor.op_run_move("running", False, at)
    except InvalidLifecycleTransition:
        return
    raise AssertionError("terminal Run accepted a transition")


def ordinary_run_completion_stamps_result(make: type[Executor]) -> None:
    executor = make()
    at = T0
    executor.op_run_move("queued", False, at)
    at = _advance(at)
    executor.op_run_move("running", False, at)
    at = _advance(at)
    executor.op_run_move("completed", True, at)
    assert executor.run.finished_at == at
    assert executor.run.result == _payload(at)


def ordinary_node_completion_requires_acceptance(make: type[Executor]) -> None:
    executor = make()
    at = T0
    executor.op_add_node("n0", at)
    at = _advance(at)
    executor.op_node_move("n0", "queued", False, at)
    at = _advance(at)
    executor.op_node_move("n0", "running", False, at)
    at = _advance(at)
    executor.op_attempt_new("n0", at)
    at = _advance(at)
    executor.op_attempt_move("n0", "running", at)
    at = _advance(at)
    executor.op_attempt_move("n0", "completed", at)
    at = _advance(at)
    try:
        executor.op_node_move("n0", "completed", False, at)
    except InvalidLifecycleTransition:
        return
    raise AssertionError("NodeRun completed without accepted evidence")


def ordinary_supersession_clears_acceptance(make: type[Executor]) -> None:
    executor = make()
    at = T0
    executor.op_add_node("n0", at)
    at = _advance(at)
    executor.op_node_move("n0", "queued", False, at)
    at = _advance(at)
    executor.op_node_move("n0", "running", False, at)
    at = _advance(at)
    executor.op_attempt_new("n0", at)
    at = _advance(at)
    executor.op_attempt_move("n0", "running", at)
    at = _advance(at)
    executor.op_attempt_move("n0", "completed", at)
    at = _advance(at)
    executor.op_node_move("n0", "waiting", True, at)
    node_run = executor.latest_node_run("n0")
    assert node_run is not None and node_run.accepted_outcome is not None
    at = _advance(at)
    executor.op_node_move("n0", "queued", False, at)
    node_run = executor.latest_node_run("n0")
    assert node_run is not None
    if node_run.accepted_outcome is not None:
        raise AssertionError("stale acceptance survived resumption")


def ordinary_completion_over_failed_node_refused(make: type[Executor]) -> None:
    executor = make()
    at = T0
    executor.op_add_node("n0", at)
    at = _advance(at)
    executor.op_node_move("n0", "queued", False, at)
    at = _advance(at)
    executor.op_node_move("n0", "running", False, at)
    at = _advance(at)
    executor.op_node_move("n0", "failed", False, at)
    at = _advance(at)
    try:
        executor.op_check_complete(at)
    except UnearnedRunCompletion:
        return
    raise AssertionError("Run completed over a failed node")


def ordinary_completion_over_paused_node_refused(make: type[Executor]) -> None:
    executor = make()
    at = T0
    executor.op_add_node("n0", at)
    at = _advance(at)
    executor.op_node_move("n0", "queued", False, at)
    at = _advance(at)
    executor.op_node_move("n0", "running", False, at)
    at = _advance(at)
    executor.op_node_move("n0", "paused", False, at)
    at = _advance(at)
    try:
        executor.op_check_complete(at)
    except UnearnedRunCompletion:
        return
    raise AssertionError("Run completed over a paused human wait")


def ordinary_cascade_error_names_run_outcome(make: type[Executor]) -> None:
    executor = make()
    at = T0
    executor.op_add_node("n0", at)
    at = _advance(at)
    executor.op_node_move("n0", "queued", False, at)
    at = _advance(at)
    executor.op_settle_open("n0", "failed", at)
    node_run = executor.latest_node_run("n0")
    assert node_run is not None
    if node_run.error != "cancelled because its Run terminalized as failed":
        raise AssertionError("cascade error no longer names the Run outcome")


def ordinary_reclaim_error_names_holder(make: type[Executor]) -> None:
    executor = make()
    at = T0
    executor.op_add_node("n0", at)
    at = _advance(at)
    executor.op_node_move("n0", "queued", False, at)
    at = _advance(at)
    executor.op_attempt_new("n0", at)
    at = _advance(at)
    executor.op_attempt_move("n0", "running", at)
    at = _advance(at)
    executor.op_lease_new("n0", at)
    at = _advance(at)
    executor.op_reclaim("n0", at)
    attempt = executor.latest_attempt("n0")
    assert attempt is not None
    expected = "lease expired; holder 'worker-1' stopped renewing before the Attempt finished"
    if attempt.error != expected:
        raise AssertionError("reclaim error no longer names the holder")


def ordinary_lease_expiry_after_ttl(make: type[Executor]) -> None:
    executor = make()
    at = T0
    executor.op_add_node("n0", at)
    at = _advance(at)
    executor.op_node_move("n0", "queued", False, at)
    at = _advance(at)
    executor.op_attempt_new("n0", at)
    at = _advance(at)
    executor.op_attempt_move("n0", "running", at)
    at = _advance(at)
    executor.op_lease_new("n0", at)
    attempt = executor.latest_attempt("n0")
    assert attempt is not None
    if executor.lease_expired(attempt, at):
        raise AssertionError("lease expired before its own deadline")
    at = at + timedelta(seconds=6)
    if not executor.lease_expired(attempt, at):
        raise AssertionError("lease never expired")


def ordinary_renewal_wrong_token_refused(make: type[Executor]) -> None:
    executor = make()
    at = T0
    executor.op_add_node("n0", at)
    at = _advance(at)
    executor.op_node_move("n0", "queued", False, at)
    at = _advance(at)
    executor.op_attempt_new("n0", at)
    at = _advance(at)
    executor.op_attempt_move("n0", "running", at)
    at = _advance(at)
    executor.op_lease_new("n0", at)
    at = _advance(at)
    try:
        executor.op_lease_renew("n0", True, at)
    except Exception:
        return
    raise AssertionError("renewal accepted a token the Attempt does not hold")


def ordinary_attempt_yield_is_terminal(make: type[Executor]) -> None:
    executor = make()
    at = T0
    executor.op_add_node("n0", at)
    at = _advance(at)
    executor.op_attempt_new("n0", at)
    at = _advance(at)
    executor.op_attempt_move("n0", "running", at)
    at = _advance(at)
    executor.op_attempt_move("n0", "yielded", at)
    attempt = executor.latest_attempt("n0")
    assert attempt is not None and attempt.finished_at is not None
    at = _advance(at)
    try:
        executor.op_attempt_move("n0", "running", at)
    except InvalidLifecycleTransition:
        return
    raise AssertionError("yielded Attempt accepted a transition")


ORDINARY_ASSERTIONS = [
    ordinary_run_first_start_stamps,
    ordinary_run_terminal_refuses,
    ordinary_run_completion_stamps_result,
    ordinary_node_completion_requires_acceptance,
    ordinary_supersession_clears_acceptance,
    ordinary_completion_over_failed_node_refused,
    ordinary_completion_over_paused_node_refused,
    ordinary_cascade_error_names_run_outcome,
    ordinary_reclaim_error_names_holder,
    ordinary_lease_expiry_after_ttl,
    ordinary_renewal_wrong_token_refused,
    ordinary_attempt_yield_is_terminal,
]


def assertion_detects(assertion: Any, mutant: type[Executor]) -> bool:
    try:
        assertion(mutant)
    except Exception:  # any failure of the assertion is detection
        return True
    return False


def defect_yield_table() -> dict[str, dict[str, bool]]:
    """The measured comparison: one row per mutant, one column per suite."""
    table: dict[str, dict[str, bool]] = {}
    for mutant in MUTANTS:
        table[mutant.id] = {
            "ordinary": any(assertion_detects(a, mutant) for a in ORDINARY_ASSERTIONS),
            "differential": any(
                run_stream(stream, mutant()) for stream in [*PROBES.values(), *CORPUS]
            ),
        }
    return table


# ---------------------------------------------------------------------------
# The experiment, as tests
# ---------------------------------------------------------------------------


class TestDifferentialAgreement:
    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("property")
    @given(ops=OP_STREAMS)
    @settings(max_examples=150, deadline=None)
    def test_model_matches_implementation_on_generated_streams(
        self, ops: list[tuple[Any, ...]]
    ) -> None:
        """THE differential property: for arbitrary generated operation
        streams, the prose-derived model and the real lifecycle agree on
        every refusal (including its category) and on the full normalized
        observable state after every accepted step."""
        assert run_stream(ops) == []

    def test_model_matches_implementation_on_the_whole_corpus(self) -> None:
        """The deterministic replay of the recorded corpus: the frozen
        evidence behind the research note's real-drift count (expected: zero
        divergences at this head)."""
        for seed, stream in enumerate(CORPUS):
            divergences = run_stream(stream)
            assert divergences == [], f"seed {seed}: {divergences}"


class TestInjectedDriftIsDetected:
    @pytest.mark.parametrize("mutant", MUTANTS, ids=lambda mutant: mutant.id)
    def test_each_drift_is_real(self, mutant: type[Executor]) -> None:
        """Non-vacuity: every mutant provably changes behavior the driver can
        observe — its probe is clean on the real implementation and diverges
        under the mutant."""
        assert run_stream(PROBES[mutant.id], Executor()) == []
        assert run_stream(PROBES[mutant.id], mutant()), "mutant is vacuous"

    @pytest.mark.parametrize("mutant", MUTANTS, ids=lambda mutant: mutant.id)
    def test_differential_harness_catches_every_drift(self, mutant: type[Executor]) -> None:
        found = [stream for stream in [*PROBES.values(), *CORPUS] if run_stream(stream, mutant())]
        assert found, f"{mutant.id} survived the differential harness"


class TestDefectYieldComparison:
    def test_ordinary_baseline_is_green_on_the_real_implementation(self) -> None:
        """The control group must be sound: every ordinary assertion passes on
        the unmutated implementation, so any detection is real detection."""
        for assertion in ORDINARY_ASSERTIONS:
            assertion(Executor)  # must not raise

    def test_yield_table_freezes_the_measured_comparison(self) -> None:
        """The recorded defect-yield table (research note, 'Record'). The
        differential harness must detect at least everything the ordinary
        suite detects — its claim to value is the rows only it catches."""
        table = defect_yield_table()
        differential = {m.id: run_stream(PROBES[m.id], m()) != [] for m in MUTANTS}
        assert table == {
            "M1-terminal-absorbing-edges-lost": {
                "ordinary": True,
                "differential": True,
            },
            "M2-completion-without-acceptance": {
                "ordinary": True,
                "differential": True,
            },
            "M3-stale-acceptance-not-superseded": {
                "ordinary": True,
                "differential": True,
            },
            "M4-oldest-node-run-counts": {
                "ordinary": False,
                "differential": True,
            },
            "M5-paused-node-cascadable": {
                "ordinary": True,
                "differential": True,
            },
            "M6-lease-expiry-off-by-one": {
                "ordinary": False,
                "differential": True,
            },
            "M7-expired-lease-renewable": {
                "ordinary": False,
                "differential": True,
            },
            "M8-started-at-overwritten-on-resume": {
                "ordinary": False,
                "differential": True,
            },
            "M9-reclaim-error-anonymized": {
                "ordinary": True,
                "differential": True,
            },
            "M10-cascade-error-anonymized": {
                "ordinary": True,
                "differential": True,
            },
        }
        assert differential == {mutant.id: True for mutant in MUTANTS}

    def test_differential_yield_dominates_ordinary_yield(self) -> None:
        table = defect_yield_table()
        for mutant_id, row in table.items():
            assert row["differential"] >= row["ordinary"], mutant_id
        ordinary_total = sum(row["ordinary"] for row in table.values())
        differential_total = sum(row["differential"] for row in table.values())
        assert differential_total > ordinary_total, (ordinary_total, differential_total)

    def test_yield_measurement_is_deterministic(self) -> None:
        assert defect_yield_table() == defect_yield_table()
        replays = [run_stream(stream) for stream in CORPUS]
        assert replays == [run_stream(stream) for stream in CORPUS]


class TestShrinkingEvidence:
    """Evidence question: can Hypothesis shrinking produce useful minimal
    divergence traces? A divergence is only shrinkable when generation can
    reach it: the harness targets the M10 drift (a three-operation chain) so
    random search finds a first counterexample, and uses a one-node reduction
    of the alphabet — the same reduction a human debugger performs — while
    the shrinking does the rest. Chain-shaped drifts whose precondition
    sequence random search cannot hit in a bounded budget (the M3 acceptance
    chain) are covered by their hand-written probes instead; that asymmetry
    is itself a recorded finding."""

    SHRINK_OPS = st.one_of(
        st.just(("add_node", "n0")),
        st.tuples(
            st.just("node_move"),
            st.just("n0"),
            st.sampled_from(["queued", "running", "waiting", "paused"]),
            st.just(False),
        ),
        st.tuples(st.just("settle_open"), st.just("n0"), st.just("failed")),
        st.just(("tick", 1)),
    )
    SHRINK_STREAMS = st.lists(SHRINK_OPS, min_size=1, max_size=12)

    _SHRINK_SETTINGS = settings(max_examples=300, database=None, derandomize=True, deadline=None)

    def test_hypothesis_shrinks_a_divergence_to_a_minimal_trace(self) -> None:
        """A realistic first counterexample is a long stream with irrelevant
        traffic around the defect. ``find`` must return a strictly shorter
        trace that still diverges — the shrinking usefulness evidence."""
        naive: list[tuple[Any, ...]] = [
            ("add_node", "n1"),
            ("node_move", "n1", "queued", False),
            ("tick", 1),
            ("add_node", "n2"),
            ("run_move", "queued", False),
            ("tick", 2),
            ("attempt_new", "n1"),
            ("settle_open", "n1", "cancelled"),
            ("tick", 1),
            ("add_node", "n3"),
            ("node_move", "n3", "queued", False),
            ("node_move", "n3", "running", False),
            *PROBES["M10-cascade-error-anonymized"],
            ("attempt_new", "n2"),
            ("attempt_move", "n2", "running"),
            ("attempt_move", "n2", "completed"),
        ]
        assert run_stream(naive, DriftCascadeAnonymized())
        assert run_stream(naive, Executor()) == []
        minimal = find(
            self.SHRINK_STREAMS,
            lambda ops: bool(run_stream(list(ops), DriftCascadeAnonymized())),
            settings=self._SHRINK_SETTINGS,
        )
        assert run_stream(list(minimal), DriftCascadeAnonymized())
        assert len(minimal) < len(naive)
        assert len(minimal) <= 4

    def test_shrunken_trace_is_stable_across_reruns(self) -> None:
        """derandomize + no database: the shrunken trace is byte-stable, so a
        recorded divergence trace can be quoted in a defect report."""
        traces = [
            find(
                self.SHRINK_STREAMS,
                lambda ops: bool(run_stream(list(ops), DriftCascadeAnonymized())),
                settings=self._SHRINK_SETTINGS,
            )
            for _ in range(2)
        ]
        assert traces[0] == traces[1]
        assert len(traces[0]) <= 4


class TestEvidenceOnlyContract:
    def test_harness_declares_itself_advisory(self) -> None:
        assert ADVISORY_ONLY is True

    def test_harness_is_test_side_and_imports_no_product_module_into_itself(
        self,
    ) -> None:
        """The oracle half of the harness imports no maistro module — only the
        driver does. Pinned by AST so the model cannot silently start
        delegating to the implementation it is supposed to be independent
        of."""
        source = Path(__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        model_class = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef) and node.name == "ReferenceModel"
        )
        for node in ast.walk(model_class):
            assert not isinstance(node, (ast.Import, ast.ImportFrom)), (
                "ReferenceModel must stay maistro-free"
            )

    def test_harness_resides_under_tests_and_declares_no_authority(
        self,
    ) -> None:
        parts = Path(__file__).resolve().parts
        assert "tests" in parts
        # The harness defines no new work-state vocabulary: it compares the
        # canonical statuses only, and the lifecycle-identity ledger gate
        # (scripts/check-execution-lifecycles.py) polices that independently.
        source = Path(__file__).read_text(encoding="utf-8")
        assert "class " + "RunStatus" not in source
        assert "class " + "AttemptStatus" not in source
