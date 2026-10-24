"""Stateful Hypothesis machine over the canonical execution lifecycle (#881).

Research prototype for M8-A1: a bounded `RuleBasedStateMachine` that drives the
real `PgRunStore` through generated Run -> NodeRun -> Attempt sequences, the
same way `test_run_lease_fence.py` (I29) does for the lease/fence slice. Where
that model covers one NodeRun's Attempts, this one moves all three levels of
the spine, because the sequencing bugs worth finding live *between* the levels:
a Run that completes over a failed node, a cascade that forgets a node, work
admitted under a closed Run.

**The oracle is arithmetic over the imported lifecycle tables, not the store.**
The machine keeps its own belief about every status and applies the same
`RUN_TRANSITIONS` / `ATTEMPT_TRANSITIONS` tables the implementation publishes.
Each rule predicts -- before touching the store -- whether the call will be
accepted and what the resulting status will be, or which domain exception the
store must raise. A store that accepted an illegal move, refused a legal one,
applied a different target than requested, or settled a row it should have
left alone diverges from that arithmetic and fails the model, even though no
line of the model ever read a status to decide what to expect. That is the
#410 evidence rule: the model evolves independently and the invariants compare
two independently-evolved states.

Invariants (each with the counterexample class it detects):

1. *At most one live Attempt per NodeRun.* The set of live statuses is
   imported from the store (`_ACTIVE_ATTEMPT_STATUSES`) rather than restated.
   Detects a store that admits a second active Attempt -- a dropped partial
   unique index or a check removed from `create_attempt`.
2. *The Run's stored status equals the model's.* Detects an illegal transition
   applied anyway, a self-transition, or a write of a target other than the
   one requested.
3. *The latest NodeRun's stored status equals the model's, and a terminal Run
   has no open NodeRun.* The second half detects a cascade that missed a row
   (ADR-082426-a47f: an open NodeRun under a terminal Run is work a closed Run
   still owns).
4. *The active Attempt's stored status equals the model's.* Detects the
   Attempt-level lifecycle diverging from the published table, including the
   #1335 guard the rules below exercise directly.
5. *The NodeRun population equals the model's count of admitted creates.*
   Detects both phantom NodeRuns and silently lost ones.

Terminal runs never gain work is enforced as rule post-conditions: after the
Run is terminal, `create_node_run` must raise `RunIntegrityError`, and the
store's refusal is the rule's assertion.

Like I29, this model is *about* the PostgreSQL store, so it is not skipped
lightly: `scripts/ac_outcome_plugin.py` counts a skip as no evidence, and
`formal-conformance.yml` provisions the service. Isolation is by fresh
Workspace per example.

Research note: docs/research/881-execution-lifecycle-state-machines.md.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any

import pytest
from hypothesis import settings as hyp_settings
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule
from hypothesis.strategies import sampled_from

from maistro.graph import Graph, Node
from maistro.runs import AcceptedNodeOutcome, AttemptResult
from maistro.runs.lifecycle import ATTEMPT_TRANSITIONS, RUN_TRANSITIONS, InvalidLifecycleTransition
from maistro.runs.model import AttemptStatus, RunStatus, TERMINAL_RUN_STATUSES
from maistro.runs.pg_store import _ACTIVE_ATTEMPT_STATUSES
from maistro.runs.store import ActiveAttemptExists, RunIntegrityError

pytestmark = pytest.mark.usefixtures()

#: The lifecycle tables are the oracle's alphabet: every rule samples targets
#: from the *full* status set, so illegal moves are generated as often as legal
#: ones and refusing them is part of what the model checks.
_ALL_RUN_STATUSES = list(RunStatus)
_ALL_ATTEMPT_STATUSES = list(AttemptStatus)
_LIVE_ATTEMPT_STATUSES = tuple(status for status in AttemptStatus if status.value in _ACTIVE_ATTEMPT_STATUSES)

#: A terminalizing Run settles every open NodeRun to this one status
#: (ADR-082426-a47f). Imported, not restated, for the same reason I29 imports
#: the live-Attempt set.
CASCADE_TARGET = RunStatus.CANCELLED


def _dsn() -> str | None:
    from maistro.testing.postgres import postgres_dsn

    return postgres_dsn()


class _Server:
    """One event loop and one pool, shared by every example (as in I29)."""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.pool: Any = None

    async def _create_pool(self, dsn: str) -> Any:
        import asyncpg

        from maistro.persistence import _register_json_codecs

        return await asyncpg.create_pool(
            dsn,
            min_size=1,
            max_size=4,
            init=_register_json_codecs,
        )

    def start(self, dsn: str) -> None:
        self.pool = self.loop.run_until_complete(self._create_pool(dsn))

    def run(self, coro: Any) -> Any:
        return self.loop.run_until_complete(coro)


_SERVER: _Server | None = None


def _server() -> _Server:
    global _SERVER
    if _SERVER is None:
        dsn = _dsn()
        if not dsn:
            pytest.skip("MAISTRO_TEST_PG_DSN is not set; see this module's docstring")
        pytest.importorskip("asyncpg")
        server = _Server()
        server.start(dsn)
        _SERVER = server
    return _SERVER


def _graph(workspace: str, project_id: str) -> Graph:
    """The same one-node shape `test_run_lease_fence.py` builds."""
    return Graph(
        workspace_id=workspace,
        project_id=project_id,
        name="Formal lifecycle graph",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )


class ExecutionLifecycleMachine(RuleBasedStateMachine):
    """One Run per example; rules move the Run, its latest NodeRun, its Attempt.

    The machine tracks the *latest* NodeRun for the single graph node. Older
    NodeRuns of the same node stay in the store and remain under the
    terminal-run invariants, but re-execution is deliberately in scope: the
    earned-completion contract consults the newest record per node, and a
    failed first visit followed by a successful retry is exactly the sequence
    a hand-written test tends to get backwards.
    """

    def __init__(self) -> None:
        super().__init__()
        server = _server()
        self._server = server

        from maistro.projects.pg_scope_store import PgProjectScopeStore
        from maistro.runs.pg_store import PgRunStore

        workspace = f"formal-lifecycle-{uuid.uuid4().hex}"
        projects = PgProjectScopeStore(server.pool)
        root = server.run(projects.create_root(workspace))
        project = server.run(
            projects.create(
                workspace_id=workspace,
                parent_project_id=root.project_id,
                name="Formal",
            )
        )
        self.store = PgRunStore(server.pool, project_store=projects)
        run = server.run(
            self.store.create_run(
                _graph(workspace, project.project_id),
                actor_principal_id=f"formal-lifecycle-{uuid.uuid4().hex}",
            )
        )
        self.run_id = run.run_id
        first_node_run = server.run(self.store.create_node_run(run.run_id, node_id="node-1"))

        # Model state, evolved by table arithmetic only. Nothing below reads a
        # stored status to decide what to expect.
        self.run_status = RunStatus.CREATED
        self.node_run_id = first_node_run.node_run_id
        self.node_run_status = RunStatus.CREATED
        self.node_run_creates = 1
        self.attempt_id: str | None = None
        self.attempt_status: AttemptStatus | None = None
        self.fencing_token: str | None = None
        self.completed_attempt_id: str | None = None

    # ── model arithmetic ──────────────────────────────────────────

    def _completion_is_earned(self) -> bool:
        """Whether a COMPLETED Run is earned, per `check_completion_is_earned`.

        Only the *latest* NodeRun per node is consulted; a node with no
        NodeRun is not consulted; an open NodeRun does not block (it is
        cascaded in the same write); a terminal-but-not-completed NodeRun and
        a paused human wait do block.
        """
        if self.node_run_id is None:
            return True
        if self.node_run_status is RunStatus.COMPLETED:
            return True
        blocked = (TERMINAL_RUN_STATUSES - {RunStatus.COMPLETED}) | {RunStatus.PAUSED}
        return self.node_run_status not in blocked

    def _settle_model_for_terminal_run(self) -> None:
        """Mirror the cascade the store performs inside the same write."""
        if self.node_run_id is not None and self.node_run_status not in TERMINAL_RUN_STATUSES:
            self.node_run_status = CASCADE_TARGET

    def _completed_attempt_result(self) -> AttemptResult:
        attempt = self._server.run(self.store.get_attempt(self.completed_attempt_id))
        assert attempt is not None
        return AttemptResult.from_attempt(attempt)

    # ── rules ─────────────────────────────────────────────────────

    @rule(status=sampled_from(_ALL_RUN_STATUSES))
    def move_run(self, status: RunStatus) -> None:
        """Move the Run, or watch the store refuse exactly as the table says.

        The #241 asymmetry is modelled, not copied: COMPLETED must be *earned*
        (the latest NodeRun completed, none failed/cancelled/timed out, no
        human wait), while FAILED/CANCELLED/TIMED_OUT are always legal exits
        from wherever the table allows them.

        The generated value is named ``status``: ``target=`` is reserved by
        ``@rule`` for a Bundle, and a strategy passed there fails at import.
        """
        illegal = status not in RUN_TRANSITIONS[self.run_status]
        unearned = status is RunStatus.COMPLETED and not self._completion_is_earned()
        if illegal or unearned:
            with pytest.raises(InvalidLifecycleTransition):
                self._server.run(self.store.transition_run(self.run_id, status))
            return
        updated = self._server.run(self.store.transition_run(self.run_id, status))
        assert updated.status is status, "the store applied a status other than the requested one"
        self.run_status = status
        if status in TERMINAL_RUN_STATUSES:
            self._settle_model_for_terminal_run()

    @rule()
    def create_node_run(self) -> None:
        """Re-execute the node, or watch a terminal Run refuse new work."""
        if self.run_status in TERMINAL_RUN_STATUSES:
            with pytest.raises(RunIntegrityError):
                self._server.run(self.store.create_node_run(self.run_id, node_id="node-1"))
            return
        node_run = self._server.run(self.store.create_node_run(self.run_id, node_id="node-1"))
        self.node_run_id = node_run.node_run_id
        self.node_run_status = RunStatus.CREATED
        self.node_run_creates += 1
        # The new NodeRun has no Attempts; the old ones stay with the old row.
        self.attempt_id = None
        self.attempt_status = None
        self.fencing_token = None
        self.completed_attempt_id = None

    @rule(holder=sampled_from(["worker-a", "worker-b", "worker-c"]))
    def claim_attempt(self, holder: str) -> None:
        """Start an Attempt, or watch one of two refusals fire in order.

        A terminal NodeRun refuses first (`RunIntegrityError` proper); an
        already-live Attempt refuses as `ActiveAttemptExists`. Both are
        subclasses of `RunIntegrityError`, so the model asserts the *specific*
        class exactly where the contract names it.
        """
        if self.node_run_status in TERMINAL_RUN_STATUSES:
            with pytest.raises(RunIntegrityError) as excinfo:
                self._server.run(self.store.create_attempt(self.node_run_id, lease_holder=holder))
            assert not isinstance(excinfo.value, ActiveAttemptExists), (
                "a terminal NodeRun was refused for the wrong reason: an Attempt was held live"
            )
            return
        if self.attempt_status in _LIVE_ATTEMPT_STATUSES:
            with pytest.raises(ActiveAttemptExists):
                self._server.run(self.store.create_attempt(self.node_run_id, lease_holder=holder))
            return
        attempt = self._server.run(self.store.create_attempt(self.node_run_id, lease_holder=holder))
        assert attempt.execution_lease is not None
        self.attempt_id = attempt.attempt_id
        self.attempt_status = AttemptStatus.CREATED
        self.fencing_token = attempt.execution_lease.fencing_token

    @precondition(lambda self: self.attempt_id is not None)
    @rule(status=sampled_from(_ALL_ATTEMPT_STATUSES))
    def move_attempt(self, status: AttemptStatus) -> None:
        """Move the live Attempt under its correct fencing token.

        The #1335 guard is modelled in the store's own order: a COMPLETED
        Attempt under an already-terminal Run is refused *before* the table
        check, while FAILED/CANCELLED/TIMED_OUT/YIELDED stay legal there --
        they record what physically happened after the Run closed.
        """
        assert self.fencing_token is not None
        target = status
        if self.run_status in TERMINAL_RUN_STATUSES and target is AttemptStatus.COMPLETED:
            with pytest.raises(InvalidLifecycleTransition):
                self._server.run(
                    self.store.transition_attempt(self.attempt_id, target, fencing_token=self.fencing_token)
                )
            return
        if target not in ATTEMPT_TRANSITIONS[self.attempt_status]:
            with pytest.raises(InvalidLifecycleTransition):
                self._server.run(
                    self.store.transition_attempt(self.attempt_id, target, fencing_token=self.fencing_token)
                )
            return
        updated = self._server.run(
            self.store.transition_attempt(self.attempt_id, target, fencing_token=self.fencing_token)
        )
        assert updated.status is target, "the store applied a status other than the requested one"
        self.attempt_status = target
        if target is AttemptStatus.COMPLETED:
            self.completed_attempt_id = self.attempt_id

    @rule(status=sampled_from(_ALL_RUN_STATUSES))
    def move_node_run(self, status: RunStatus) -> None:
        """Move the latest NodeRun through the same table the Run uses.

        A COMPLETED node must carry an `AcceptedNodeOutcome` projected from a
        physically completed Attempt, so the rule only offers COMPLETED when
        the model holds such evidence; without it the store must refuse.
        Under a terminal Run every move is refused before the table is even
        consulted (`_refuse_under_terminal_run`), which is why that check
        comes first here too.
        """
        target = status
        if self.run_status in TERMINAL_RUN_STATUSES:
            with pytest.raises(RunIntegrityError):
                self._server.run(self.store.transition_node_run(self.node_run_id, target))
            return
        if target not in RUN_TRANSITIONS[self.node_run_status]:
            with pytest.raises(InvalidLifecycleTransition):
                self._server.run(self.store.transition_node_run(self.node_run_id, target))
            return
        if target is RunStatus.COMPLETED and self.completed_attempt_id is None:
            with pytest.raises(InvalidLifecycleTransition):
                self._server.run(self.store.transition_node_run(self.node_run_id, target))
            return
        if target is RunStatus.COMPLETED:
            outcome = AcceptedNodeOutcome(
                node_run_id=self.node_run_id,
                attempt_result=self._completed_attempt_result(),
                logical_status=RunStatus.COMPLETED,
                result=None,
            )
            updated = self._server.run(
                self.store.transition_node_run(self.node_run_id, target, accepted_outcome=outcome)
            )
        else:
            updated = self._server.run(self.store.transition_node_run(self.node_run_id, target))
        assert updated.status is target, "the store applied a status other than the requested one"
        self.node_run_status = target

    # ── invariants ────────────────────────────────────────────────

    @invariant()
    def at_most_one_live_attempt(self) -> None:
        """No NodeRun ever holds two live Attempts."""
        attempts = self._server.run(self.store.list_attempts(self.node_run_id))
        live = [a for a in attempts if a.status.value in _ACTIVE_ATTEMPT_STATUSES]
        assert len(live) <= 1, f"{len(live)} live Attempts on NodeRun {self.node_run_id}"

    @invariant()
    def stored_run_status_matches_model(self) -> None:
        """The store is exactly where table arithmetic says the Run is."""
        run = self._server.run(self.store.get_run(self.run_id))
        assert run is not None
        assert run.status is self.run_status, (
            f"Run {self.run_id}: store says {run.status.value}, model says {self.run_status.value}"
        )

    @invariant()
    def stored_node_run_status_matches_model(self) -> None:
        """The latest NodeRun is exactly where table arithmetic says it is."""
        node_run = self._server.run(self.store.get_node_run(self.node_run_id))
        assert node_run is not None
        assert node_run.status is self.node_run_status, (
            f"NodeRun {self.node_run_id}: store says {node_run.status.value}, model says {self.node_run_status.value}"
        )

    @invariant()
    def no_open_node_run_under_terminal_run(self) -> None:
        """A terminal Run settled every NodeRun it owned (ADR-082426-a47f)."""
        if self.run_status not in TERMINAL_RUN_STATUSES:
            return
        for node_run in self._server.run(self.store.list_node_runs(self.run_id)):
            assert node_run.status in TERMINAL_RUN_STATUSES, (
                f"terminal Run {self.run_status.value} still owns open NodeRun "
                f"{node_run.node_run_id} ({node_run.status.value})"
            )

    @invariant()
    def stored_attempt_status_matches_model(self) -> None:
        """The live Attempt is exactly where table arithmetic says it is."""
        if self.attempt_id is None:
            return
        attempt = self._server.run(self.store.get_attempt(self.attempt_id))
        assert attempt is not None
        assert attempt.status is self.attempt_status, (
            f"Attempt {self.attempt_id}: store says {attempt.status.value}, model says {self.attempt_status.value}"
        )

    @invariant()
    def node_run_population_matches_model(self) -> None:
        """The store holds exactly the NodeRuns the model admitted."""
        node_runs = self._server.run(self.store.list_node_runs(self.run_id))
        assert len(node_runs) == self.node_run_creates, (
            f"Run {self.run_id}: store holds {len(node_runs)} NodeRuns, model admitted {self.node_run_creates}"
        )


# A live database is orders of magnitude slower than the in-process models, so
# this one runs the same reduced budget as I29 with a longer sequence: an
# earned completion alone takes nine coordinated steps (admit, start, claim,
# begin, complete, queue, run, accept, complete). The nightly workflow raises
# this budget by exporting MAISTRO_FORMAL_PG_EXAMPLES (the conftest nightly
# hook cannot reach a module that pins its own settings).
ExecutionLifecycleMachine.TestCase.settings = hyp_settings(
    max_examples=int(os.environ.get("MAISTRO_FORMAL_PG_EXAMPLES", "15")),
    stateful_step_count=16,
    deadline=None,
)

TestExecutionLifecycleMachine = ExecutionLifecycleMachine.TestCase


# ── deterministic witnesses for the deepest sequencing contracts ──────────────
#
# Two contracts sit at the end of long, specific rule sequences -- a Run may
# only complete when its latest NodeRun earns it, and a COMPLETED Attempt is
# refused under a terminal Run (#1335). A random walk threads them too rarely
# to prove anything at the PR budget (M2 in the research note sailed through
# 15 x 16 random steps), so each is pinned here as an ordinary test that runs
# every CI pass, while the machine above still explores their interleavings.


def _spine(prefix: str) -> tuple[Any, Any, Any, Any]:
    """One fresh workspace scope with an open Run and one open NodeRun."""
    from maistro.projects.pg_scope_store import PgProjectScopeStore
    from maistro.runs.pg_store import PgRunStore

    server = _server()
    workspace = f"{prefix}-{uuid.uuid4().hex}"
    projects = PgProjectScopeStore(server.pool)
    root = server.run(projects.create_root(workspace))
    project = server.run(projects.create(workspace_id=workspace, parent_project_id=root.project_id, name="Formal"))
    store = PgRunStore(server.pool, project_store=projects)
    run = server.run(
        store.create_run(
            _graph(workspace, project.project_id),
            actor_principal_id=f"{prefix}-{uuid.uuid4().hex}",
        )
    )
    node_run = server.run(store.create_node_run(run.run_id, node_id="node-1"))
    return server, store, run, node_run


def _running(store: Any, server: _Server, run: Any, node_run: Any) -> None:
    """Admit the Run and start Run and NodeRun."""
    server.run(store.transition_run(run.run_id, RunStatus.QUEUED))
    server.run(store.transition_run(run.run_id, RunStatus.RUNNING))
    server.run(store.transition_node_run(node_run.node_run_id, RunStatus.QUEUED))
    server.run(store.transition_node_run(node_run.node_run_id, RunStatus.RUNNING))


def test_completion_of_the_run_is_earned_by_its_latest_node_run() -> None:
    """The #241 contract, both directions, against the real store.

    Counterexample class: a Run reporting COMPLETED over a settled-but-failed
    NodeRun -- the combination #43's fourth criterion calls impossible, which
    needs no race to produce, only an executor that reports success without
    checking what the spine recorded.
    """
    server, store, run, node_run = _spine("formal-earned")
    _running(store, server, run, node_run)

    # A failed node blocks completion even though the Run itself is RUNNING.
    server.run(store.transition_node_run(node_run.node_run_id, RunStatus.FAILED))
    with pytest.raises(InvalidLifecycleTransition):
        server.run(store.transition_run(run.run_id, RunStatus.COMPLETED))

    # Retrying is a *new* NodeRun for the same node; only the newest counts.
    retry = server.run(store.create_node_run(run.run_id, node_id="node-1"))
    server.run(store.transition_node_run(retry.node_run_id, RunStatus.QUEUED))
    server.run(store.transition_node_run(retry.node_run_id, RunStatus.RUNNING))
    attempt = server.run(store.create_attempt(retry.node_run_id, lease_holder="worker-earned"))
    assert attempt.execution_lease is not None
    server.run(
        store.transition_attempt(
            attempt.attempt_id, AttemptStatus.RUNNING, fencing_token=attempt.execution_lease.fencing_token
        )
    )
    server.run(
        store.transition_attempt(
            attempt.attempt_id,
            AttemptStatus.COMPLETED,
            fencing_token=attempt.execution_lease.fencing_token,
        )
    )

    # A completed node needs accepted evidence projected from that Attempt.
    with pytest.raises(InvalidLifecycleTransition):
        server.run(store.transition_node_run(retry.node_run_id, RunStatus.COMPLETED))
    outcome = AcceptedNodeOutcome(
        node_run_id=retry.node_run_id,
        attempt_result=AttemptResult.from_attempt(server.run(store.get_attempt(attempt.attempt_id))),
        logical_status=RunStatus.COMPLETED,
        result=None,
    )
    server.run(store.transition_node_run(retry.node_run_id, RunStatus.COMPLETED, accepted_outcome=outcome))

    # Now, and only now, the Run's success is earned.
    completed = server.run(store.transition_run(run.run_id, RunStatus.COMPLETED))
    assert completed.status is RunStatus.COMPLETED
    assert completed.finished_at is not None


def test_attempt_completion_is_refused_under_a_terminal_run() -> None:
    """The #1335 fence: a stale success cannot land under a closed Run.

    Counterexample class: a worker whose provider lost a cancel writes
    COMPLETED after the Run terminalized, so the audit trail shows finished
    work under a Run that owns nothing -- the TOCTOU the store-side guard
    exists to close. Its siblings stay legal: FAILED and CANCELLED record
    what physically happened after the close.
    """
    server, store, run, node_run = _spine("formal-fence")
    _running(store, server, run, node_run)
    attempt = server.run(store.create_attempt(node_run.node_run_id, lease_holder="worker-stale"))
    token = attempt.execution_lease.fencing_token
    assert token is not None
    server.run(store.transition_attempt(attempt.attempt_id, AttemptStatus.RUNNING, fencing_token=token))

    # Terminalizing the Run cascades the open NodeRun but leaves the live
    # Attempt exactly as it is -- and COMPLETED is then the one exit refused.
    server.run(store.transition_run(run.run_id, RunStatus.CANCELLED))
    cascaded = server.run(store.get_node_run(node_run.node_run_id))
    assert cascaded is not None and cascaded.status is RunStatus.CANCELLED
    with pytest.raises(InvalidLifecycleTransition):
        server.run(store.transition_attempt(attempt.attempt_id, AttemptStatus.COMPLETED, fencing_token=token))

    # The physical outcome -- the work failed when the Run closed under it --
    # is still recordable, under the same token the worker already held.
    failed = server.run(store.transition_attempt(attempt.attempt_id, AttemptStatus.FAILED, fencing_token=token))
    assert failed.status is AttemptStatus.FAILED

    # A closed Run also admits no new work at either level.
    with pytest.raises(RunIntegrityError):
        server.run(store.create_node_run(run.run_id, node_id="node-1"))
    with pytest.raises(RunIntegrityError):
        server.run(store.create_attempt(node_run.node_run_id, lease_holder="worker-late"))
