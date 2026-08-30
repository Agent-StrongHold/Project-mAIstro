"""Unit tests for PgDesignProjectStore."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from maistro_design.stores import (
    PgDesignProjectStore,
    _coerce_design_output,
    _coerce_design_project,
)
from maistro_design.trust import TrustTier
from maistro_design.types import (
    ArtifactKind,
    ArtifactNode,
    DesignOutput,
    DesignProject,
    DiscoveryResult,
    OutputFormat,
)


def make_mock_session_factory():
    """Create a callable that returns an async context manager for a mock session."""

    mock_session = AsyncMock()

    @asynccontextmanager
    async def factory():
        yield mock_session

    return factory, mock_session


@pytest.fixture
def sample_project():
    """Create a sample DesignProject for testing."""
    discovery = DiscoveryResult(
        skill_slug="login-flow",
        responses={"auth_methods": "Email/Password", "brand_tone": "Professional"},
        design_system_slug="default",
        trust_tier=TrustTier.T3,
    )
    output = DesignOutput(
        root=ArtifactNode(
            key="root",
            kind=ArtifactKind.FILE,
            format=OutputFormat.REACT_TSX,
            value="export default function LoginFlow() { ... }",
        ),
        trust_tier=TrustTier.T3,
        metadata={"generated_at": "2026-06-28T00:00:00Z"},
    )
    return DesignProject(
        id="test-project-1",
        name="Login Flow (Default)",
        skill_slug="login-flow",
        design_system_slug="default",
        org_id="org-123",
        team_id="team-456",
        trust_tier=TrustTier.T3,
        outputs=[output],
        discovery=discovery,
    )


def test_coerce_design_output():
    """Test that _coerce_design_output converts database row to DesignOutput."""

    class MockRow(dict):
        def __getitem__(self, key):
            return super().get(key)

    row = MockRow(
        format="react_tsx",
        content="export default function() {}",
        url=None,
        trust_tier="t3",
        metadata_json='{"custom": "value"}',
    )

    output = _coerce_design_output(row)

    assert output.format == OutputFormat.REACT_TSX
    assert output.content == "export default function() {}"
    assert output.trust_tier == TrustTier.T3
    assert output.metadata["custom"] == "value"


def test_coerce_design_output_empty_metadata():
    """Test _coerce_design_output with empty metadata."""

    class MockRow(dict):
        def __getitem__(self, key):
            return super().get(key)

    row = MockRow(
        format="html",
        content="<html></html>",
        url=None,
        trust_tier="t1",
        metadata_json=None,
    )

    output = _coerce_design_output(row)

    assert output.format == OutputFormat.HTML
    assert output.metadata == {}


def test_coerce_design_project():
    """Test that _coerce_design_project converts database row to DesignProject."""

    class MockRow(dict):
        def __getitem__(self, key):
            return super().get(key)

    discovery_data = {
        "skill_slug": "login-flow",
        "responses": {"auth": "email"},
        "design_system_slug": "default",
        "trust_tier": "t3",
        "created_at": "2026-06-28T12:00:00+00:00",
    }

    row = MockRow(
        id="proj-123",
        name="Test Project",
        skill_slug="login-flow",
        design_system_slug="default",
        org_id="org-456",
        team_id="team-789",
        trust_tier="t3",
        canvas_id=None,
        discovery_json=json.dumps(discovery_data),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    project = _coerce_design_project(row, outputs=[])

    assert project.id == "proj-123"
    assert project.name == "Test Project"
    assert project.org_id == "org-456"
    assert project.team_id == "team-789"
    assert project.discovery is not None
    assert project.discovery.skill_slug == "login-flow"


def test_pg_store_instantiation():
    """Test that PgDesignProjectStore can be instantiated."""
    mock_factory = AsyncMock()
    store = PgDesignProjectStore(session_factory=mock_factory)

    assert store is not None
    assert store.session_factory == mock_factory


@pytest.mark.asyncio
async def test_create_returns_project_with_id(sample_project):
    """Test that create() returns a project with an assigned ID."""
    mock_factory, _session = make_mock_session_factory()
    store = PgDesignProjectStore(session_factory=mock_factory)
    result = await store.create(sample_project)

    assert result.id is not None
    assert result.id != "test-project-1"  # Should have new UUID
    assert len(result.id) == 36  # UUID format
    assert result.name == "Login Flow (Default)"
    assert result.org_id == "org-123"
    assert result.team_id == "team-456"


@pytest.mark.asyncio
async def test_create_calls_execute_for_project_and_outputs(sample_project):
    """Test that create() calls session.execute for project and outputs."""
    mock_factory, session = make_mock_session_factory()
    store = PgDesignProjectStore(session_factory=mock_factory)
    await store.create(sample_project)

    assert session.execute.await_count == 1 + len(sample_project.outputs)
    project_call, output_call = session.execute.await_args_list
    assert "INSERT INTO design_projects" in str(project_call.args[0])
    assert project_call.args[1]["name"] == "Login Flow (Default)"
    assert project_call.args[1]["org_id"] == "org-123"
    assert "INSERT INTO design_outputs" in str(output_call.args[0])
    assert output_call.args[1]["content"] == "export default function LoginFlow() { ... }"
    assert output_call.args[1]["project_id"] != "test-project-1"
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_modifies_project(sample_project):
    """Test that update() persists the changed fields and commits."""
    mock_factory, session = make_mock_session_factory()
    store = PgDesignProjectStore(session_factory=mock_factory)
    sample_project.name = "Updated Name"
    # `update` refuses a statement that matched nothing, so the double has to
    # report a row (#326); AsyncMock's default `rowcount` is a Mock, not 0.
    session.execute.return_value.rowcount = 1
    result = await store.update(sample_project)

    execute_call = session.execute.await_args
    assert "UPDATE design_projects" in str(execute_call.args[0])
    assert execute_call.args[1]["id"] == "test-project-1"
    assert execute_call.args[1]["org_id"] == "org-123"
    assert execute_call.args[1]["name"] == "Updated Name"
    session.commit.assert_awaited_once()
    assert result is sample_project


@pytest.mark.asyncio
async def test_delete_project(sample_project):
    """Test that delete() issues the project delete and commits."""
    mock_factory, session = make_mock_session_factory()
    store = PgDesignProjectStore(session_factory=mock_factory)

    await store.delete("proj-123", org_id="org-123")

    execute_call = session.execute.await_args
    assert "DELETE FROM design_projects" in str(execute_call.args[0])
    assert execute_call.args[1] == {"id": "proj-123", "org_id": "org-123"}
    session.commit.assert_awaited_once()
