"""P0.4: one durable audit store (Workspace cutover plan, #53 / #325).

Four security-relevant events -- a failed login, an elevation, a HITL cancel
and a denied tool call -- are driven through Hive's own backend paths with a
real SQLite Container bound where the bridge binds it. Each must leave exactly
one row readable through the Container's Sentinel ``AuditLog``. ``GET /v1/audit``
must serve that same store. Hive today keys JsonStore rows by username for auth
events and by ``user_id`` for chat-tool blocks; convergence must normalize to
``Principal.user_id`` (and later Workspace/Run — SQLite audit has neither column yet).

Today none of them reach the core store: Hive's ``log_audit`` writes
``stores.audit_log`` (a ``JsonStore``) and nothing in the Hive backend reaches
``container.audit_log``. HITL cancel does write the JsonStore
(``routes/hitl.py``); canonical ``_mutate_hitl`` still emits nothing.
Each such case is in ``KNOWN_GAPS``, where the test asserts the event is still
absent from the core store -- so the change that converges one fails here until
its entry is deleted.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import httpx
import pytest
import services.chat_completion as chat_completion
from services.workspace_authority import canonical_store_for_tests, create_workspace

from maistro.container import Container, create_container
from maistro.graph import Graph, Node
from maistro.graph.durable_runs import run_durable_graph
from maistro.graph.nodes import get_node
from maistro.runs.model import RunStatus
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID
from maistro.types.config import AgentConfig
from maistro.types.security import AuditEntry

pytestmark = [pytest.mark.contract("cross-service")]

KNOWN_GAPS: frozenset[str] = frozenset()

# Seeded by conftest._seed_test_user.
_USER = ("user", "testuser", "testpass")
_ADMIN = ("admin", "testadmin", "adminpass")


@pytest.fixture
async def container(tmp_path: Path) -> AsyncIterator[Container]:
    built = await create_container(
        AgentConfig(
            router_api_key="test-key",
            database_url=f"sqlite:///{tmp_path / 'audit-convergence.db'}",
        )
    )
    try:
        yield built
    finally:
        await built.aclose()


@pytest.fixture
def booted(container: Container, monkeypatch: pytest.MonkeyPatch) -> Container:
    """Bind the Container to the running engine exactly where the bridge puts it."""
    from services.engine import get_engine

    monkeypatch.setattr(get_engine(), "_agent_port", SimpleNamespace(container=container))
    return container


@pytest.fixture
async def client(booted: Container) -> AsyncIterator[httpx.AsyncClient]:
    """The Hive app on the test's own event loop, so the SQLite pool is shared."""
    from main import app

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as http:
        yield http


async def _login(client: httpx.AsyncClient, username: str, password: str) -> None:
    response = await client.post(
        "/v1/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text


async def _core_rows(container: Container) -> list[AuditEntry]:
    """Every unscoped row in the Container's audit store, newest first."""
    audit_log: Any = container.audit_log
    assert audit_log is not None
    rows: list[AuditEntry] = await audit_log.get_entries(limit=10_000)
    return rows


async def _assert_converges(
    case: str, container: Container, before: list[AuditEntry], expected_actor: str
) -> None:
    after = await _core_rows(container)
    new = after[: len(after) - len(before)]
    if case in KNOWN_GAPS:
        assert new == [], f"{case} now reaches the core AuditLog; delete it from KNOWN_GAPS"
        return
    assert len(new) == 1, new
    assert new[0].user_id == expected_actor


def test_known_gaps_name_real_cases() -> None:
    cases = {
        "failed_login",
        "elevation",
        "hitl_cancel",
        "denied_tool_call",
        "audit_read_path",
    }
    assert cases >= KNOWN_GAPS


async def test_failed_login_is_one_core_audit_row(
    client: httpx.AsyncClient, booted: Container
) -> None:
    _user_id, username, _password = _USER
    before = await _core_rows(booted)

    response = await client.post(
        "/v1/auth/login", json={"username": username, "password": "not-the-password"}
    )

    assert response.status_code == 401
    await _assert_converges("failed_login", booted, before, username)


async def test_elevation_is_one_core_audit_row(
    client: httpx.AsyncClient, booted: Container
) -> None:
    _user_id, username, password = _USER
    await _login(client, username, password)
    before = await _core_rows(booted)

    response = await client.post(
        "/v1/auth/elevate", json={"password": password, "task_id": f"task-{uuid4().hex}"}
    )

    assert response.status_code == 200, response.text
    await _assert_converges("elevation", booted, before, username)


async def _paused_hitl_run(container: Container, *, creator: str) -> str:
    """A real ``human.approve_draft`` Run paused on the Container's canonical spine."""
    workspace = await create_workspace(
        creator_user_id=creator,
        name=f"Audit Convergence {uuid4().hex[:8]}",
        persona_template_id="default",
        checklist=[],
        theme_id="default",
        voice_tone_override=None,
    )
    root = await canonical_store_for_tests().project_store.root_for_workspace(workspace.id)
    graph = Graph(
        workspace_id=workspace.id,
        project_id=root.project_id,
        name="approval",
        nodes=[
            Node(
                node_id="ask",
                node_type="human.approve_draft",
                inputs={"draft": {"ticket": "PROJ-1"}, "timeout_seconds": 3600},
            )
        ],
    )
    assert container.run_store is not None
    assert container.graph_run_store is not None
    admitted = await container.run_store.create_run(
        graph,
        initial_status=RunStatus.QUEUED,
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
    )
    paused = await run_durable_graph(
        graph,
        store=container.graph_run_store,
        node_resolver=lambda _node_id, _graph: get_node("human.approve_draft")(),
        run_id=admitted.run_id,
        run_store=container.run_store,
    )
    assert paused.status is RunStatus.PAUSED
    return admitted.run_id


async def test_hitl_cancel_is_one_core_audit_row(
    client: httpx.AsyncClient, booted: Container
) -> None:
    user_id, username, password = _ADMIN
    await _login(client, username, password)
    run_id = await _paused_hitl_run(booted, creator=user_id)
    before = await _core_rows(booted)

    response = await client.post(f"/v1/hitl/{run_id}/ask/cancel")

    assert response.status_code == 200, response.text
    await _assert_converges("hitl_cancel", booted, before, username)


async def test_denied_tool_call_is_one_core_audit_row(booted: Container) -> None:
    """The chat tool loop's dispatch seam refuses an unapproved workflow run."""
    user_id = _USER[0]
    before = await _core_rows(booted)

    result = await chat_completion._execute_tool(
        "run_workflow", {"dag_id": f"dag-{uuid4().hex}"}, user_id
    )

    assert result["blocked"] is True
    await _assert_converges("denied_tool_call", booted, before, user_id)


async def test_audit_route_reads_the_core_audit_log(
    client: httpx.AsyncClient, booted: Container
) -> None:
    _user_id, username, password = _ADMIN
    await _login(client, username, password)
    marker = f"p0-4-{uuid4().hex}"
    audit_log = booted.audit_log
    assert audit_log is not None
    await audit_log.log(
        AuditEntry(
            timestamp=datetime.now(UTC),
            boundary="test",
            user_id="user",
            verdict="denied",
            detail=marker,
            request_id=marker,
        )
    )

    response = await client.get("/v1/audit")

    assert response.status_code == 200, response.text
    served = response.text.count(marker)
    if "audit_read_path" in KNOWN_GAPS:
        assert served == 0, "GET /v1/audit now serves the core AuditLog; delete it from KNOWN_GAPS"
        return
    assert served >= 1
