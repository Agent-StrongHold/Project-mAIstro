"""M7-A11 model-judge: rubric dimensions scored through governed Invocations.

Acceptance under test (#987):

- a ``model_judge`` dimension writes eval records that name the Invocation;
- records name the Goal revision, Rubric revision, NodeRun/Attempt and judge
  identity, and are persisted as the judge NodeRun's Attempt evidence — no
  second eval lifecycle;
- the records are canonical ``#792`` Run evidence: ``RunEvalScore`` rows on the
  producing Run, readable through ``maistro.runs.eval.eval_summary``;
- ``deterministic`` scores in-process and still writes records;
- ``human`` is refused (it waits on #794), never silently skipped;
- missing Binding fails closed before any dimension runs.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

pytestmark = pytest.mark.asyncio

GOAL_ID = "goal-design-1"
GOAL_REVISION = 7
RUBRIC_ID = "rubric-design-1"
RUBRIC_REVISION = 3


def _judge_body(score: int, rationale: str) -> dict[str, Any]:
    content = json.dumps({"score": score, "rationale": rationale})
    return {
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 90, "completion_tokens": 15},
    }


def _theses() -> list[dict[str, Any]]:
    return [
        {
            "thesis_id": "thesis-a",
            "title": "Direction A",
            "summary": "First direction",
            "body": "A coherent direction body.",
            "node_run_id": "nr-thesis-a",
            "attempt_id": "att-thesis-a",
        },
        {
            "thesis_id": "thesis-b",
            "title": "Direction B",
            "summary": "Second direction",
            "body": "A different direction body.",
        },
    ]


def _judge_graph(
    governed: Any,
    governed_kit: Any,
    *,
    dimensions: list[dict[str, Any]],
    binding_id: str = "",
    theses: list[dict[str, Any]] | None = None,
):
    from maistro.graph.definitions import Graph, Node

    parameters: dict[str, Any] = {
        "theses": theses if theses is not None else _theses(),
        "dimensions": dimensions,
        "goal_id": GOAL_ID,
        "goal_revision": GOAL_REVISION,
        "rubric_id": RUBRIC_ID,
        "rubric_revision": RUBRIC_REVISION,
        "binding_id": binding_id or governed.binding.binding_id,
        "model": governed_kit.model_alias,
    }
    return Graph(
        workspace_id=governed.workspace_id,
        project_id=governed.project_id,
        name="design judge",
        nodes=[Node(node_id="judge", node_type="design.judge", parameters=parameters)],
        edges=[],
    )


async def _run_judge(
    governed: Any,
    graph: Any,
    governed_kit: Any,
    *,
    patch_gateway: Any | None = None,
    bodies: list[dict[str, Any]] | None = None,
) -> Any:
    sent: list[dict[str, Any]] = []
    if patch_gateway is not None:
        sent = patch_gateway(bodies)
    record = await governed_kit.run_wave(
        governed,
        graph,
        nodes_by_kind={"design.judge": governed_kit.judge_node(governed)},
    )
    return record, sent


async def test_model_judge_records_name_the_invocation(
    governed: Any,
    governed_kit: Any,
    patch_gateway: Any,
) -> None:
    """One Invocation per (thesis x model_judge dimension); records name it."""

    from maistro.capabilities.invocation import InvocationStatus
    from maistro.runs.model import RunStatus

    bodies = [
        _judge_body(81, "Strong composition logic."),
        _judge_body(44, "Weak contrast handling."),
        _judge_body(67, "Adequate hierarchy."),
        _judge_body(90, "Excellent rhythm."),
    ]
    graph = _judge_graph(
        governed,
        governed_kit,
        dimensions=[
            {"name": "visual-hierarchy", "method": "model_judge", "prompt": "hierarchy quality"},
            {"name": "brand-fit", "method": "model_judge", "prompt": "brand fit"},
        ],
    )
    record, sent = await _run_judge(
        governed, graph, governed_kit, patch_gateway=patch_gateway, bodies=bodies
    )

    assert record.run.status is RunStatus.COMPLETED
    judge_run = next(nr for nr in record.node_runs if nr.node_id == "judge")
    output = judge_run.result
    assert output["eval_complete"] is True
    records = output["records"]
    assert len(records) == 4, "one record per (thesis x dimension) pair"

    model_records = [r for r in records if r["method"] == "model_judge"]
    assert len(model_records) == 4
    invocation_ids = {r["invocation_id"] for r in model_records}
    assert len(invocation_ids) == 4, "one Invocation per pair, none shared"
    assert output["model_invocations"] == 4
    assert len(sent) == 4

    for record_json in model_records:
        invocation = await governed.effects.invocation_store.get(record_json["invocation_id"])
        assert invocation is not None
        assert invocation.status is InvocationStatus.COMPLETED
        assert invocation.node_run_id == judge_run.node_run_id
        # Every record names the revisions, the judge NodeRun/Attempt and identity.
        assert record_json["goal_id"] == GOAL_ID
        assert record_json["goal_revision"] == GOAL_REVISION
        assert record_json["rubric_id"] == RUBRIC_ID
        assert record_json["rubric_revision"] == RUBRIC_REVISION
        assert record_json["node_run_id"] == judge_run.node_run_id
        assert record_json["attempt_id"] == judge_run.accepted_outcome.attempt_result.attempt_id
        assert record_json["judge_identity"]
        assert record_json["thesis_node_run_id"] in {"", "nr-thesis-a"}


async def test_judge_invocations_are_scoped_by_the_wave_logical_key(
    governed: Any,
    governed_kit: Any,
    patch_gateway: Any,
) -> None:
    """The judge's Invocations carry the wave's logical effect scope.

    ``design.judge`` declares ``EFFECT_KEY`` replay semantics, so a retry of
    the same wave must reconcile with the Invocations the first Attempt
    recorded rather than dispatching a second round of judge calls (#1194).
    The scope is what makes that reconciliation possible.
    """

    graph = _judge_graph(
        governed,
        governed_kit,
        dimensions=[{"name": "visual-hierarchy", "method": "model_judge", "prompt": "quality"}],
    )
    record, sent = await _run_judge(
        governed,
        graph,
        governed_kit,
        patch_gateway=patch_gateway,
        bodies=[_judge_body(75, "Solid."), _judge_body(52, "Mixed.")],
    )

    judge_run = next(nr for nr in record.node_runs if nr.node_id == "judge")
    output = judge_run.result
    for record_json in output["records"]:
        invocation = await governed.effects.invocation_store.get(record_json["invocation_id"])
        assert invocation is not None
        assert invocation.effect_scope.startswith("design.judge.wave:")
        assert invocation.effect_scope != invocation.node_run_id
    assert len(sent) == 2


async def test_records_are_canonical_792_run_evidence(
    governed: Any,
    governed_kit: Any,
    patch_gateway: Any,
) -> None:
    """The eval rows live on the Run in the canonical ``#792`` shape.

    Not a side ledger and not a second lifecycle: the rows are
    ``RunEvalScore`` records on the producing Run, and the canonical
    completeness projection (``maestro.runs.eval.eval_summary``) sees them.
    """

    from maistro.runs.eval import eval_summary

    graph = _judge_graph(
        governed,
        governed_kit,
        dimensions=[
            {"name": "visual-hierarchy", "method": "model_judge", "prompt": "hierarchy"},
            {"name": "brand-fit", "method": "model_judge", "prompt": "brand"},
        ],
    )
    record, _ = await _run_judge(
        governed,
        graph,
        governed_kit,
        patch_gateway=patch_gateway,
        bodies=[
            _judge_body(81, "Strong."),
            _judge_body(44, "Weak."),
            _judge_body(67, "Adequate."),
            _judge_body(90, "Excellent."),
        ],
    )

    judge_run = next(nr for nr in record.node_runs if nr.node_id == "judge")
    attempt_id = judge_run.accepted_outcome.attempt_result.attempt_id

    rows = await governed.run_store.list_eval_scores(record.run_id)
    assert len(rows) == 4, "one canonical row per (thesis x dimension) pair"
    for row in rows:
        assert row.run_id == record.run_id
        assert row.node_run_id == judge_run.node_run_id
        assert row.attempt_id == attempt_id
        # The rows name the exact revisions the Run was admitted for.
        assert row.goal_id == GOAL_ID
        assert row.goal_revision == GOAL_REVISION
        assert row.rubric_id == RUBRIC_ID
        assert row.rubric_revision == RUBRIC_REVISION
        assert row.method == "model_judge"
        assert row.judge is not None and row.judge.identity
        # The Invocation that produced the score is named as evidence.
        assert any(pointer.startswith("invocation:") for pointer in row.evidence_pointers)
        assert row.detail["thesis_id"]
        # The dimension identity is thesis-qualified: one row per pair, never
        # one thesis's score superseding another's under a shared name.
        name, _, thesis_id = row.dimension_id.partition("@")
        assert name in {"visual-hierarchy", "brand-fit"}
        assert thesis_id in {"thesis-a", "thesis-b"}

    # The canonical projection reads the persisted rows back — per
    # (thesis x dimension) pair, the identity they were persisted under.
    summary = await eval_summary(
        governed.run_store,
        record.run_id,
        rubric_id=RUBRIC_ID,
        rubric_revision=RUBRIC_REVISION,
        dimension_ids=[
            f"{dimension}@{thesis}"
            for thesis in ("thesis-a", "thesis-b")
            for dimension in ("visual-hierarchy", "brand-fit")
        ],
    )
    assert summary.complete is True
    assert len(summary.records) == 4
    assert summary.passed is False, "thesis-a's brand-fit 44 must stay visible"


async def test_a_failing_thesis_is_not_hidden_by_a_later_passing_thesis(
    governed: Any,
    governed_kit: Any,
    patch_gateway: Any,
) -> None:
    """Scores for distinct theses never supersede one another.

    ``eval_summary`` keeps the latest record per ``dimension_id``; if both
    theses' scores for one rubric dimension were persisted under the bare
    dimension name, the later passing thesis would replace the earlier
    failing one and the summary would report ``passed``. Thesis-qualified
    identities keep the failing pair queryable.
    """

    from maistro.runs.eval import eval_summary
    from maistro.runs.model import RunStatus

    graph = _judge_graph(
        governed,
        governed_kit,
        dimensions=[{"name": "visual-hierarchy", "method": "model_judge", "prompt": "hierarchy"}],
    )
    record, _ = await _run_judge(
        governed,
        graph,
        governed_kit,
        patch_gateway=patch_gateway,
        # thesis-a fails the dimension, thesis-b passes it — scored in that
        # order, so the passing row lands last.
        bodies=[_judge_body(44, "Weak."), _judge_body(90, "Excellent.")],
    )
    assert record.run.status is RunStatus.COMPLETED

    summary = await eval_summary(
        governed.run_store,
        record.run_id,
        rubric_id=RUBRIC_ID,
        rubric_revision=RUBRIC_REVISION,
        dimension_ids=["visual-hierarchy@thesis-a", "visual-hierarchy@thesis-b"],
    )
    assert summary.complete is True
    assert summary.passed is False
    assert summary.failed_dimensions == ("visual-hierarchy@thesis-a",)
    assert summary.latest_by_dimension["visual-hierarchy@thesis-b"].raw_score == 90.0


async def test_judge_refuses_a_goal_revision_the_run_was_not_admitted_for(
    governed: Any,
    governed_kit: Any,
    patch_gateway: Any,
) -> None:
    """Eval evidence may not name a Goal revision the Run never referenced."""

    from maistro.runs.model import RunStatus

    graph = _judge_graph(
        governed,
        governed_kit,
        dimensions=[{"name": "visual-hierarchy", "method": "model_judge", "prompt": "quality"}],
    )
    # The graph's judge node asks for a different Goal revision than the Run
    # was admitted for.
    graph = graph.model_copy(
        deep=True,
        update={
            "nodes": [
                node.model_copy(
                    deep=True,
                    update={"parameters": {**node.parameters, "goal_revision": 99}},
                )
                for node in graph.nodes
            ]
        },
    )
    record, sent = await _run_judge(
        governed, graph, governed_kit, patch_gateway=patch_gateway, bodies=[]
    )

    assert record.run.status is RunStatus.FAILED
    judge_run = next(nr for nr in record.node_runs if nr.node_id == "judge")
    assert judge_run.error is not None
    assert "admitted for Goal" in judge_run.error
    assert sent == [], "a mismatched Goal revision must not reach the gateway"
    assert await governed.run_store.list_eval_scores(record.run_id) == []


async def test_records_are_persisted_run_evidence(
    governed: Any,
    governed_kit: Any,
    patch_gateway: Any,
) -> None:
    """eval-complete is backed by the judge NodeRun's Attempt, not a side ledger."""

    from maistro.runs.model import AttemptStatus, RunStatus

    graph = _judge_graph(
        governed,
        governed_kit,
        dimensions=[{"name": "visual-hierarchy", "method": "model_judge", "prompt": "quality"}],
    )
    record, _ = await _run_judge(
        governed,
        graph,
        governed_kit,
        patch_gateway=patch_gateway,
        bodies=[_judge_body(75, "Solid."), _judge_body(52, "Mixed.")],
    )

    assert record.run.status is RunStatus.COMPLETED
    judge_run = next(nr for nr in record.node_runs if nr.node_id == "judge")
    assert judge_run.accepted_outcome is not None
    attempt_id = judge_run.accepted_outcome.attempt_result.attempt_id
    attempt = await governed.run_store.get_attempt(attempt_id)
    assert attempt is not None and attempt.status is AttemptStatus.COMPLETED
    # The canonical Attempt evidence carries the eval records themselves.
    evidence = attempt.result
    persisted_output = getattr(evidence, "output", None)
    persisted = getattr(persisted_output, "records", None) or persisted_output.get("records")
    assert [r["invocation_id"] if isinstance(r, dict) else r.invocation_id for r in persisted] != [
        "",
        "",
    ]


async def test_judge_without_the_canonical_run_store_refuses(
    governed: Any,
    governed_kit: Any,
) -> None:
    """Without the canonical Run store there is nowhere to persist evidence."""

    from maistro.graph.nodes.base import NodeContext
    from maistro_design.model_judge import DesignJudgeIn, DesignJudgeNode

    node = DesignJudgeNode(
        effect_context=governed.effects,
        registry=governed.registry,
        router=governed.router,
    )
    inputs = DesignJudgeIn(
        theses=_theses(),
        dimensions=[{"name": "visual-hierarchy", "method": "model_judge", "prompt": "quality"}],
        goal_id=GOAL_ID,
        goal_revision=GOAL_REVISION,
        rubric_id=RUBRIC_ID,
        rubric_revision=RUBRIC_REVISION,
        binding_id=governed.binding.binding_id,
    )
    result = await node.run(
        inputs,
        NodeContext(run_id="run-x", dag_id="dag-x", node_id="judge", node_run_id="nr-x"),
    )
    assert result.success is False
    assert result.error_message is not None
    assert "canonical Run store" in result.error_message


async def test_deterministic_dimension_scores_in_process(
    governed: Any,
    governed_kit: Any,
) -> None:
    """Same spirit as persona RubricEval: no network, records still written."""

    from maistro.runs.model import RunStatus

    graph = _judge_graph(
        governed,
        governed_kit,
        dimensions=[
            {
                "name": "has-body",
                "method": "deterministic",
                "criteria": [
                    {
                        "name": "mentions direction",
                        "weight": 2,
                        "op": "keywords_any",
                        "words": ["direction"],
                    },
                    {"name": "reasonably long", "weight": 1, "op": "word_count", "min": 3},
                ],
            }
        ],
    )
    record, sent = await _run_judge(governed, graph, governed_kit)

    assert record.run.status is RunStatus.COMPLETED
    judge_run = next(nr for nr in record.node_runs if nr.node_id == "judge")
    output = judge_run.result
    assert output["eval_complete"] is True
    assert output["model_invocations"] == 0
    assert sent == []
    records = output["records"]
    assert len(records) == 2
    for record_json in records:
        assert record_json["method"] == "deterministic"
        assert record_json["invocation_id"] == ""
        assert record_json["judge_identity"] == "deterministic:rubric-vocabulary"
        assert 0 <= record_json["score"] <= 100
        assert record_json["rationale"]


async def test_human_dimension_is_refused_not_skipped(
    governed: Any,
    governed_kit: Any,
) -> None:
    """Human judgment waits on #794 — the node refuses, it does not fake."""

    from maistro.runs.model import RunStatus

    graph = _judge_graph(
        governed,
        governed_kit,
        dimensions=[
            {"name": "human-taste", "method": "human"},
            {"name": "visual-hierarchy", "method": "model_judge", "prompt": "quality"},
        ],
    )
    record, _ = await _run_judge(governed, graph, governed_kit)

    assert record.run.status is RunStatus.FAILED
    judge_run = next(nr for nr in record.node_runs if nr.node_id == "judge")
    assert judge_run.error is not None
    assert judge_run.error.startswith("HumanJudgeNotResolvedError:")
    assert "#794" in judge_run.error


async def test_missing_binding_fails_before_any_dimension(
    governed: Any,
    governed_kit: Any,
    patch_gateway: Any,
) -> None:
    """No authorized Binding: refusal first, zero judge calls, zero records."""

    from maistro.runs.model import RunStatus

    graph = _judge_graph(
        governed,
        governed_kit,
        binding_id="binding-never-registered",
        dimensions=[{"name": "visual-hierarchy", "method": "model_judge", "prompt": "quality"}],
    )
    record, sent = await _run_judge(
        governed, graph, governed_kit, patch_gateway=patch_gateway, bodies=[]
    )

    assert record.run.status is RunStatus.FAILED
    judge_run = next(nr for nr in record.node_runs if nr.node_id == "judge")
    assert judge_run.error is not None
    assert judge_run.error.startswith("BindingNotFound:")
    assert sent == []


async def test_scoreless_judge_response_never_completes(
    governed: Any,
    governed_kit: Any,
    patch_gateway: Any,
) -> None:
    """A judge answer without a score fails the node — no invented eval records."""

    from maistro.runs.model import RunStatus

    graph = _judge_graph(
        governed,
        governed_kit,
        dimensions=[{"name": "visual-hierarchy", "method": "model_judge", "prompt": "quality"}],
    )
    record, _ = await _run_judge(
        governed,
        graph,
        governed_kit,
        patch_gateway=patch_gateway,
        bodies=[
            {
                "choices": [
                    {"message": {"role": "assistant", "content": '{"rationale": "no score"}'}}
                ]
            }
        ],
    )

    assert record.run.status is RunStatus.FAILED
    judge_run = next(nr for nr in record.node_runs if nr.node_id == "judge")
    assert judge_run.error is not None
    assert "no integer score" in judge_run.error
