"""End-to-end smoke test for UX flow 1: chat-builds-graph.

A single simulated chat turn flows through every real, wired-together
component in the "chat builds and runs an agent" path:

    classifier (ClassifierEngine)
        -> spec emission (builders.spec_emitter.emit_spec) — the orchestrator's
           decompose stage equivalent: turns the classified request into a
           machine-checkable Spec with acceptance criteria/invariants
        -> spawner (agents.spawner.Spawner) — instantiates a single agent
           (the "new agent spec" emitted for the request) and runs it once
           through the LLM boundary
        -> graph executor (graph.run.GraphRun) — runs the resulting
           planner -> coder -> reviewer graph to completion

Only the LLM boundary is stubbed, via maistro.testing.FauxProvider /
create_test_environment(). Every other component (Container, ClassifierEngine,
RouterEngine, Spawner, GraphRun, spec_emitter) is the real production class —
this test exercises the actual call chain, not mocks of internal seams.
"""

from __future__ import annotations

from typing import Any

import pytest

from maistro.agents.spawner.spawner import Spawner
from maistro.agents.spec.agent_spec import AgentOutput, AgentSpec
from maistro.agents.spec.agent_spec import AgentRole as SpawnerAgentRole
from maistro.builders.spec_emitter import emit_spec
from maistro.classifier.engine import ClassifierEngine
from maistro.graph.phases import GraphPhase, NodePhase
from maistro.testing.faux_provider import FauxProvider, FauxResponse, code_output, review_output
from maistro.testing.harness import create_test_environment
from maistro.types.config import TaskTypeConfig
from maistro.types.spec import Spec, SpecStatus

CODING_KEYWORDS = ["implement", "function", "code", "write"]


class _SpawnerLLMCaller:
    """Adapts FauxProvider's chat-completion interface to Spawner's LLMCaller
    protocol (a single `.call(system, user, *, model, temperature, max_tokens,
    tier, lane)` -> dict with `content`/`model`/`usage`)."""

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
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        resp = await self._provider.complete(messages, model=model, temperature=temperature)
        choice = resp["choices"][0]
        return {
            "content": choice["message"]["content"],
            "model": resp["model"],
            "usage": resp["usage"],
        }


@pytest.fixture
def task_types() -> dict[str, TaskTypeConfig]:
    # "code" is the canonical task-type name recognized by the keyword
    # classifier's STRONG_INDICATORS table (classifier/keyword.py); phrases
    # like "implement this" / "write a function" score +3.0 there.
    return {
        "code": TaskTypeConfig(
            keywords=CODING_KEYWORDS,
            min_tier="small",
            preferred_strengths=["coding"],
        ),
        "chat": TaskTypeConfig(keywords=[], min_tier="small", preferred_strengths=["chat"]),
    }


class TestChatToGraphE2E:
    """Single path: classify -> emit spec -> spawn agent -> run graph."""

    async def test_full_chat_to_graph_pipeline(self, task_types: dict[str, TaskTypeConfig]) -> None:
        # --- Step 1: a real chat turn through the real classifier -------------
        env = create_test_environment()
        classifier = env.classifier
        assert isinstance(classifier, ClassifierEngine)

        user_message = "Please implement this function that adds two numbers."
        intent = await classifier.classify(
            messages=[{"role": "user", "content": user_message}],
            task_types=task_types,
        )

        assert intent.task_type == "code"
        assert intent.classified_by == "keywords"
        assert intent.keyword_score >= 3.0

        # --- Step 2: orchestrator-equivalent decompose -> spec emission -------
        spec = emit_spec(
            issue_number=1,
            title="Add two-number addition function",
            body=(
                "- Function must accept two numeric arguments\n- Function must return their sum\n"
            ),
            complexity="simple",
            files_touched=["src/maistro/protocols/math_ops.py"],
        )
        assert isinstance(spec, Spec)
        assert spec.status == SpecStatus.ACTIVE
        assert spec.complexity == "S"
        assert spec.acceptance_criteria == (
            "Function must accept two numeric arguments",
            "Function must return their sum",
        )
        assert len(spec.invariants) == 2
        assert spec.protocols_touched == ("math_ops",)

        # --- Step 3: spawner instantiates a new agent for the spec ------------
        caller = _SpawnerLLMCaller(env.provider)
        spawner = Spawner(llm_caller=caller)

        env.provider.seed(
            FauxResponse(
                content='{"files_changed": ["src/maistro/protocols/math_ops.py"], '
                '"description": "Implemented add()", "tests_added": true}',
                usage_prompt_tokens=12,
                usage_completion_tokens=18,
                model="faux://test-model",
            )
        )

        agent_spec = AgentSpec(
            role=SpawnerAgentRole.CODER,
            task_id="task-1",
            subtask_id="sub-1",
            description=spec.acceptance_criteria[0],
            context={"layer0": "You implement code that satisfies a Spec."},
        )
        output = await spawner.spawn(agent_spec)

        assert isinstance(output, AgentOutput)
        assert output.success is True
        assert output.agent_id == agent_spec.agent_id
        assert output.role == SpawnerAgentRole.CODER
        assert output.output_parsed == {
            "files_changed": ["src/maistro/protocols/math_ops.py"],
            "description": "Implemented add()",
            "tests_added": True,
        }
        # Spawned call recorded against the same FauxProvider used by the graph run.
        assert env.provider.call_count == 1
        spawn_call = env.provider.last_call()
        assert spawn_call is not None
        assert spawn_call["messages"][1]["content"] == f"## Task\n{agent_spec.description}"

        # --- Step 4: graph executor runs the resulting planner/coder/reviewer
        #             graph to completion through the same provider -----------
        env.provider.seed(
            FauxResponse(
                content='{"summary": "Add two-number addition function", '
                '"subtasks": [{"title": "add()", "description": "implement add", '
                '"file_paths": ["src/maistro/protocols/math_ops.py"]}], '
                '"estimated_files": ["src/maistro/protocols/math_ops.py"]}'
            ),
            code_output(
                files_changed=["src/maistro/protocols/math_ops.py"],
                description="Implemented add()",
                tests_added=True,
            ),
            review_output(approved=True, score=9.0),
        )

        result = await env.run_graph(
            task_description="implement add(a, b) -> a + b", workspace="/tmp"
        )

        assert env.graph_run.phase == GraphPhase.COMPLETED
        assert result.success is True
        assert all(nr.phase == NodePhase.SUCCEEDED for nr in env.graph_run.node_runs)
        assert result.plan is not None
        assert result.plan.summary == "Add two-number addition function"
        assert result.code is not None
        assert result.code.files_changed == ["src/maistro/protocols/math_ops.py"]
        assert result.review is not None
        assert result.review.approved is True
        assert result.review.score == 9.0
        assert result.final_answer == "Task completed. Review score: 9.0/10."

        roles_run = {nr.role.value for nr in env.graph_run.node_runs}
        assert roles_run == {"planner", "coder", "reviewer"}
        types_seen = {e.type for e in env.events}
        assert "graph_started" in types_seen
        assert "graph_completed" in types_seen

        # Total LLM calls across the whole chat-to-graph path: 1 spawn + 3 graph nodes.
        assert env.provider.call_count == 4

    async def test_pipeline_propagates_graph_failure(
        self, task_types: dict[str, TaskTypeConfig]
    ) -> None:
        """Negative branch: if the graph's review rejects, the result reports
        failure and the conditional edge does NOT advance past review."""
        env = create_test_environment()
        intent = await env.classifier.classify(
            messages=[{"role": "user", "content": "implement this broken function"}],
            task_types=task_types,
        )
        assert intent.task_type == "code"

        spec = emit_spec(issue_number=2, title="Broken impl", body="- must work\n")
        assert spec.acceptance_criteria == ("must work",)

        env.provider.seed(
            FauxResponse(content='{"summary": "plan", "subtasks": [], "estimated_files": []}'),
            code_output(files_changed=["broken.py"], description="broken", tests_added=False),
            review_output(approved=False, score=2.0, issues=["fails tests"]),
        )

        result = await env.run_graph(task_description="implement a broken function")

        assert env.graph_run.phase == GraphPhase.COMPLETED
        # Node-level execution succeeded (the LLM call itself didn't error),
        # but the *business* outcome carried by the review is a rejection.
        assert result.review is not None
        assert result.review.approved is False
        assert result.final_answer == "Review not approved (score: 2.0/10): fails tests"
