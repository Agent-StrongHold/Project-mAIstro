"""Conductor's Graph inspection explains each artifact's lineage (#775 AC-10).

`GET /v1/dag-runs/{id}` and the run list used to expose only lifecycle truth
(status/result/error) from the canonical overlay: nothing on the projection
answer said which Goal revision, CreativeBrief version, shared decision or
Agent delegation produced the artifacts behind a creative fulfillment, even
though the canonical Run and its durable record carry all of it. The
inspection door now relays that lineage — the run-level `goal_run_evidence`
provenance block plus per-artifact records reconstructed from the persisted
DurableRunRecord through
`maistro_design.creative_graph.artifact_provenance`.

The wiring is read-only and door-preserving: per-artifact state is attached
only after the same scoped overlay that already authorized the canonical Run
for this caller, a non-creative run gains no creative block at all, an
out-of-scope caller still gets the 404-shaped refusal, and a missing durable
spine degrades to the run-level block instead of failing the read.

The creative Run under test is produced by the real canonical durable
executor (`maistro_design.creative_graph.run_creative_graph` over
`InMemoryDurableRunStore`) — the same machinery the maistro-design suite
exercises — so the per-artifact records asserted here are reconstructed from
real persisted Run/NodeRun/Attempt/blackboard state, not fixtures.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

pytestmark = [pytest.mark.contract("boundary")]

_AUTHED_USER_ID = "user"  # the session conftest seeds


# ── the canonical creative fulfillment under inspection ─────────────────────


def _brief(workspace_id: str) -> Any:
    """One Goal revision, one brief version, three artifact branches."""
    from maistro_design.brief import ArtifactRequest, BriefReference, CreativeBrief

    return CreativeBrief.model_validate(
        {
            "workspace_id": workspace_id,
            "project_id": "proj-campaign",
            "goal_id": "goal-spring-launch",
            "goal_revision": 4,
            "goal_owner_agent_id": "agent-orchestrator",
            "goal_delegation_ref": BriefReference(
                kind="delegation", ref_id="delegation-launch-family", workspace_id=workspace_id
            ),
            "persona": BriefReference(
                kind="persona", ref_id="persona-bakery", version="p-v2", workspace_id=workspace_id
            ),
            "design_system": BriefReference(
                kind="design_system", ref_id="brand-x", version="2026.09"
            ),
            "audience": "home bakers",
            "required_messages": ("Fresh daily", "Local grain"),
            "cta": "Order by Friday",
            "artifact_requests": (
                ArtifactRequest(request_id="landing-page", channel="website", format="html"),
                ArtifactRequest(request_id="launch-deck", channel="deck", format="pdf"),
                ArtifactRequest(
                    request_id="poster-launch", channel="poster", format="png", dimensions="A2"
                ),
            ),
        }
    )


@pytest.fixture()
def user_workspace(authed_client: Any) -> str:
    """A real canonical Workspace the caller owns (the established pattern:
    the projection row, the canonical Run and the authorization universe
    must name the same Workspace for inspection to answer at all)."""
    r = authed_client.post(
        "/v1/workspaces", json={"persona_template_id": "pm_fleet", "name": "Creative inspection"}
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture()
def creative_fulfillment(user_workspace: str):
    """Run the reference creative Graph through the canonical durable executor.

    Returns the completed DurableRunRecord: canonical Run (carrying the
    `goal_run_evidence` provenance block), NodeRuns, Attempts and the
    blackboard snapshot the inspection reconstructs from. The brief consumes
    the caller's real Workspace so the run's canonical scope is one the
    caller's universe contains.
    """
    import asyncio

    from maistro.graph.durable_runs import InMemoryDurableRunStore
    from maistro_design.creative_graph import run_creative_graph

    store = InMemoryDurableRunStore()
    brief = _brief(user_workspace)

    async def _run() -> Any:
        return await run_creative_graph(brief, store=store)

    record = asyncio.run(_run())
    assert record.status.value == "completed"
    assert record.run.workspace_id == user_workspace
    return record


class _SpineStub:
    """The canonical bridge the inspection reads through.

    `run_reader` answers with the durable record's own canonical Run (the
    same object the executor minted and filed the provenance block on);
    `graph_run_store` answers durable-record reads by id.
    """

    def __init__(self, record: Any) -> None:
        self.record = record

    async def get_runs(self, run_ids: Any, *, principal_id: str) -> dict[str, Any]:
        return {rid: self.record.run for rid in run_ids if rid == self.record.run.run_id}

    async def get(self, run_id: str) -> Any:
        return self.record if run_id == self.record.run.run_id else None


class _RunlessSpine:
    """A spine with a Run reader but no durable graph store (degraded)."""

    def __init__(self, record: Any) -> None:
        self._run = record.run

    async def get_runs(self, run_ids: Any, *, principal_id: str) -> dict[str, Any]:
        return {rid: self._run for rid in run_ids if rid == self._run.run_id}


def _wire_spine(monkeypatch: pytest.MonkeyPatch, spine: Any) -> None:
    import services.engine as engine_mod

    monkeypatch.setattr(
        engine_mod, "_singleton", SimpleNamespace(run_reader=spine, graph_run_store=spine)
    )


async def _seed_projection(record: Any) -> None:
    from services.dag_run_store import get_dag_run_store

    await get_dag_run_store().start_run(
        run_id=record.run.run_id,
        user_id=_AUTHED_USER_ID,
        workspace_id=record.run.workspace_id,
    )


# ── the acceptance: inspection explains each artifact's lineage ─────────────


async def test_detail_explains_each_artifacts_goal_brief_decision_and_agent_lineage(
    creative_fulfillment: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-10: the inspection answer names, per artifact, which Goal revision,
    CreativeBrief version, shared decision and Agent delegation produced it —
    read from persisted canonical state alone."""
    from services.dag_run_inspection import visible_run_detail

    record = creative_fulfillment
    await _seed_projection(record)
    _wire_spine(monkeypatch, _SpineStub(record))

    detail = await visible_run_detail(_AUTHED_USER_ID, record.run.run_id)
    assert detail is not None

    creative = detail["creative_provenance"]
    assert creative["goal_id"] == "goal-spring-launch"
    assert creative["goal_revision"] == 4
    assert creative["brief_id"] == record.run.provenance["brief_id"]
    assert creative["brief_version"] == 1
    assert creative["goal_owner_agent_id"] == "agent-orchestrator"
    assert creative["goal_delegation_ref"]["ref_id"] == "delegation-launch-family"
    # No explicit plan is passed, but run_creative_graph auto-selects and
    # instantiates a template; its ref must surface in the provenance (#775).
    assert creative.get("graph_template")

    artifacts = {row["request_id"]: row for row in detail["artifacts"]}
    assert set(artifacts) == {"landing-page", "launch-deck", "poster-launch"}
    for row in artifacts.values():
        # Every artifact names the same Goal/brief/agent lineage...
        assert row["goal_id"] == "goal-spring-launch"
        assert row["goal_revision"] == 4
        assert row["brief_id"] == creative["brief_id"]
        assert row["goal_owner_agent_id"] == "agent-orchestrator"
        assert row["goal_delegation_ref"]["ref_id"] == "delegation-launch-family"
        # ...the shared decisions it consumed (persisted once, cited per
        # branch)...
        assert row["consumed_message_decision_id"]
        assert row["consumed_visual_decision_id"]
        # ...and its canonical physical history.
        assert row["status"] == "completed"
        assert row["attempt_count"] >= 1
        assert row["node_run_ids"]
        assert row["content_digest"]
    # The shared message decision is one identity cited by every branch.
    message_ids = {row["consumed_message_decision_id"] for row in artifacts.values()}
    assert len(message_ids) == 1


async def test_detail_of_a_non_creative_run_gains_no_creative_block(
    user_workspace: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The relay keys off the canonical `goal_run_evidence` provenance block:
    a run that never carried one is returned exactly as before, with no
    invented lineage and no artifacts lookup."""
    from services.dag_run_inspection import visible_run_detail

    class _PlainRun:
        run_id = "r-plain"
        workspace_id = user_workspace
        status = SimpleNamespace(value="completed")
        result = None
        error = None

        def __init__(self) -> None:
            self.provenance: dict[str, Any] = {"executor": "durable_graph"}

    plain_run = _PlainRun()

    class _PlainSpine:
        async def get_runs(self, run_ids: Any, *, principal_id: str) -> dict[str, Any]:
            return {rid: plain_run for rid in run_ids if rid == plain_run.run_id}

        async def get(self, run_id: str) -> None:
            return None

    from services.dag_run_store import get_dag_run_store

    await get_dag_run_store().start_run(
        run_id="r-plain", user_id=_AUTHED_USER_ID, workspace_id=user_workspace
    )
    _wire_spine(monkeypatch, _PlainSpine())

    detail = await visible_run_detail(_AUTHED_USER_ID, "r-plain")
    assert detail is not None
    assert "creative_provenance" not in detail
    assert "artifacts" not in detail


async def test_out_of_scope_caller_gets_no_creative_lineage(
    creative_fulfillment: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Per-artifact state is behind the same Workspace boundary as the run:
    a caller outside the run's universe still gets the non-existence answer,
    never the lineage."""
    from services.dag_run_inspection import visible_run_detail

    record = creative_fulfillment
    await _seed_projection(record)
    _wire_spine(monkeypatch, _SpineStub(record))

    assert await visible_run_detail("someone-else", record.run.run_id) is None


async def test_detail_degrades_to_run_level_lineage_without_the_durable_spine(
    creative_fulfillment: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No durable graph store in the process: the run-level creative block
    still answers (the canonical Run reader is enough for it) and the
    per-artifact reconstruction degrades to an empty list instead of failing
    the read."""
    from services.dag_run_inspection import visible_run_detail

    record = creative_fulfillment
    await _seed_projection(record)
    import services.engine as engine_mod

    monkeypatch.setattr(
        engine_mod,
        "_singleton",
        SimpleNamespace(run_reader=_RunlessSpine(record), graph_run_store=None),
    )

    detail = await visible_run_detail(_AUTHED_USER_ID, record.run.run_id)
    assert detail is not None
    assert detail["creative_provenance"]["goal_revision"] == 4
    assert detail["artifacts"] == []


async def test_artifact_reconstruction_degrades_when_the_durable_read_fails(
    creative_fulfillment: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A durable-store read error is a degraded answer, not a failed read:
    the run-level creative block still answers and the per-artifact
    reconstruction degrades to an empty list (#775's no-invented-state rule)."""
    from services.dag_run_inspection import visible_run_detail

    record = creative_fulfillment
    await _seed_projection(record)

    class _ExplodingStore:
        async def get(self, run_id: str) -> Any:
            raise RuntimeError("durable spine unavailable")

    import services.engine as engine_mod

    monkeypatch.setattr(
        engine_mod,
        "_singleton",
        SimpleNamespace(run_reader=_SpineStub(record), graph_run_store=_ExplodingStore()),
    )

    detail = await visible_run_detail(_AUTHED_USER_ID, record.run.run_id)
    assert detail is not None
    assert detail["creative_provenance"]["goal_revision"] == 4
    assert detail["artifacts"] == []


async def test_artifact_reconstruction_degrades_when_the_spine_never_saw_the_run(
    creative_fulfillment: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A durable store that answers None (run unknown to the spine) yields the
    same degraded empty-artifact answer — never fabricated lineage."""
    from services.dag_run_inspection import visible_run_detail

    record = creative_fulfillment
    await _seed_projection(record)

    class _AmnesiacStore:
        async def get(self, run_id: str) -> None:
            return None

    import services.engine as engine_mod

    monkeypatch.setattr(
        engine_mod,
        "_singleton",
        SimpleNamespace(run_reader=_SpineStub(record), graph_run_store=_AmnesiacStore()),
    )

    detail = await visible_run_detail(_AUTHED_USER_ID, record.run.run_id)
    assert detail is not None
    assert detail["creative_provenance"]["goal_revision"] == 4
    assert detail["artifacts"] == []


async def test_engine_graph_run_store_degrades_without_a_container_bridge() -> None:
    """The `graph_run_store` seam is None — never a fabricated store — when the
    agent port carries no container or the container carries no durable graph
    store, mirroring the `run_store` seam it was modeled on."""
    from types import SimpleNamespace as NS

    from services.engine import EngineService

    engine = EngineService()
    # No port bound at all: both getattrs take their defaults.
    assert engine.graph_run_store is None
    # A container without the durable graph store: still None.
    engine._agent_port = NS(container=NS())
    assert engine.graph_run_store is None
    # A container that carries one: exactly that object, no wrapper.
    store = object()
    engine._agent_port = NS(container=NS(graph_run_store=store))
    assert engine.graph_run_store is store
