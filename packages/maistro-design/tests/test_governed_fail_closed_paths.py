"""M7-A11 governed explore/judge: the refusal paths, pinned (#987).

The governed path's contract is negative-space: a wave that fails closed in no
observable way is a wave that can quietly start succeeding. Every case below is
a refusal the issue requires, exercised through the production wiring (the
canonical Run/NodeRun/Attempt spine and the governed gateway seam):

- the operator redirect and the rejected theses actually reach the model;
- a response with no choices, or JSON that is not an object, is never a thesis;
- a blank binding id, or a deployment with no gateway configured, refuses
  before any prompt is assembled or any physical effect exists;
- a rubric dimension without a prompt is still judged; a non-integer score, a
  duplicated dimension name, or a response with no choices is not a score;
- a judge pointed at a store that does not hold the Run, at a Run admitted
  without a Goal binding, or at a store that keeps nothing, refuses instead of
  inventing evidence.
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


def _thesis_body(title: str, model_alias: str) -> dict[str, Any]:
    content = json.dumps(
        {
            "title": title,
            "summary": "A distinct direction",
            "body": {"kind": "design.thesis", "detail": "artifact payload"},
        }
    )
    return {
        "model": f"{model_alias}-v2",
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 120, "completion_tokens": 40},
    }


def _judge_body(score: Any, rationale: str) -> dict[str, Any]:
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
        }
    ]


def _judge_graph(
    governed: Any,
    governed_kit: Any,
    *,
    dimensions: list[dict[str, Any]],
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
        "binding_id": governed.binding.binding_id,
        "model": governed_kit.model_alias,
    }
    return Graph(
        workspace_id=governed.workspace_id,
        project_id=governed.project_id,
        name="design judge",
        nodes=[Node(node_id="judge", node_type="design.judge", parameters=parameters)],
        edges=[],
    )


def _judge_node_on(governed: Any, governed_kit: Any, *, run_store: Any) -> Any:
    """A judge node wired to a specific Run store (the canonical one by default)."""

    from maistro_design.model_judge import DesignJudgeNode

    return DesignJudgeNode(
        effect_context=governed.effects,
        registry=governed.registry,
        router=governed.router,
        run_store=run_store,
    )


async def _run_judge_graph(
    governed: Any,
    graph: Any,
    node: Any,
    *,
    bind_goal: bool = True,
) -> Any:
    """Walk one judge graph on the canonical spine.

    ``bind_goal=False`` admits the Run without a Goal binding, which is the
    only way to reach the judge's "admitted without a canonical Goal binding"
    refusal: the store writes the binding once, at admission.
    """

    from maistro.graph.durable_runs import run_durable_graph
    from maistro.graph.durable_runs.launch import durable_graph_launch_provenance
    from maistro.runs.model import RunStatus
    from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID

    def node_resolver(_node_id: str, _walk_graph: Any) -> Any:
        return node

    admission: dict[str, Any] = {}
    if bind_goal:
        admission = {"goal_id": GOAL_ID, "goal_revision": GOAL_REVISION}
    run = await governed.run_store.create_run(
        graph,
        provenance=durable_graph_launch_provenance(inputs={}, blackboard_metadata={}),
        initial_status=RunStatus.QUEUED,
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
        **admission,
    )
    return await run_durable_graph(
        graph,
        store=governed.durable_store,
        node_resolver=node_resolver,
        run_store=governed.run_store,
        run_id=run.run_id,
    )


def _user_message(sent: list[dict[str, Any]]) -> str:
    messages = sent[0]["messages"]
    return str(next(m for m in messages if m["role"] == "user")["content"])


# --- explore: the prompt the model actually receives -------------------------


async def test_the_operator_redirect_and_rejected_theses_reach_the_model_prompt(
    patch_gateway: Any,
    governed: Any,
    governed_kit: Any,
) -> None:
    """The wave envelope's steering fields are not decoration.

    A redirect the model never sees is an operator redirect that did not
    happen, and a rejected thesis the model may repeat is a thesis the wave
    was supposed to avoid.
    """

    from maistro.runs.model import RunStatus

    sent = patch_gateway([_thesis_body("Direction A", governed_kit.model_alias)])
    graph = governed_kit.wave_graph(
        governed,
        width=1,
        redirect="prefer diagram-led directions",
        rejected_theses=["a pie-chart dashboard"],
    )
    record = await governed_kit.run_wave(
        governed, graph, nodes_by_kind=governed_kit.design_nodes(governed)
    )

    assert record.run.status is RunStatus.COMPLETED
    assert len(sent) == 1
    prompt = _user_message(sent)
    assert "Operator redirect (obey): prefer diagram-led directions" in prompt
    assert "Do not repeat these rejected theses:\n- a pie-chart dashboard" in prompt


async def test_a_thesis_response_with_no_choices_is_never_a_thesis(
    patch_gateway: Any,
    governed: Any,
    governed_kit: Any,
) -> None:
    """An empty completion is a failed slot, not an empty thesis.

    The slot asks for a JSON object; a response with no choice carries none, so
    the payload cannot be parsed and the slot must record the failure instead
    of storing a thesis with no body.
    """

    from maistro.runs.model import RunStatus

    patch_gateway([{"model": governed_kit.model_alias, "choices": []}])
    graph = governed_kit.wave_graph(governed, width=1)
    record = await governed_kit.run_wave(
        governed, graph, nodes_by_kind=governed_kit.design_nodes(governed)
    )

    thesis_run = next((nr for nr in record.node_runs if nr.node_id == "thesis-0"), None)
    assert thesis_run is not None and thesis_run.status is RunStatus.FAILED
    assert thesis_run.error is not None
    assert "malformed JSON" in thesis_run.error


async def test_a_thesis_payload_that_is_not_an_object_is_refused(
    patch_gateway: Any,
    governed: Any,
    governed_kit: Any,
) -> None:
    """JSON that parses but is not an object is refused like malformed JSON.

    A list (or a bare string) has no ``title``/``body`` to read; reading it as
    one would invent a thesis nobody produced.
    """

    from maistro.runs.model import RunStatus

    patch_gateway(
        [
            {
                "model": governed_kit.model_alias,
                "choices": [{"message": {"role": "assistant", "content": "[1, 2]"}}],
            }
        ]
    )
    graph = governed_kit.wave_graph(governed, width=1)
    record = await governed_kit.run_wave(
        governed, graph, nodes_by_kind=governed_kit.design_nodes(governed)
    )

    thesis_run = next((nr for nr in record.node_runs if nr.node_id == "thesis-0"), None)
    assert thesis_run is not None and thesis_run.status is RunStatus.FAILED
    assert thesis_run.error is not None
    assert "not an object" in thesis_run.error


# --- governance: refusals before any prompt exists ---------------------------


async def test_a_blank_binding_id_refuses_before_any_prompt(
    patch_gateway: Any,
    governed: Any,
    governed_kit: Any,
) -> None:
    """A binding id that is only whitespace authorizes nothing.

    The refusal has to happen before the wave assembles a prompt: an
    unauthorized wave that reached the model would have spent a physical
    effect on work it was never authorized to do.
    """

    from maistro.runs.model import RunStatus

    sent = patch_gateway([_thesis_body("Should never run", governed_kit.model_alias)])

    graph = governed_kit.wave_graph(governed, width=2, binding_id="   ")
    record = await governed_kit.run_wave(
        governed, graph, nodes_by_kind=governed_kit.design_nodes(governed)
    )

    assert record.run.status is RunStatus.FAILED
    explore_run = next(nr for nr in record.node_runs if nr.node_id == "explore")
    assert explore_run.status is RunStatus.FAILED
    assert explore_run.error is not None
    assert explore_run.error.startswith("BindingNotFound:")
    assert [nr for nr in record.node_runs if nr.node_id.startswith("thesis-")] == []
    assert sent == [], "a refused wave must not reach the gateway"


async def test_a_deployment_without_a_gateway_base_url_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No configured gateway is a hard refusal, not an empty endpoint.

    Reading the endpoint from the environment is what keeps saved design packs
    portable; a deployment without one has to say so instead of failing
    obscurely inside an HTTP client.
    """

    from maistro_design.governance import gateway_endpoint_from_env

    for name in ("MAISTRO_LLM_BASE_URL", "LITELLM_URL", "LITELLM_API_BASE"):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(RuntimeError, match="no LLM gateway base URL configured"):
        gateway_endpoint_from_env(30.0)


# --- judge: refusals that are not scores ------------------------------------


async def test_a_rubric_dimension_without_a_prompt_is_still_judged(
    patch_gateway: Any,
    governed: Any,
    governed_kit: Any,
) -> None:
    """An empty dimension prompt is a rubric choice, not a refusal.

    The judge still asks the model about the dimension by name; what it must
    not do is invent an "Assess:" instruction the rubric never wrote.
    """

    from maistro.runs.model import RunStatus

    sent = patch_gateway([_judge_body(77, "Solid.")])
    graph = _judge_graph(
        governed,
        governed_kit,
        dimensions=[{"name": "visual-hierarchy", "method": "model_judge", "prompt": ""}],
    )
    record = await _run_judge_graph(governed, graph, governed_kit.judge_node(governed))

    assert record.run.status is RunStatus.COMPLETED
    judge_run = next(nr for nr in record.node_runs if nr.node_id == "judge")
    assert judge_run.result["eval_complete"] is True
    assert len(sent) == 1
    prompt = _user_message(sent)
    assert "Dimension: visual-hierarchy" in prompt
    assert "Assess:" not in prompt


async def test_a_non_integer_score_is_not_a_score(
    patch_gateway: Any,
    governed: Any,
    governed_kit: Any,
) -> None:
    """A model that answers "high" instead of 80 fails the judge.

    The canonical record carries an integer score; coercing a string into one
    would put a number on the Run that the model never produced.
    """

    from maistro.runs.model import RunStatus

    patch_gateway([_judge_body("high", "Feels right.")])
    graph = _judge_graph(
        governed,
        governed_kit,
        dimensions=[{"name": "visual-hierarchy", "method": "model_judge", "prompt": "hierarchy"}],
    )
    record = await _run_judge_graph(governed, graph, governed_kit.judge_node(governed))

    judge_run = next(nr for nr in record.node_runs if nr.node_id == "judge")
    assert judge_run.status is RunStatus.FAILED
    assert judge_run.error is not None
    assert "no integer score" in judge_run.error


async def test_duplicate_dimension_names_refuse_before_any_model_call(
    patch_gateway: Any,
    governed: Any,
    governed_kit: Any,
) -> None:
    """Two dimensions with one name would collapse into one score set.

    The canonical completeness projection keys on dimension id, so the judge
    refuses the rubric instead of writing two rows that read back as one.
    """

    from maistro.runs.model import RunStatus

    sent = patch_gateway([_judge_body(70, "Fine.")])
    graph = _judge_graph(
        governed,
        governed_kit,
        dimensions=[
            {"name": "visual-hierarchy", "method": "model_judge", "prompt": "hierarchy"},
            {"name": "visual-hierarchy", "method": "model_judge", "prompt": "hierarchy again"},
        ],
    )
    record = await _run_judge_graph(governed, graph, governed_kit.judge_node(governed))

    judge_run = next(nr for nr in record.node_runs if nr.node_id == "judge")
    assert judge_run.status is RunStatus.FAILED
    assert judge_run.error is not None
    assert "distinct names" in judge_run.error
    assert sent == [], "a refused rubric must not reach the gateway"


async def test_a_judge_response_with_no_choices_is_not_a_score(
    patch_gateway: Any,
    governed: Any,
    governed_kit: Any,
) -> None:
    """An empty judge completion fails the wave instead of scoring zero."""

    from maistro.runs.model import RunStatus

    patch_gateway([{"model": governed_kit.model_alias, "choices": []}])
    graph = _judge_graph(
        governed,
        governed_kit,
        dimensions=[{"name": "visual-hierarchy", "method": "model_judge", "prompt": "hierarchy"}],
    )
    record = await _run_judge_graph(governed, graph, governed_kit.judge_node(governed))

    judge_run = next(nr for nr in record.node_runs if nr.node_id == "judge")
    assert judge_run.status is RunStatus.FAILED
    assert judge_run.error is not None
    assert "malformed JSON" in judge_run.error


async def test_a_judge_refuses_a_run_admitted_without_a_goal_binding(
    patch_gateway: Any,
    governed: Any,
    governed_kit: Any,
) -> None:
    """A Run admitted with no Goal binding cannot be judged.

    The eval rows must name the Goal revision the Run was admitted for; a Run
    with no binding has none to name, so the judge refuses instead of
    inventing one.
    """

    from maistro.runs.model import RunStatus

    sent = patch_gateway([_judge_body(70, "Fine.")])
    graph = _judge_graph(
        governed,
        governed_kit,
        dimensions=[{"name": "visual-hierarchy", "method": "model_judge", "prompt": "hierarchy"}],
    )
    record = await _run_judge_graph(
        governed, graph, governed_kit.judge_node(governed), bind_goal=False
    )

    judge_run = next(nr for nr in record.node_runs if nr.node_id == "judge")
    assert judge_run.status is RunStatus.FAILED
    assert judge_run.error is not None
    assert "admitted without a canonical Goal binding" in judge_run.error
    assert sent == []


async def test_a_judge_pointed_at_a_store_without_the_run_refuses(
    patch_gateway: Any,
    governed: Any,
    governed_kit: Any,
) -> None:
    """Evidence about a Run the judge cannot read is not evidence.

    A judge wired to a store that does not hold the Run has no Run to bind
    its rows to, and must refuse rather than score into a void.
    """

    from maistro.runs.model import RunStatus
    from maistro.runs.store import InMemoryRunStore

    patch_gateway([_judge_body(70, "Fine.")])
    graph = _judge_graph(
        governed,
        governed_kit,
        dimensions=[{"name": "visual-hierarchy", "method": "model_judge", "prompt": "hierarchy"}],
    )
    empty_store = InMemoryRunStore(project_store=governed.project_store)
    node = _judge_node_on(governed, governed_kit, run_store=empty_store)
    record = await _run_judge_graph(governed, graph, node)

    judge_run = next(nr for nr in record.node_runs if nr.node_id == "judge")
    assert judge_run.status is RunStatus.FAILED
    assert judge_run.error is not None
    assert "is not on the canonical Run store" in judge_run.error


async def test_a_store_that_keeps_nothing_makes_the_judge_refuse(
    patch_gateway: Any,
    governed: Any,
    governed_kit: Any,
) -> None:
    """ "Eval complete" is a property of persisted rows, not of intent.

    A store that accepts the write and keeps nothing leaves the Run with no
    evidence; the judge must notice that on read-back and refuse to report
    completeness it cannot show.
    """

    from maistro.runs.model import RunStatus

    class _LossyStore:
        """Delegates every read, drops every eval write."""

        def __init__(self, inner: Any) -> None:
            self._inner = inner

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

        async def record_eval_score(self, score: Any) -> Any:
            return None

    patch_gateway([_judge_body(70, "Fine.")])
    graph = _judge_graph(
        governed,
        governed_kit,
        dimensions=[{"name": "visual-hierarchy", "method": "model_judge", "prompt": "hierarchy"}],
    )
    node = _judge_node_on(governed, governed_kit, run_store=_LossyStore(governed.run_store))
    record = await _run_judge_graph(governed, graph, node)

    judge_run = next(nr for nr in record.node_runs if nr.node_id == "judge")
    assert judge_run.status is RunStatus.FAILED
    assert judge_run.error is not None
    assert "no complete persisted eval evidence" in judge_run.error
    assert await governed.run_store.list_eval_scores(record.run_id) == []
