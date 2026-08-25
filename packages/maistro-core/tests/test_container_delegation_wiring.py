"""The delegation dependencies reach the delegate node (#147, ADR-082526-3ca6).

`build_node_resolver` has always accepted `a2a_delegator`, `guest_peers` and
`run_store`; nothing supplied them, so `AgentDelegateRemoteNode` arrived with
all three `None` and every delegation refused for want of a delegator. These
cover the seam — the Container owning them, and the resolver handing them on.

The product half (Hive's registered-DAG path reading them off the Container)
is covered in `packages/hive-conductor/backend/tests/test_dag_agents.py`, which
this collector cannot see: that tree is not in `testpaths`, for the reason
`_suite_paths` documents.
"""

from __future__ import annotations

import pytest

from maistro.container import Container, build_node_resolver

_DELEGATE_DAG = {"nodes": [{"id": "d", "kind": "agent.delegate_remote"}]}


@pytest.mark.ac("ADR-082526-3ca6/AC-1")
def test_the_container_declares_both_delegation_dependencies() -> None:
    fields = Container.__dataclass_fields__
    assert "a2a_delegator" in fields
    assert "guest_peers" in fields


@pytest.mark.ac("ADR-082526-3ca6/AC-1")
def test_both_dependencies_construct_without_configuration() -> None:
    """ADR-082526-3ca6 declines to make them optional on this basis, so it is
    asserted rather than assumed: a constructor that grew a required argument
    would turn "not optional" into a startup failure."""
    from maistro.a2a.delegate import A2ADelegator
    from maistro.a2a.guest_peers import GuestPeerManager

    assert A2ADelegator() is not None
    assert GuestPeerManager() is not None


@pytest.mark.ac("ADR-082526-3ca6/AC-2")
def test_the_resolver_hands_all_three_to_the_delegate_node() -> None:
    delegator, peers, runs = object(), object(), object()
    node = build_node_resolver(a2a_delegator=delegator, guest_peers=peers, run_store=runs)(
        "d", _DELEGATE_DAG
    )

    assert node._a2a_delegator is delegator
    assert node._guest_peers is peers
    assert node._run_store is runs


@pytest.mark.ac("ADR-082526-3ca6/AC-2")
def test_the_no_arg_resolver_still_produces_an_unwired_node() -> None:
    """The defect, pinned. This is what the shipped path used to get, and it is
    still what a caller supplying nothing gets — the fix is at the call site,
    not a new default, because a default delegator would be a second one nobody
    asked for."""
    node = build_node_resolver()("d", _DELEGATE_DAG)

    assert node._a2a_delegator is None
    assert node._guest_peers is None
    assert node._run_store is None


@pytest.mark.ac("ADR-082526-3ca6/AC-3")
def test_the_run_store_parameter_is_the_canonical_one() -> None:
    """`RunStore` and `DurableRunStore` are one word apart and share no method.

    `build_node_resolver`'s docstring records that passing the durable store
    type-checked and then raised AttributeError on the first accepted
    delegation — after the work had been dispatched. The annotation is the
    guard; this asserts the two are still distinguishable rather than quietly
    converged into one.
    """
    from maistro.graph.durable_runs import InMemoryDurableRunStore
    from maistro.runs.store import InMemoryRunStore

    canonical = {name for name in dir(InMemoryRunStore) if not name.startswith("_")}
    durable = {name for name in dir(InMemoryDurableRunStore) if not name.startswith("_")}

    assert "create_run" in canonical and "create_run" not in durable
    assert "create" in durable and "create" not in canonical
