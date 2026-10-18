"""Every shipped node kind, composed by `Container.node_resolver()` (#44, #1082).

`test_node_composition` proves `compose_node` hands a kind the exact objects
it is given. That cannot catch the step before it: `Container.node_resolver()`
dropping or substituting one of its own authorities on the way into
`build_node_resolver`, whose bare defaults (an empty adapter map, the
process-wide usage log, ``None``) would then be built into production nodes.
This sweep resolves each shipped kind through a real Container and asserts
every declared authority is the Container-owned instance. The universe is the
reconciled production registration universe (`_production_registration`): the
reachable registration modules are loaded here, so the design-side
`creative.*` kinds are proved by the same identity sweep that covers the core
five, not left to whichever registration modules a pytest process imported.
"""

from __future__ import annotations

from typing import Any

import pytest

from maistro.graph.definitions import Graph, Node
from maistro.graph.nodes import get_node, list_kinds
from maistro.quota.usage_log import InMemoryUsageLog, get_default_usage_log

# Loads the reachable production registration modules at import time; the
# universe's completeness is proven in test_production_registration_universe.
from ._production_registration import LOADED_REGISTRATION_MODULES, production_kinds

#: Authority name -> the Container attribute production composition must hand
#: over. ``node_resolver`` is the resolver itself and is checked separately.
_CONTAINER_ATTRIBUTE = {
    "harness_adapters": "harness_adapters",
    "usage_log": "usage_log",
    "a2a_delegator": "a2a_delegator",
    "guest_peers": "guest_peers",
    "run_store": "run_store",
    "graph_run_store": "graph_run_store",
    "effect_context": "capability_effects",
    "provider_registry": "provider_registry",
    "llm_router": "llm_router",
}


def _kinds_declaring_authorities() -> list[str]:
    return sorted(
        kind
        for kind in list_kinds()
        if not kind.startswith("test.")
        and (get_node(kind).required_authorities or get_node(kind).optional_authorities)
    )


async def _production_container() -> Any:
    from maistro.container import create_container
    from maistro.types import AgentConfig

    container = await create_container(AgentConfig(router_api_key="test-key"))
    # A default Container shares the process-wide usage log, which is also
    # `build_node_resolver`'s own fallback; a deployment-owned log is the
    # only way a dropped `usage_log` shows up as a substitution.
    container.usage_log = InMemoryUsageLog()
    return container


def test_the_sweep_covers_every_authority_a_node_can_declare() -> None:
    declared = {
        authority
        for kind in _kinds_declaring_authorities()
        for authority in {
            **get_node(kind).required_authorities,
            **get_node(kind).optional_authorities,
        }.values()
    }
    assert declared <= set(_CONTAINER_ATTRIBUTE) | {"node_resolver"}
    assert _kinds_declaring_authorities(), "no shipped kind declares an authority"


def test_the_declaring_sweep_is_a_subset_of_the_reconciled_universe() -> None:
    """The identity sweep cannot silently shrink below the reconciled
    production universe — nor does it claim more than declarations: kinds
    without authorities participate through the whole-universe test below."""
    assert set(_kinds_declaring_authorities()) <= set(production_kinds())
    assert LOADED_REGISTRATION_MODULES, "production registration modules were not loaded"
    assert set(production_kinds()) - set(_kinds_declaring_authorities()), (
        "every production kind declares an authority; the whole-universe "
        "participation test below is vacuous"
    )


@pytest.mark.parametrize("kind", _kinds_declaring_authorities())
async def test_the_container_resolver_hands_every_kind_its_own_authorities(
    kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    node_cls = get_node(kind)
    # Built first: the Container constructs some kinds itself while wiring
    # (`spawn_harness_node`), and those kwargs must not be mistaken for the
    # resolver's.
    container = await _production_container()
    assert container.usage_log is not get_default_usage_log()
    resolver = container.node_resolver()
    received: dict[str, Any] = {}
    real_init = node_cls.__init__

    def _recording_init(self: Any, *args: Any, **kwargs: Any) -> None:
        received.update(kwargs)
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(node_cls, "__init__", _recording_init)
    graph = Graph(
        workspace_id="ws-composition",
        project_id="proj-composition",
        name=f"one {kind}",
        nodes=[Node(node_id="n", node_type=kind)],
    )

    node = resolver("n", graph)

    assert isinstance(node, node_cls)
    declared = {**node_cls.required_authorities, **node_cls.optional_authorities}
    for keyword, authority in declared.items():
        value = received.get(keyword)
        if authority == "node_resolver":
            assert callable(value)
            assert value is resolver, f"{kind} got a resolver other than the Container's"
            continue
        owned = getattr(container, _CONTAINER_ATTRIBUTE[authority])
        assert owned is not None, f"the Container does not own a {authority!r}"
        assert value is owned, (
            f"{kind} received {value!r} as {keyword!r}, not the Container's {authority!r}"
        )


@pytest.mark.parametrize("kind", sorted(production_kinds()))
async def test_the_container_resolver_composes_every_production_kind(
    kind: str,
) -> None:
    """The reconciled universe participates in the Container identity proof,
    not just the kinds that declare authorities: every production kind — the
    eleven `creative.*` kinds included — resolves through the Container's own
    resolver to an instance of the registered class. A production registration
    that arrived with a required authority the Container cannot supply would
    fail the declaring sweep above; one that cannot be composed at all fails
    here."""
    container = await _production_container()
    node_cls = get_node(kind)
    graph = Graph(
        workspace_id="ws-composition",
        project_id="proj-composition",
        name=f"one {kind}",
        nodes=[Node(node_id="n", node_type=kind)],
    )

    node = container.node_resolver()("n", graph)

    assert type(node) is node_cls


async def test_the_production_resolved_synth_dag_keeps_its_default_deny_seam() -> None:
    """The recorded Warden resolution (#1082 step 3): no node-level Warden or
    Sentinel authority exists in `AUTHORITY_NAMES`, on purpose. `Container`
    owns a Warden for its own gate wiring (`warden_scan`); a node's
    `warden`/`sentinel` constructor parameters are intentionally local
    strategy seams whose defaults are the #1165 fail-closed pair — a fresh
    `Warden()` and a `Sentinel` whose permission table is empty, deny-on-miss,
    with no governed permission source (ADR-072726-0d6b). Canonicalizing any
    node-level Warden dependency is the Security-on-Agent workstream
    (WORKSPACE-CUTOVER-PLAN #66/#1171), not this composition guard: this pin
    exists so that decision cannot drift silently in either direction."""
    from maistro.graph.nodes.agent_synth_dag import AgentSynthDagNode

    container = await _production_container()
    graph = Graph(
        workspace_id="ws-composition",
        project_id="proj-composition",
        name="synth seam",
        nodes=[Node(node_id="s", node_type="agent.synth_dag")],
    )

    node = container.node_resolver()("s", graph)

    assert isinstance(node, AgentSynthDagNode)
    # The store and resolver are canonical Container instances (asserted in
    # test_node_composition); the warden/sentinel pair is the recorded seam:
    # the node's Warden is its own, not the Container's.
    assert node._warden is not container.warden
    # Fail-closed by #1165: an empty static table, no compatibility mode, and
    # no governed permission source invented for the seam.
    assert node._sentinel._permission_table == {}
    assert node._sentinel._allow_on_miss is False
    assert node._sentinel._permission_source is None
