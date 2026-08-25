"""I29 — execution lease and fence, against the real PostgreSQL Run store (#132).

Every other model here explores a pure in-process object. This one drives
`PgRunStore` against a live server, because the invariant it checks is *about*
concurrent writers and a store that has only ever been asked one thing at a
time cannot answer it. `test_spine_conformance.py` already races ten workers
by hand; what a state machine adds is the interleavings nobody thought to
write down — a fence checked after a retry, a token reused two attempts later,
a terminal write arriving behind a fresh lease.

**Two invariants, both stated by the store rather than restated here.**

1. *At most one Attempt on a NodeRun is active.* The set of active statuses is
   imported from the store (`_ACTIVE_ATTEMPT_STATUSES`) rather than spelled
   again — a model that hardcoded `("created", "running")` would keep passing
   on the day the store added a third and stop being about the store at all.
2. *A write carrying anything other than the live lease's fencing token is
   refused.* Not "usually refused": the model keeps every token it has ever
   seen and replays retired ones, which is the shape of the bug — a worker
   that paused, lost its lease, and came back believing it still held one.

**Why this is not skipped when no server is configured.** It is, and that is a
real cost: `scripts/ac_outcome_plugin.py` counts a skip as *no evidence*, so a
skipped run leaves #132's criterion unproven however green the build looks.
`formal-conformance.yml` therefore runs a PostgreSQL service. If this file ever
starts skipping in CI, the criterion has quietly stopped being checked.

Isolation is by fresh Workspace per example, following the conformance
harness — the tables are shared and durable, so scoping is cheaper and truer
than truncating between hundreds of Hypothesis examples.
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
from maistro.runs.lifecycle import ATTEMPT_TRANSITIONS
from maistro.runs.model import AttemptStatus
from maistro.runs.pg_store import _ACTIVE_ATTEMPT_STATUSES
from maistro.runs.store import ActiveAttemptExists, StaleExecutionFence

pytestmark = pytest.mark.usefixtures()

#: Taken from the lifecycle table rather than restated. A model that invented
#: its own legal transitions would fail on the store's table rather than on the
#: fence, and would stop being a model of this system the day the table moved.
_FROM_RUNNING = tuple(sorted(ATTEMPT_TRANSITIONS[AttemptStatus.RUNNING], key=lambda s: s.value))


def _dsn() -> str | None:
    from maistro.testing.postgres import postgres_dsn

    return postgres_dsn()


class _Server:
    """One event loop and one pool, shared by every example.

    A pool per example would mean hundreds of connection setups for a suite
    whose whole point is to run many cheap examples. asyncpg binds a pool to
    the loop that created it, so the loop has to outlive the pool — hence both
    living here rather than in a fixture torn down per example.
    """

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.pool: Any = None

    async def _create_pool(self, dsn: str) -> Any:
        """Create asyncpg resources while this server's loop is actually running.

        On Python 3.12 ``asyncpg.create_pool(...)`` consults the current event
        loop when the call expression is evaluated. Passing that expression
        directly to ``run_until_complete`` evaluates it *before* the loop starts,
        which fails on a thread with no implicit loop. Keeping creation inside
        this coroutine makes the loop ownership explicit instead of relying on
        the pre-3.12 ambient-loop behavior.
        """
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
    """The same shape `tests/runs/test_spine_conformance.py` builds."""
    return Graph(
        workspace_id=workspace,
        project_id=project_id,
        name="Formal graph",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )


class RunLeaseFenceMachine(RuleBasedStateMachine):
    """One NodeRun per example; rules drive its Attempts through the lifecycle."""

    def __init__(self) -> None:
        super().__init__()
        server = _server()
        self._server = server

        from maistro.projects.pg_scope_store import PgProjectScopeStore
        from maistro.runs.pg_store import PgRunStore

        workspace = f"formal-i29-{uuid.uuid4().hex}"
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
        run = server.run(self.store.create_run(_graph(workspace, project.project_id)))
        self.node_run = server.run(self.store.create_node_run(run.run_id, node_id="node-1"))

        # Model state, deliberately independent of the store's.
        self.attempt_id: str | None = None
        self.status: AttemptStatus | None = None
        self.live_token: str | None = None
        self.retired_tokens: list[str] = []

    def _transition(self, status: AttemptStatus, token: str | None) -> Any:
        return self._server.run(
            self.store.transition_attempt(
                self.attempt_id,
                status,
                fencing_token=token,
            )
        )

    def _retire(self) -> None:
        if self.live_token is not None:
            self.retired_tokens.append(self.live_token)
        self.attempt_id = None
        self.status = None
        self.live_token = None

    # ── rules ─────────────────────────────────────────────────────

    @rule(holder=sampled_from(["worker-a", "worker-b", "worker-c"]))
    def start_attempt(self, holder: str) -> None:
        """Start one. A second while one is live must be refused, not queued."""
        try:
            attempt = self._server.run(
                self.store.create_attempt(
                    self.node_run.node_run_id,
                    lease_holder=holder,
                )
            )
        except ActiveAttemptExists:
            assert self.attempt_id is not None, (
                "the store refused a second Attempt while the model believed none was active"
            )
            return

        assert self.attempt_id is None, "the store admitted a second Attempt while one was already active"
        assert attempt.execution_lease is not None
        self.attempt_id = attempt.attempt_id
        self.status = AttemptStatus.CREATED
        self.live_token = attempt.execution_lease.fencing_token

    @precondition(lambda self: self.status is AttemptStatus.CREATED)
    @rule()
    def begin_running(self) -> None:
        """The holder may write. This is the case that must keep working."""
        self._transition(AttemptStatus.RUNNING, self.live_token)
        self.status = AttemptStatus.RUNNING

    # `status`, not `target`: `target=` is reserved by @rule for a Bundle, and
    # passing a strategy there fails at import rather than at run time.
    @precondition(lambda self: self.status is AttemptStatus.RUNNING)
    @rule(status=sampled_from(_FROM_RUNNING))
    def leave_running(self, status: AttemptStatus) -> None:
        """Every exit the lifecycle table allows, including YIELDED.

        `YIELDED` is not in `_ACTIVE_ATTEMPT_STATUSES`, so yielding frees the
        NodeRun for a fresh Attempt exactly as completing does. That is the
        kind of edge a hand-written test tends to miss and a state machine
        reaches by construction.
        """
        self._transition(status, self.live_token)
        self._retire()

    @precondition(lambda self: self.status is AttemptStatus.CREATED)
    @rule()
    def cancel_before_running(self) -> None:
        """`CREATED -> CANCELLED` is the table's other legal exit."""
        self._transition(AttemptStatus.CANCELLED, self.live_token)
        self._retire()

    @precondition(lambda self: self.attempt_id is not None and self.retired_tokens)
    @rule()
    def a_retired_token_is_refused(self) -> None:
        """The bug this exists for: a worker that lost its lease and came back.

        Replaying an *old* token rather than a random string — a random string
        is refused by any comparison, while a token that was genuinely valid
        one Attempt ago is what a real stale worker sends.

        The target is a *legal* transition for the current status, so a refusal
        can only have come from the fence. An illegal target would be rejected
        either way and would prove nothing about fencing.
        """
        legal = next(iter(ATTEMPT_TRANSITIONS[self.status]))
        with pytest.raises(StaleExecutionFence):
            self._transition(legal, self.retired_tokens[-1])

    @precondition(lambda self: self.attempt_id is not None)
    @rule()
    def an_absent_token_is_refused(self) -> None:
        """A leased Attempt refuses an unfenced write."""
        legal = next(iter(ATTEMPT_TRANSITIONS[self.status]))
        with pytest.raises(StaleExecutionFence):
            self._transition(legal, None)

    # ── invariants ────────────────────────────────────────────────

    def _attempts(self) -> Any:
        return self._server.run(self.store.list_attempts(self.node_run.node_run_id))

    @invariant()
    def at_most_one_active_attempt(self) -> None:
        active = [a for a in self._attempts() if a.status.value in _ACTIVE_ATTEMPT_STATUSES]
        assert len(active) <= 1, f"{len(active)} Attempts active at once on one NodeRun"

    @invariant()
    def the_store_agrees_with_the_model(self) -> None:
        active = [a for a in self._attempts() if a.status.value in _ACTIVE_ATTEMPT_STATUSES]
        if self.attempt_id is None:
            assert active == [], "the model believes nothing is active; the store disagrees"
        else:
            assert [a.attempt_id for a in active] == [self.attempt_id]
            assert active[0].status is self.status

    @invariant()
    def ordinals_are_contiguous_from_one(self) -> None:
        """A gap means an ordinal was allocated and lost — the read-modify-write
        race `MAX(ordinal) + 1` invites, and the reason the row is locked."""
        ordinals = sorted(a.ordinal for a in self._attempts())
        assert ordinals == list(range(1, len(ordinals) + 1)), f"ordinals not contiguous: {ordinals}"


# A live database is orders of magnitude slower than the in-process models here,
# so this one runs a smaller budget than the suite default. The nightly sweep
# raises it through the same conftest hook every other model uses.
RunLeaseFenceMachine.TestCase.settings = hyp_settings(
    max_examples=int(os.environ.get("MAISTRO_FORMAL_PG_EXAMPLES", "15")),
    stateful_step_count=8,
    deadline=None,
)

TestRunLeaseFenceMachine = RunLeaseFenceMachine.TestCase
