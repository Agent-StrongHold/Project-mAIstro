from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from maistro_evolve.serialize import (
    from_json,
    from_yaml,
    load_json,
    load_yaml,
    save_json,
    save_yaml,
    to_json,
    to_yaml,
)
from maistro_evolve.types import DAGTopology, EvalWeights, NodeGenome, PipelineGenome


def _genome() -> PipelineGenome:
    return PipelineGenome(
        id="test-g1",
        name="test",
        topology=DAGTopology(
            nodes=[
                NodeGenome(
                    id="q1",
                    role="queen",
                    strategy="react",
                    model="gpt-4",
                    temperature=0.3,
                    max_tokens=4096,
                    system_prompt="test",
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
        eval_scores={"proxy_ifeval": 0.5},
        harness_params={"k": "v"},
        generation=2,
        parent_a_id="p1",
        parent_b_id="p2",
        created_at=datetime.now(UTC).isoformat(),
        updated_at=datetime.now(UTC).isoformat(),
    )


def test_to_yaml_and_from_yaml_roundtrip() -> None:
    genome = _genome()
    text = to_yaml(genome)
    restored = from_yaml(text)
    assert restored == genome


def test_to_json_and_from_json_roundtrip() -> None:
    genome = _genome()
    text = to_json(genome)
    restored = from_json(text)
    assert restored == genome


def test_save_yaml_and_load_yaml_roundtrip_and_creates_parent_dirs(tmp_path: Path) -> None:
    genome = _genome()
    path = tmp_path / "nested" / "genome.yaml"
    save_yaml(genome, path)
    assert path.exists()
    assert load_yaml(path) == genome


def test_save_json_and_load_json_roundtrip_and_creates_parent_dirs(tmp_path: Path) -> None:
    genome = _genome()
    path = tmp_path / "nested" / "genome.json"
    save_json(genome, path)
    assert path.exists()
    assert load_json(path) == genome


def test_to_yaml_uses_block_style_not_flow_style() -> None:
    genome = _genome()
    text = to_yaml(genome)
    assert "id: test-g1" in text
    assert "{" not in text
