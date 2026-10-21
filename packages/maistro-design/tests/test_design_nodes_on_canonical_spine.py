"""M7-A11 production reachability: the design wave nodes are canonical graph kinds.

The explore wave and the judge are Graph node kinds on the canonical
``Goal -> Graph -> Run -> NodeRun -> Attempt`` spine — not a Studio button with
its own client, and not a private director LLM. These tests prove the
production wiring reaches them:

- importing :mod:`maistro_design` registers the kinds in the canonical node
  registry, so a pack Graph can name ``design.explore`` / ``design.thesis`` /
  ``design.judge``;
- the production node resolver (``maestro.container.build_node_resolver``,
  which the Hive backend builds from the Container) constructs the judge from
  the authorities the node declares;
- the judge *requires* the canonical ``run_store`` authority: a resolver
  without one refuses the kind instead of building a judge that cannot persist
  its ``#792`` eval evidence.
"""

from __future__ import annotations

from typing import Any

import pytest


def _judge_graph(governed: Any) -> Any:
    from maistro.graph.definitions import Graph, Node

    return Graph(
        workspace_id=governed.workspace_id,
        project_id=governed.project_id,
        name="design judge",
        nodes=[Node(node_id="judge", node_type="design.judge", parameters={})],
        edges=[],
    )


def test_design_kinds_are_registered_by_importing_the_package() -> None:
    """A pack Graph can name these kinds because the package registers them."""

    import maistro_design  # noqa: F401  (the import is the registration)
    from maistro.graph.nodes import get_node

    assert get_node("design.explore").__name__ == "DesignExploreNode"
    assert get_node("design.thesis").__name__ == "DesignThesisNode"
    assert get_node("design.judge").__name__ == "DesignJudgeNode"


def test_judge_requires_the_canonical_run_store_authority() -> None:
    """The ``#792`` eval rows live in the canonical Run store — declared, not implied."""

    import maistro_design  # noqa: F401  (the import is the registration)
    from maistro.graph.nodes import get_node

    judge = get_node("design.judge")
    assert dict(judge.required_authorities) == {"run_store": "run_store"}
    # The effect authorities are the canonical capability ones.
    assert dict(judge.optional_authorities) == {
        "effect_context": "effect_context",
        "registry": "provider_registry",
        "router": "llm_router",
    }


def test_judge_composes_through_the_production_resolver(governed: Any) -> None:
    """The Container's authorities are enough to build the judge."""

    from maistro.container import build_node_resolver
    from maistro_design.judge import DesignJudgeNode

    resolver = build_node_resolver(
        run_store=governed.run_store,
        effect_context=governed.effects,
        provider_registry=governed.registry,
        llm_router=governed.router,
    )
    node = resolver("judge", _judge_graph(governed))
    assert isinstance(node, DesignJudgeNode)


def test_judge_refuses_composition_without_the_canonical_run_store(governed: Any) -> None:
    """No Run store means no canonical eval evidence: the kind is refused."""

    from maistro.container import build_node_resolver
    from maistro.graph.nodes import NodeCompositionError

    resolver = build_node_resolver(
        effect_context=governed.effects,
        provider_registry=governed.registry,
        llm_router=governed.router,
    )
    with pytest.raises(NodeCompositionError):
        resolver("judge", _judge_graph(governed))
