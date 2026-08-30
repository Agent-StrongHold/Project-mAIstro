"""A projected legacy definition says what it was projected from (AC-10).

SPEC-081226-bb3a AC-10 is a Scenario Outline, and the outline is the point:
it names two kinds, `agent` and `graph/workflow`, and asks the same thing of
both. Only the agent half held. `snapshot_to_template` copied a legacy DAG
snapshot into a `GraphTemplate` and recorded nothing about its origin, so a
projected workflow was indistinguishable from one authored canonically and
no audit could trace a Run back to the legacy definition behind it.

These run the outline as an outline -- one parametrised body over both kinds,
rather than two tests that happen to look similar -- so a future third kind
that forgets provenance fails here by being added to the list.
"""

from __future__ import annotations

from typing import Any

import pytest

from maistro.agents.recipes import AgentRecipe, agent_recipe_to_node_template
from maistro.graph.import_provenance import SOURCE_IMPORT_PROVENANCE, snapshot_hash
from maistro.graph.template_adapter import snapshot_to_template

_DAG_SNAPSHOT: dict[str, Any] = {
    "id": "daily-status",
    "name": "Daily status",
    "description": "legacy editable DAG",
    "nodes": [
        {"id": "collect", "kind": "agent", "name": "Collect", "config": {"model": "primary"}},
        {"id": "report", "kind": "transform", "name": "Report"},
    ],
    "edges": [{"id": "e1", "from_node": "collect", "to_node": "report"}],
    "entry_node": "collect",
}


def _agent_projection():
    recipe = AgentRecipe(name="researcher", role="scout", prompt_name="scout_v1")
    return (
        agent_recipe_to_node_template(recipe, workspace_id="w1", node_type="agent"),
        recipe.model_dump(mode="json"),
        "AgentRecipe",
    )


def _workflow_projection():
    return (
        snapshot_to_template(dict(_DAG_SNAPSHOT), workspace_id="w1"),
        dict(_DAG_SNAPSHOT),
        "DAGFile",
    )


KINDS = {"agent": _agent_projection, "graph/workflow": _workflow_projection}


@pytest.mark.ac("SPEC-081226-bb3a/AC-10")
@pytest.mark.parametrize("kind", sorted(KINDS))
def test_a_projected_legacy_definition_preserves_source_provenance(kind: str) -> None:
    """Both examples of the outline, held to the same record."""
    template, source, definition = KINDS[kind]()

    provenance = template.metadata.get(SOURCE_IMPORT_PROVENANCE)

    assert provenance is not None, f"{kind} projection recorded no source provenance"
    assert provenance["source_definition"] == definition
    assert provenance["source_name"]
    assert provenance["source_format"]
    # The hash is the part that makes provenance checkable rather than
    # decorative: a name says which definition it claims to come from, the
    # digest lets an audit prove the claim against the source it still has.
    assert provenance["source_hash"] == snapshot_hash(source)


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_source_provenance_is_about_the_source_not_the_template(kind: str) -> None:
    """`source_hash` and `content_hash` answer different questions.

    Asserted because they are the same kind of value in the same object and
    the tempting simplification -- reuse the content hash -- would produce a
    provenance record that cannot detect a projection changing what it emits.
    """
    template, source, _ = KINDS[kind]()

    provenance = template.metadata[SOURCE_IMPORT_PROVENANCE]

    assert provenance["source_hash"] == snapshot_hash(source)
    assert provenance["source_hash"] != template.content_hash


def test_a_changed_legacy_source_changes_the_recorded_hash() -> None:
    """The digest tracks the source, so two snapshots cannot share a record."""
    edited = dict(_DAG_SNAPSHOT)
    edited["description"] = "edited legacy DAG"

    first = snapshot_to_template(dict(_DAG_SNAPSHOT), workspace_id="w1")
    second = snapshot_to_template(edited, workspace_id="w1")

    assert (
        first.metadata[SOURCE_IMPORT_PROVENANCE]["source_hash"]
        != second.metadata[SOURCE_IMPORT_PROVENANCE]["source_hash"]
    )


def test_the_workflow_projection_hashes_the_snapshot_as_received() -> None:
    """Not the projection's reading of it.

    `snapshot_to_template` splits recognised keys out of the snapshot and
    sweeps the rest into `metadata`. Hashing after that split would digest
    this function's interpretation rather than the source, and would change
    silently whenever `_SNAPSHOT_OWN_KEYS` changed.
    """
    template = snapshot_to_template(dict(_DAG_SNAPSHOT), workspace_id="w1")

    assert template.metadata[SOURCE_IMPORT_PROVENANCE]["source_hash"] == snapshot_hash(
        _DAG_SNAPSHOT
    )
