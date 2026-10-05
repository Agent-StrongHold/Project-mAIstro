"""Core producer evidence for the scoped operator service and its governed seam."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace

import aiosqlite
import pytest

from maistro.capabilities.binding import ResolvedBinding
from maistro.capabilities.effect_context import binding_scope_policy, new_effect_context
from maistro.capabilities.invocation import (
    InMemoryInvocationStore,
    Invocation,
    InvocationStatus,
    ReconciliationDisposition,
    StaleInvocationUpdate,
)
from maistro.capabilities.invocation_store import SqliteInvocationStore
from maistro.capabilities.operator_reconciliation import (
    INVOCATIONS_INSPECT,
    INVOCATIONS_RECONCILE,
    InvocationNotVisible,
    OperatorInvocationReconciliation,
)
from maistro.projects.scope import ProjectMembership
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.workspaces.store import InMemoryWorkspaceStore


@pytest.fixture(params=["memory", "sqlite"])
async def operator(tmp_path, request):
    async with aiosqlite.connect(tmp_path / "operator.sqlite") as connection:
        store = (
            InMemoryInvocationStore()
            if request.param == "memory"
            else SqliteInvocationStore(connection)
        )
        if isinstance(store, SqliteInvocationStore):
            await store.ensure_schema()
        effects = new_effect_context(invocation_store=store, policy_evaluator=binding_scope_policy)
        projects = InMemoryProjectScopeStore()
        workspaces = InMemoryWorkspaceStore(project_store=projects)
        await workspaces.create(creator_user_id="operator", name="One", workspace_id="ws")
        await workspaces.create(creator_user_id="operator", name="Other", workspace_id="other")
        root = await projects.root_for_workspace("ws")
        project = await projects.create(
            workspace_id="ws", parent_project_id=root.project_id, name="Project"
        )
        sibling = await projects.create(
            workspace_id="ws", parent_project_id=root.project_id, name="Sibling"
        )
        await projects.set_membership(
            ProjectMembership(
                workspace_id="ws",
                project_id=project.project_id,
                principal_id="operator",
                grants={INVOCATIONS_INSPECT, INVOCATIONS_RECONCILE},
            )
        )
        yield SimpleNamespace(
            store=store,
            connection=connection,
            effects=effects,
            projects=projects,
            workspaces=workspaces,
            root=root,
            project=project,
            sibling=sibling,
            service=OperatorInvocationReconciliation(effects, workspaces, projects),
        )


def scope(operator, **changes):
    return {
        "principal_id": "operator",
        "workspace_id": "ws",
        "project_id": operator.project.project_id,
        **changes,
    }


async def seed(operator, identifier="unknown", **changes):
    created = datetime(2020, 1, 1, tzinfo=UTC)
    binding = ResolvedBinding(
        binding_id=identifier,
        workspace_id=changes.pop("workspace_id", "ws"),
        project_id=changes.pop("project_id", operator.project.project_id),
        capability="external_write",
        provider_name="provider",
        provider_trust_tier="trusted",
    )
    status = changes.pop("status", InvocationStatus.UNKNOWN)
    return await operator.store.create(
        Invocation(
            invocation_id=identifier,
            run_id=identifier,
            node_run_id=identifier,
            attempt_id=identifier,
            binding=binding,
            effect_key="effect",
            **{
                "status": status,
                "created_at": created,
                "finished_at": created
                if status in {InvocationStatus.UNKNOWN, InvocationStatus.COMPLETED}
                else None,
                **changes,
            },
        )
    )


@pytest.mark.parametrize("permission", [INVOCATIONS_INSPECT, INVOCATIONS_RECONCILE])
async def test_explicit_project_grants_admit_the_existing_scoped_record(operator, permission):
    item = await seed(operator)
    assert (
        await operator.service.get(item.invocation_id, **scope(operator), permission=permission)
        == item
    )
    assert await operator.store.get(item.invocation_id) == item


@pytest.mark.parametrize("target", ["nonmember", "missing_project", "foreign_project"])
async def test_invalid_authority_is_hidden_before_the_invocation_store_is_read(
    operator, monkeypatch, target
):
    async def forbidden_read(_identifier):
        pytest.fail("an unauthorized caller must never read Invocation evidence")

    monkeypatch.setattr(operator.store, "get", forbidden_read)
    changes = {
        "nonmember": {"principal_id": "outsider"},
        "missing_project": {"project_id": "missing"},
        "foreign_project": {"workspace_id": "other"},
    }[target]
    with pytest.raises(InvocationNotVisible, match=r"^Invocation not found$"):
        await operator.service.get("unknown", **scope(operator, **changes))


async def test_workspace_owner_and_unrelated_project_grants_are_not_operator_authority(operator):
    item = await seed(operator)
    await operator.projects.set_membership(
        ProjectMembership(
            workspace_id="ws",
            project_id=operator.project.project_id,
            principal_id="operator",
            grants={"config.write"},
        )
    )
    with pytest.raises(InvocationNotVisible):
        await operator.service.get(item.invocation_id, **scope(operator))
    assert await operator.store.get(item.invocation_id) == item


@pytest.mark.parametrize("permission", [INVOCATIONS_INSPECT, INVOCATIONS_RECONCILE])
async def test_ancestor_denies_override_the_explicit_project_grant(operator, permission):
    await operator.projects.set_membership(
        ProjectMembership(
            workspace_id="ws",
            project_id=operator.root.project_id,
            principal_id="operator",
            denies={permission},
        )
    )
    with pytest.raises(InvocationNotVisible):
        await operator.service.authorize(**scope(operator), permission=permission)


async def test_unknown_permission_is_rejected_as_a_service_contract_error(operator):
    with pytest.raises(ValueError, match="unknown Invocation permission"):
        await operator.service.authorize(**scope(operator), permission="config.write")


@pytest.mark.parametrize("target", ["missing", "sibling", "foreign_workspace", "legacy"])
async def test_missing_and_out_of_scope_invocations_have_the_same_public_answer(operator, target):
    if target != "missing":
        changes = {
            "sibling": {"project_id": operator.sibling.project_id},
            "foreign_workspace": {"workspace_id": "other"},
            "legacy": {"workspace_id": "", "project_id": ""},
        }[target]
        await seed(operator, target, **changes)
    with pytest.raises(InvocationNotVisible, match=r"^Invocation not found$"):
        await operator.service.get(target, **scope(operator))


async def test_project_revocation_applies_to_discovery_and_existing_record_reads(operator):
    item = await seed(operator)
    assert await operator.service.get(item.invocation_id, **scope(operator)) == item
    await operator.projects.remove_membership(operator.project.project_id, principal_id="operator")
    with pytest.raises(InvocationNotVisible):
        await operator.service.get(item.invocation_id, **scope(operator))
    with pytest.raises(InvocationNotVisible):
        await operator.service.discover(**scope(operator), stale_before=datetime.now(UTC))


async def test_discovery_delegates_bounded_scope_cursor_and_normalized_cutoff(
    operator, monkeypatch
):
    created = datetime(2020, 1, 1, tzinfo=UTC)
    await seed(operator, "a")
    await seed(operator, "b", status=InvocationStatus.RUNNING, started_at=created)
    await seed(operator, "c", status=InvocationStatus.CREATED)
    await seed(
        operator, "live", status=InvocationStatus.RUNNING, started_at=created + timedelta(hours=2)
    )
    await seed(operator, "terminal", status=InvocationStatus.COMPLETED)
    await seed(operator, "foreign", project_id=operator.sibling.project_id)

    async def forbidden_global(**_kwargs):
        pytest.fail("operator discovery must not materialize an unbounded ledger")

    monkeypatch.setattr(operator.store, "list_ambiguous", forbidden_global)
    cutoff = (created + timedelta(hours=1)).astimezone(timezone(timedelta(hours=5)))
    first = await operator.service.discover(**scope(operator), stale_before=cutoff, limit=2)
    assert [item.invocation_id for item in first] == ["a", "b"]
    second = await operator.service.discover(
        **scope(operator),
        stale_before=cutoff,
        limit=2,
        after=(first[-1].created_at.astimezone(timezone(timedelta(hours=5))), "b"),
    )
    assert [item.invocation_id for item in second] == ["c"]
    assert all(item.revision == 0 for item in first + second)


@pytest.mark.parametrize(
    "disposition,status",
    [
        (ReconciliationDisposition.APPLIED, InvocationStatus.COMPLETED),
        (ReconciliationDisposition.NOT_APPLIED, InvocationStatus.FAILED),
        (ReconciliationDisposition.INDETERMINATE, InvocationStatus.UNKNOWN),
    ],
)
async def test_governed_settlement_retains_accepted_audit_and_rejects_a_stale_revision(
    operator, disposition, status
):
    item = await seed(operator)
    inspected = await operator.service.get(
        item.invocation_id, **scope(operator), permission=INVOCATIONS_RECONCILE
    )
    args = {
        "disposition": disposition,
        "source": "operator-api",
        "actor": "operator",
        "reason": "checked provider outcome",
        "evidence": {"receipt": "accepted"},
        "workspace_id": "ws",
        "project_id": operator.project.project_id,
        "expected_revision": inspected.revision,
    }
    settled = await operator.effects.invocations.reconcile(item.invocation_id, **args)
    assert (settled.status, settled.revision) == (status, inspected.revision + 1)
    assert settled.reconciliation_history[-1].evidence == {"receipt": "accepted"}
    with pytest.raises(StaleInvocationUpdate, match="inspect"):
        await operator.effects.invocations.reconcile(
            item.invocation_id, **{**args, "evidence": {"receipt": "stale"}}
        )
    assert await operator.store.get(item.invocation_id) == settled


async def test_concurrent_store_update_is_not_reported_as_accepted_operator_evidence(
    operator, monkeypatch
):
    item = await seed(operator)
    original_save = operator.store.save
    winner = await original_save(item.model_copy(update={"error": "concurrent evidence"}))
    original_get = operator.store.get

    async def stale_read(identifier):
        monkeypatch.setattr(operator.store, "get", original_get)
        assert identifier == item.invocation_id
        return item

    # The operator read preceded another writer's save. The real store CAS
    # must reject this settlement rather than return the competing update as
    # though it accepted the operator's evidence.
    monkeypatch.setattr(operator.store, "get", stale_read)
    with pytest.raises(StaleInvocationUpdate):
        await operator.effects.invocations.reconcile(
            item.invocation_id,
            disposition=ReconciliationDisposition.NOT_APPLIED,
            source="operator-api",
            actor="operator",
            reason="provider receipt was absent",
            evidence={"receipt": "rejected"},
            workspace_id="ws",
            project_id=operator.project.project_id,
            expected_revision=item.revision,
        )
    assert await operator.store.get(item.invocation_id) == winner
    assert winner.reconciliation_history == ()


async def test_unreadable_sqlite_evidence_does_not_establish_record_visibility(tmp_path):
    async with aiosqlite.connect(tmp_path / "unreadable.sqlite") as connection:
        store = SqliteInvocationStore(connection)
        await store.ensure_schema()
        projects = InMemoryProjectScopeStore()
        workspaces = InMemoryWorkspaceStore(project_store=projects)
        await workspaces.create(creator_user_id="operator", name="One", workspace_id="ws")
        root = await projects.root_for_workspace("ws")
        await projects.set_membership(
            ProjectMembership(
                workspace_id="ws",
                project_id=root.project_id,
                principal_id="operator",
                grants={INVOCATIONS_INSPECT},
            )
        )
        fixture = SimpleNamespace(store=store, project=root)
        item = await seed(fixture)
        await connection.execute(
            "UPDATE capability_invocations SET payload_json = json_set(payload_json, '$.unexpected', 1) WHERE invocation_id = ?",
            (item.invocation_id,),
        )
        await connection.commit()
        service = OperatorInvocationReconciliation(
            new_effect_context(invocation_store=store), workspaces, projects
        )
        with pytest.raises(InvocationNotVisible, match=r"^Invocation not found$"):
            await service.get(item.invocation_id, **scope(fixture))
