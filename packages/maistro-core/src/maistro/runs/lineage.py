"""Lineage: reconstruct a Run's full provenance from persisted objects only (M7-A6).

One queryable answer to "where did this artifact come from, and what was it
scored against": `run_lineage` projects a Run — its Graph snapshot identity,
every NodeRun and physical Attempt, and every persisted `RunEvalScore` — out
of a `RunStore`, and `artifact_lineage` locates one artifact inside that
projection and returns the exact Attempt/NodeRun that produced it.

Lineage is a **read model**. It mints no identity, holds no state, and never
writes: every fact it returns is a persisted object the store already owned.
The Goal and Rubric revisions a Run scored against are read from the eval
records themselves (each `RunEvalScore` names the exact `goal_revision` and
`rubric_revision` it applied), so the answer cannot drift from the evidence —
a Run with no eval records reports no rubric rather than a remembered one.

Design Studio's inspector (#286, #773) and the M7-A6 proof
(`docs/product/M7-A6-DESIGN-LOOP-PROOF.md`) consume this module; neither
re-implements it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from maistro.runs.model import RunEvalScore, evidence_values_equal
from maistro.runs.store import RunNotFound, RunStore

__all__ = [
    "ArtifactNotInRunLineage",
    "AttemptLineage",
    "NodeRunLineage",
    "RubricRevisionBinding",
    "RunLineage",
    "artifact_lineage",
    "run_lineage",
]


class ArtifactNotInRunLineage(KeyError):
    """No persisted Attempt result on the Run carries that artifact value."""


@dataclass(frozen=True, slots=True)
class AttemptLineage:
    """One physical Attempt in the lineage, with the eval records naming it."""

    attempt_id: str
    node_run_id: str
    ordinal: int
    status: str
    result: Any | None
    error: str | None
    eval_scores: tuple[RunEvalScore, ...]


@dataclass(frozen=True, slots=True)
class NodeRunLineage:
    """One logical node execution with its Attempts, oldest ordinal first.

    `node_id` is the minted identity the spine executed; `node_name` is the
    semantic name the Graph definition carried for it (empty when the
    definition named none) — the human-readable handle the proof and the
    inspector use.
    """

    node_run_id: str
    run_id: str
    node_id: str
    node_name: str
    ordinal: int
    status: str
    result: Any | None
    error: str | None
    attempts: tuple[AttemptLineage, ...]


@dataclass(frozen=True, slots=True)
class RubricRevisionBinding:
    """One (Goal revision, Rubric revision) pair the Run's eval evidence applied.

    Derived from the persisted eval records — never from caller memory — so
    a Run that scored against two Rubric revisions (the redirect pattern)
    reports both, and a Run that scored against none reports none.
    """

    goal_id: str
    goal_revision: int
    rubric_id: str
    rubric_revision: int


@dataclass(frozen=True, slots=True)
class RunLineage:
    """Everything one Run did, read back from the store that owns it."""

    run_id: str
    workspace_id: str
    project_id: str
    status: str
    graph_id: str
    graph_content_hash: str
    graph_definition_json: str
    node_runs: tuple[NodeRunLineage, ...]
    eval_scores: tuple[RunEvalScore, ...]
    rubric_bindings: tuple[RubricRevisionBinding, ...]

    def find_artifact(self, artifact: Any) -> tuple[NodeRunLineage, AttemptLineage]:
        """Locate an artifact value among the persisted Attempt results.

        Returns the (NodeRun, Attempt) whose terminal result carries the
        artifact (compared with the canonical evidence equality). Raises
        :class:`ArtifactNotInRunLineage` when no persisted Attempt on this
        Run produced it — the honest answer for an artifact the Run never
        made, and the guard against crediting an artifact to a memory the
        spine never recorded.
        """
        for node_run in self.node_runs:
            for attempt in node_run.attempts:
                if attempt.result is not None and _contains_evidence(attempt.result, artifact):
                    return node_run, attempt
        raise ArtifactNotInRunLineage(
            f"no Attempt result on run {self.run_id!r} carries this artifact"
        )


def _contains_evidence(haystack: Any, needle: Any) -> bool:
    """Whether the persisted evidence value contains the artifact value.

    A direct match, a list member, or a dict value/`result`-named entry —
    the shapes `AttemptResult.result` actually takes on the spine. A pydantic
    envelope is unwrapped first: the in-memory spine keeps live `NodeResult`
    objects whose `output` is the node's own BaseModel, where the SQL spine
    round-trips the same Attempt as plain JSON — one lineage answer, both
    stores (M7-A6).
    """
    if evidence_values_equal(haystack, needle):
        return True
    if isinstance(haystack, BaseModel):
        return _contains_evidence(haystack.model_dump(mode="json"), needle)
    if isinstance(haystack, dict):
        for value in haystack.values():
            if _contains_evidence(value, needle):
                return True
    if isinstance(haystack, (list, tuple)):
        for value in haystack:
            if _contains_evidence(value, needle):
                return True
    return False


async def run_lineage(store: RunStore, run_id: str) -> RunLineage:
    """Project one Run's complete lineage out of the store.

    Raises :class:`RunNotFound` for an unknown Run. Everything else is read
    from persisted rows: NodeRuns in ordinal order, each with its Attempts
    (ordinal order) and the eval scores naming that Attempt.
    """
    run = await store.get_run(run_id)
    if run is None:
        raise RunNotFound(run_id)
    node_names = _graph_node_names(run.graph.definition_json)
    eval_scores = tuple(
        sorted(await store.list_eval_scores(run_id), key=lambda s: (s.scored_at, s.eval_id))
    )
    scores_by_attempt: dict[str, list[RunEvalScore]] = {}
    for score in eval_scores:
        scores_by_attempt.setdefault(score.attempt_id, []).append(score)

    node_runs = await store.list_node_runs(run_id)
    lineage_nodes: list[NodeRunLineage] = []
    for node_run in sorted(node_runs, key=lambda n: n.ordinal):
        attempts = await store.list_attempts(node_run.node_run_id)
        lineage_attempts = tuple(
            AttemptLineage(
                attempt_id=attempt.attempt_id,
                node_run_id=attempt.node_run_id,
                ordinal=attempt.ordinal,
                status=attempt.status.value,
                result=attempt.result,
                error=attempt.error,
                eval_scores=tuple(scores_by_attempt.get(attempt.attempt_id, ())),
            )
            for attempt in sorted(attempts, key=lambda a: a.ordinal)
        )
        lineage_nodes.append(
            NodeRunLineage(
                node_run_id=node_run.node_run_id,
                run_id=node_run.run_id,
                node_id=node_run.node_id,
                node_name=node_names.get(node_run.node_id, ""),
                ordinal=node_run.ordinal,
                status=node_run.status.value,
                result=node_run.result,
                error=node_run.error,
                attempts=lineage_attempts,
            )
        )

    return RunLineage(
        run_id=run.run_id,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        status=run.status.value,
        graph_id=run.graph.graph_id,
        graph_content_hash=run.graph.content_hash,
        graph_definition_json=run.graph.definition_json,
        node_runs=tuple(lineage_nodes),
        eval_scores=eval_scores,
        rubric_bindings=tuple(_rubric_bindings(eval_scores)),
    )


def _graph_node_names(graph_definition_json: str) -> dict[str, str]:
    """The definition's node_id → semantic name map, for lineage display.

    Read from the Run's own Graph snapshot — the definition the Run executed —
    never from a caller-side template, so the names cannot drift from the
    persisted evidence. Unparsable definitions yield an empty map rather than
    inventing names.
    """
    try:
        definition = json.loads(graph_definition_json)
    except ValueError:
        return {}
    nodes = definition.get("nodes") if isinstance(definition, dict) else None
    if not isinstance(nodes, list):
        return {}
    names: dict[str, str] = {}
    for node in nodes:
        if not isinstance(node, dict) or not isinstance(node.get("node_id"), str):
            continue
        name = node.get("name")
        names[node["node_id"]] = name if isinstance(name, str) else ""
    return names


def _rubric_bindings(scores: tuple[RunEvalScore, ...]) -> list[RubricRevisionBinding]:
    seen: dict[tuple[str, int, str, int], RubricRevisionBinding] = {}
    for score in scores:
        key = (score.goal_id, score.goal_revision, score.rubric_id, score.rubric_revision)
        seen.setdefault(key, RubricRevisionBinding(*key))
    return sorted(seen.values(), key=lambda b: (b.rubric_revision, b.rubric_id, b.goal_revision))


async def artifact_lineage(
    store: RunStore, run_id: str, artifact: Any
) -> tuple[RunLineage, NodeRunLineage, AttemptLineage]:
    """Trace one artifact back through Attempt → NodeRun → Run in one call.

    The accepted-artifact query of the M7 proof: from the artifact a fence
    accept cited to the physical Attempt that produced it, the logical
    NodeRun that owns that Attempt, and the Run's full lineage (Graph,
    Goal revisions, Rubric revisions, every eval record).
    """
    lineage = await run_lineage(store, run_id)
    node_run, attempt = lineage.find_artifact(artifact)
    return lineage, node_run, attempt
