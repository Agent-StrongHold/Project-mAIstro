"""Live Turing cognitive state, scoped to canonical Workspace principals (#859).

Every piece of private cognitive state — the self-model snapshot (mood,
personality facets) and chat sessions — is keyed by the canonical Workspace
identity the execution plane resolves for the authenticated principal. There is
no process-global self model to fall back on: a scope-less accessor refuses
rather than silently sharing one Workspace's mind with another.

Restart and replica semantics are explicit, not implied:

- The default ``InProcessSelfModelStateStore`` is ephemeral and authoritative
  for exactly one process. A restart starts every Workspace from the default
  self model; the durable trace of cognition is the episodic memory produced
  through the memory bridge, wherever a durable episodic store is composed.
- Chat sessions are disposable by contract: process-local, TTL- and
  cardinality-bounded, and truthfully lost on restart. A returning client
  reconnects to a fresh session, never to a stale one that survived.
- A multi-replica deployment cannot enable replicas against the divergent
  process-local authority: composition refuses (``TURING_REPLICA_COUNT > 1``
  with no shared ``SelfModelStateStore``). Composing a shared store
  implementation is the single seam that makes self-model state survive
  restarts and stay consistent across replicas.

The producer-artifact feed is the one deliberately shared surface: it is
published content (each artifact names its ``self_id`` provenance), not private
cognitive state, and it is bounded in count and payload size.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable
from uuid import uuid4

from maistro.observability.correlation import current_execution_context
from maistro_turing.bridge import (
    TuringClassifierBridge,
    TuringMemoryBridge,
    TuringProviderBridge,
    TuringSecurityBridge,
)
from maistro_turing.runtime import TuringActor, TuringChatSession, TuringConfig
from maistro_turing.self_model import ALL_FACETS, Mood

from .config import replica_count
from .security import TuringInboundSecurity, TuringSecurityContext

SELF_ID = "turing"

# The producer kinds Turing emits. Mirrors the producer classes in
# maistro_turing.producers (blog / self-reflection / curiosity / emotion).
ARTIFACT_KINDS = frozenset({"blog", "reflection", "curiosity", "emotion"})

# Published-content bounds. The feed is shared by contract, so its growth is
# bounded here rather than trusted to callers.
MAX_ARTIFACTS = 500
MAX_ARTIFACT_TITLE_CHARS = 200
MAX_ARTIFACT_BODY_CHARS = 20_000

# Chat-session bounds (#859): cardinality and lifetime are declared here, not
# implicit in however many session ids callers happen to invent.
MAX_CHAT_SESSIONS = 256
CHAT_SESSION_TTL_SECONDS = 60.0 * 60.0
MAX_SESSION_ID_CHARS = 128


def _now() -> datetime:
    return datetime.now(UTC)


def _default_mood() -> Mood:
    return Mood(
        self_id=SELF_ID,
        valence=0.2,
        arousal=0.5,
        focus=0.6,
        last_tick_at=_now(),
    )


def _default_facet_scores() -> dict[str, float]:
    return {facet: 3.0 for _trait, facet in ALL_FACETS}


@dataclass
class WorkspaceSelfModelState:
    """One Workspace's self-model snapshot — the state one principal owns.

    A fresh scope starts from the documented defaults; nothing is inherited
    from another Workspace or from a process-wide baseline.

    M1 product-local projection: Workspace

    Not the canonical Workspace model — ``maistro.workspaces`` owns that.
    This is Turing's optional cognitive state keyed by the canonical
    ``workspace_id`` the execution plane resolves; it holds no shared
    semantics of its own.
    """

    workspace_id: str
    mood: Mood = field(default_factory=_default_mood)
    facet_scores: dict[str, float] = field(default_factory=_default_facet_scores)


@runtime_checkable
class SelfModelStateStore(Protocol):
    """Where scoped self-model state lives.

    The in-process implementation below is the single-replica default. A
    durable deployment (restart survival, replica consistency) composes its
    own implementation behind this contract; no other code changes.
    """

    def load_scope(self, workspace_id: str) -> WorkspaceSelfModelState | None: ...

    def save_scope(self, workspace_id: str, state: WorkspaceSelfModelState) -> None: ...


class InProcessSelfModelStateStore:
    """Process-local backing store: ephemeral, single-writer, one process.

    Stated rather than implied: state kept here dies with the process and must
    never be presented as durable or replica-consistent. ``reset_state``
    refuses this store for a multi-replica deployment declaration.
    """

    def __init__(self) -> None:
        self._scopes: dict[str, WorkspaceSelfModelState] = {}

    def load_scope(self, workspace_id: str) -> WorkspaceSelfModelState | None:
        return self._scopes.get(workspace_id)

    def save_scope(self, workspace_id: str, state: WorkspaceSelfModelState) -> None:
        self._scopes[workspace_id] = state


@dataclass
class ChatSessionEntry:
    """One live chat session, owned by exactly one Workspace scope."""

    session: TuringChatSession
    workspace_id: str
    created_at: datetime
    last_used_at: datetime


class ChatSessionRegistry:
    """Bounded, workspace-owned registry of live chat sessions.

    Sessions are keyed by ``(workspace_id, session_id)``: the client-supplied
    session id selects a conversation *inside* the caller's resolved scope and
    never decides ownership or authorization. A guessed or colliding id from
    another Workspace resolves to that Workspace's own (absent) entry, so
    session-id guessing collapses into an isolated fresh session, never into
    someone else's conversation.

    Cardinality is capped (LRU eviction) and lifetime is TTL-bounded, swept on
    access. Entries are disposable: nothing here survives a restart, and the
    durable trace of a conversation is the episodic chat capture.
    """

    def __init__(
        self,
        *,
        max_sessions: int = MAX_CHAT_SESSIONS,
        ttl_seconds: float = CHAT_SESSION_TTL_SECONDS,
    ) -> None:
        if max_sessions < 1:
            raise ValueError("max_sessions must be >= 1")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._entries: OrderedDict[tuple[str, str], ChatSessionEntry] = OrderedDict()
        self._lock = threading.RLock()
        self._max_sessions = max_sessions
        self._ttl = timedelta(seconds=ttl_seconds)

    def resolve(
        self,
        *,
        workspace_id: str,
        session_id: str,
        factory: Callable[[], TuringChatSession],
    ) -> TuringChatSession:
        """Return the caller's session for this id, creating it if absent."""
        _require_scope(workspace_id)
        if not session_id or not session_id.strip():
            raise ValueError("session_id must be a non-empty string")
        if len(session_id) > MAX_SESSION_ID_CHARS:
            raise ValueError(
                f"session_id exceeds {MAX_SESSION_ID_CHARS} characters: {len(session_id)}"
            )
        with self._lock:
            self._sweep_expired()
            key = (workspace_id, session_id)
            entry = self._entries.get(key)
            if entry is not None:
                entry.last_used_at = _now()
                self._entries.move_to_end(key)
                return entry.session
            session = factory()
            self._entries[key] = ChatSessionEntry(
                session=session,
                workspace_id=workspace_id,
                created_at=_now(),
                last_used_at=_now(),
            )
            while len(self._entries) > self._max_sessions:
                self._entries.popitem(last=False)
            return session

    def _sweep_expired(self) -> None:
        cutoff = _now() - self._ttl
        expired = [k for k, e in self._entries.items() if e.last_used_at < cutoff]
        for key in expired:
            self._entries.pop(key, None)

    def active_count(self) -> int:
        with self._lock:
            self._sweep_expired()
            return len(self._entries)


@dataclass
class ProducerArtifact:
    """A single static artifact produced by one of Turing's producers.

    Published content is bounded at the write seam: oversized payloads are
    refused here rather than accepted into process memory (#859).
    """

    artifact_id: str
    self_id: str
    kind: str
    title: str
    body: str
    created_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        if not isinstance(self.title, str) or len(self.title) > MAX_ARTIFACT_TITLE_CHARS:
            raise ValueError(
                f"artifact title must be a string of <= {MAX_ARTIFACT_TITLE_CHARS} chars"
            )
        if not isinstance(self.body, str) or len(self.body) > MAX_ARTIFACT_BODY_CHARS:
            raise ValueError(
                f"artifact body must be a string of <= {MAX_ARTIFACT_BODY_CHARS} chars"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "artifact_id": self.artifact_id,
            "self_id": self.self_id,
            "kind": self.kind,
            "title": self.title,
            "body": self.body,
            "created_at": self.created_at.isoformat(),
        }


def _require_scope(workspace_id: str) -> None:
    """Refuse scope-less access: there is no global self model to fall back on."""
    if not isinstance(workspace_id, str) or not workspace_id.strip():
        raise LookupError(
            "a canonical Workspace scope is required for Turing cognitive state; "
            "there is no process-global self model"
        )


class TuringState:
    """Live state for the backend, partitioned by canonical Workspace scope.

    Thread-safe for the simple read/append/replace operations the routes need;
    a TestClient drives requests on a thread pool so the lock matters. Every
    self-model accessor names its Workspace; the routes resolve that Workspace
    through the execution plane from the authenticated principal, so identity
    and scope come from the canonical spine, never from the request body.
    """

    def __init__(
        self,
        config: TuringConfig | None = None,
        *,
        inbound_security: TuringInboundSecurity | None = None,
        state_store: SelfModelStateStore | None = None,
        session_registry: ChatSessionRegistry | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self.config = config or TuringConfig()
        if inbound_security is None:
            raise RuntimeError("canonical Turing security is required for backend startup")
        self.inbound_security = inbound_security
        self.state_store: SelfModelStateStore = state_store or InProcessSelfModelStateStore()
        self.sessions = session_registry or ChatSessionRegistry()

        self._artifacts: list[ProducerArtifact] = []

        # Memory and provider implementations remain optional, but the
        # canonical Warden is mandatory for every protected runtime path.
        self.memory = TuringMemoryBridge()
        self.security = TuringSecurityBridge(
            warden=self.inbound_security.warden,
            audit_hook=self._audit_runtime_verdict,
        )
        self.provider = TuringProviderBridge()
        self.classifier = TuringClassifierBridge()

        self.actor = TuringActor(
            memory=self.memory,
            security=self.security,
            provider=self.provider,
            self_id=SELF_ID,
        )

    async def _audit_runtime_verdict(self, verdict: object, content: str, boundary: str) -> None:
        execution = current_execution_context()
        if not execution.run_id:
            raise RuntimeError("canonical Run context is required for runtime security audit")

        # Model/tool output is produced inside a canonical Run. Resolve every
        # audit identity from that Run rather than attributing it to Turing.
        from .execution import get_execution_plane

        run = await get_execution_plane().run_store.get_run(execution.run_id)
        if run is None or not run.actor_principal_id:
            raise RuntimeError("canonical Run actor is unavailable for security audit")

        await self.inbound_security.audit_verdict(
            verdict,  # type: ignore[arg-type]
            content,
            boundary=boundary,
            context=TuringSecurityContext(
                principal=str(run.actor_principal_id),
                route="runtime",
                action=f"turing.{boundary}",
                workspace_id=run.workspace_id,
                project_id=run.project_id,
                run_id=run.run_id,
                invocation_id=execution.invocation_id,
            ),
        )

    # ------------------------------------------------- self-model (scoped) --

    def _scope(self, workspace_id: str) -> WorkspaceSelfModelState:
        """Load (or materialize) one Workspace's state — the only scope seam."""
        _require_scope(workspace_id)
        state = self.state_store.load_scope(workspace_id)
        if state is None:
            state = WorkspaceSelfModelState(workspace_id=workspace_id)
            self.state_store.save_scope(workspace_id, state)
        return state

    def mood_snapshot(self, workspace_id: str) -> Mood:
        _require_scope(workspace_id)
        with self._lock:
            return self._scope(workspace_id).mood

    def facet_scores(self, workspace_id: str) -> dict[str, float]:
        _require_scope(workspace_id)
        with self._lock:
            return dict(self._scope(workspace_id).facet_scores)

    def set_mood(self, workspace_id: str, **fields: float) -> Mood:
        """Validated mood mutation for exactly one Workspace scope.

        The ``Mood`` constructor is the range authority (valence [-1, 1],
        arousal/focus [0, 1]); an out-of-range proposal raises here and never
        reaches the snapshot. Every mood write in the backend goes through
        this method — there is no second mutation path.
        """
        _require_scope(workspace_id)
        with self._lock:
            current = self._scope(workspace_id)
            updated = Mood(
                self_id=SELF_ID,
                valence=fields.get("valence", current.mood.valence),
                arousal=fields.get("arousal", current.mood.arousal),
                focus=fields.get("focus", current.mood.focus),
                last_tick_at=current.mood.last_tick_at,
                updated_at=_now(),
            )
            current.mood = updated
            self.state_store.save_scope(workspace_id, current)
            return updated

    def set_facet(self, workspace_id: str, facet_id: str, score: float) -> None:
        """Validated facet mutation for exactly one Workspace scope."""
        _require_scope(workspace_id)
        with self._lock:
            current = self._scope(workspace_id)
            if facet_id not in current.facet_scores:
                raise KeyError(facet_id)
            if not 1.0 <= score <= 5.0:
                raise ValueError(f"facet score out of range: {score}")
            current.facet_scores[facet_id] = float(score)
            self.state_store.save_scope(workspace_id, current)

    # ------------------------------------------------------------- feed ------

    def add_artifact(self, kind: str, title: str, body: str) -> ProducerArtifact:
        if kind not in ARTIFACT_KINDS:
            raise ValueError(f"unknown artifact kind: {kind}")
        with self._lock:
            artifact = ProducerArtifact(
                artifact_id=str(uuid4()),
                self_id=SELF_ID,
                kind=kind,
                title=title,
                body=body,
            )
            self._artifacts.append(artifact)
            if len(self._artifacts) > MAX_ARTIFACTS:
                del self._artifacts[:-MAX_ARTIFACTS]
            return artifact

    def list_artifacts(
        self,
        *,
        kind: str | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[ProducerArtifact], int]:
        with self._lock:
            items = list(reversed(self._artifacts))
            if kind:
                items = [a for a in items if a.kind == kind]
            total = len(items)
            return items[offset : offset + limit], total

    def get_artifact(self, artifact_id: str) -> ProducerArtifact | None:
        with self._lock:
            for artifact in self._artifacts:
                if artifact.artifact_id == artifact_id:
                    return artifact
            return None

    # ------------------------------------------------------------- chat -----

    def new_chat_session(self) -> TuringChatSession:
        return TuringChatSession(
            memory=self.memory,
            provider=self.provider,
            classifier=self.classifier,
            security=self.security,
            self_id=SELF_ID,
        )


_state: TuringState | None = None


def get_state() -> TuringState:
    if _state is None:
        raise RuntimeError("canonical Turing security has not been composed")
    return _state


def _guard_replica_authority(state_store: SelfModelStateStore | None) -> None:
    """Refuse a multi-replica declaration over the divergent process-local store.

    The in-process store is authoritative for exactly one process. Letting N
    replicas each keep their own authoritative self model would silently
    diverge them; the deployment must either declare one process or compose a
    shared ``SelfModelStateStore``. Fail composition, not correctness (#859).
    """
    if state_store is None and replica_count() > 1:
        raise RuntimeError(
            f"TURING_REPLICA_COUNT={replica_count()} declares a multi-replica "
            "Turing deployment, but no shared SelfModelStateStore is composed; "
            "the process-local self-model authority would diverge across "
            "replicas. Compose a shared store implementation to enable replicas."
        )


def reset_state(
    config: TuringConfig | None = None,
    *,
    inbound_security: TuringInboundSecurity,
    state_store: SelfModelStateStore | None = None,
) -> TuringState:
    """Replace the singleton — used by tests and the composition root."""
    global _state
    _guard_replica_authority(state_store)
    _state = TuringState(config=config, inbound_security=inbound_security, state_store=state_store)
    return _state
