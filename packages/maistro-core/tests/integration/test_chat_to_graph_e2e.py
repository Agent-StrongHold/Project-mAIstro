"""Algorithm-only coverage for the pre-durable chat-to-Graph preparation path.

This fixture intentionally stops before physical Graph execution. The durable
Graph executor owns Run/NodeRun/Attempt evidence; this test only verifies that
classification, spec emission, and agent spawning still compose without
reintroducing the retired ``GraphRun`` convenience path.
"""

from __future__ import annotations

from typing import Any

from maistro.agents.spawner.spawner import Spawner
from maistro.agents.spec.agent_spec import AgentOutput, AgentSpec
from maistro.agents.spec.agent_spec import AgentRole as SpawnerAgentRole
from maistro.builders.spec_emitter import emit_spec
from maistro.classifier.engine import ClassifierEngine
from maistro.testing.faux_provider import FauxProvider, FauxResponse
from maistro.testing.harness import create_test_environment
from maistro.types.config import TaskTypeConfig
from maistro.types.spec import Spec, SpecStatus

CODING_KEYWORDS = ["implement", "function", "code", "write"]


class _SpawnerLLMCaller:
    """Adapt the harness provider to the spawner's LLMCaller protocol."""

    def __init__(self, provider: FauxProvider) -> None:
        self._provider = provider

    async def call(
        self,
        system: str,
        user: str,
        *,
        model: str,
        temperature: float,
        max_tokens: int,
        tier: int,
        lane: str,
    ) -> dict[str, Any]:
        response = await self._provider.complete(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            model=model,
            temperature=temperature,
        )
        choice = response["choices"][0]
        return {
            "content": choice["message"]["content"],
            "model": response["model"],
            "usage": response["usage"],
        }


def _task_types() -> dict[str, TaskTypeConfig]:
    return {
        "code": TaskTypeConfig(
            keywords=CODING_KEYWORDS,
            min_tier="small",
            preferred_strengths=["coding"],
        ),
        "chat": TaskTypeConfig(keywords=[], min_tier="small", preferred_strengths=["chat"]),
    }


async def test_chat_to_graph_preparation_stops_before_physical_execution() -> None:
    env = create_test_environment()
    intent = await env.classifier.classify(
        messages=[
            {"role": "user", "content": "Please implement this function that adds two numbers."}
        ],
        task_types=_task_types(),
    )

    assert isinstance(env.classifier, ClassifierEngine)
    assert intent.task_type == "code"
    assert intent.classified_by == "keywords"

    spec = emit_spec(
        issue_number=1,
        title="Add two-number addition function",
        body="- Function must accept two numeric arguments\n- Function must return their sum\n",
        complexity="simple",
        files_touched=["src/maistro/protocols/math_ops.py"],
    )
    assert isinstance(spec, Spec)
    assert spec.status == SpecStatus.ACTIVE
    assert spec.acceptance_criteria == (
        "Function must accept two numeric arguments",
        "Function must return their sum",
    )

    env.provider.seed(
        FauxResponse(
            content='{"files_changed": ["src/maistro/protocols/math_ops.py"], '
            '"description": "Implemented add()", "tests_added": true}'
        )
    )
    agent_spec = AgentSpec(
        role=SpawnerAgentRole.CODER,
        task_id="task-1",
        subtask_id="sub-1",
        description=spec.acceptance_criteria[0],
        context={"layer0": "You implement code that satisfies a Spec."},
    )
    output = await Spawner(llm_caller=_SpawnerLLMCaller(env.provider)).spawn(agent_spec)

    assert isinstance(output, AgentOutput)
    assert output.success is True
    assert output.agent_id == agent_spec.agent_id
    assert output.output_parsed == {
        "files_changed": ["src/maistro/protocols/math_ops.py"],
        "description": "Implemented add()",
        "tests_added": True,
    }
    assert env.provider.call_count == 1
