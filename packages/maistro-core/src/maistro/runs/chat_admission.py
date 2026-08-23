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

from collections import OrderedDict
from typing import TYPE_CHECKING, Any

from maistro.runs.admission import admit_direct_work
from maistro.runs.model import TERMINAL_RUN_STATUSES
from maistro.runs.task_kinds import resolve_direct_work

if TYPE_CHECKING:  # pragma: no cover - typing only
    from maistro.agents.intents import IntentRegistry
    from maistro.projects.scope_store import ProjectScopeStore
    from maistro.runs.model import Run
    from maistro.runs.store import RunStore

#: `admission_source` value for work that entered as a chat turn.
CHAT_SOURCE = "chat"

#: Provenance keys correlating the Run back to the conversation it belongs to.
SESSION_ID_KEY = "session_id"
REQUEST_ID_KEY = "request_id"

#: How many chat-originated Runs one process keeps before sweeping. Small on
#: purpose: a chat Run's job is to be followable while the turn is in flight
#: and for a short while after, not to be an archive of what people typed. See
#: the ADR for why the number is this rather than the store's own bound.
MAX_RETAINED_CHAT_RUNS = 500

#: Node name used when a turn carries no usable text.
DEFAULT_TURN_NAME = "chat turn"


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
        actor_principal_id: str | None = None,
    ) -> Run:
        """Admit one chat turn as a Run over the trivial one-node Graph."""
        description = last_user_message(messages) or DEFAULT_TURN_NAME
        work = resolve_direct_work(
            description=description,
            task_type=intent_hint,
            registry=self._intents,
        )
        provenance: dict[str, Any] = {}
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
            parameters=work.parameters,
            description=description,
            actor_principal_id=actor_principal_id,
            provenance=provenance,
        )
        self._window[run.run_id] = None
        await self._sweep()
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
        for run_id in list(self._window):
            # `len` is read fresh each pass: the deletions below shrink the
            # window as they go, so a saved count would sweep too far.
            if len(self._window) <= self._max_retained:
                break
            run = await self._runs.get_run(run_id)
            if run is None:
                # Already gone — another sweep, or the store's own bound.
                del self._window[run_id]
                forgotten += 1
                continue
            if run.status not in TERMINAL_RUN_STATUSES:
                continue
            await self._runs.delete_run(run_id)
            del self._window[run_id]
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
    "CHAT_SOURCE",
    "DEFAULT_TURN_NAME",
    "MAX_RETAINED_CHAT_RUNS",
    "REQUEST_ID_KEY",
    "SESSION_ID_KEY",
    "ChatRunAdmitter",
    "last_user_message",
]
