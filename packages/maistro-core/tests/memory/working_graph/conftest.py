"""Shared fixtures for the working-memory seam tests (#776).

The durable side is the engine's **real** in-process episodic and learning
stores — not mocks — so the tests prove the projection reads durable truth.
Only the sources the engine does not own yet (artifact versions, Run
provenance, terminology) are small in-memory fakes implementing the seam's
source protocols.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from maistro.memory.episodic.store import InMemoryEpisodicStore
from maistro.memory.exposure import MemoryExposureMode
from maistro.memory.learnings.store import InMemoryLearningStore
from maistro.memory.types import EpisodicMemory, Learning, MemoryScope, MemoryTier
from maistro.memory.working_graph.hydration import (
    ArtifactVersionRecord,
    RunProvenanceRecord,
    TerminologyRecord,
)

WORKSPACE_A = "ws-aaaa"
WORKSPACE_B = "ws-bbbb"


def make_memory(
    memory_id: str,
    content: str,
    *,
    run_id: str = "",
    node_run_id: str = "",
    attempt_id: str = "",
    org_id: str = "org-1",
    team_id: str = "team-1",
    user_id: str | None = "user-1",
    agent_id: str | None = None,
    project_id: str = "",
    tier: MemoryTier = MemoryTier.OBSERVATION,
) -> EpisodicMemory:
    return EpisodicMemory(
        memory_id=memory_id,
        tier=tier,
        weight=0.4,
        content=content,
        org_id=org_id,
        team_id=team_id,
        user_id=user_id,
        agent_id=agent_id,
        scope=MemoryScope.USER if user_id else MemoryScope.AGENT,
        project_id=project_id,
        run_id=run_id,
        node_run_id=node_run_id,
        attempt_id=attempt_id,
    )


def make_learning(
    learning_text: str,
    *,
    learning_id: int | None = None,
    org_id: str = "org-1",
    team_id: str = "team-1",
    user_id: str | None = "user-1",
    run_id: str = "",
    status: str = "active",
    category: str = "correction",
) -> Learning:
    learning = Learning(
        category=category,
        learning=learning_text,
        org_id=org_id,
        team_id=team_id,
        user_id=user_id,
        run_id=run_id,
        status=status,
    )
    learning.id = learning_id
    return learning


@dataclass
class FakeArtifactSource:
    versions: list[ArtifactVersionRecord] = field(default_factory=list)

    async def versions_for_workspace(
        self, workspace_id: str, *, limit: int
    ) -> list[ArtifactVersionRecord]:
        return [v for v in self.versions if v.workspace_id == workspace_id][:limit]


@dataclass
class FakeRunProvenanceSource:
    runs: list[RunProvenanceRecord] = field(default_factory=list)

    async def recent_runs(self, workspace_id: str, *, limit: int) -> list[RunProvenanceRecord]:
        return [r for r in self.runs if r.workspace_id == workspace_id][:limit]


@dataclass
class FakeTerminologySource:
    terms: list[TerminologyRecord] = field(default_factory=list)

    async def terms_for_workspace(
        self, workspace_id: str, *, limit: int
    ) -> list[TerminologyRecord]:
        return [t for t in self.terms if t.workspace_id == workspace_id][:limit]


@dataclass
class ExplodingSource:
    """A hydration source whose durable read fails — the degraded-path driver."""

    error: Exception
    calls: int = 0

    async def collect(self, workspace_id: str, *, limit: int) -> object:
        self.calls += 1
        raise self.error


@pytest.fixture
def episodic() -> InMemoryEpisodicStore:
    return InMemoryEpisodicStore(exposure_mode=MemoryExposureMode.AGENT_MANAGED)


@pytest.fixture
def learnings() -> InMemoryLearningStore:
    return InMemoryLearningStore(exposure_mode=MemoryExposureMode.AGENT_MANAGED)
