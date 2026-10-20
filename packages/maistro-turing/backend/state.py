"""Live Turing cognitive state, scoped to canonical Workspace principals (#859).

Holds the per-Workspace in-memory self-model scopes, the producer-artifact
feed, and the wired runtime objects (actor / chat / bridges). Routes read and
mutate this composed object.

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
  restarts and stay consistent across replicas — and because the execution
  plane resolves the same deterministic Workspace id for a principal in every
  process, a shared store actually converges instead of silently forking one
  Workspace's state per replica.

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
# implicit in however many session ids callers happen to invent. Both bounds
# are enforced per Workspace partition, so one scope cannot spend another
# scope's capacity.
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


def _require_scope(workspace_id: str) -> None:
    """Refuse scope-less access: there is no global self model to fall back on."""
    if not isinstance(workspace_id, str) or not workspace_id.strip():
        raise LookupError(
            "a canonical Workspace scope is required for Turing cognitive state; "
            "there is no process-global self model"
        )


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
    """Where scoped self-model snapshots persist.

    The protocol is the durability seam (#859): the default implementation is
    process-local and ephemeral; a deployment that needs restart survival or
    replica consistency composes a shared implementation here, without the
    state machine or routes knowing the difference. Implementations must
    explicitly declare whether they are shared across replicas; an arbitrary
    injected store is not evidence of replica-safe authority.
    """

    is_shared_across_replicas: bool

    def load_scope(self, workspace_id: str) -> WorkspaceSelfModelState | None: ...

    def save_scope(self, workspace_id: str, state: WorkspaceSelfModelState) -> None: ...


class InProcessSelfModelStateStore:
    """Process-local backing store: ephemeral, single-writer, one process.

    Stated rather than implied: state kept here dies with the process and must
    never be presented as durable or replica-consistent. ``reset_state``
    refuses this store for a multi-replica deployment declaration.
    """

    is_shared_across_replicas = False

    def __init__(self) -> None:
        self._scopes: dict[str, WorkspaceSelfModelState] = {}

    def load_scope(self, workspace_id: str) -> WorkspaceSelfModelState | None:
        state = self._scopes.get(workspace_id)
        if state is None:
            return None
        # Defensive copy: a caller that mutates the returned snapshot (or
        # its mood/facet map) cannot bypass the validated mutation seam and
        # corrupt the authoritative stored scope (#859).
        return WorkspaceSelfModelState(
            workspace_id=state.workspace_id,
            mood=Mood(
                self_id=state.mood.self_id,
                valence=state.mood.valence,
                arousal=state.mood.arousal,
                focus=state.mood.focus,
                last_tick_at=state.mood.last_tick_at,
                updated_at=state.mood.updated_at,
            ),
            facet_scores=dict(state.facet_scores),
        )

    def save_scope(self, workspace_id: str, state: WorkspaceSelfModelState) -> None:
        # Store a defensive copy so later mutation of the caller's object
        # cannot retroactively change persisted state (#859).
        self._scopes[workspace_id] = WorkspaceSelfModelState(
            workspace_id=state.workspace_id,
            mood=Mood(
                self_id=state.mood.self_id,
                valence=state.mood.valence,
                arousal=state.mood.arousal,
                focus=state.mood.focus,
                last_tick_at=state.mood.last_tick_at,
                updated_at=state.mood.updated_at,
            ),
            facet_scores=dict(state.facet_scores),
        )


@dataclass
class ChatSessionEntry:
    """One live chat session, owned by exactly one Workspace scope."""

    session: TuringChatSession
    workspace_id: str
    created_at: datetime
    last_used_at: datetime


class ChatSessionRegistry:
    """Bounded, Workspace-partitioned registry of live chat sessions.

    Sessions are keyed by ``(workspace_id, session_id)``: the client-supplied
    session id selects a conversation *inside* the caller's resolved scope and
    never decides ownership or authorization. A guessed or colliding id from
    another Workspace resolves to that Workspace's own (absent) entry, so
    session-id guessing collapses into an isolated fresh session, never into
    someone else's conversation.

    Capacity and LRU are enforced *within* each Workspace's own partition: a
    Workspace holds at most ``max_sessions`` sessions and eviction removes only
    that Workspace's least-recently-used entry, so flooding distinct session
    ids can never evict another Workspace's live session. Lifetime is
    TTL-bounded, swept on access; because every hit also moves its entry to the
    partition's recency end, a frozen or coarse clock still evicts the true
    least-recently-used session. Entries are disposable: nothing here survives
    a restart, and the durable trace of a conversation is the episodic chat
    capture.
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
        # workspace_id -> (session_id -> entry), each partition an OrderedDict
        # kept in LRU order: every hit does move_to_end and every create
        # appends, so the front entry is the true LRU even when timestamps tie.
        self._partitions: dict[str, OrderedDict[str, ChatSessionEntry]] = {}
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
            partition = self._partitions.get(workspace_id)
            if partition is None:
                partition = self._partitions[workspace_id] = OrderedDict()
            entry = partition.get(session_id)
            if entry is not None:
                entry.last_used_at = _now()
                partition.move_to_end(session_id)
                return entry.session
            while len(partition) >= self._max_sessions:
                partition.popitem(last=False)  # this Workspace's own LRU only
            partition[session_id] = ChatSessionEntry(
                session=factory(),
                workspace_id=workspace_id,
                created_at=_now(),
                last_used_at=_now(),
            )
            return partition[session_id].session

    def _sweep_expired(self) -> None:
        """Drop entries idle past the TTL, then empty partitions. Lock required."""
        cutoff = _now() - self._ttl
        for partition in self._partitions.values():
            expired = [sid for sid, e in partition.items() if e.last_used_at < cutoff]
            for sid in expired:
                del partition[sid]
        for workspace_id in [w for w, p in self._partitions.items() if not p]:
            del self._partitions[workspace_id]

    def active_count(self) -> int:
        with self._lock:
            self._sweep_expired()
            return sum(len(partition) for partition in self._partitions.values())


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
        # Refuse a multi-replica declaration over the divergent process-local
        # store at composition time, even when TuringState is constructed
        # directly rather than through reset_state (#859).
        _guard_replica_authority(state_store)
        # An injected store is selected by identity, not truthiness (#859): an
        # empty mapping-backed shared store is falsey but is still the
        # deployment's chosen authority — replacing it here would silently
        # downgrade durability to the process-local default.
        self.state_store: SelfModelStateStore = (
            state_store if state_store is not None else InProcessSelfModelStateStore()
        )
        self.sessions = session_registry if session_registry is not None else ChatSessionRegistry()

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
            mood = self._scope(workspace_id).mood
            return Mood(
                self_id=mood.self_id,
                valence=mood.valence,
                arousal=mood.arousal,
                focus=mood.focus,
                last_tick_at=mood.last_tick_at,
                updated_at=mood.updated_at,
            )

    def facet_scores(self, workspace_id: str) -> dict[str, float]:
        _require_scope(workspace_id)
        with self._lock:
            return dict(self._scope(workspace_id).facet_scores)

    def set_mood(self, workspace_id: str, **fields: float) -> Mood:
        """Validated mood mutation for exactly one Workspace scope.

        The ``Mood`` constructor is the range authority (valence [-1, 1],
        arousal/focus [0, 1]); the candidate is validated before any state is
        materialized or replaced, so a rejected write persists nothing and
        leaves no default scope behind for a previously unseen Workspace.
        Every mood write in the backend goes through this method — there is
        no second mutation path.
        """
        _require_scope(workspace_id)
        with self._lock:
            current = self.state_store.load_scope(workspace_id)
            base = current.mood if current is not None else _default_mood()
            updated = Mood(
                self_id=SELF_ID,
                valence=fields.get("valence", base.valence),
                arousal=fields.get("arousal", base.arousal),
                focus=fields.get("focus", base.focus),
                last_tick_at=base.last_tick_at,
                updated_at=_now(),
            )
            if current is not None:
                current.mood = updated
                self.state_store.save_scope(workspace_id, current)
            else:
                self.state_store.save_scope(
                    workspace_id,
                    WorkspaceSelfModelState(workspace_id=workspace_id, mood=updated),
                )
            return Mood(
                self_id=updated.self_id,
                valence=updated.valence,
                arousal=updated.arousal,
                focus=updated.focus,
                last_tick_at=updated.last_tick_at,
                updated_at=updated.updated_at,
            )

    def set_facet(self, workspace_id: str, facet_id: str, score: float) -> None:
        """Validated facet mutation for exactly one Workspace scope.

        Like ``set_mood``, the candidate is validated against the scope's
        candidate facet map before any state is materialized or replaced: a
        rejected write persists nothing and installs no default scope.
        """
        _require_scope(workspace_id)
        with self._lock:
            current = self.state_store.load_scope(workspace_id)
            scores = dict(current.facet_scores) if current is not None else _default_facet_scores()
            if facet_id not in scores:
                raise KeyError(facet_id)
            if not 1.0 <= score <= 5.0:
                raise ValueError(f"facet score out of range: {score}")
            scores[facet_id] = float(score)
            if current is not None:
                current.facet_scores = scores
                self.state_store.save_scope(workspace_id, current)
            else:
                self.state_store.save_scope(
                    workspace_id,
                    WorkspaceSelfModelState(workspace_id=workspace_id, facet_scores=scores),
                )

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

    def new_chat_session(
        self,
        *,
        user_id: str = "",
        workspace_id: str = "",
        project_id: str = "",
    ) -> TuringChatSession:
        """Create one disposable chat session, bound to its caller's scope.

        The scope rides on the session so the episodic chat capture persists
        with the caller's provenance (user/project) instead of blank scope
        fields — unscoped captures from different Workspaces would be
        indistinguishable in a shared episodic store (#859).
        """
        return TuringChatSession(
            memory=self.memory,
            provider=self.provider,
            classifier=self.classifier,
            security=self.security,
            self_id=SELF_ID,
            user_id=user_id,
            workspace_id=workspace_id,
            project_id=project_id,
        )


_state: TuringState | None = None


def get_state() -> TuringState:
    if _state is None:
        raise RuntimeError("canonical Turing security has not been composed")
    return _state


def _guard_replica_authority(state_store: SelfModelStateStore | None) -> None:
    """Refuse a multi-replica declaration without an explicitly shared store.

    The in-process store is authoritative for exactly one process. Merely
    injecting a store object is not sufficient: an explicitly injected local
    store (or a custom store that does not declare its replica semantics) would
    still let replicas diverge. Fail composition, not correctness (#859).
    """
    count = replica_count()
    if count > 1 and not getattr(state_store, "is_shared_across_replicas", False):
        raise RuntimeError(
            f"TURING_REPLICA_COUNT={count} declares a multi-replica Turing "
            "deployment, but the composed SelfModelStateStore is not declared "
            "shared across replicas; the self-model authority could diverge. "
            "Compose a shared store implementation to enable replicas."
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
    _state = TuringState(
        config=config,
        inbound_security=inbound_security,
        state_store=state_store,
    )
    return _state
