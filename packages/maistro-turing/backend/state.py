"""Process-wide live state for the Turing backend.

Holds the single in-memory self-model snapshot, the producer-artifact feed, and
the wired runtime objects (actor / chat / bridges). Routes read and mutate this
singleton.

GAP: this is an in-memory, single-process store. A production deployment would
back the self-model snapshot and producer feed with the persistence layer
(maistro.persistence / a Turing episodic store via TuringMemoryBridge) so that
state survives restarts and is shared across workers. The shapes here mirror the
real `maistro_turing.self_model` types so that swap is mechanical.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

from maistro_turing.bridge import (
    TuringClassifierBridge,
    TuringMemoryBridge,
    TuringProviderBridge,
    TuringSecurityBridge,
)
from maistro_turing.runtime import TuringActor, TuringChatSession, TuringConfig
from maistro_turing.self_model import ALL_FACETS, Mood

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


class TuringState:
    """Single source of live truth for the backend.

    Thread-safe for the simple read/append/replace operations the routes need;
    a TestClient drives requests on a thread pool so the lock matters.
    """

    def __init__(self, config: TuringConfig | None = None) -> None:
        self._lock = threading.RLock()
        self.config = config or TuringConfig()

        self._mood = Mood(
            self_id=SELF_ID,
            valence=0.2,
            arousal=0.5,
            focus=0.6,
            last_tick_at=_now(),
        )
        self._facet_scores = _default_facet_scores()
        self._artifacts: list[ProducerArtifact] = []

        # GAP: bridges are constructed without backing maistro-core
        # implementations (no episodic/learning store, no warden, no LLM
        # client). The runtime degrades gracefully (memory writes are dropped,
        # scans pass-through) — see TuringMemoryBridge/TuringSecurityBridge.
        # Production wiring injects real stores + a warden + an LLM client here,
        # typically via maistro.container.
        self.memory = TuringMemoryBridge()
        self.security = TuringSecurityBridge()
        self.provider = TuringProviderBridge()
        self.classifier = TuringClassifierBridge()

        self.actor = TuringActor(
            memory=self.memory,
            security=self.security,
            provider=self.provider,
            self_id=SELF_ID,
        )

    # ----------------------------------------------------------- self-model --

    def mood_snapshot(self) -> Mood:
        with self._lock:
            return self._mood

    def facet_scores(self) -> dict[str, float]:
        with self._lock:
            return dict(self._facet_scores)

    def set_mood(self, **fields: float) -> Mood:
        with self._lock:
            current = self._mood
            self._mood = Mood(
                self_id=SELF_ID,
                valence=fields.get("valence", current.valence),
                arousal=fields.get("arousal", current.arousal),
                focus=fields.get("focus", current.focus),
                last_tick_at=current.last_tick_at,
                updated_at=_now(),
            )
            return self._mood

    def set_facet(self, facet_id: str, score: float) -> None:
        with self._lock:
            if facet_id not in self._facet_scores:
                raise KeyError(facet_id)
            if not 1.0 <= score <= 5.0:
                raise ValueError(f"facet score out of range: {score}")
            self._facet_scores[facet_id] = score

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
    global _state
    if _state is None:
        _state = TuringState()
    return _state


def reset_state(config: TuringConfig | None = None) -> TuringState:
    """Replace the singleton — used by tests for isolation."""
    global _state
    _state = TuringState(config=config)
    return _state
