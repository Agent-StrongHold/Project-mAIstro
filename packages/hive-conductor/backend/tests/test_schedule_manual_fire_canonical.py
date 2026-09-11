"""E2E: `POST /v1/schedules/{id}/run` fires through the canonical spine (#1119).

The unit suites prove the admitter and the runner in isolation. What only an
end-to-end drive can prove is the acceptance this issue actually names: the
HTTP route, against a *real configured Container* (``create_container``, not a
SimpleNamespace), produces a Run whose Workspace and Project are the
configured canonical ones — not the synthetic ``hive:schedule:{id}`` identities
the compatibility path used to fabricate — with the schedule's provenance and
actor on it, and the product row's ``last_run_id`` resolving into the
Container's own Run store.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

_SID = "s-e2e-manual-fire"
_TPL = "e2e-manual-fire-template"


async def _build_container() -> Any:
    """A real wired Container: in-memory spine, Root Project already created."""
    from maistro.container import create_container
    from maistro.types.config import AgentConfig

    return await create_container(AgentConfig(router_api_key="test-key"))


def _descriptor() -> dict[str, Any]:
    return {
        "id": _TPL,
        "name": "E2E manual fire",
        "entry_node": "only",
        "nodes": [{"id": "only", "kind": "transform.alias_keys", "config": {"mapping": {}}}],
        "edges": [],
    }


def _row() -> Any:
    from models.schemas import Schedule

    now = datetime.now(UTC)
    return Schedule(
        id=_SID,
        # The owner the product row carries; the Run must name it as actor.
        user_id="user-1",
        name="e2e manual fire",
        description="",
        cron_expression="0 * * * *",
        mission_template_id=_TPL,
        enabled=True,
        timezone="UTC",
        max_runs=None,
        last_run=None,
        last_run_id=None,
        next_run=None,
        created_at=now,
        updated_at=now,
    )


def _install(row: Any) -> None:
    import stores

    stores.schedules._data[row.id] = row  # type: ignore[attr-defined]


def _remove() -> None:
    import stores

    stores.schedules._data.pop(_SID, None)  # type: ignore[attr-defined]


@pytest.fixture
def _configured_container(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Swap the session engine's stub port for one carrying a real Container.

    The stub port has no ``container`` attribute — that absence is exactly what
    steers `fire_now` to the standalone compatibility path, and what the
    configured-product path below must not be reachable without.
    """
    import services.engine as engine_mod

    container = asyncio.run(_build_container())
    service = engine_mod.get_engine()
    previous = service._agent_port
    service._agent_port = SimpleNamespace(container=container)
    yield container
    service._agent_port = previous


def test_manual_fire_over_http_creates_one_canonical_run(
    admin_client: Any, _configured_container: Any
) -> None:
    """AC: canonical Workspace/Project/Run identities, provenance, actor, and
    exactly one Run for the accepted request."""
    from config import get_settings
    from services.dag_agents import get_registry

    from maistro.runs.model import RunStatus

    container = _configured_container
    registry = get_registry()
    registry.register(_descriptor())
    _install(_row())
    try:
        response = admin_client.post(f"/v1/schedules/{_SID}/run")
        assert response.status_code == 200, response.text
        body = response.json()
        run_id = body["last_run_id"]
        assert run_id, "the row must name the Run it produced"

        async def assert_canonical() -> None:
            workspace = get_settings().hive_default_workspace_id
            root = await container.project_scope_store.root_for_workspace(workspace)

            run = await container.run_store.get_run(run_id)
            assert run is not None, "last_run_id resolves inside the configured Container"
            assert run.workspace_id == workspace
            assert run.project_id == root.project_id
            assert run.project_id != f"hive:schedule:{_SID}"
            assert run.status is RunStatus.QUEUED, "admission is submission (#251)"
            assert run.actor_principal_id == "user-1"
            assert run.provenance["admission_source"] == "schedule"
            assert run.provenance["schedule_id"] == _SID
            assert run.provenance["catchup"] is False
            assert "scheduled_for" in run.provenance

            template = await container.template_store.get(_TPL)
            assert template is not None, "the durable template, not the registry, backed it"
            assert template.workspace_id == workspace

            recorded = await container.schedule_store.get(_SID)
            assert recorded is not None
            assert recorded.last_run_id == run_id
            assert recorded.runs_so_far == 1

            scheduled = [
                other
                for other in container.run_store._runs.values()  # type: ignore[attr-defined]
                if other.provenance.get("schedule_id") == _SID
            ]
            assert scheduled == [run], "exactly one canonical Run for one accepted request"

        asyncio.run(assert_canonical())

        import stores

        audit_targets = [
            entry for entry in list(stores.audit_log.values()) if entry.get("target") == _SID
        ]
        assert [e["action"] for e in audit_targets] == ["schedule_fire", "schedule_run"]
        assert audit_targets[1]["detail"]["run_id"] == run_id
    finally:
        _remove()
        registry.deregister(_TPL)


def test_manual_fire_with_an_unresolvable_template_is_a_409_that_changes_nothing(
    admin_client: Any, _configured_container: Any
) -> None:
    """AC: the product-visible refusal survives the migration, and neither the
    canonical cursor nor the row moves."""
    _install(_row())
    try:
        response = admin_client.post(f"/v1/schedules/{_SID}/run")
        assert response.status_code == 409, response.text
        assert "may not be registered" in response.json()["detail"]

        after = admin_client.get(f"/v1/schedules/{_SID}").json()
        assert after["last_run"] is None
        assert after["last_run_id"] is None

        container = _configured_container

        async def assert_unchanged() -> None:
            recorded = await container.schedule_store.get(_SID)
            assert recorded is not None
            assert recorded.runs_so_far == 0
            assert recorded.last_fired_at is None
            assert recorded.last_run_id is None
            assert len(container.run_store._runs) == 0  # type: ignore[attr-defined]

        asyncio.run(assert_unchanged())
    finally:
        _remove()


def test_manual_fire_on_a_half_wired_container_is_a_503_not_a_fallback(
    admin_client: Any, _configured_container: Any
) -> None:
    """AC: a configured Container missing a collaborator fails closed — the
    compatibility path must not become reachable through its absence."""
    _configured_container.schedule_admitter = None  # the canonical collaborator is missing
    _install(_row())
    try:
        response = admin_client.post(f"/v1/schedules/{_SID}/run")
        assert response.status_code == 503, response.text
        assert "admission" in response.json()["detail"].lower()

        after = admin_client.get(f"/v1/schedules/{_SID}").json()
        assert after["last_run"] is None
        assert after["last_run_id"] is None
    finally:
        _remove()
