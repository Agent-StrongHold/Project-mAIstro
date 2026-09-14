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

        self._mood = Mood(
            self_id=SELF_ID,
            valence=0.2,
            arousal=0.5,
            focus=0.6,
            last_tick_at=_now(),
        )
        self._facet_scores = _default_facet_scores()
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
        principal = SELF_ID
        if execution.run_id:
            # Model/tool output is produced inside a canonical Run. Resolve its
            # actor from the Run record rather than attributing the verdict to
            # the Turing runtime itself.
            from .execution import get_execution_plane

            run = await get_execution_plane().run_store.get_run(execution.run_id)
            if run is None or not run.actor_principal_id:
                raise RuntimeError("canonical Run actor is unavailable for security audit")
            principal = str(run.actor_principal_id)

        await self.inbound_security.audit_verdict(
            verdict,  # type: ignore[arg-type]
            content,
            boundary=boundary,
            context=TuringSecurityContext(
                principal=principal,
                route="runtime",
                action=f"turing.{boundary}",
                workspace_id=execution.workspace_id,
                project_id=execution.project_id,
                run_id=execution.run_id,
                invocation_id=execution.invocation_id,
            ),
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
