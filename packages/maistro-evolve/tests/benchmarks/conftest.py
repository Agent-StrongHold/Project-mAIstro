from __future__ import annotations

from datetime import UTC, datetime

import pytest

from maistro_evolve.types import DAGTopology, EvalWeights, NodeGenome, PipelineGenome


def make_genome(
    system_prompt: str = "You are a helpful AI assistant.",
    model: str = "gpt-4",
    temperature: float = 0.3,
    max_tokens: int = 4096,
) -> PipelineGenome:
    return PipelineGenome(
        id="bench-g1",
        name="bench-test",
        topology=DAGTopology(
            nodes=[
                NodeGenome(
                    id="q1",
                    role="queen",
                    strategy="react",
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    system_prompt=system_prompt,
                    max_tool_rounds=5,
                )
            ],
            edges=[],
            entry_node="q1",
            max_cycles=3,
            beam_width=1,
            use_scout=False,
        ),
        eval_weights=EvalWeights(),
        created_at=datetime.now(UTC).isoformat(),
        updated_at=datetime.now(UTC).isoformat(),
    )


def make_empty_genome() -> PipelineGenome:
    """A genome with no topology nodes, exercising prompt_builder's fallback branch."""
    return PipelineGenome(
        id="bench-empty",
        name="bench-empty",
        topology=DAGTopology(
            nodes=[],
            edges=[],
            entry_node="none",
            max_cycles=1,
            beam_width=1,
            use_scout=False,
        ),
        eval_weights=EvalWeights(),
        created_at=datetime.now(UTC).isoformat(),
        updated_at=datetime.now(UTC).isoformat(),
    )


@pytest.fixture
def genome() -> PipelineGenome:
    return make_genome()


@pytest.fixture
def empty_genome() -> PipelineGenome:
    return make_empty_genome()
