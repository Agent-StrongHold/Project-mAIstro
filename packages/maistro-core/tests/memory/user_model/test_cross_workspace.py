"""Cross-Workspace user-model E2E: consolidation, relevance, isolation (#1047).

One authenticated user works in Workspace A (photography) and later in
Workspace B (software development). The scenario proves the #1047 acceptance
chain end to end through the one ``UserModelService`` both the Agent runtime
and the HTTP API call:

- evidence from A consolidates into a user-level fact and is recalled by B
  for a task A never saw, without B reading A's working graph;
- the same fact is NOT injected into B's unrelated tasks;
- a Workspace-private fact that was never promoted stays invisible;
- two users with colliding Workspaces, Personas and statements cannot see
  each other's facts;
- correction changes later retrieval and carries provenance;
- forgetting tombstones the lineage, and a stale working-graph replay cannot
  resurrect it.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from maistro.memory.types import EpisodicMemory, MemoryScope, MemoryTier
from maistro.memory.user_model import (
    CrossUserPromotionError,
    FactState,
    InMemoryUserModelStore,
    StaleEvidenceError,
    TombstonedLineageError,
    promote_evidence,
)
from maistro.memory.user_model.retrieval import RecallQuery
from maistro.memory.user_model.service import UserModelService
from maistro.security.sentinel.audit import InMemoryAuditLog


def _observation(user_id: str, content: str, project_id: str, run_id: str) -> EpisodicMemory:
    """One consolidated observation inside the named Project's memory.

    ``EpisodicMemory`` has no workspace column: Workspace binding is carried
    as ids next to the scope (ADR-092526-4391 §2), which is exactly what the
    promotion call records in the fact's ``EvidenceRef``.
    """
    return EpisodicMemory(
        tier=MemoryTier.OBSERVATION,
        content=content,
        user_id=user_id,
        agent_id="agent-1",
        scope=MemoryScope.AGENT,
        project_id=project_id,
        run_id=run_id,
    )


def _task(owner: str, text: str, workspace_id: str, persona: tuple[str, ...] = ()) -> RecallQuery:
    return RecallQuery(
        owner_user_id=owner,
        task_text=text,
        workspace_id=workspace_id,
        persona_hints=persona,
        now=datetime.now(UTC),
    )


class _WorkspaceAgent:
    """The Agent-side door: a Workspace Agent acting for one authenticated user.

    It holds only its own working memory and the shared user-model service.
    It has no handle on any other Workspace's graph -- nothing here could
    traverse Workspace A's Ladybug projection even by accident.
    """

    def __init__(self, workspace_id: str, user_id: str, service: UserModelService) -> None:
        self.workspace_id = workspace_id
        self.user_id = user_id
        self.service = service
        self.private_memory: list[EpisodicMemory] = []

    async def observe(self, content: str, run_id: str, *, promote: bool) -> None:
        memory = _observation(self.user_id, content, f"proj-{self.workspace_id}", run_id)
        self.private_memory.append(memory)
        if promote:
            # Consolidation's one promotion door, aimed at the same store and
            # audit log this agent's UserModelService holds.
            await promote_evidence(
                memory,
                acting_user_id=self.user_id,
                store=self.service.store,
                audit_log=self.service.audit_log,
                workspace_id=self.workspace_id,
                kind="possession",
            )

    async def recall_for(self, text: str, persona: tuple[str, ...] = ()) -> list[str]:
        scored = await self.service.recall_for_task(
            _task(self.user_id, text, self.workspace_id, persona)
        )
        return [item.fact.statement for item in scored]


@pytest.fixture
def shared_model() -> tuple[UserModelService, InMemoryUserModelStore]:
    """One durable user-model store behind the one canonical service."""
    store = InMemoryUserModelStore()
    return UserModelService(store=store, audit_log=InMemoryAuditLog()), store


async def test_workspace_a_evidence_surfaces_in_workspace_b_only_when_relevant(
    shared_model,
) -> None:
    service, store = shared_model
    # Workspace A: photography. The conversation learns the user's camera.
    workspace_a = _WorkspaceAgent("ws-photography", "alice", service)
    await workspace_a.observe(
        "user shoots with a Canon 7D camera and 70-200mm lens", "run-a1", promote=True
    )
    fact = (await store.list_for_user("alice"))[0]
    assert [ref.workspace_id for ref in fact.evidence] == ["ws-photography"]

    # Workspace B: software development, never discussed photography. A task
    # that suddenly becomes camera-specific gets the fact -- the cross-domain
    # surprise -- and the provenance still points at Workspace A, not at any
    # of B's own memory.
    workspace_b = _WorkspaceAgent("ws-software", "alice", service)
    recalled = await workspace_b.recall_for(
        "the task changed: it now needs a lens choice for the product photos",
        persona=("software", "photography"),
    )
    assert recalled == ["user shoots with a Canon 7D camera and 70-200mm lens"]

    # The same Workspace B, unrelated software task: the camera fact is NOT
    # injected. Relevance filtering, not blanket sharing.
    assert await workspace_b.recall_for("refactor the payment parser module") == []
    assert await workspace_b.recall_for("fix the flaky integration test") == []


async def test_workspace_private_fact_that_was_never_promoted_stays_invisible(
    shared_model,
) -> None:
    service, store = shared_model
    workspace_a = _WorkspaceAgent("ws-a", "alice", service)
    # A's private working memory: observed but deliberately not promoted.
    await workspace_a.observe(
        "the team's staging database is called hermes", "run-a2", promote=False
    )

    workspace_b = _WorkspaceAgent("ws-b", "alice", service)
    assert await workspace_b.recall_for("which database is called hermes") == []
    assert await service.facts("alice") == []
    assert await store.list_for_user("alice") == []


async def test_colliding_users_cannot_observe_each_others_facts(shared_model) -> None:
    service, store = shared_model
    # Two principals, same Workspace name, same Persona, same statement text,
    # ONE shared durable store: ownership is what separates them.
    alice_ws = _WorkspaceAgent("ws-shared", "alice", service)
    bob_ws = _WorkspaceAgent("ws-shared", "bob", service)
    await alice_ws.observe(
        "user shoots with a Canon 7D camera and 70-200mm lens", "run-1", promote=True
    )
    await bob_ws.observe(
        "user shoots with a Canon 7D camera and 70-200mm lens", "run-1", promote=True
    )

    alice_fact = (await store.list_for_user("alice"))[0]
    bob_fact = (await store.list_for_user("bob"))[0]
    assert alice_fact.statement == bob_fact.statement  # the collision is real

    # Each recalls exactly one fact -- their own -- never the other's twin.
    assert await bob_ws.recall_for("which camera should I shoot with") == [
        "user shoots with a Canon 7D camera and 70-200mm lens"
    ]
    assert await alice_ws.recall_for("which camera should I shoot with") == [
        "user shoots with a Canon 7D camera and 70-200mm lens"
    ]
    bob_recalled = await service.recall_for_task(
        _task("bob", "which camera should I shoot with", "ws-shared")
    )
    assert [item.fact.fact_id for item in bob_recalled] == [bob_fact.fact_id]
    assert bob_fact.fact_id != alice_fact.fact_id

    # Forgetting his own fact does not touch hers, and vice versa.
    await service.forget(bob_fact.lineage_id, acting_user_id="bob", reason="cleanup")
    assert await bob_ws.recall_for("which camera should I shoot with") == []
    assert await alice_ws.recall_for("which camera should I shoot with") == [
        "user shoots with a Canon 7D camera and 70-200mm lens"
    ]


async def test_user_correction_changes_later_retrieval_and_keeps_provenance(
    shared_model,
) -> None:
    service, store = shared_model
    workspace_a = _WorkspaceAgent("ws-a", "alice", service)
    await workspace_a.observe(
        "user shoots with a Canon 7D camera and 70-200mm lens", "run-a1", promote=True
    )
    lineage = (await store.list_for_user("alice"))[0].lineage_id

    corrected = await service.correct(
        lineage,
        acting_user_id="alice",
        statement="user now shoots with a Sony A7 IV after selling the old body",
        reason="user says the Canon body was sold in March",
    )
    assert corrected.revision == 2
    assert corrected.correction is not None
    assert corrected.correction.corrected_by == "alice"
    assert "sold" in corrected.correction.reason

    # Later retrieval follows the correction, not the original wording.
    workspace_b = _WorkspaceAgent("ws-b", "alice", service)
    assert await workspace_b.recall_for("canon 70-200mm lens settings") == []
    assert await workspace_b.recall_for("sony a7 settings for the product shot") == [
        "user now shoots with a Sony A7 IV after selling the old body"
    ]

    # And the correction is provenance-bearing: the lineage retains both
    # revisions with their evidence.
    history = await service.history(lineage, acting_user_id="alice")
    assert [rev.revision for rev in history] == [1, 2]
    assert history[0].statement == "user shoots with a Canon 7D camera and 70-200mm lens"
    # The superseded revision is history, never an assertion: recall gates on
    # the ACTIVE head only.
    assert history[0].state is FactState.SUPERSEDED


async def test_forgotten_fact_survives_a_stale_working_graph_replay(shared_model) -> None:
    service, store = shared_model
    workspace_a = _WorkspaceAgent("ws-a", "alice", service)
    await workspace_a.observe(
        "user shoots with a Canon 7D camera and 70-200mm lens", "run-a1", promote=True
    )
    lineage = (await store.list_for_user("alice"))[0].lineage_id

    tomb = await service.forget(lineage, acting_user_id="alice", reason="user asked to forget")
    assert tomb.state is FactState.TOMBSTONED

    # A stale consolidation pass replays A's still-cached working memory:
    # promotion refuses instead of recreating the fact.
    stale_replay = workspace_a.private_memory[0]
    with pytest.raises(TombstonedLineageError):
        await promote_evidence(
            stale_replay,
            acting_user_id="alice",
            store=store,
            audit_log=InMemoryAuditLog(),
            workspace_id="ws-a",
        )
    # Even the corrected wording stays blocked after a deletion.
    with pytest.raises(TombstonedLineageError):
        await service.correct(
            lineage,
            acting_user_id="alice",
            statement="user shoots with a Canon 7D",
            reason="trying to revive it",
        )

    workspace_b = _WorkspaceAgent("ws-b", "alice", service)
    assert await workspace_b.recall_for("canon 7d settings") == []
    assert await service.facts("alice") == []
    # The content is gone from the record; only the tombstone remains.
    history = await store.history(lineage)
    assert len(history) == 1
    assert history[0].state is FactState.TOMBSTONED
    assert history[0].statement == ""
    assert history[0].correction is not None
    assert history[0].correction.reason == "user asked to forget"


async def test_stale_replay_of_a_corrected_fact_cannot_revive_the_old_statement(
    shared_model,
) -> None:
    service, store = shared_model
    workspace_a = _WorkspaceAgent("ws-a", "alice", service)
    await workspace_a.observe("user prefers dark mode terminals", "run-a3", promote=True)
    lineage = (await store.list_for_user("alice"))[0].lineage_id
    await service.correct(
        lineage,
        acting_user_id="alice",
        statement="user prefers a minimal desk setup with warm lighting",
        reason="changed setups",
    )

    # A stale consolidation replays the pre-correction observation.
    with pytest.raises(StaleEvidenceError):
        await promote_evidence(
            workspace_a.private_memory[0],
            acting_user_id="alice",
            store=store,
            audit_log=InMemoryAuditLog(),
            workspace_id="ws-a",
        )
    workspace_b = _WorkspaceAgent("ws-b", "alice", service)
    assert await workspace_b.recall_for("dark mode terminal preferences") == []
    assert await workspace_b.recall_for("minimal desk setup lighting") == [
        "user prefers a minimal desk setup with warm lighting"
    ]


async def test_persona_shapes_ranking_but_never_authorization(shared_model) -> None:
    service, _store = shared_model
    workspace_a = _WorkspaceAgent("ws-a", "alice", service)
    await workspace_a.observe(
        "user shoots with a Canon 7D camera and 70-200mm lens", "run-a1", promote=True
    )
    # The same evidence owned by bob: promoting it under alice's name is a
    # cross-user write, refused however relevant bob's Persona finds it.
    bob_memory = _observation(
        "bob", "user shoots with a Canon 7D camera and 70-200mm lens", "proj-ws-a", "run-a1"
    )
    with pytest.raises(CrossUserPromotionError):
        await promote_evidence(
            bob_memory,
            acting_user_id="alice",
            store=service.store,
            audit_log=service.audit_log,
            workspace_id="ws-a",
        )
    # bob's identical Persona cannot pull alice's fact into his context.
    bob_ws = _WorkspaceAgent("ws-a", "bob", service)
    assert await bob_ws.recall_for("canon 7d", persona=("photography", "cameras")) == []


async def test_workspace_affinity_ranks_homework_above_foreign_evidence(shared_model) -> None:
    service, _store = shared_model
    workspace_a = _WorkspaceAgent("ws-photography", "alice", service)
    await workspace_a.observe(
        "user shoots with a Canon 7D camera and 70-200mm lens", "run-a1", promote=True
    )
    # A second Workspace also produced a camera fact for alice, sharing the
    # same single task term so lexical overlap is equal and affinity decides.
    await promote_evidence(
        _observation(
            "alice", "user prefers RAW capture with the studio camera", "proj-ws-studio", "run-s1"
        ),
        acting_user_id="alice",
        store=service.store,
        audit_log=service.audit_log,
        workspace_id="ws-studio",
        kind="preference",
    )

    # Task "camera": both facts overlap on exactly one term, both are equally
    # fresh and equally confident, so the workspace-affinity bonus is the
    # only difference: the fact learned in the asking Workspace ranks first.
    scored = await service.recall_for_task(_task("alice", "camera", "ws-studio"))
    assert len(scored) == 2
    assert scored[0].fact.statement == "user prefers RAW capture with the studio camera"
    assert scored[0].score > scored[1].score
