"""The optimizer target gate reads durable canonical registration (#2469).

`test_optimizer_workspace_authorization.py` pins the gate's decisions
against the embedded canonical authority. This module pins the other half
of the acceptance contract: the gate resolves the owning Workspace from
the *configured* durable canonical Workspace authority and the canonical
template store — the same wired stores a real deployment boots — and keeps
resolving them correctly across a full process restart and a revocation
that was written before that restart. An in-process fake can prove neither.

The harness is the same one `test_workspace_authority_durable.py` uses: a
real `MaistroCoreBridge` against a real database URL and a real Hive
persisted state on disk, booted, restarted, and re-read. The SQLite leg
runs everywhere; the PostgreSQL leg runs wherever `MAISTRO_TEST_PG_DSN`
names a migrated server, and fails rather than silently skipping when CI
demands the legs (`MAISTRO_REQUIRE_PG_LEGS`).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import stores
from adapters.maistro_core import MaistroCoreBridge
from config import Settings
from services import workspace_authority
from services.optimizer_scope import (
    OptimizerTargetNotAuthorized,
    authorize_dag_run,
    authorize_proposal_decision,
    canonical_dag_workspace,
)

from maistro.state import PersistedStore, State
from maistro.testing.postgres import postgres_dsn

REPO_ROOT = Path(__file__).resolve().parents[4]

pytestmark = [pytest.mark.contract("behavioral")]


def _database_url(backend: str, tmp_path: Path) -> str:
    if backend == "sqlite":
        return f"sqlite:///{tmp_path / 'canonical.db'}"
    dsn = postgres_dsn()
    if not dsn:
        if os.environ.get("MAISTRO_REQUIRE_PG_LEGS"):
            msg = (
                "MAISTRO_REQUIRE_PG_LEGS is set but MAISTRO_TEST_PG_DSN is empty: "
                "the optimizer gate's durable leg cannot be checked and must "
                "not be silently skipped"
            )
            raise RuntimeError(msg)
        pytest.skip("set MAISTRO_TEST_PG_DSN to a migrated PostgreSQL database")
    return dsn


class _HiveProcess:
    """One Hive process lifetime: Hive's own state file plus the embedded bridge."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, database_url: str):
        self._state_db = tmp_path / "hive-state.db"
        self._monkeypatch = monkeypatch
        self._database_url = database_url
        self.state: State | None = None
        self.persisted: PersistedStore | None = None
        self.bridge: MaistroCoreBridge | None = None

    def open_hive_state(self) -> PersistedStore:
        self.state = State(db_path=str(self._state_db))
        self.persisted = PersistedStore(self.state)
        self.persisted.initialize()
        return self.persisted

    async def boot(self) -> None:
        import services.engine as engine_mod

        persisted = self.open_hive_state()
        self._monkeypatch.setattr(stores, "_persisted", persisted)
        self._monkeypatch.setattr(stores.workspaces, "_persisted", persisted)
        stores.workspaces.initialize()
        workspace_authority.reset_for_tests()

        self._monkeypatch.setenv("DATABASE_URL", self._database_url)
        self.bridge = MaistroCoreBridge()
        await self.bridge.start(
            Settings(
                maistro_router_api_key="k" * 32,
                maistro_agents_dir=str(REPO_ROOT / "agents"),
            )
        )
        self._monkeypatch.setattr(engine_mod.get_engine(), "_agent_port", self.bridge)

    async def stop(self) -> None:
        if self.bridge is not None and self.bridge.container is not None:
            await self.bridge.container.aclose()
        self.bridge = None
        self.close_hive_state()

    def close_hive_state(self) -> None:
        if self.state is not None:
            self.state.flush()
            self.state.close()
        self.state = None
        self.persisted = None

    @property
    def template_store(self) -> Any:
        assert self.bridge is not None and self.bridge.container is not None
        return self.bridge.container.template_store


@pytest.fixture
async def hive(
    request: pytest.FixtureRequest,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[_HiveProcess]:
    monkeypatch.setattr(stores.workspaces, "_data", {})
    process = _HiveProcess(tmp_path, monkeypatch, _database_url(request.param, tmp_path))
    await process.boot()
    try:
        yield process
    finally:
        await process.stop()
        workspace_authority.reset_for_tests()


BACKENDS = pytest.mark.parametrize("hive", ["sqlite", "postgres"], indirect=True)


def _descriptor(dag_id: str) -> dict[str, Any]:
    return {
        "id": dag_id,
        "name": f"DAG {dag_id}",
        "description": "durable gate fixture",
        "entry_node": "n1",
        "max_cycles": 5,
        "run_scout": False,
        "status": "draft",
        "created_at": "2026-09-01T00:00:00+00:00",
        "updated_at": "2026-09-01T00:00:00+00:00",
        "nodes": [
            {"id": "n1", "role": "worker", "name": "Worker", "model": "m-a", "prompt": "p"},
            {"id": "n2", "role": "reviewer", "name": "Review", "model": "m-b", "prompt": "q"},
        ],
        "edges": [{"id": "e1", "from_node": "n1", "to_node": "n2"}],
    }


def _proposal(proposal_id: str, dag_id: str, workspace_id: str) -> dict[str, Any]:
    return {
        "id": proposal_id,
        "dag_id": dag_id,
        "target_node_id": "n1",
        "class": "propose",
        "kind": "prompt_rewrite",
        "field_path": "nodes.n1.prompt",
        "rationale": "durable registration evidence",
        "priority_score": 1.0,
        "to_value": None,
        "source_dag_hash": "deadbeef",
        "source_template_version": 1,
        "evaluator_version": "eval-judge/1",
        "workspace_id": workspace_id,
        "blocked_by_edit_lock": False,
        "applied": False,
        "apply_outcome": None,
        "apply_detail": "",
        "resulting_version": None,
        "candidate_hash": None,
        "decision": "pending",
        "created_at": "2026-09-01T12:00:00+00:00",
        "topology_proposal": None,
    }


@BACKENDS
@pytest.mark.asyncio
async def test_gate_resolves_durable_registration_across_restart_and_revocation(
    hive: _HiveProcess,
) -> None:
    # The canonical authority is the configured durable store, not the
    # embedded fallback this process would otherwise use.
    from maistro.workspaces.store import InMemoryWorkspaceStore

    store = await workspace_authority.canonical_workspace_store()
    assert not isinstance(store, InMemoryWorkspaceStore)

    workspace_b = f"ws-b-{uuid.uuid4().hex[:8]}"
    workspace_a = f"ws-a-{uuid.uuid4().hex[:8]}"
    await store.create(creator_user_id="owner-b", workspace_id=workspace_b, name="B")
    await store.create(creator_user_id="owner-a", workspace_id=workspace_a, name="A")

    dag_b = f"dag-b-{uuid.uuid4().hex[:8]}"
    stores.dags[dag_b] = _descriptor(dag_b)

    # The DAG's canonical registration lives in the wired template store
    # under tenant B's Workspace; one stale proposal row claims tenant A.
    from maistro.graph.template_adapter import snapshot_to_template

    template = snapshot_to_template(
        dict(stores.dags[dag_b]),
        workspace_id=workspace_b,
        template_id=dag_b,
        version=1,
    )
    await hive.template_store.put(template)
    stores.optimizer_proposals["stale-row"] = _proposal("stale-row", dag_b, workspace_a)
    stores.optimizer_proposals["honest-row"] = _proposal("honest-row", dag_b, workspace_b)

    # Registration wins over the stale recording: the DAG's tenancy is B,
    # the stale row discloses itself to no one, B's honest row survives.
    assert await canonical_dag_workspace(dag_b) == workspace_b
    with pytest.raises(OptimizerTargetNotAuthorized):
        await authorize_proposal_decision("owner-a", "stale-row")
    target = await authorize_proposal_decision("owner-b", "honest-row")
    assert target.workspace_id == workspace_b
    scope = await authorize_dag_run("owner-b", dag_b, workspace_id=workspace_b)
    assert scope.workspace_id == workspace_b
    with pytest.raises(OptimizerTargetNotAuthorized):
        await authorize_dag_run("owner-a", dag_b, workspace_id=workspace_a)

    # Revoke B's initiator through the canonical authority (a neutral owner
    # holds the Workspace while B is removed), then restart the whole
    # process. The registration, the revocation, and therefore the refusals
    # all come back from durable state, not memory.
    await store.set_membership(workspace_b, user_id="owner-neutral", role="owner")
    await store.remove_membership(workspace_b, user_id="owner-b")
    await hive.stop()
    await hive.boot()

    assert await canonical_dag_workspace(dag_b) == workspace_b
    with pytest.raises(OptimizerTargetNotAuthorized):
        await authorize_proposal_decision("owner-b", "honest-row")
    # The revoked initiator's Workspace selection shares the seam's
    # historical refusal: a non-member selection is "not found" at the
    # selection boundary (the route maps it to 403) before any tenancy
    # question is even asked.
    from services.dag_execution_scope import DagWorkspaceSelectionError

    with pytest.raises(DagWorkspaceSelectionError):
        await authorize_dag_run("owner-b", dag_b, workspace_id=workspace_b)
