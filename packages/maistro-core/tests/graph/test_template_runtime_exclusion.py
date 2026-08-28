"""Template content is a definition, never a record of an execution (#40).

SPEC-081226-bb3a R12 forbids live execution state from persisted NodeTemplate
and GraphTemplate content: Run/NodeRun/Attempt identifiers, terminal state,
retry counters, and runtime cancellation/deadline state. Nothing enforced it —
`parameters`, `permissions`, `policies`, `inputs`, `outputs` and `metadata` are
open `dict[str, Any]`, so a `run_id` or a `deadline_at` could be persisted into
a reusable template and replayed into every object instantiated from it.

The exclusion list is the interesting part, because it is a judgment that can
drift away from the models it describes. `TestTheExclusionSetTracksTheModels`
pins it in both directions: every excluded name is a real field on a canonical
execution model, and every field of those models is either excluded or
explicitly admitted with a reason. A new field on `Attempt` therefore fails
this suite until somebody decides which it is.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from maistro.graph.definitions import (
    RUNTIME_STATE_ADMITTED,
    RUNTIME_STATE_FIELDS,
    GraphTemplate,
    Node,
    NodeTemplate,
    RuntimeStateInTemplate,
    separate_runtime_state,
)
from maistro.runs.model import Attempt, ExecutionLease, NodeRun, Run


def _refusal(exc: ValidationError) -> RuntimeStateInTemplate:
    """Pydantic wraps a validator's exception; the refusal is what we assert on."""
    inner = exc.errors()[0]["ctx"]["error"]
    assert isinstance(inner, RuntimeStateInTemplate)
    return inner


def _node_template(**content: object) -> NodeTemplate:
    return NodeTemplate(workspace_id="w", name="n", node_type="agent", **content)


class TestALiveRecordCannotBecomeATemplate:
    @pytest.mark.ac("SPEC-081226-bb3a/AC-9")
    @pytest.mark.parametrize(
        ("field", "payload", "where"),
        [
            ("parameters", {"run_id": "r1"}, "parameters.run_id"),
            ("metadata", {"attempt_id": "a1"}, "metadata.attempt_id"),
            ("policies", {"status": "SUCCEEDED"}, "policies.status"),
            ("inputs", {"ordinal": 3}, "inputs.ordinal"),
            ("outputs", {"deadline_at": "2026-01-01T00:00:00Z"}, "outputs.deadline_at"),
            ("permissions", {"execution_lease": {}}, "permissions.execution_lease"),
        ],
    )
    def test_each_category_r12_names_is_refused(
        self, field: str, payload: dict[str, object], where: str
    ) -> None:
        with pytest.raises(ValidationError) as caught:
            _node_template(**{field: payload})

        assert _refusal(caught.value).paths == [where]

    @pytest.mark.ac("SPEC-081226-bb3a/AC-9")
    def test_it_reaches_state_buried_below_the_top_level(self) -> None:
        """A scan of top-level keys would miss the shape state actually arrives in.

        An execution record copied wholesale into a template lands nested, not
        flattened, so depth is the case that matters rather than the easy one.
        """
        with pytest.raises(ValidationError) as caught:
            _node_template(parameters={"retry": {"policy": {"attempt_id": "a1"}}})

        assert _refusal(caught.value).paths == ["parameters.retry.policy.attempt_id"]

    @pytest.mark.ac("SPEC-081226-bb3a/AC-9")
    def test_a_graph_template_is_answerable_for_the_nodes_it_embeds(self) -> None:
        """`GraphTemplate` holds Nodes by value, so their content is its content."""
        with pytest.raises(ValidationError) as caught:
            GraphTemplate(
                workspace_id="w",
                name="g",
                nodes=[Node(node_type="agent", metadata={"node_run_id": "nr1"})],
            )

        assert _refusal(caught.value).paths == ["nodes[0].metadata.node_run_id"]

    @pytest.mark.ac("SPEC-081226-bb3a/AC-9")
    def test_the_refusal_names_every_offending_path_not_just_the_first(self) -> None:
        """One round trip per template, not one per field a caller must find."""
        with pytest.raises(ValidationError) as caught:
            _node_template(parameters={"run_id": "r1"}, metadata={"finished_at": "then"})

        assert sorted(_refusal(caught.value).paths) == ["metadata.finished_at", "parameters.run_id"]

    @pytest.mark.ac("SPEC-081226-bb3a/AC-9")
    def test_definition_data_that_merely_influences_execution_still_passes(self) -> None:
        """R12 admits defaults and policies as definition data.

        A rule that rejected these would push authors to smuggle their retry and
        timeout defaults somewhere unvalidated, which is worse than the leak.
        """
        template = _node_template(
            parameters={"model": "claude", "max_retries": 3, "timeout_seconds": 30},
            policies={"on_failure": "park", "runtime_id": "python"},
        )

        assert template.content_hash
        assert template.instantiate().parameters["max_retries"] == 3


class TestSeparatingAnExecutionRecordFromItsDefinition:
    @pytest.mark.ac("SPEC-081226-bb3a/AC-9")
    def test_the_runtime_half_is_returned_rather_than_discarded(self) -> None:
        """R13 requires adapters to separate runtime fields, not drop them.

        Returning the projection is what lets a caller file it where it belongs
        instead of choosing between a refused template and silent data loss.
        """
        definition, runtime = separate_runtime_state(
            {"model": "claude", "run_id": "r1", "retry": {"status": "FAILED", "limit": 3}}
        )

        assert definition == {"model": "claude", "retry": {"limit": 3}}
        assert runtime == {"run_id": "r1", "retry": {"status": "FAILED"}}

    @pytest.mark.ac("SPEC-081226-bb3a/AC-9")
    def test_what_it_returns_is_accepted_as_template_content(self) -> None:
        """The projection is only useful if its output actually constructs."""
        definition, runtime = separate_runtime_state({"model": "claude", "attempt_id": "a1"})

        assert _node_template(parameters=definition).parameters == {"model": "claude"}
        assert runtime == {"attempt_id": "a1"}

    @pytest.mark.ac("SPEC-081226-bb3a/AC-9")
    def test_content_with_nothing_to_separate_is_returned_unchanged(self) -> None:
        definition, runtime = separate_runtime_state({"model": "claude", "nested": {"k": 1}})

        assert definition == {"model": "claude", "nested": {"k": 1}}
        assert runtime == {}


class TestTheExclusionSetTracksTheModels:
    """The list is a judgment about the canonical models; pin it to them."""

    @pytest.mark.ac("SPEC-081226-bb3a/AC-9")
    def test_every_excluded_name_is_a_real_execution_field(self) -> None:
        """Otherwise the set can accumulate names that guard nothing."""
        canonical = (
            set(Run.model_fields)
            | set(NodeRun.model_fields)
            | set(Attempt.model_fields)
            | set(ExecutionLease.model_fields)
        )

        assert RUNTIME_STATE_FIELDS - canonical == set()

    @pytest.mark.ac("SPEC-081226-bb3a/AC-9")
    def test_every_execution_field_is_excluded_or_admitted_with_a_reason(self) -> None:
        """A new field on Run/NodeRun/Attempt fails here until somebody decides.

        This is the drift the exclusion set would otherwise suffer silently: the
        canonical models grow, and a list written once keeps guarding the shape
        they used to have.
        """
        canonical = (
            set(Run.model_fields)
            | set(NodeRun.model_fields)
            | set(Attempt.model_fields)
            | set(ExecutionLease.model_fields)
        )
        undecided = canonical - RUNTIME_STATE_FIELDS - set(RUNTIME_STATE_ADMITTED)

        assert undecided == set(), (
            f"canonical execution fields with no R12 disposition: {sorted(undecided)}. "
            "Add each to RUNTIME_STATE_FIELDS, or to RUNTIME_STATE_ADMITTED with why."
        )

    @pytest.mark.ac("SPEC-081226-bb3a/AC-9")
    def test_no_name_is_both_excluded_and_admitted(self) -> None:
        assert RUNTIME_STATE_FIELDS & set(RUNTIME_STATE_ADMITTED) == set()

    @pytest.mark.ac("SPEC-081226-bb3a/AC-9")
    def test_every_admission_carries_a_reason(self) -> None:
        """An empty reason is a banked exception nobody has to defend."""
        assert [name for name, why in RUNTIME_STATE_ADMITTED.items() if not why.strip()] == []


class TestAGraphTemplateVersionPinsWhatItEmbeds:
    @pytest.mark.ac("SPEC-081226-bb3a/AC-5")
    def test_editing_a_node_template_afterwards_cannot_reach_a_published_graph(self) -> None:
        """AC-5 holds by construction, and construction is what can change.

        `GraphTemplate.nodes` is `list[Node]` — materialised content, not a
        reference to a NodeTemplate — so a later edit to that NodeTemplate has
        nowhere to reach. The test exists because that is a property of the
        field's type, and a well-meant refactor to store template references
        instead would silently turn nested versions into floating ones.
        """
        node_template = NodeTemplate(
            workspace_id="w", name="worker", node_type="agent", parameters={"model": "v1"}
        )
        published = GraphTemplate(
            workspace_id="w", name="pipeline", nodes=[node_template.instantiate()]
        )
        before = published.instantiate(project_id="p")
        published_hash_before = published.content_hash

        NodeTemplate(
            workspace_id="w",
            template_id=node_template.template_id,
            version=2,
            name="worker",
            node_type="agent",
            parameters={"model": "v2"},
        )
        after = published.instantiate(project_id="p")

        assert before.nodes[0].parameters == {"model": "v1"}
        assert after.nodes[0].parameters == {"model": "v1"}
        # The published version's own content is what must not move. Comparing
        # the two instantiated Graphs' hashes would compare identities instead:
        # `instantiate` allocates fresh node and edge ids on every call, by
        # design, so those hashes differ for two instantiations of an unchanged
        # template.
        assert published.content_hash == published_hash_before
