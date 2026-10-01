"""Harness components as evolvable targets (EPIC M4-E, issue #25).

Every proposal-to-live path must (a) keep the active version untouched until a
governed promotion runs, (b) refuse to let an optimizer artifact self-activate
by being stored, and (c) route activation through `templates.promote_audited`
with its required approval and audit entries. The store fixture follows
`test_template_store.py` — all three backends the execution spine selects.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from maistro.graph.definitions import Edge, GraphTemplate, Node
from maistro.graph.harness_targets import (
    PROVENANCE_METADATA_KEY,
    HarnessComponentTarget,
    HarnessEvolutionProposal,
    HarnessProposalInconsistent,
    HarnessTargetBaseNotActive,
    HarnessTargetKind,
    HarnessTargetScopeMismatch,
    apply_harness_proposal,
    materialize_candidate,
)
from maistro.graph.templates import (
    GraphTemplateNotFound,
    InMemoryGraphTemplateStore,
    PromotionApproval,
)

WORKSPACE = "m4e-workspace"
OTHER_WORKSPACE = "not-the-owner"


@pytest.fixture(params=["memory", "sqlite", "postgres"])
async def store(request: pytest.FixtureRequest, pg_pool: Any) -> Any:
    """All three backends `wire_execution_spine` can select (test_template_store)."""
    if request.param == "postgres":
        if pg_pool is None:
            pytest.skip("MAISTRO_TEST_PG_DSN is not set")
        from maistro.graph.pg_templates import PgGraphTemplateStore

        yield PgGraphTemplateStore(pg_pool)
        return
    if request.param == "sqlite":
        import aiosqlite

        from maistro.graph.sqlite_templates import SqliteGraphTemplateStore

        # Closed rather than dropped: aiosqlite's non-daemon thread must not
        # block interpreter shutdown (see test_template_store.py).
        conn = await aiosqlite.connect(":memory:")
        made = SqliteGraphTemplateStore(conn)
        await made.ensure_schema()
        try:
            yield made
        finally:
            await conn.close()
        return
    yield InMemoryGraphTemplateStore()


class RecordingAudit:
    """The two entries a governed promotion must leave, in order."""

    def __init__(self, fail_on: str | None = None) -> None:
        self.events: list[tuple[str, str, int]] = []
        self._fail_on = fail_on

    async def record(self, event: str, template_id: str, version: int) -> None:
        if self._fail_on == event:
            raise RuntimeError(f"audit sink down at {event}")
        self.events.append((event, template_id, version))


def _nodes(prompt: str = "base prompt") -> list[Node]:
    return [
        Node(
            node_id="n1",
            node_type="agent",
            name="worker",
            parameters={"system_prompt": prompt},
        ),
        Node(node_id="n2", node_type="agent", name="reviewer"),
    ]


def _edges() -> list[Edge]:
    return [Edge(edge_id="e1", from_node="n1", to_node="n2")]


def _base(template_id: str, *, workspace_id: str = WORKSPACE) -> GraphTemplate:
    return GraphTemplate(
        template_id=template_id,
        workspace_id=workspace_id,
        version=1,
        name="daily status",
        nodes=_nodes(),
        edges=_edges(),
    )


def _proposal(
    template_id: str,
    *,
    workspace_id: str = WORKSPACE,
    base_version: int | None = None,
    targets: list[HarnessComponentTarget] | None = None,
    prompt: str = "evolved prompt",
    topology_changed: bool = False,
) -> HarnessEvolutionProposal:
    if targets is None:
        targets = [
            HarnessComponentTarget(
                kind=HarnessTargetKind.PROMPT,
                locator="n1",
                change_summary="tighten the worker's system prompt",
            )
        ]
    nodes = _nodes(prompt)
    edges = _edges()
    if topology_changed:
        edges = [
            Edge(edge_id="e1", from_node="n1", to_node="n2"),
            Edge(edge_id="e2", from_node="n2", to_node="n1"),
        ]
    return HarnessEvolutionProposal(
        proposal_id=f"prop-{template_id}",
        workspace_id=workspace_id,
        template_id=template_id,
        base_version=base_version,
        targets=targets,
        rationale="weak-model traces show the worker ignoring output constraints",
        produced_by_run_id="run-1234",
        produced_by_node_id="node-opt-1",
        candidate_nodes=nodes,
        candidate_edges=edges,
    )


def _approval() -> PromotionApproval:
    return PromotionApproval(approver="workspace-owner", reason="lift shown on the weak model")


# ── proposal construction ─────────────────────────────────────────


def test_the_target_vocabulary_is_exactly_the_epics_component_set() -> None:
    """The closed enum is the epic's list: prompts, tool selection/config,
    skills, memory/retrieval policy, planning strategy, subagent definitions,
    Graph topology, authorized code."""
    assert {kind.value for kind in HarnessTargetKind} == {
        "prompt",
        "tool_selection",
        "skills",
        "memory_retrieval_policy",
        "planning_strategy",
        "subagent_definitions",
        "graph_topology",
        "authorized_code",
    }


def test_a_proposal_without_targets_is_refused() -> None:
    with pytest.raises(ValidationError):
        HarnessEvolutionProposal(
            proposal_id="p",
            workspace_id=WORKSPACE,
            template_id="tpl",
            targets=[],
            rationale="r",
            produced_by_run_id="run-1",
        )


def test_a_proposal_without_a_producing_run_is_refused() -> None:
    """Optimizer work is physical work on the canonical spine; the record
    names its producing execution (ADR-083026-e602)."""
    with pytest.raises(ValidationError):
        HarnessEvolutionProposal(
            proposal_id="p",
            workspace_id=WORKSPACE,
            template_id="tpl",
            targets=[
                HarnessComponentTarget(
                    kind=HarnessTargetKind.PROMPT, locator="n1", change_summary="c"
                )
            ],
            rationale="r",
            produced_by_run_id="  ",
        )


def test_a_candidate_edge_outside_the_candidate_topology_is_refused_early() -> None:
    with pytest.raises(ValidationError, match="outside the candidate topology"):
        HarnessEvolutionProposal(
            proposal_id="p",
            workspace_id=WORKSPACE,
            template_id="tpl",
            targets=[
                HarnessComponentTarget(
                    kind=HarnessTargetKind.GRAPH_TOPOLOGY, locator="e9", change_summary="c"
                )
            ],
            rationale="r",
            produced_by_run_id="run-1",
            candidate_nodes=_nodes(),
            candidate_edges=[Edge(edge_id="e1", from_node="n1", to_node="missing")],
        )


def test_an_unclassifiable_target_kind_cannot_be_constructed() -> None:
    """A proposal cannot smuggle a component class outside the closed set."""
    with pytest.raises(ValidationError):
        HarnessEvolutionProposal.model_validate(
            {
                "proposal_id": "p",
                "workspace_id": WORKSPACE,
                "template_id": "tpl",
                "targets": [{"kind": "memory_write_policy", "locator": "x", "change_summary": "c"}],
                "rationale": "r",
                "produced_by_run_id": "run-1",
            }
        )


# ── materialization ───────────────────────────────────────────────


async def test_materialization_creates_a_candidate_not_an_active_version(
    store: Any, request: pytest.FixtureRequest
) -> None:
    """The self-activation the epic forbids: GraphTemplate's field default is
    "active", so an optimizer-constructed template could activate by being
    stored. It must not."""
    template_id = f"tpl-{request.node.name}"
    await store.put(_base(template_id))

    candidate = await materialize_candidate(store, _proposal(template_id))

    assert candidate.lifecycle == "candidate"
    assert candidate.version == 2
    # The unversioned door still resolves the active base — nothing changed
    # for executors.
    still_active = await store.get(template_id)
    assert still_active is not None
    assert still_active.version == 1
    assert still_active.lifecycle == "active"


async def test_materialization_stamps_its_provenance_into_the_version(
    store: Any, request: pytest.FixtureRequest
) -> None:
    template_id = f"tpl-{request.node.name}"
    await store.put(_base(template_id))

    candidate = await materialize_candidate(store, _proposal(template_id))

    record = candidate.metadata[PROVENANCE_METADATA_KEY]
    assert record["proposal_id"] == f"prop-{template_id}"
    assert record["targets"] == ["prompt"]
    assert record["produced_by_run_id"] == "run-1234"
    assert record["produced_by_node_id"] == "node-opt-1"
    assert record["base_version"] == 1


async def test_materialization_without_any_registered_template_is_refused(
    store: Any, request: pytest.FixtureRequest
) -> None:
    with pytest.raises(GraphTemplateNotFound, match="no GraphTemplate"):
        await materialize_candidate(store, _proposal(f"tpl-{request.node.name}"))


async def test_materialization_without_an_active_base_is_refused(
    store: Any, request: pytest.FixtureRequest
) -> None:
    """A registered-but-never-active template is a promotion that is owed, not
    a base a proposal can improve."""
    template_id = f"tpl-{request.node.name}"
    candidate_only = _base(template_id)
    candidate_only = candidate_only.model_copy(update={"lifecycle": "candidate"})
    await store.put(candidate_only)

    with pytest.raises(GraphTemplateNotFound, match="no active version"):
        await materialize_candidate(store, _proposal(template_id))


async def test_materialization_refuses_a_candidate_base_named_explicitly(
    store: Any, request: pytest.FixtureRequest
) -> None:
    template_id = f"tpl-{request.node.name}"
    await store.put(_base(template_id))
    v2 = _base(template_id).model_copy(
        update={"version": 2, "lifecycle": "candidate", "name": "daily status v2"}
    )
    await store.put(v2)

    with pytest.raises(HarnessTargetBaseNotActive, match="candidate, not active"):
        await materialize_candidate(store, _proposal(template_id, base_version=2))


async def test_materialization_refuses_a_proposal_from_outside_the_owning_workspace(
    store: Any, request: pytest.FixtureRequest
) -> None:
    template_id = f"tpl-{request.node.name}"
    await store.put(_base(template_id))

    with pytest.raises(HarnessTargetScopeMismatch, match=OTHER_WORKSPACE):
        await materialize_candidate(store, _proposal(template_id, workspace_id=OTHER_WORKSPACE))


async def test_a_topology_claim_without_a_topology_change_is_refused(
    store: Any, request: pytest.FixtureRequest
) -> None:
    """A no-op diff may not claim to have rewired the graph."""
    template_id = f"tpl-{request.node.name}"
    await store.put(_base(template_id))
    proposal = _proposal(
        template_id,
        targets=[
            HarnessComponentTarget(
                kind=HarnessTargetKind.GRAPH_TOPOLOGY,
                locator="e1",
                change_summary="claims a rewiring",
            )
        ],
    )

    with pytest.raises(HarnessProposalInconsistent, match="graph_topology"):
        await materialize_candidate(store, proposal)


async def test_a_genuine_topology_change_materializes_with_all_kinds_recorded(
    store: Any, request: pytest.FixtureRequest
) -> None:
    """The same claim that is refused without a structural diff is honored
    with one, and every target kind lands in the provenance record."""
    from maistro.graph.harness_targets import HarnessComponentTarget

    template_id = f"tpl-{request.node.name}"
    await store.put(_base(template_id))
    proposal = _proposal(
        template_id,
        targets=[
            HarnessComponentTarget(
                kind=HarnessTargetKind.GRAPH_TOPOLOGY,
                locator="e2",
                change_summary="add a reviewer feedback edge",
            ),
            HarnessComponentTarget(
                kind=HarnessTargetKind.AUTHORIZED_CODE,
                locator="node-lint-4f2a",
                change_summary="point the lint node at the promoted revision",
            ),
        ],
        topology_changed=True,
    )

    candidate = await materialize_candidate(store, proposal)

    assert candidate.lifecycle == "candidate"
    record = candidate.metadata[PROVENANCE_METADATA_KEY]
    assert record["targets"] == ["authorized_code", "graph_topology"]
    assert [(edge.from_node, edge.to_node) for edge in candidate.edges] == [
        ("n1", "n2"),
        ("n2", "n1"),
    ]


async def test_each_application_allocates_a_fresh_version(
    store: Any, request: pytest.FixtureRequest
) -> None:
    """Two proposals never compete for one version number, and an identical
    re-proposal is a new version, not a rewrite of the one a Run cited."""
    template_id = f"tpl-{request.node.name}"
    await store.put(_base(template_id))

    first = await materialize_candidate(store, _proposal(template_id))
    second = await materialize_candidate(store, _proposal(template_id, prompt="second try"))

    assert (first.version, second.version) == (2, 3)
    versions = await store.versions(template_id)
    assert versions == [1, 2, 3]


# ── application: the governed gate ────────────────────────────────


async def test_application_promotes_only_through_the_governed_path(
    store: Any, request: pytest.FixtureRequest
) -> None:
    template_id = f"tpl-{request.node.name}"
    await store.put(_base(template_id))
    audit = RecordingAudit()

    promoted = await apply_harness_proposal(
        store, _proposal(template_id), audit=audit, approval=_approval()
    )

    assert promoted.lifecycle == "active"
    assert promoted.version == 2
    assert [(event, version) for event, _, version in audit.events] == [
        ("template_promotion_attempt", 2),
        ("template_promotion_committed", 2),
    ]
    # The approval is part of the record, not a silent gate.
    live = await store.get(template_id)
    assert live is not None
    assert live.version == 2
    assert live.nodes[0].parameters["system_prompt"] == "evolved prompt"


async def test_application_without_an_approval_is_a_type_error(
    store: Any, request: pytest.FixtureRequest
) -> None:
    """No default approval exists to forget: the gate is a required argument,
    same posture as `templates.promote_audited` itself."""
    template_id = f"tpl-{request.node.name}"
    await store.put(_base(template_id))

    with pytest.raises(TypeError):
        await apply_harness_proposal(store, _proposal(template_id), audit=RecordingAudit())  # type: ignore[call-arg]


async def test_an_audit_sink_failure_before_the_state_change_blocks_promotion(
    store: Any, request: pytest.FixtureRequest
) -> None:
    """A sink that is down blocks the promotion entirely; nothing moved, and
    the candidate is not left half-promoted."""
    template_id = f"tpl-{request.node.name}"
    await store.put(_base(template_id))
    audit = RecordingAudit(fail_on="template_promotion_attempt")

    with pytest.raises(RuntimeError, match="audit sink down"):
        await apply_harness_proposal(
            store, _proposal(template_id), audit=audit, approval=_approval()
        )

    found = await store.get(template_id, version=2)
    assert found is not None
    assert found.lifecycle == "candidate"


async def test_the_provenance_survives_promotion(
    store: Any, request: pytest.FixtureRequest
) -> None:
    """After promotion the live version still names the proposal, the run, and
    the targets that produced it — the audit trail is on the artifact."""
    template_id = f"tpl-{request.node.name}"
    await store.put(_base(template_id))

    promoted = await apply_harness_proposal(
        store, _proposal(template_id), audit=RecordingAudit(), approval=_approval()
    )

    record = promoted.metadata[PROVENANCE_METADATA_KEY]
    assert record["produced_by_run_id"] == "run-1234"
    assert record["targets"] == ["prompt"]
    assert record["base_version"] == 1
