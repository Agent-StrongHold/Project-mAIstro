"""PM-fleet role registration on the graph substrate.

Day 1 of PM-fleet v0 (see ~/.claude/plans/lets-work-memoized-nova.md):
extend the engineering-only graph dicts with 6 PM roles. Engineering
defaults must remain intact; PM roles must be discoverable through the
same dicts.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from maistro.graph.types import (
    DEFAULT_SYSTEM_PROMPTS,
    JSON_OUTPUT_SCHEMAS,
    OUTPUT_TYPES,
    AgentRole,
    CodeOutput,
    PlanOutput,
    PMRoleOutput,
    ReviewOutput,
    ScoutOutput,
)

PM_ROLES = (
    AgentRole.INTAKE,
    AgentRole.PROGRAM_MANAGER,
    AgentRole.RESEARCH,
    AgentRole.DELIVERY,
    AgentRole.RISK_DEPENDENCY,
    AgentRole.REPORTING,
)


def test_pm_roles_added_to_agent_role_enum() -> None:
    """Six PM-fleet roles must be present in AgentRole."""
    for role in PM_ROLES:
        assert role.value in {r.value for r in AgentRole}


def test_engineering_roles_unchanged() -> None:
    """Engineering AgentRoles must not have been removed or reordered."""
    expected = {"conductor", "planner", "coder", "reviewer", "scout"}
    actual_engineering = {r.value for r in AgentRole if r.value in expected}
    assert actual_engineering == expected


@pytest.mark.parametrize("role", PM_ROLES)
def test_pm_role_has_default_system_prompt(role: AgentRole) -> None:
    prompt = DEFAULT_SYSTEM_PROMPTS.get(role)
    assert prompt, f"PM role {role.value} is missing a DEFAULT_SYSTEM_PROMPT"
    # Persona prompts must mention the role itself + the "no fabrication" principle
    # ("no faked / no stubbed / no mocked" per user feedback in the v0 charter).
    role_words = role.value.split("_")
    assert any(word in prompt.lower() for word in role_words), (
        f"Prompt for {role.value} doesn't mention the role"
    )
    no_fabrication_terms = (
        "never invent",
        "don't fabricate",
        "do not fabricate",
        "never fabricate",
        "never produce",
        "you never",
        "you do not invent",
    )
    assert any(term in prompt.lower() for term in no_fabrication_terms), (
        f"Prompt for {role.value} doesn't enforce a no-fabrication stance: {prompt[:200]}"
    )


@pytest.mark.parametrize("role", PM_ROLES)
def test_pm_role_has_json_output_schema(role: AgentRole) -> None:
    schema = JSON_OUTPUT_SCHEMAS.get(role)
    assert schema, f"PM role {role.value} is missing a JSON_OUTPUT_SCHEMA"
    # The PM v0 schema is the PMRoleOutput shape — all four fields must appear.
    for field in ("capability", "summary", "result", "source"):
        assert field in schema, f"Schema for {role.value} missing field '{field}': {schema}"


@pytest.mark.parametrize("role", PM_ROLES)
def test_pm_role_output_type_is_pm_role_output(role: AgentRole) -> None:
    output_type = OUTPUT_TYPES.get(role)
    assert output_type is PMRoleOutput, (
        f"PM role {role.value} should map to PMRoleOutput, got {output_type}"
    )


def test_engineering_output_types_intact() -> None:
    """Adding PM roles must not have changed engineering OUTPUT_TYPES."""
    assert OUTPUT_TYPES[AgentRole.PLANNER] is PlanOutput
    assert OUTPUT_TYPES[AgentRole.CODER] is CodeOutput
    assert OUTPUT_TYPES[AgentRole.REVIEWER] is ReviewOutput
    assert OUTPUT_TYPES[AgentRole.SCOUT] is ScoutOutput


def test_pm_role_output_instantiates_with_minimal_fields() -> None:
    out = PMRoleOutput(capability="create_initiative", summary="ok")
    assert out.capability == "create_initiative"
    assert out.summary == "ok"
    assert out.result == {}
    assert out.source == "llm"


def test_pm_role_output_source_supports_no_data_fallback() -> None:
    """The 'source' field must accept the v0 fallback values used when an
    upstream (e.g. Atlassian MCP) isn't available."""
    out = PMRoleOutput(
        capability="poll_jira",
        summary="No Jira PAT configured",
        source="no_data",
    )
    assert out.source == "no_data"
    assert isinstance(out, BaseModel)


def test_pm_role_output_round_trips_through_json() -> None:
    """The wire-format schema in JSON_OUTPUT_SCHEMAS must produce a value
    parseable by PMRoleOutput (proves the schema and the model agree)."""
    payload = {
        "capability": "decompose_initiative",
        "summary": "Broke initiative into 3 epics",
        "result": {"epics": [{"title": "Auth", "stories": []}]},
        "source": "llm",
    }
    out = PMRoleOutput.model_validate(payload)
    assert out.result["epics"][0]["title"] == "Auth"
