"""Live state for the Turing backend.

Holds the per-principal in-memory self-model scopes, the producer-artifact
feed, and the wired runtime objects (actor / chat / bridges). Routes read and
mutate this composed object.

Cognitive state is never process-global shared state (#27/#859): self-model
reads and writes are keyed by the authenticated canonical principal, and a
missing scope is an error — there is no fallback to one shared snapshot. Chat
sessions are (principal, session)-keyed and bounded in per-principal
cardinality and lifetime by :class:`ChatSessionRegistry`.

GAP: this is an in-memory, single-process store. A production deployment would
back the self-model scopes and producer feed with the persistence layer
(maistro.persistence / a Turing episodic store via TuringMemoryBridge) so that
state survives restarts and is shared across workers. The shapes here mirror the
real `maistro_turing.self_model` types so that swap is mechanical.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
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

from .security import TuringInboundSecurity, TuringSecurityContext

SELF_ID = "turing"

# The producer kinds Turing emits. Mirrors the producer classes in
# maistro_turing.producers (blog / self-reflection / curiosity / emotion).
ARTIFACT_KINDS = frozenset({"blog", "reflection", "curiosity", "emotion"})


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class ProducerArtifact:
    """A single static artifact produced by one of Turing's producers."""

    artifact_id: str
    self_id: str
    kind: str
    title: str
    body: str
    created_at: datetime = field(default_factory=_now)

    def to_dict(self) -> dict[str, object]:
        return {
            "artifact_id": self.artifact_id,
            "self_id": self.self_id,
            "kind": self.kind,
            "title": self.title,
            "body": self.body,
            "created_at": self.created_at.isoformat(),
        }


def _default_facet_scores() -> dict[str, float]:
    return {facet: 3.0 for _trait, facet in ALL_FACETS}


def _default_mood() -> Mood:
    return Mood(
        self_id=SELF_ID,
        valence=0.2,
        arousal=0.5,
        focus=0.6,
        last_tick_at=_now(),
    )


def _require_scope_id(scope_id: str) -> str:
    """Reject absent/blank scopes instead of falling back to shared state."""
    scope = (scope_id or "").strip()
    if not scope:
        raise ValueError(
            "Turing self-model state requires an explicit principal scope; "
            "there is no process-global fallback"
        )
    return scope


@dataclass
class _SelfModelScope:
    """One principal's private self-model view (#859)."""

    mood: Mood
    facet_scores: dict[str, float]


@dataclass
class _ChatSessionEntry:
    """One live chat session plus its recency timestamp for TTL purging."""

    session: TuringChatSession
    last_used: float


class ChatSessionRegistry:
    """Bounded per-principal partitions of ``session_id -> TuringChatSession``.

    Chat history is cognitive state, so it is keyed by the authenticated
    canonical principal: a client-supplied session id alone never selects a
    session, and one caller cannot attach to another principal's session by
    guessing its id (#859). Capacity and LRU are enforced within each
    principal's own partition — each principal holds at most ``max_sessions``
    sessions and eviction removes only that principal's least-recently-used
    entry — so flooding distinct session ids can never evict another
    principal's session (review P1). Entries idle past ``idle_ttl_seconds``
    are dropped.

    Sessions are disposable process-local objects; a restart truthfully loses
    them (they are conversation convenience, not durable state).
    """

    def __init__(
        self,
        *,
        factory: Callable[[], TuringChatSession],
        max_sessions: int = 1024,
        idle_ttl_seconds: float = 1800.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_sessions < 1:
            raise ValueError("max_sessions must be >= 1")
        if idle_ttl_seconds <= 0:
            raise ValueError("idle_ttl_seconds must be positive")
        self._factory = factory
        self._max_sessions = max_sessions
        self._idle_ttl_seconds = idle_ttl_seconds
        self._clock = clock
        self._lock = threading.Lock()
        # principal_id -> (session_id -> entry), each partition an OrderedDict
        # kept in LRU order: every hit does move_to_end and every create
        # appends, so the front entry is the true LRU even when timestamps tie
        # under a coarse or frozen clock (review P2).
        self._sessions: dict[str, OrderedDict[str, _ChatSessionEntry]] = {}

    def get_or_create(self, principal_id: str, session_id: str) -> TuringChatSession:
        """Return the principal's session for ``session_id``, or a new one.

        ``principal_id`` must be the authenticated canonical principal — never
        a client-controlled value alone.
        """
        if not principal_id:
            raise ValueError("chat sessions require the authenticated principal id")
        if not session_id:
            raise ValueError("chat sessions require a session id")
        now = self._clock()
        with self._lock:
            self._purge_expired(now)
            partition = self._sessions.get(principal_id)
            if partition is None:
                partition = self._sessions[principal_id] = OrderedDict()
            entry = partition.get(session_id)
            if entry is not None:
                entry.last_used = now
                partition.move_to_end(session_id)
                return entry.session
            while len(partition) >= self._max_sessions:
                partition.popitem(last=False)  # this principal's own LRU only
            session = self._factory()
            partition[session_id] = _ChatSessionEntry(session=session, last_used=now)
            return session

    def _purge_expired(self, now: float) -> None:
        """Drop sessions idle past the TTL. Caller holds the lock."""
        for partition in self._sessions.values():
            expired = [
                session_id
                for session_id, entry in partition.items()
                if now - entry.last_used > self._idle_ttl_seconds
            ]
            for session_id in expired:
                del partition[session_id]
        for principal_id in [
            principal_id for principal_id, partition in self._sessions.items() if not partition
        ]:
            del self._sessions[principal_id]


class TuringState:
    """Single source of live truth for the backend.

    Thread-safe for the simple read/append/replace operations the routes need;
    a TestClient drives requests on a thread pool so the lock matters.
    """

    def __init__(
        self,
        config: TuringConfig | None = None,
        *,
        inbound_security: TuringInboundSecurity | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self.config = config or TuringConfig()
        if inbound_security is None:
            raise RuntimeError("canonical Turing security is required for backend startup")
        self.inbound_security = inbound_security

        # Per-principal self-model scopes; created lazily per scope id.
        self._scopes: dict[str, _SelfModelScope] = {}
        self._artifacts: list[ProducerArtifact] = []
        self.chat_sessions = ChatSessionRegistry(factory=self.new_chat_session)

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

    # ----------------------------------------------------------- self-model --

    def _self_model_scope(self, scope_id: str) -> _SelfModelScope:
        """Resolve (or lazily create) one principal's scope. Lock required."""
        scope = _require_scope_id(scope_id)
        with self._lock:
            scoped = self._scopes.get(scope)
            if scoped is None:
                scoped = _SelfModelScope(
                    mood=_default_mood(),
                    facet_scores=_default_facet_scores(),
                )
                self._scopes[scope] = scoped
            return scoped

    def mood_snapshot(self, scope_id: str) -> Mood:
        """The principal's own mood snapshot — never another principal's."""
        with self._lock:
            return self._self_model_scope(scope_id).mood

    def facet_scores(self, scope_id: str) -> dict[str, float]:
        with self._lock:
            return dict(self._self_model_scope(scope_id).facet_scores)

    def set_mood(self, scope_id: str, **fields: float) -> Mood:
        """Mutate one principal's mood within the documented ranges.

        The authoritative write seam: constructing :class:`Mood` validates
        valence/arousal/focus in ``__post_init__``, so an out-of-range value
        raises here and nothing is persisted — for every caller, not only the
        HTTP layer's pydantic schema (#859).
        """
        with self._lock:
            scope = _require_scope_id(scope_id)
            scoped = self._scopes.get(scope)
            current = scoped.mood if scoped is not None else _default_mood()
            # Construct (and therefore validate) the candidate before any
            # map mutation: a rejected write must not install a default
            # scope entry for a previously unseen principal.
            updated = Mood(
                self_id=SELF_ID,
                valence=fields.get("valence", current.valence),
                arousal=fields.get("arousal", current.arousal),
                focus=fields.get("focus", current.focus),
                last_tick_at=current.last_tick_at,
                updated_at=_now(),
            )
            if scoped is None:
                scoped = _SelfModelScope(
                    mood=updated,
                    facet_scores=_default_facet_scores(),
                )
                self._scopes[scope] = scoped
            else:
                scoped.mood = updated
            return updated

    def set_facet(self, scope_id: str, facet_id: str, score: float) -> None:
        """Mutate one principal's facet score, bounds-checked at this seam."""
        with self._lock:
            scope = _require_scope_id(scope_id)
            scoped = self._scopes.get(scope)
            known = scoped.facet_scores if scoped is not None else _default_facet_scores()
            # Validate against the candidate facet map before any map
            # mutation, mirroring set_mood: a rejected write must not
            # install a default scope entry for an unseen principal.
            if facet_id not in known:
                raise KeyError(facet_id)
            if not 1.0 <= score <= 5.0:
                raise ValueError(f"facet score out of range: {score}")
            known[facet_id] = score
            if scoped is None:
                self._scopes[scope] = _SelfModelScope(
                    mood=_default_mood(),
                    facet_scores=known,
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


def reset_state(
    config: TuringConfig | None = None,
    *,
    inbound_security: TuringInboundSecurity,
) -> TuringState:
    """Replace the singleton — used by tests for isolation."""
    global _state
    _state = TuringState(config=config, inbound_security=inbound_security)
    return _state
