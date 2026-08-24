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
keeps its own small window of the Runs it admitted and deletes the oldest
terminal ones as it overflows, which holds on any store rather than only the
one that happens to prune.

The window is per-process and starts empty after a restart, so a durable store
can still hold chat Runs that nothing will sweep. That gap is named in the ADR
and belongs to the durable spine (#132), which is where a startup sweep can see
the whole table; it is not a reason to leave the live process unbounded.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Container
from typing import TYPE_CHECKING, Any

from maistro.runs.admission import admit_direct_work
from maistro.runs.model import TERMINAL_RUN_STATUSES
from maistro.runs.retention import RetentionPolicy, RunRetentionSweeper
from maistro.runs.sources import CHAT_SOURCE
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
        self._sweeper = RunRetentionSweeper(run_store, self._retention)

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

        Binding the *actually dispatched* agent onto the Run needs the Conduit
        to report its selection, which is #142's convergence.
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
        return run

    async def _sweep(self) -> int:
        """Forget the oldest terminal chat Runs above the retention window.

        Returns how many were forgotten. A non-terminal Run at the front is
        skipped, not deleted and not counted against the window's head: work in
        flight keeps its identity however old it is, and a window full of live
        Runs therefore grows rather than eating them — the same failure the
        store's own bound chooses, and for the same reason.
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
                if run.status not in TERMINAL_RUN_STATUSES:
                    continue
                await self._runs.delete_run(run_id)
                # `pop`, not `del`: the lock makes a concurrent sweep
                # impossible, but a caller may also have deleted this Run
                # directly, and a sweep must not fail over work it wanted done.
                if self._window.pop(run_id, None) is not None:
                    forgotten += 1
        return forgotten

    async def _resolve_project_id(self) -> str:
        if self._project_id is not None:
            return self._project_id
        if self._projects is None:  # pragma: no cover - guarded in __init__
            raise RuntimeError("ChatRunAdmitter has no project_store to resolve a Project")
        root = await self._projects.root_for_workspace(self._workspace_id)
        self._project_id = root.project_id
        return self._project_id


__all__ = [
    "AGENT_SELECTION_KEY",
    "CHAT_SOURCE",
    "DEFAULT_TURN_NAME",
    "DEFERRED_AGENT_SELECTION",
    "MAX_RECORDED_ANSWER_CHARS",
    "MAX_RETAINED_CHAT_RUNS",
    "REQUEST_ID_KEY",
    "SESSION_ID_KEY",
    "ChatRunAdmitter",
    "chat_turn_outcome",
    "last_user_message",
]
