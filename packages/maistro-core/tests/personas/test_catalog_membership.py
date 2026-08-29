"""Cataloguing a template is not editing it (AC-8).

SPEC-081226-bb3a AC-8: adding a template to a Persona's catalog, or removing
it, must leave the template's content and every object instantiated from it
unchanged.

This holds structurally rather than by enforcement -- `Persona` carries
`node_template_ids` and `graph_template_ids`, which are *identifier* lists, so
there is no template content in a Persona for membership to disturb. That is
the reason to assert it rather than a reason to skip it: the obvious
convenience of storing the templates themselves on the Persona, so a catalog
read needs no second lookup, would satisfy every other criterion in this spec
and break this one silently. The structural assertion below is what a change
of that shape trips over.
"""

from __future__ import annotations

import pytest

from maistro.graph.definitions import NodeTemplate
from maistro.graph.templates import InMemoryNodeTemplateStore
from maistro.personas.model import Persona


def _persona(**overrides: object) -> Persona:
    values: dict[str, object] = {
        "id": "persona-1",
        "workspace_id": "w1",
        "name": "House style",
    }
    values.update(overrides)
    return Persona(**values)  # type: ignore[arg-type]


def _template() -> NodeTemplate:
    return NodeTemplate(
        template_id="node-template",
        workspace_id="w1",
        version=1,
        name="Researcher",
        node_type="agent",
        parameters={"model": "primary", "tuning": {"temperature": 0.2}},
    )


@pytest.mark.ac("SPEC-081226-bb3a/AC-8")
async def test_catalog_membership_changes_leave_the_template_and_its_objects_alone() -> None:
    """The scenario as written: add, then remove, and nothing moves.

    The template is read back **from the store** rather than from the local
    variable, so this also covers a catalog that reached through to the
    registry -- which is the only way membership could reach template content
    at all, and would be invisible to a comparison against an in-hand object.

    The baseline is deep-copied out of what the store returns rather than
    held as the store returned it. Otherwise the baseline is only as fixed as
    the store's own copy discipline, and a store handing out live objects
    would move the baseline in step with the value under test -- comparing a
    thing against itself and passing whatever happened.

    The criterion says *each* add or removal leaves objects unchanged, so the
    assertions run after the add and again after the removal. Checking only at
    the end would pass an implementation that mutated on add and restored on
    remove -- a violation with a tidy net effect, not a non-event.
    """
    store = InMemoryNodeTemplateStore()
    template = await store.put(_template())
    node = template.instantiate(node_id="node-1")

    stored = await store.get("node-template", version=1)
    assert stored is not None
    before_stored = stored.model_copy(deep=True)
    before_node = node.model_copy(deep=True)
    persona = _persona()

    persona.node_template_ids.append("node-template")
    persona.graph_template_ids.append("graph-template")

    assert await store.get("node-template", version=1) == before_stored
    assert node == before_node

    persona.node_template_ids.remove("node-template")

    assert await store.get("node-template", version=1) == before_stored
    assert node == before_node
    assert node.parameters == {"model": "primary", "tuning": {"temperature": 0.2}}

    # The structural reason the three assertions above hold, asserted with
    # them rather than beside them. On its own the behavioural half cannot
    # fail: with the catalog holding identifiers there is nothing for
    # membership to reach, so it would pass unchanged against a Persona that
    # had grown template content and started drifting from the registry.
    # `extra="forbid"` is what makes attaching that content a deliberate
    # schema change rather than an accident, so it is part of this criterion.
    assert all(isinstance(entry, str) for entry in persona.graph_template_ids)
    with pytest.raises(ValueError, match="Extra inputs"):
        _persona(node_templates=[_template()])


async def test_the_catalog_is_identifiers_only() -> None:
    """Why AC-8 holds, asserted so a change of shape has to face it.

    A Persona that held template *content* could drift from the registry, and
    membership would then be an edit. Both catalogs are checked: they were
    added together and would be extended together.
    """
    persona = _persona(node_template_ids=["a", "b"], graph_template_ids=["c"])

    for catalog in (persona.node_template_ids, persona.graph_template_ids):
        assert all(isinstance(entry, str) for entry in catalog)

    # `extra="forbid"` on the model is what stops a template object being
    # attached under some new key without a deliberate schema change.
    with pytest.raises(ValueError, match="Extra inputs"):
        _persona(node_templates=[_template()])


async def test_membership_does_not_republish_or_version_the_template() -> None:
    """Cataloguing must not look like a publish.

    A catalog implemented as "put the template so the Persona's copy is
    current" would keep content identical and still be wrong: it would add a
    version, and every Run citing the old one would then cite a version the
    registry rewrote under it.
    """
    store = InMemoryNodeTemplateStore()
    await store.put(_template())
    persona = _persona()

    persona.node_template_ids.append("node-template")

    assert await store.versions("node-template") == [1]
