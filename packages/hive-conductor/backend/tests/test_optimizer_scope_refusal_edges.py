"""Fail-closed refusal edges of the optimizer target gate (#2469).

The ASGI authorization suite proves the gate's cross-tenant refusals through
real routes. A single-threaded request cannot reach every edge the gate
guards: resolution-layer invariants (blank ids, an unreadable template
version, garbage or blank projection rows, one template registered under two
Workspaces, a row contradicting the precomputed DAG tenancy), the decision
edges (a proposal whose DAG was deleted, a scope-less row), and the
defense-in-depth contradiction check in `record_decision` that the route can
only reach through a race between authorization and mutation. Each case
here pins one of those edges: the gate refuses, discloses nothing, and
writes nothing — the fail-closed posture the issue requires for absent,
foreign, deleted, revoked, scope-less, and aliasing targets.
"""

from __future__ import annotations

import asyncio
import copy
import pathlib
import sys
from types import SimpleNamespace
from typing import Any

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

pytestmark = [pytest.mark.contract("boundary")]

_TENANT_A = "ws-refusal-tenant-a"
_TENANT_B = "ws-refusal-tenant-b"
_MEMBER = "owner-refusal-a"


def _wipe(store: Any) -> None:
    for key in list(store.keys()):
        store.pop(key)


def _descriptor(dag_id: str) -> dict[str, Any]:
    """The minimal descriptor `snapshot_to_template` registers."""
    return {
        "id": dag_id,
        "name": f"DAG {dag_id}",
        "description": "refusal edge fixture",
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
    """A stored proposal row in the projection's own shape."""
    return {
        "id": proposal_id,
        "dag_id": dag_id,
        "target_node_id": "n1",
        "class": "propose",
        "kind": "prompt_rewrite",
        "field_path": "nodes.n1.prompt",
        "rationale": "refusal edge evidence",
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


@pytest.fixture(autouse=True)
def _isolated():
    """Fresh stores and template store for every test."""
    import stores
    from services.optimizer_candidates import set_template_store

    from maistro.graph.templates import InMemoryGraphTemplateStore

    template_store = InMemoryGraphTemplateStore()
    set_template_store(template_store)
    yield template_store
    set_template_store(None)
    for target in (stores.audit_log, stores.eval_verdicts, stores.optimizer_proposals, stores.dags):
        _wipe(target)


def _owned_workspace(store: Any, workspace_id: str) -> None:
    """A canonical Workspace whose creator holds live ownership."""
    asyncio.run(store.create(creator_user_id=_MEMBER, workspace_id=workspace_id, name="W"))


def _register(descriptor: dict[str, Any], store: Any, workspace_id: str, version: int) -> None:
    from maistro.graph.template_adapter import snapshot_to_template

    asyncio.run(
        store.put(
            snapshot_to_template(
                dict(descriptor),
                workspace_id=workspace_id,
                template_id=descriptor["id"],
                version=version,
            )
        )
    )


def _audit_actions() -> list[dict[str, Any]]:
    import stores

    return [entry for entry in stores.audit_log.values() if isinstance(entry, dict)]


# --- resolution-layer invariants -------------------------------------------


def test_a_blank_dag_id_has_no_canonical_workspace(_isolated: Any) -> None:
    from services.optimizer_scope import (
        OptimizerTargetNotAuthorized,
        canonical_dag_workspace,
    )

    for blank in ("", "   "):
        with pytest.raises(OptimizerTargetNotAuthorized):
            asyncio.run(canonical_dag_workspace(blank))
    assert _audit_actions() == []


def test_an_unreadable_template_version_contributes_no_claim(_isolated: Any) -> None:
    from services.optimizer_candidates import set_template_store
    from services.optimizer_scope import canonical_dag_workspace

    class _VersionWithoutPayload:
        async def versions(self, template_id: str) -> list[int]:
            return [1]

        async def get(self, template_id: str, *, version: int | None = None) -> None:
            return None

    set_template_store(_VersionWithoutPayload())
    # A registered version whose payload cannot be read makes no Workspace
    # claim; the DAG is unclaimed, not foreign.
    assert asyncio.run(canonical_dag_workspace("dag-unreadable")) == ""


def test_a_template_store_outage_refuses_closed(_isolated: Any) -> None:
    from services.optimizer_candidates import set_template_store
    from services.optimizer_scope import (
        OptimizerTargetNotAuthorized,
        canonical_dag_workspace,
        canonical_proposal_workspace,
    )

    class _OutageStore:
        async def versions(self, template_id: str) -> list[int]:
            raise ConnectionError("pool exhausted")

        async def get(self, template_id: str, *, version: int | None = None) -> None:
            raise TimeoutError("read timed out")

    set_template_store(_OutageStore())
    import stores

    _wipe(stores.optimizer_proposals)
    stores.optimizer_proposals["stale-row"] = {
        "id": "stale-row",
        "dag_id": "dag-outage",
        "workspace_id": _TENANT_A,
    }
    try:
        # A store outage is not an unregistered DAG: neither the canonical
        # answer nor the recorded-row fallback may answer while the
        # registration authority is unreadable.
        with pytest.raises(OptimizerTargetNotAuthorized):
            asyncio.run(canonical_dag_workspace("dag-outage"))
        with pytest.raises(OptimizerTargetNotAuthorized):
            asyncio.run(
                canonical_proposal_workspace(
                    {
                        "id": "stale-row",
                        "dag_id": "dag-outage",
                        "workspace_id": _TENANT_A,
                    }
                )
            )
    finally:
        _wipe(stores.optimizer_proposals)


def test_an_unreadable_version_read_refuses_closed(_isolated: Any) -> None:
    from services.optimizer_candidates import set_template_store
    from services.optimizer_scope import (
        OptimizerTargetNotAuthorized,
        canonical_dag_workspace,
    )

    class _VersionReadFails:
        async def versions(self, template_id: str) -> list[int]:
            return [1]

        async def get(self, template_id: str, *, version: int | None = None) -> None:
            raise ConnectionError("connection reset")

    set_template_store(_VersionReadFails())
    # Same posture for the per-version read: a failure mid-loop refuses the
    # target rather than downgrading to a partial (possibly empty) claim.
    with pytest.raises(OptimizerTargetNotAuthorized):
        asyncio.run(canonical_dag_workspace("dag-outage"))


def test_a_template_version_without_a_workspace_claims_nothing(_isolated: Any) -> None:
    from services.optimizer_candidates import set_template_store
    from services.optimizer_scope import canonical_dag_workspace

    class _VersionWithoutTenant:
        async def versions(self, template_id: str) -> list[int]:
            return [1, 2]

        async def get(self, template_id: str, *, version: int | None = None) -> Any:
            return SimpleNamespace(workspace_id="   ", version=version)

    set_template_store(_VersionWithoutTenant())
    assert asyncio.run(canonical_dag_workspace("dag-tenantless")) == ""


def test_projection_garbage_and_blank_rows_make_no_recording(_isolated: Any) -> None:
    import stores
    from services.optimizer_scope import canonical_dag_workspace

    stores.dags["dag-messy"] = _descriptor("dag-messy")
    stores.optimizer_proposals["garbage"] = "not-a-proposal-row"
    stores.optimizer_proposals["blank-tenant"] = {
        "id": "blank-tenant",
        "dag_id": "dag-messy",
        "workspace_id": "",
    }
    # Neither row claims a tenant: the DAG stays unclaimed and the surface
    # answers empty instead of guessing.
    assert asyncio.run(canonical_dag_workspace("dag-messy")) == ""


def test_one_template_registered_under_two_workspaces_is_an_aliasing_fault(
    _isolated: Any,
) -> None:
    import stores
    from services.optimizer_scope import (
        OptimizerTargetNotAuthorized,
        canonical_dag_workspace,
        canonical_proposal_workspace,
    )

    descriptor = _descriptor("dag-split")
    stores.dags["dag-split"] = descriptor
    _register(descriptor, _isolated, _TENANT_A, 1)
    _register(descriptor, _isolated, _TENANT_B, 2)
    stores.optimizer_proposals["honest-row"] = _proposal("honest-row", "dag-split", _TENANT_A)

    with pytest.raises(OptimizerTargetNotAuthorized):
        asyncio.run(canonical_dag_workspace("dag-split"))
    # The fault refuses the rows too: no decision can slip through either
    # tenant while the conflicting registration stands.
    with pytest.raises(OptimizerTargetNotAuthorized):
        asyncio.run(canonical_proposal_workspace(stores.optimizer_proposals["honest-row"]))
    assert _audit_actions() == []


def test_a_proposal_without_a_dag_resolves_to_nothing(_isolated: Any) -> None:
    from services.optimizer_scope import (
        OptimizerTargetNotAuthorized,
        canonical_proposal_workspace,
    )

    with pytest.raises(OptimizerTargetNotAuthorized):
        asyncio.run(canonical_proposal_workspace({"id": "p-orphan", "workspace_id": _TENANT_A}))
    with pytest.raises(OptimizerTargetNotAuthorized):
        asyncio.run(canonical_proposal_workspace({"id": "p-blank", "dag_id": "   "}))


def test_a_row_contradicting_the_precomputed_tenancy_refuses(_isolated: Any) -> None:
    from services.optimizer_scope import (
        OptimizerTargetNotAuthorized,
        canonical_proposal_workspace,
    )

    # The DAG's tenancy of record is tenant A; a row claiming tenant B (or
    # claiming nothing) is stale, forged, or rehomed. It refuses instead of
    # resolving to whichever id the caller asked about.
    stale = _proposal("stale-row", "dag-claimed", _TENANT_B)
    with pytest.raises(OptimizerTargetNotAuthorized):
        asyncio.run(canonical_proposal_workspace(stale, dag_tenancy=_TENANT_A))
    scopeless = _proposal("scopeless-row", "dag-claimed", "")
    with pytest.raises(OptimizerTargetNotAuthorized):
        asyncio.run(canonical_proposal_workspace(scopeless, dag_tenancy=_TENANT_A))


def test_member_role_refuses_blank_identities(_isolated: Any) -> None:
    from services.optimizer_scope import _member_role

    assert asyncio.run(_member_role("", _TENANT_A)) is None
    assert asyncio.run(_member_role(_MEMBER, "   ")) is None


# --- visible-row edges ------------------------------------------------------


def test_visible_rows_skip_garbage_and_honor_the_decision_filter(_isolated: Any) -> None:
    import stores
    from services.optimizer_scope import visible_proposals

    _owned_workspace(workspace_authority_store(), _TENANT_A)
    accepted = _proposal("row-accepted", "dag-filter", _TENANT_A)
    accepted["decision"] = "accepted"
    accepted["created_at"] = "2026-09-02T00:00:00+00:00"
    pending = _proposal("row-pending", "dag-filter", _TENANT_A)
    pending["created_at"] = "2026-09-01T00:00:00+00:00"
    stores.optimizer_proposals["row-accepted"] = accepted
    stores.optimizer_proposals["row-pending"] = pending
    stores.optimizer_proposals["row-garbage"] = 42

    rows = asyncio.run(visible_proposals(_MEMBER))
    assert [row["id"] for row in rows] == ["row-accepted", "row-pending"]
    only_pending = asyncio.run(visible_proposals(_MEMBER, decision="pending"))
    assert [row["id"] for row in only_pending] == ["row-pending"]
    only_accepted = asyncio.run(visible_proposals(_MEMBER, decision="accepted"))
    assert [row["id"] for row in only_accepted] == ["row-accepted"]


def test_an_unclaimed_dag_answers_an_empty_list_without_disclosure(_isolated: Any) -> None:
    import stores
    from services.optimizer_scope import visible_dag_proposals

    stores.dags["dag-quiet"] = _descriptor("dag-quiet")
    # No registration, no recordings: the DAG has nothing to disclose, and
    # the answer is the empty list — not an error, not another tenant's rows.
    assert asyncio.run(visible_dag_proposals(_MEMBER, "dag-quiet")) == []


def workspace_authority_store() -> Any:
    from services.workspace_authority import canonical_store_for_tests

    return canonical_store_for_tests()


# --- decision edges ---------------------------------------------------------


def test_a_decision_refuses_a_deleted_target_dag_and_a_scopeless_row(
    _isolated: Any,
) -> None:
    import stores
    from services.optimizer_scope import (
        OptimizerTargetNotAuthorized,
        authorize_proposal_decision,
    )

    stores.dags["dag-live"] = _descriptor("dag-live")

    blank_dag = _proposal("p-blank-dag", "", _TENANT_A)
    stores.optimizer_proposals["p-blank-dag"] = blank_dag
    deleted_target = _proposal("p-deleted", "dag-gone", _TENANT_A)
    stores.optimizer_proposals["p-deleted"] = deleted_target
    scopeless = _proposal("p-scopeless", "dag-live", "")
    stores.optimizer_proposals["p-scopeless"] = scopeless

    with pytest.raises(OptimizerTargetNotAuthorized):
        asyncio.run(authorize_proposal_decision(_MEMBER, "p-blank-dag"))
    with pytest.raises(OptimizerTargetNotAuthorized):
        asyncio.run(authorize_proposal_decision(_MEMBER, "p-deleted"))
    with pytest.raises(OptimizerTargetNotAuthorized):
        asyncio.run(authorize_proposal_decision(_MEMBER, "p-scopeless"))

    # Every refusal wrote nothing: no decision fields, no audit entries.
    for proposal_id in ("p-blank-dag", "p-deleted", "p-scopeless"):
        row = stores.optimizer_proposals[proposal_id]
        assert row["decision"] == "pending"
        assert "decided_by" not in row and "decided_at" not in row
    assert _audit_actions() == []


def test_record_decision_refuses_a_recording_contradicting_the_authorized_tenant(
    _isolated: Any,
) -> None:
    import stores
    from services.optimizer import record_decision

    row = _proposal("p-aliased", "dag-any", _TENANT_A)
    stores.optimizer_proposals["p-aliased"] = row
    before = copy.deepcopy(row)

    # Defense in depth behind the gate: a caller that (through a race or a
    # bug) arrives with an authorized Workspace the row does not record is
    # refused — never rehomed onto the authorized tenant.
    with pytest.raises(KeyError):
        asyncio.run(
            record_decision(
                "p-aliased",
                "accepted",
                actor="admin",
                workspace_id=_TENANT_B,
            )
        )

    assert stores.optimizer_proposals["p-aliased"] == before
    assert _audit_actions() == []
