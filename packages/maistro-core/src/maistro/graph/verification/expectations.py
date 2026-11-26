"""Plan-queue post-state expectations and halt-on-mismatch supervision.

A plan is a claim about the future: "when this node finishes, the world will
look like *this*". Verification-aware execution (epic M4-I) keeps that claim
next to the node it predicts, checks the claim when the node's result
arrives, and halts the Run when reality contradicts the plan instead of
routing the mismatched state onward silently.

Expectations are declared on the Graph node itself —
``policies["expect_post_state"]`` — so they are part of the immutable
:class:`~maistro.runs.model.GraphSnapshot` admitted with the Run: every
restart supervises the same prediction, and the plan queue never needs a
store of its own.

The queue is the plan: node expectations in deterministic topological order,
consumed as nodes complete. A node with no declared expectation consumes
nothing and is never supervised — graphs opt in per node, so existing DAGs
execute exactly as before.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from maistro.graph.definitions import Graph
from maistro.graph.verification.taxonomy import ResultState

#: Node policy key carrying the declared post-state expectation.
EXPECT_POST_STATE_POLICY_KEY = "expect_post_state"


class ExpectationViolation(BaseModel):
    """One concrete way reality contradicted the predicted post-state."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["result_state", "missing_output", "output_mismatch", "output_not_contained"]
    path: str
    expected: Any = None
    actual: Any = None


class ExpectationVerdict(BaseModel):
    """The supervised comparison of one completed node against its prediction."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str
    matched: bool
    violations: tuple[ExpectationViolation, ...] = Field(default_factory=tuple)

    def describe(self) -> str:
        """Human-readable mismatch summary for durable error evidence."""
        if self.matched:
            return f"node {self.node_id!r} matched its predicted post-state"
        details = "; ".join(
            f"{violation.kind} at {violation.path or '<output>'}: "
            f"expected {violation.expected!r}, got {violation.actual!r}"
            for violation in self.violations
        )
        return f"node {self.node_id!r} violated its predicted post-state: {details}"


class PostStateExpectation(BaseModel):
    """The predicted post-state of one node's successful completion.

    ``expected_output`` asserts a subset of the node's output mapping by
    exact equality (nested values compare by JSON equality). It is a subset,
    not a whole: a prediction that pins every field breaks on any harmless
    addition, and supervision exists to catch *wrong worlds*, not extra ones.
    ``expected_output_contains`` asserts a substring on string output fields.
    ``expect_result_state`` asserts the classified
    :class:`~maistro.graph.verification.taxonomy.ResultState`.
    """

    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1)
    expect_result_state: ResultState | None = None
    expected_output: Mapping[str, Any] = Field(default_factory=dict)
    expected_output_contains: Mapping[str, str] = Field(default_factory=dict)
    description: str = ""

    def evaluate(
        self,
        *,
        output: object,
        result_state: ResultState | None,
        check_output: bool = True,
    ) -> ExpectationVerdict:
        """Compare an actual post-state against this prediction.

        ``check_output=False`` supervises only the result-state claim. A paused
        completion has a state but not the final output the plan predicted, so
        output assertions are deferred until the resumed visit completes.
        """
        mapping = output if isinstance(output, Mapping) else None
        state_violation = _result_state_violation(self, result_state)
        violations: list[ExpectationViolation] = (
            [] if state_violation is None else [state_violation]
        )
        if check_output:
            violations.extend(_output_violations(self, mapping, output))
            violations.extend(_contains_violations(self, mapping))
        return ExpectationVerdict(
            node_id=self.node_id,
            matched=not violations,
            violations=tuple(violations),
        )


class _Missing:
    """Sentinel distinguishing "absent" from a legitimate ``None`` value."""


_MISSING = _Missing()


def _value_at_path(mapping: Mapping[str, Any], path: str) -> Any:
    """Resolve a dotted path against nested mappings, or the missing sentinel."""
    current: Any = mapping
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return _MISSING
        current = current[part]
    return current


def _json_equal(actual: Any, expected: Any) -> bool:
    """Compare actual against expected with JSON-style container equality."""
    if isinstance(actual, Mapping) and isinstance(expected, Mapping):
        return dict(actual) == dict(expected)
    if isinstance(actual, (list, tuple)) and isinstance(expected, (list, tuple)):
        return list(actual) == list(expected)
    return bool(actual == expected)


def _result_state_violation(
    expectation: PostStateExpectation, result_state: ResultState | None
) -> ExpectationViolation | None:
    """The result-state violation, or ``None`` when the state matches (or is undeclared)."""
    if expectation.expect_result_state is None or result_state is expectation.expect_result_state:
        return None
    return ExpectationViolation(
        kind="result_state",
        path="<result_state>",
        expected=expectation.expect_result_state.value,
        actual=result_state.value if result_state is not None else None,
    )


def _output_violations(
    expectation: PostStateExpectation,
    mapping: Mapping[str, Any] | None,
    output: object,
) -> list[ExpectationViolation]:
    """Exact-equality violations for the predicted output subset.

    A non-mapping output misses every predicted path; the raw output is
    carried as the actual so the evidence shows what *did* come out.
    """
    violations: list[ExpectationViolation] = []
    for key, expected in expectation.expected_output.items():
        if mapping is None:
            violations.append(
                ExpectationViolation(
                    kind="missing_output",
                    path=str(key),
                    expected=expected,
                    actual=output,
                )
            )
            continue
        actual: Any = _value_at_path(mapping, str(key))
        if actual is _MISSING:
            violations.append(
                ExpectationViolation(
                    kind="missing_output",
                    path=str(key),
                    expected=expected,
                    actual=None,
                )
            )
        elif not _json_equal(actual, expected):
            violations.append(
                ExpectationViolation(
                    kind="output_mismatch",
                    path=str(key),
                    expected=expected,
                    actual=actual,
                )
            )
    return violations


def _contains_violations(
    expectation: PostStateExpectation,
    mapping: Mapping[str, Any] | None,
) -> list[ExpectationViolation]:
    """Substring violations for the ``expected_output_contains`` assertions."""
    violations: list[ExpectationViolation] = []
    for key, needle in expectation.expected_output_contains.items():
        actual = None if mapping is None else _value_at_path(mapping, str(key))
        if not isinstance(actual, str) or needle not in actual:
            violations.append(
                ExpectationViolation(
                    kind="output_not_contained",
                    path=str(key),
                    expected=needle,
                    actual=actual,
                )
            )
    return violations


def expectation_from_policy(
    node_id: str, policies: Mapping[str, Any]
) -> PostStateExpectation | None:
    """Read a node's declared expectation, or ``None`` when it declares none.

    A declared expectation that does not parse raises: a plan nobody can
    read is worse than no plan, because supervision silently skipping it
    would look identical to the plan holding.
    """
    declared = policies.get(EXPECT_POST_STATE_POLICY_KEY)
    if declared is None:
        return None
    if not isinstance(declared, Mapping):
        raise ValueError(
            f"node {node_id!r} policy {EXPECT_POST_STATE_POLICY_KEY!r} must be a mapping, "
            f"got {type(declared).__name__}"
        )
    declared = dict(declared)
    if "node_id" in declared and str(declared["node_id"]) != node_id:
        raise ValueError(
            f"node {node_id!r} declares an expectation for node "
            f"{declared['node_id']!r}; expectations are declared on the node they predict"
        )
    declared.pop("node_id", None)
    return PostStateExpectation.model_validate({"node_id": node_id, **declared})


class PlanExpectationQueue:
    """Ordered plan queue of post-state expectations, consumed as nodes complete.

    Order is the graph's topological order with node-id tie-breaking, so two
    rebuilds of the same Graph produce the same queue and the same
    supervision order. Cycles cannot be topologically ordered; their nodes
    keep the same deterministic node-id order so supervision stays total.
    """

    def __init__(self, expectations: tuple[PostStateExpectation, ...]) -> None:
        self._expectations = expectations
        self._by_node_id = {expectation.node_id: expectation for expectation in expectations}
        self._consumed: set[str] = set()

    @classmethod
    def from_graph(cls, graph: Graph) -> PlanExpectationQueue:
        expectations: list[PostStateExpectation] = []
        for node_id in _topological_node_ids(graph):
            node = next(item for item in graph.nodes if item.node_id == node_id)
            expectation = expectation_from_policy(node.node_id, node.policies)
            if expectation is not None:
                expectations.append(expectation)
        return cls(tuple(expectations))

    @property
    def expectations(self) -> tuple[PostStateExpectation, ...]:
        return self._expectations

    @property
    def pending_node_ids(self) -> tuple[str, ...]:
        """Expected nodes not yet completed, in plan order."""
        return tuple(
            expectation.node_id
            for expectation in self._expectations
            if expectation.node_id not in self._consumed
        )

    def mark_completed(self, node_id: str) -> None:
        """Record that a node completed in an earlier fold.

        The queue is rebuilt per frontier, so durable supervision must seed
        consumption from the Run's completed NodeRuns; otherwise a later
        mismatch reports already-finished plan steps as still awaited.
        """
        if node_id in self._by_node_id:
            self._consumed.add(node_id)

    def supervise(
        self,
        node_id: str,
        *,
        output: object,
        result_state: ResultState | None,
        check_output: bool = True,
    ) -> ExpectationVerdict | None:
        """Consume one node's completion against its expectation, if any.

        Returns ``None`` for nodes the plan says nothing about.
        """
        expectation = self._by_node_id.get(node_id)
        if expectation is None:
            return None
        self._consumed.add(node_id)
        return expectation.evaluate(
            output=output,
            result_state=result_state,
            check_output=check_output,
        )


def _drain_ready_order(
    ready: list[str], successors: dict[str, list[str]], indegree: dict[str, int]
) -> list[str]:
    """Pop the readiness queue in node-id order, unlocking successors as ids emit."""
    ordered: list[str] = []
    while ready:
        current = ready.pop(0)
        ordered.append(current)
        for target in successors[current]:
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
        ready.sort()
    return ordered


def _topological_node_ids(graph: Graph) -> tuple[str, ...]:
    """Deterministic topological order (Kahn's, node-id tie-break); cycles fall back to node-id order."""
    node_ids = [node.node_id for node in graph.nodes]
    by_id = set(node_ids)
    successors: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    indegree: dict[str, int] = dict.fromkeys(node_ids, 0)
    for edge in graph.edges:
        if edge.from_node in by_id and edge.to_node in by_id:
            successors[edge.from_node].append(edge.to_node)
            indegree[edge.to_node] += 1
    ready = sorted(node_id for node_id in node_ids if indegree[node_id] == 0)
    ordered = _drain_ready_order(ready, successors, indegree)
    if len(ordered) < len(node_ids):
        cyclic = sorted(set(node_ids) - set(ordered))
        ordered.extend(cyclic)
    return tuple(ordered)


__all__ = [
    "EXPECT_POST_STATE_POLICY_KEY",
    "ExpectationVerdict",
    "ExpectationViolation",
    "PlanExpectationQueue",
    "PostStateExpectation",
    "expectation_from_policy",
]
