"""Canvas/Davinci DAG — visual generation pipeline as optimizable nodes.

Pipeline: Style Interpreter → Composition Planner → Generator → Compositor → Critic → Refiner → Store

Each node is an LLM call that can be hill-climbed:
  - Style Interpreter: prompt engineering target
  - Generator: model selection target
  - Critic: eval-as-judge for visual quality
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from maistro.capabilities.model_chat import ModelChatRequest

CANVAS_DAG = {
    "id": "canvas_davinci",
    "name": "Canvas/Davinci Visual Pipeline",
    "department": "creative_visual",
    "description": "Multi-stage image generation with style interpretation, composition, and quality refinement",
    "nodes": [
        {
            "id": "style_interpreter",
            "prompt": "Interpret the visual style request into precise art direction: color palette (hex codes), mood, lighting, composition rules, reference artists/movements, and texture notes. Request: {input}",
            "model": "claude-opus-4-6",
            "role": "art_director",
            "optimizable": ["prompt", "model"],
        },
        {
            "id": "composition_planner",
            "prompt": "Plan the image composition: layout grid, focal point placement (rule of thirds), depth layers (foreground/mid/background), negative space usage, and visual hierarchy. Style direction: {style_interpreter}",
            "model": "claude-opus-4-6",
            "role": "compositor",
            "optimizable": ["prompt"],
        },
        {
            "id": "generator",
            "prompt": "Generate a detailed image description that an image model could render. Include every visual element, their exact positions, colors, lighting, and textures. Composition plan: {composition_planner}\nStyle: {style_interpreter}",
            "model": "gemini-3.5-pro",
            "role": "generator",
            "optimizable": ["model", "prompt"],
        },
        {
            "id": "compositor",
            "prompt": "Layer the generated elements: specify z-order, blending modes, opacity for each layer, shadow/highlight placement, and edge treatment between layers. Elements: {generator}",
            "model": "claude-opus-4-6",
            "role": "compositor",
            "optimizable": ["prompt"],
        },
        {
            "id": "critic",
            "prompt": 'Score this visual output 0-100 on: composition (25), color harmony (25), style adherence (25), technical quality (25). Identify the single biggest improvement. Output JSON: {"score": int, "composition": int, "color": int, "style": int, "technical": int, "improvement": str}. Image description: {compositor}',
            "model": "gemini-3.5-pro",
            "role": "critic",
            "optimizable": ["prompt"],
        },
        {
            "id": "refiner",
            "prompt": "Apply the critic's feedback to refine the image description. Make the specific improvement suggested while preserving what scored well. Original: {compositor}\nCritique: {critic}",
            "model": "claude-opus-4-6",
            "role": "refiner",
            "optimizable": ["prompt", "model"],
        },
    ],
    "edges": [
        {"from_node": "style_interpreter", "to_node": "composition_planner"},
        {"from_node": "style_interpreter", "to_node": "generator"},
        {"from_node": "composition_planner", "to_node": "generator"},
        {"from_node": "generator", "to_node": "compositor"},
        {"from_node": "compositor", "to_node": "critic"},
        {"from_node": "compositor", "to_node": "refiner"},
        {"from_node": "critic", "to_node": "refiner"},
    ],
    "evals": ["visual_quality"],
}


class VisualQualityEgress(Protocol):
    async def complete(
        self,
        *,
        context: dict[str, str],
        request: ModelChatRequest,
        response_validator: Callable[[Any], object] | None = None,
    ) -> Any: ...


def _parse_visual_quality_result(result: Any) -> dict[str, Any]:
    body = getattr(result, "body", None)
    if not isinstance(body, dict):
        raise ValueError("visual quality provider returned no response body")
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("visual quality provider returned no message content") from exc
    if not isinstance(content, str):
        raise ValueError("visual quality provider returned non-text message content")
    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        raise ValueError("visual quality response must be a JSON object")
    return parsed


async def visual_quality_eval(
    output: str,
    context: dict[str, Any] | None = None,
    *,
    egress: VisualQualityEgress | None = None,
) -> dict[str, Any]:
    """Score a Canvas output through an injected governed model egress.

    Prompt construction and response parsing stay Canvas behavior. A missing
    egress or execution context is an unavailable evaluation, never a score.
    """
    if egress is None:
        raise RuntimeError("Canvas visual evaluation has no governed model egress")
    if context is None:
        raise RuntimeError("Canvas visual evaluation requires canonical execution context")

    judge_prompt = (
        "You are a visual quality judge. Score this image description on a 0-100 scale.\n"
        "Criteria:\n"
        "- Composition clarity (25 pts): Is the layout well-organized with clear focal point?\n"
        "- Color coherence (25 pts): Do colors work together harmoniously?\n"
        "- Style consistency (25 pts): Does it maintain a unified artistic style?\n"
        "- Detail richness (25 pts): Are textures, lighting, and depth well-described?\n\n"
        'Reply with JSON only: {"score": int, "composition": int, "color": int, "style": int, "detail": int, "rationale": str}'
    )
    parsed: dict[str, Any] | None = None

    def validate(result: Any) -> dict[str, Any]:
        nonlocal parsed
        parsed = _parse_visual_quality_result(result)
        return parsed

    await egress.complete(
        context={key: str(value) for key, value in context.items()},
        request=ModelChatRequest(
            model="claude-opus-4-6",
            messages=[
                {"role": "system", "content": judge_prompt},
                {
                    "role": "user",
                    "content": f"Image description to judge:\n\n{output[:3000]}",
                },
            ],
            temperature=0.0,
        ),
        response_validator=validate,
    )
    assert parsed is not None  # The validator runs before the egress settles success.
    return parsed


class CanvasHillClimber:
    """Hill-climb the Canvas DAG by mutating style interpreter prompts and generator model."""

    def __init__(self, *, egress: VisualQualityEgress | None = None):
        self._egress = egress
        self.best_score = 0
        self.best_config: dict[str, Any] = {}
        self.history: list[dict[str, Any]] = []

    async def run_pass(
        self,
        input_text: str,
        run_dag: Callable[[dict, str], Awaitable[dict[str, Any]]],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run one optimization pass: execute DAG, eval, propose mutation."""
        dag = CANVAS_DAG.copy()
        result = await run_dag(dag, input_text)

        # Get the final output (refiner node)
        final_output = result.get("node_results", {}).get("refiner", {}).get("output", "")
        eval_result = await visual_quality_eval(
            final_output,
            context=context,
            egress=self._egress,
        )
        score = eval_result.get("score", 0)

        pass_record = {
            "score": score,
            "eval": eval_result,
            "improved": score > self.best_score,
        }

        if score > self.best_score:
            self.best_score = score
            self.best_config = {"dag": dag, "score": score}

        self.history.append(pass_record)
        return pass_record
