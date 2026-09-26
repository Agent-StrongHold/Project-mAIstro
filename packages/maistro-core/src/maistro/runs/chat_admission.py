"""Admitting one chat turn as a canonical Run, and forgetting it again (#131).

#41's rule is that work has exactly one execution identity regardless of where
it entered. A chat turn is work. What it lacked, and a task did not, was any
answer to *how long that identity lives*: a task has a receipt, a lifecycle and
a retention policy; `route_request()` is a synchronous request/response with
none of the three. Bolting a Run onto it without deciding retention would ship
a memory leak wearing the convergence program's own vocabulary.

Both decisions are recorded in ADR-082326-c126 and implemented here.

**One Run per turn, not per conversation.** A Run has a terminal state and a
conversation does not: a Run-per-session would sit RUNNING for as long as
somebody might type again, which is exactly what recovery scans read as a
process that died. The conversation already has an identity — `session_id` —
and it travels in the Run's provenance, so "every Run in this conversation" is
a query rather than a second kind of Run.

**Bounded in-process, by the admitter that creates the pressure.** Chat turns
arrive orders of magnitude more often than task submissions, so the shared
store bound (`MAX_IN_MEMORY_RUNS`) is the wrong instrument: at chat volume it
would evict *task* Runs to make room for chat ones. This admitter therefore
keeps its own small window of the Runs it admitted and deletes the oldest ones
as it overflows — terminal Runs, and stalled non-terminal ones with nothing
left living in them. A Run still CREATED/QUEUED is mid-admission, which the
admission path compensates itself; a Run the dispatching seam has marked is
awaiting its dispatch; a Run holding an Attempt inside its lease is executing.
Everything else — a stranded admission, a lapsed lease, a finished Attempt
under a Run nobody closed — is a stall, and stalls are what the window
forgets: the lease, not the Run's status, is what says a turn is alive, and
it is the liveness signal the spine already trusts
(`recover_abandoned_attempts` reclaims on exactly its expiry).

The window is per-process and starts empty after a restart, so a durable store
can still hold chat Runs that nothing will sweep. That gap is named in the ADR
and belongs to the durable spine (#132), which is where a startup sweep can see
the whole table; it is not a reason to leave the live process unbounded.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Container
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from maistro.runs.admission import admit_direct_work
from maistro.runs.archival import ArchivePolicy, RunArchiveSweeper
from maistro.runs.lifecycle import lease_is_expired
from maistro.runs.model import TERMINAL_ATTEMPT_STATUSES, TERMINAL_RUN_STATUSES, RunStatus
from maistro.runs.retention import RetentionPolicy, RunRetentionSweeper
from maistro.runs.retention_scope import WorkspaceRetentionScope
from maistro.runs.sources import CHAT_SOURCE
from maistro.runs.store import RunIntegrityError
from maistro.runs.task_kinds import resolve_direct_work

if TYPE_CHECKING:  # pragma: no cover - typing only
    from maistro.agents.intents import IntentRegistry
    from maistro.projects.scope_store import ProjectScopeStore
    from maistro.runs.model import Run
    from maistro.runs.store import RunStore

#: Provenance keys correlating the Run back to the conversation it belongs to.
SESSION_ID_KEY = "session_id"
REQUEST_ID_KEY = "request_id"

#: Provenance key recording that the turn's agent was not resolved at
#: admission, and its one value.
AGENT_SELECTION_KEY = "agent_selection"
DEFERRED_AGENT_SELECTION = "deferred"

#: How many chat-originated Runs one process keeps before sweeping. Small on
#: purpose: a chat Run's job is to be followable while the turn is in flight
#: and for a short while after, not to be an archive of what people typed. See
#: the ADR for why the number is this rather than the store's own bound.
MAX_RETAINED_CHAT_RUNS = 500

#: Node name used when a turn carries no usable text.
DEFAULT_TURN_NAME = "chat turn"


#: How much of a turn's answer the Run keeps. The Run is an audit record, not
#: a transcript store — the conversation itself lives in `maistro.sessions` —
#: and a chat Run's small size is part of why the retention window can be as
#: generous as it is (ADR-082326-c126).
MAX_RECORDED_ANSWER_CHARS = 2_000


#: What a failed chat turn records on its Run — a category, never the
#: exception text. `/runs/{run_id}` returns `Run.error` verbatim to anyone
#: holding the run_id, and a provider error's message carries the endpoint it
#: called and can carry the key it sent. The detail belongs in the log, which
#: is not handed out with a run_id.
UPSTREAM_FAILURE = "upstream_error"
INTERNAL_FAILURE = "internal_error"
TIMEOUT_FAILURE = "timeout"

#: What a compensated Run records when admission persisted a pre-RUNNING state
#: and then could not finish (#338). A category like the failure constants
#: above, and for the same reason: the exception that interrupted admission is
#: for the log, not for anyone holding the run_id.
ADMISSION_INCOMPLETE = "admission_incomplete"

#: What a compensated Run records when admission reached RUNNING durably but
#: nothing ever executed under it (#338). Distinct from `ADMISSION_INCOMPLETE`:
#: admission itself finished here -- what never started is the physical
#: Attempt, because the process died between `_admit_chat_turn` returning and
#: `ChatAttemptExecutor.execute()` persisting the turn's first NodeRun.
EXECUTION_NEVER_STARTED = "execution_never_started"


def failure_category(exc: BaseException) -> str:
    """The failure a chat Run may record, with no provider detail in it.

    Matched on the exception type rather than its message for the same reason
    the message is not recorded: the type is ours, the message is whatever the
    provider sent.
    """
    from maistro.agents.types import LLMProviderError

    if isinstance(exc, TimeoutError):
        return TIMEOUT_FAILURE
    if isinstance(exc, LLMProviderError):
        return UPSTREAM_FAILURE
    return INTERNAL_FAILURE


def chat_turn_outcome(response: dict[str, Any]) -> dict[str, Any]:
    """What a completed chat turn records on its Run.

    Enough to answer "what did this turn do", which for a Gate refusal is the
    refusal itself — the ADR promises that a blocked turn's answer is on the
    record, and a Run whose result is always None would not keep that promise.
    """
    choices = response.get("choices")
    first = choices[0] if isinstance(choices, list) and choices else {}
    message = first.get("message", {}) if isinstance(first, dict) else {}
    content = message.get("content", "") if isinstance(message, dict) else ""
    text = content if isinstance(content, str) else ""
    return {
        "finish_reason": first.get("finish_reason") if isinstance(first, dict) else None,
        "answer": text[:MAX_RECORDED_ANSWER_CHARS],
        "answer_truncated": len(text) > MAX_RECORDED_ANSWER_CHARS,
    }


def last_user_message(messages: list[dict[str, Any]]) -> str:
    """The text a chat turn is about: the last user message, or empty."""
    for message in reversed(messages):
        if message.get("role") == "user":
            content = message.get("content")
            return content if isinstance(content, str) else ""
    return ""


class ChatRunAdmitter:
    """Admit chat turns as canonical Runs and keep their number bounded."""

    def __init__(
        self,
        run_store: RunStore,
        *,
        workspace_id: str,
        project_id: str | None = None,
        project_store: ProjectScopeStore | None = None,
        intents: IntentRegistry | None = None,
        max_retained: int = MAX_RETAINED_CHAT_RUNS,
        retention: RetentionPolicy | None = None,
        archive: ArchivePolicy | None = None,
    ) -> None:
        if not workspace_id.strip():
            raise ValueError("workspace_id must be a non-empty string")
        if project_id is None and project_store is None:
            raise ValueError(
                "ChatRunAdmitter needs either an explicit project_id or a project_store "
                "to resolve the Workspace's Root Project"
            )
        if max_retained < 1:
            raise ValueError("max_retained must be >= 1")
        self._runs = run_store
        self._workspace_id = workspace_id
        self._project_id = project_id
        self._projects = project_store
        self._intents = intents
        self._max_retained = max_retained
        # Insertion-ordered, so the oldest admitted Run is the first candidate
        # to forget. Holding ids rather than Runs keeps the window itself cheap
        # — the Run is read back from the store only when it is a candidate.
        self._window: OrderedDict[str, None] = OrderedDict()
        # Runs the dispatching seam has admitted and will dispatch imminently.
        # Between admission returning and the turn's Attempt existing, a Run
        # shows RUNNING with nothing under it — indistinguishable, to a sweep,
        # from a turn whose dispatch never comes. The seam says which is which:
        # `route_request` marks its Run while the Run is still QUEUED and
        # releases it when the turn closes, and the window shields a marked
        # Run. A live turn is then bounded by how many turns can be in flight,
        # not by the window; an admission nobody will dispatch is never
        # marked, and is evictable like any other abandonment.
        self._dispatch_pending: set[str] = set()
        # One sweep at a time. Two overlapping admissions would otherwise both
        # snapshot the window, both await deletion of the same terminal Run,
        # and the loser would find its key already gone — an error raised after
        # a new Run had already been created, so the caller got no run_id for a
        # Run that then sat CREATED forever.
        self._sweep_lock = asyncio.Lock()
        # The durable half of the same policy (#132). The window above is
        # per-process and starts empty after a restart, so on a durable store a
        # chat Run admitted by a process that has since exited is one nothing
        # would ever sweep. Giving the Run a deadline at admission puts the
        # answer on the row, where a later process can act on it.
        self._retention = retention if retention is not None else RetentionPolicy()
        # The admitter's own Workspace is the sweep's whole deletion authority
        # (#1175): this sweeper can never purge another Workspace's expired
        # Runs, however shared the store underneath is.
        self._sweeper = RunRetentionSweeper(
            run_store,
            self._retention,
            scope=WorkspaceRetentionScope(workspace_id=self._workspace_id),
        )
        # The cold half of the same clock (#273). Deliberately a second
        # sweeper rather than a branch inside the first: archiving and
        # purging select disjoint populations (ADR-082226-f436 decision
        # 10), and one object that did both would be one edit away from
        # letting a storage decision stand in for a deletion decision.
        # Inert unless a deployment names a horizon, and inert on a store
        # that cannot archive.
        self._archive_sweeper = RunArchiveSweeper(run_store, archive)

    @property
    def retention(self) -> RetentionPolicy:
        """The durable retention policy this admitter stamps onto its Runs."""
        return self._retention

    @property
    def sweeper(self) -> RunRetentionSweeper:
        """The sweeper that enforces that policy against the store."""
        return self._sweeper

    @property
    def retained(self) -> int:
        """How many admitted chat Runs this process is still tracking."""
        return len(self._window)

    def mark_dispatch_pending(self, run_id: str) -> None:
        """Shield one admitted Run from the window until its dispatch settles.

        For the dispatching seam (`Container.route_request`), which marks its
        Run in the moment between the Run's QUEUED and RUNNING transitions —
        before any sweep can observe it RUNNING with no Attempt under it — and
        releases the mark when the turn closes. The mark must never outlive
        the dispatch it describes: every release sits on the seam's own exits,
        and a process death clears the set with the window that reads it.
        """
        self._dispatch_pending.add(run_id)

    def release_dispatch_pending(self, run_id: str) -> None:
        """Drop the dispatch shield; the Run stands on its lease and status."""
        self._dispatch_pending.discard(run_id)

    async def sweep(self) -> int:
        """Re-apply the window after a Run becomes terminal.

        Admission can only sweep Runs that are terminal at the time a new Run
        arrives. The canonical chat execution seam terminalizes after
        dispatch, so it calls this hook as well; otherwise a final burst that
        ends with no following admission would leave completed Runs beyond
        the policy window until the next turn.
        """
        return await self._sweep()

    async def admit(
        self,
        messages: list[dict[str, Any]],
        *,
        session_id: str | None = None,
        request_id: str | None = None,
        intent_hint: str = "",
        known_task_types: Container[str] | None = None,
        actor_principal_id: str | None = None,
    ) -> Run:
        """Admit one chat turn as a Run over the trivial one-node Graph.

        The agent is recorded only when the submission named an intent the
        deployment knows. That is the one case where admission can resolve the
        same agent the Conduit will: `_apply_intent_hint` overrides the
        classification with a valid hint, so registry resolution here and there
        agree by construction. Without a hint the Conduit classifies the
        message, and resolving the empty hint here would name the registry's
        fallback for work another agent went on to do — a canonical record
        contradicting what happened, which is worse than one that says the
        agent was not yet chosen.

        The Run deliberately keeps this admission-time fact as `deferred`. The
        Conduit reports the agent it actually dispatches, and #223 records that
        execution-time identity on the Attempt rather than rewriting this
        provenance after admission (ADR-082526-7f02).
        """
        description = last_user_message(messages) or DEFAULT_TURN_NAME
        hint = intent_hint.strip()
        hint_is_known = bool(hint) and (known_task_types is None or hint in known_task_types)
        work = resolve_direct_work(
            description=description,
            task_type=hint if hint_is_known else None,
            registry=self._intents,
        )
        parameters = dict(work.parameters)
        provenance: dict[str, Any] = {}
        if not hint_is_known:
            parameters["to_agent"] = ""
            # Named, so a blank `to_agent` reads as "not chosen yet" rather
            # than as a resolution that happened to come out empty.
            provenance[AGENT_SELECTION_KEY] = DEFERRED_AGENT_SELECTION
        if session_id:
            provenance[SESSION_ID_KEY] = session_id
        if request_id:
            provenance[REQUEST_ID_KEY] = request_id
        run = await admit_direct_work(
            self._runs,
            workspace_id=self._workspace_id,
            project_id=await self._resolve_project_id(),
            node_type=work.node_type,
            name=work.name,
            source=CHAT_SOURCE,
            parameters=parameters,
            description=description,
            actor_principal_id=actor_principal_id,
            provenance=provenance,
            retention_expires_at=self._retention.deadline(),
        )
        self._window[run.run_id] = None
        await self._sweep()
        # Opportunistic, and deliberately after the Run is safely created: the
        # sweep is bounded and rate-limited by the policy, it swallows its own
        # errors, and a turn is never refused because retention could not run.
        # This is what closes the restart gap — the window this process holds
        # says nothing about the Runs a previous one left behind.
        await self._sweeper.maybe_sweep()
        # And the cold sweep, on the same tick. This turn's own Run is the
        # one thing it will never touch -- a chat Run carries a retention
        # deadline, which makes it purge-eligible and therefore never
        # archive-eligible. Admission is the clock here, not the subject.
        await self._archive_sweeper.maybe_sweep()
        return run

    async def _sweep(self) -> int:
        """Forget the oldest chat Runs above the retention window.

        Returns how many were forgotten. A non-terminal Run is forgotten like
        any other once nothing under it is executing any more, and skipped
        only while a turn could still be living in it: dispatch-pending (the
        seam admitted it and has not settled its dispatch), still
        CREATED/QUEUED (mid-admission, which the admission path compensates
        itself), or holding an Attempt inside its lease. The stall shapes — a
        stranded admission with no Attempt, a finished Attempt under a Run
        nobody closed, a lapsed lease — all leave a Run that will never
        terminalize on its own, and a window that shields every non-terminal
        Run grows without limit exactly when the process is misbehaving,
        which is when it must not.
        """
        forgotten = 0
        async with self._sweep_lock:
            for run_id in list(self._window):
                # `len` is read fresh each pass: the deletions below shrink the
                # window as they go, so a saved count would sweep too far.
                if len(self._window) <= self._max_retained:
                    break
                run = await self._runs.get_run(run_id)
                if run is None:
                    # Already gone — another sweep, or the store's own bound.
                    if self._window.pop(run_id, None) is not None:
                        forgotten += 1
                    continue
                terminal = run.status in TERMINAL_RUN_STATUSES
                if not terminal and await self._a_turn_could_still_live_here(run_id, run):
                    continue
                try:
                    # `force` is the store's contract for a caller that has
                    # established the Run is abandoned — which the checks
                    # above just did, and the store re-checks what only it
                    # knows (child Runs) on the way down.
                    await self._runs.delete_run(run_id, force=not terminal)
                except RunIntegrityError:
                    # A parent with a child Run is intentionally not deletable.
                    # Keep walking: a protected old Run must not strand younger
                    # ones that can be forgotten.
                    continue
                # `pop`, not `del`: the lock makes a concurrent sweep
                # impossible, but a caller may also have deleted this Run
                # directly, and a sweep must not fail over work it wanted done.
                if self._window.pop(run_id, None) is not None:
                    forgotten += 1
        return forgotten

    async def _a_turn_could_still_live_here(self, run_id: str, run: Run) -> bool:
        """Whether a non-terminal Run is shielded from the window.

        Three shields, each answering "could a turn still be living in this
        Run?" with a signal the spine already trusts, never with the status
        byte alone — that is the test the pre-repair sweep used, and it is
        what let stalled turns hold the window open forever.

        - **Dispatch-pending**: the seam admitted this Run and its dispatch
          has not settled yet. `route_request` marks between the Run's QUEUED
          and RUNNING transitions, so a sweep never observes the RUNNING,
          Attempt-less, unmarked moment.
        - **Still CREATED/QUEUED**: mid-admission, or an admission its caller
          has not finished. The admission path owns these states and
          compensates its own — a failed admission cancels a CREATED/QUEUED
          Run on the spot — so the window neither evicts them nor owes them
          a bound.
        - **Executing**: an open Attempt inside its lease. A *finished*
          Attempt and a *lapsed* lease are stalls, not turns, and do not
          shield — see `_turn_is_executing`.
        """
        if run_id in self._dispatch_pending:
            return True
        if run.status in (RunStatus.CREATED, RunStatus.QUEUED):
            return True
        return await self._turn_is_executing(run_id)

    async def _turn_is_executing(self, run_id: str) -> bool:
        """Whether anything under this Run is still executing inside its lease.

        The chat executor leases every Attempt it creates and renews it while
        the turn runs (#1170), so an open Attempt with an unexpired lease is
        work in flight. A *finished* Attempt does not shield its Run — that is
        a turn whose executor died between the Attempt completing and the Run
        closing, which is a stall, not a turn. Neither does an expired lease,
        by the same rule `recover_abandoned_attempts` reclaims on. An open
        Attempt with no lease at all shields: a deployment that opted its chat
        executor out of leases has no better signal, and the conservative
        reading is the one that never deletes possibly-live work.
        """
        moment = datetime.now(UTC)
        for node_run in await self._runs.list_node_runs(run_id):
            for attempt in await self._runs.list_attempts(node_run.node_run_id):
                if attempt.status not in TERMINAL_ATTEMPT_STATUSES and not lease_is_expired(
                    attempt, moment
                ):
                    return True
        return False

    async def _resolve_project_id(self) -> str:
        if self._project_id is not None:
            return self._project_id
        if self._projects is None:  # pragma: no cover - guarded in __init__
            raise RuntimeError("ChatRunAdmitter has no project_store to resolve a Project")
        root = await self._projects.root_for_workspace(self._workspace_id)
        self._project_id = root.project_id
        return self._project_id


__all__ = [
    "ADMISSION_INCOMPLETE",
    "AGENT_SELECTION_KEY",
    "CHAT_SOURCE",
    "DEFAULT_TURN_NAME",
    "DEFERRED_AGENT_SELECTION",
    "EXECUTION_NEVER_STARTED",
    "MAX_RECORDED_ANSWER_CHARS",
    "MAX_RETAINED_CHAT_RUNS",
    "REQUEST_ID_KEY",
    "SESSION_ID_KEY",
    "ChatRunAdmitter",
    "chat_turn_outcome",
    "last_user_message",
]
