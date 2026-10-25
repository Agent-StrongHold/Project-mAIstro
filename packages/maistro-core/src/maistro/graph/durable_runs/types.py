"""Canonical durable graph persistence envelope."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, model_validator

from maistro.graph.execution_state import GraphEdgeDecision, GraphExecutionState
from maistro.graph.traversal_commit import (
    TraversalCheckpoint,
    TraversalCommit,
    accepted_outcome_id,
    edge_decision_id,
)
from maistro.runs.model import TERMINAL_RUN_STATUSES, Attempt, NodeRun, Run, RunStatus


def _validate_node_run_links(run: Run, node_runs: tuple[NodeRun, ...]) -> set[str]:
    if any(node_run.run_id != run.run_id for node_run in node_runs):
        raise ValueError("every NodeRun must belong to the persisted Run")
    ordinals = [node_run.ordinal for node_run in node_runs]
    if ordinals != list(range(1, len(ordinals) + 1)):
        raise ValueError("NodeRun ordinals must be consecutive in persistence order")
    return {node_run.node_run_id for node_run in node_runs}


def _validate_attempt_links(attempts: tuple[Attempt, ...], node_run_ids: set[str]) -> None:
    if any(attempt.node_run_id not in node_run_ids for attempt in attempts):
        raise ValueError("every Attempt must belong to a persisted NodeRun")
    attempts_by_node_run: dict[str, list[int]] = {}
    for attempt in attempts:
        attempts_by_node_run.setdefault(attempt.node_run_id, []).append(attempt.ordinal)
    if any(
        ordinals != list(range(1, len(ordinals) + 1)) for ordinals in attempts_by_node_run.values()
    ):
        raise ValueError("Attempt ordinals must be consecutive per NodeRun")


def _validate_graph_links(run: Run, graph_state: GraphExecutionState) -> None:
    if graph_state.run_id != run.run_id:
        raise ValueError("graph_state.run_id must match run.run_id")
    node_ids = {node.node_id for node in run.graph.materialize().nodes}
    if any(node_id not in node_ids for node_id in graph_state.active_node_ids):
        raise ValueError("active graph frontier must reference nodes in the Run Graph snapshot")


def _validate_checkpoint_record(
    *,
    run: Run,
    checkpoint: TraversalCheckpoint,
    node_run_ids: set[str],
    checkpoints_by_id: dict[str, TraversalCheckpoint],
) -> None:
    if checkpoint.run_id != run.run_id:
        raise ValueError("every TraversalCheckpoint must belong to the persisted Run")
    if checkpoint.graph_snapshot_hash != run.graph.content_hash:
        raise ValueError("TraversalCheckpoint graph snapshot must match the Run snapshot")
    if any(
        node_run_id not in node_run_ids for node_run_id in checkpoint.ordered_source_node_run_ids
    ):
        raise ValueError("TraversalCheckpoint source NodeRun must be persisted")
    if checkpoint.traversal_checkpoint_id in checkpoints_by_id:
        raise ValueError("TraversalCheckpoint identities must be unique")


def _validate_traversal_checkpoints(
    *,
    run: Run,
    node_runs: tuple[NodeRun, ...],
    checkpoints: tuple[TraversalCheckpoint, ...],
) -> dict[str, TraversalCheckpoint]:
    if [checkpoint.checkpoint_sequence for checkpoint in checkpoints] != list(
        range(1, len(checkpoints) + 1)
    ):
        raise ValueError("TraversalCheckpoint sequences must be consecutive from one")

    node_run_ids = {node_run.node_run_id for node_run in node_runs}
    checkpoints_by_id: dict[str, TraversalCheckpoint] = {}
    for checkpoint in checkpoints:
        _validate_checkpoint_record(
            run=run,
            checkpoint=checkpoint,
            node_run_ids=node_run_ids,
            checkpoints_by_id=checkpoints_by_id,
        )
        checkpoints_by_id[checkpoint.traversal_checkpoint_id] = checkpoint
    return checkpoints_by_id


def _checkpoint_bridge(
    commit: TraversalCommit,
    checkpoints_by_id: dict[str, TraversalCheckpoint],
    referenced_checkpoint_ids: set[str],
) -> TraversalCheckpoint | None:
    if commit.checkpoint_id is None:
        return None
    checkpoint = checkpoints_by_id.get(commit.checkpoint_id)
    if checkpoint is None:
        raise ValueError("TraversalCommit checkpoint bridge must be persisted")
    if commit.checkpoint_id in referenced_checkpoint_ids:
        raise ValueError("TraversalCheckpoint cannot bridge more than one TraversalCommit")
    if checkpoint.state_hash != commit.prior_state_hash:
        raise ValueError("TraversalCommit prior state must match its checkpoint bridge")
    if (
        checkpoint.ordered_source_node_run_ids
        and checkpoint.ordered_source_node_run_ids != commit.ordered_source_node_run_ids
    ):
        raise ValueError("TraversalCommit checkpoint sources must match advancing NodeRuns")
    if checkpoint.checkpointed_at > commit.committed_at:
        raise ValueError("TraversalCommit cannot precede its checkpoint bridge")
    referenced_checkpoint_ids.add(commit.checkpoint_id)
    return checkpoint


def _validate_commit_chain(
    run: Run,
    commit: TraversalCommit,
    previous: TraversalCommit | None,
    checkpoints_by_id: dict[str, TraversalCheckpoint],
    referenced_checkpoint_ids: set[str],
) -> None:
    if commit.run_id != run.run_id:
        raise ValueError("every TraversalCommit must belong to the persisted Run")
    if commit.graph_snapshot_hash != run.graph.content_hash:
        raise ValueError("TraversalCommit graph snapshot must match the Run snapshot")
    expected_parent = previous.traversal_commit_id if previous is not None else None
    if commit.prior_commit_id != expected_parent:
        raise ValueError("TraversalCommit history must form one parent-linked chain")

    checkpoint = _checkpoint_bridge(
        commit,
        checkpoints_by_id,
        referenced_checkpoint_ids,
    )
    if checkpoint is not None:
        return
    if previous is not None and commit.prior_state_hash != previous.resulting_state_hash:
        raise ValueError(
            "adjacent TraversalCommits must link resulting and prior state hashes "
            "or persist a TraversalCheckpoint bridge"
        )


def _commit_source_runs(
    commit: TraversalCommit,
    node_runs_by_id: dict[str, NodeRun],
) -> tuple[list[NodeRun], set[str]]:
    source_runs: list[NodeRun] = []
    source_ids = set(commit.ordered_source_node_run_ids)
    for node_run_id in commit.ordered_source_node_run_ids:
        source = node_runs_by_id.get(node_run_id)
        if source is None:
            raise ValueError("TraversalCommit source NodeRun must be persisted")
        if source.accepted_outcome is None:
            raise ValueError("TraversalCommit source NodeRun requires an accepted outcome")
        source_runs.append(source)
    return source_runs, source_ids


def _validate_commit_outcomes(commit: TraversalCommit, source_runs: list[NodeRun]) -> None:
    persisted_outcome_ids = tuple(
        accepted_outcome_id(source.accepted_outcome)
        for source in source_runs
        if source.accepted_outcome is not None
    )
    if persisted_outcome_ids != commit.accepted_outcome_ids:
        raise ValueError("TraversalCommit outcome identities must match persisted NodeRuns")


def _validate_commit_decisions(
    commit: TraversalCommit,
    decisions_by_id: dict[str, GraphEdgeDecision],
    source_ids: set[str],
) -> None:
    for decision_id in commit.edge_decision_ids:
        decision = decisions_by_id.get(decision_id)
        if decision is None:
            raise ValueError("TraversalCommit routing decisions must exist in GraphExecutionState")
        if decision.source_node_run_id not in source_ids:
            raise ValueError("TraversalCommit routing decision must belong to a source NodeRun")


def _validate_traversal_commits(
    *,
    run: Run,
    graph_state: GraphExecutionState,
    node_runs: tuple[NodeRun, ...],
    checkpoints_by_id: dict[str, TraversalCheckpoint],
    commits: tuple[TraversalCommit, ...],
) -> None:
    if not commits:
        return
    if [commit.commit_sequence for commit in commits] != list(range(1, len(commits) + 1)):
        raise ValueError("TraversalCommit sequences must be consecutive from one")

    node_runs_by_id = {node_run.node_run_id: node_run for node_run in node_runs}
    decisions_by_id = {
        edge_decision_id(decision): decision for decision in graph_state.edge_decisions
    }
    previous: TraversalCommit | None = None
    referenced_checkpoint_ids: set[str] = set()

    for commit in commits:
        _validate_commit_chain(
            run,
            commit,
            previous,
            checkpoints_by_id,
            referenced_checkpoint_ids,
        )
        source_runs, source_ids = _commit_source_runs(commit, node_runs_by_id)
        _validate_commit_outcomes(commit, source_runs)
        _validate_commit_decisions(commit, decisions_by_id, source_ids)
        previous = commit

    if (
        run.status not in TERMINAL_RUN_STATUSES
        and commits[-1].resulting_frontier != graph_state.active_node_ids
    ):
        raise ValueError("latest TraversalCommit frontier must match persisted GraphExecutionState")


class DurableRunRecord(BaseModel):
    """Persisted canonical Run plus graph continuation, physical history, and commits."""

    model_config = ConfigDict(extra="forbid")

    run: Run
    graph_state: GraphExecutionState
    node_runs: tuple[NodeRun, ...] = Field(default_factory=tuple)
    attempts: tuple[Attempt, ...] = Field(default_factory=tuple)
    traversal_checkpoints: tuple[TraversalCheckpoint, ...] = Field(default_factory=tuple)
    traversal_commits: tuple[TraversalCommit, ...] = Field(default_factory=tuple)
    resume_at: datetime | None = None
    version: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _validate_links(self) -> DurableRunRecord:
        _validate_graph_links(self.run, self.graph_state)
        node_run_ids = _validate_node_run_links(self.run, self.node_runs)
        _validate_attempt_links(self.attempts, node_run_ids)
        checkpoints_by_id = _validate_traversal_checkpoints(
            run=self.run,
            node_runs=self.node_runs,
            checkpoints=self.traversal_checkpoints,
        )
        _validate_traversal_commits(
            run=self.run,
            graph_state=self.graph_state,
            node_runs=self.node_runs,
            checkpoints_by_id=checkpoints_by_id,
            commits=self.traversal_commits,
        )
        return self

    @property
    def run_id(self) -> str:
        return self.run.run_id

    @property
    def status(self) -> RunStatus:
        return self.run.status

    @property
    def project_id(self) -> str:
        return self.run.project_id

    @property
    def active_node_id(self) -> str | None:
        active = self.graph_state.active_node_ids
        return active[0] if active else None

    @property
    def latest_traversal_checkpoint(self) -> TraversalCheckpoint | None:
        return self.traversal_checkpoints[-1] if self.traversal_checkpoints else None

    @property
    def latest_traversal_commit(self) -> TraversalCommit | None:
        return self.traversal_commits[-1] if self.traversal_commits else None

    @property
    def hitl_answers(self) -> dict[str, dict[str, object]]:
        raw = self.graph_state.metadata.get("hitl_answers", {})
        if not isinstance(raw, Mapping):
            return {}
        return {
            str(node_id): dict(answer)
            for node_id, answer in raw.items()
            if isinstance(answer, Mapping)
        }


if TYPE_CHECKING:

    def _vulture_pydantic_contract_usage(record: DurableRunRecord) -> None:
        _ = record._validate_links
        _ = record.latest_traversal_checkpoint
        _ = record.latest_traversal_commit

    _: object
    _ = _vulture_pydantic_contract_usage
    _ = _validate_traversal_checkpoints
    _ = _validate_traversal_commits


__all__ = ["DurableRunRecord", "RunStatus"]
