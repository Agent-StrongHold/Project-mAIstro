"""LLM hyper-mutator: guided, evidence-based mutation of the typed FixerGenome.

Where ``mutate.mutate_fixer_genome`` flips enums and jitters floats at random,
this module is the *guided* alternative (the "hyperagent"/intelligent-design step
from the DAG optimizer lineage): a meta-LLM reviews the genome's current slots,
its lineage's scores (OPRO-style worst→best so the trajectory is visible), the
operator's goal, and user preferences — then proposes new **typed slot values as
JSON**. Because the genome is structured (see ``fixer_genome``), the mutator can
write a concrete lesson into ``learned_successes`` / ``learned_failures`` instead
of rewriting one undifferentiated prompt blob and hoping the right part changed.

Discipline mirrors ``reflect.reflective_improve`` (GEPA-style propose-then-verify):
- the parent is never mutated in place — an accepted challenger joins the
  population as its child, lineage preserved;
- a challenger is accepted only if it verifiably beats the parent's score on the
  target benchmark (plus ``accept_margin``);
- stub-only verification is refused (SPEC-202 signal honesty — never accept a
  candidate scored by noise).

One deliberate cost divergence from reflect: the parent's *stored* benchmark
score is used as the baseline instead of re-evaluating it. ``code_rsi`` — the
benchmark fixer populations evolve against — costs a full agent run plus the
fitness scorecard per evaluation, so re-scoring the baseline every proposal
round would double both cost and (agent-nondeterminism) noise.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ValidationError

from .fixer_genome import FixerGenome, render_system_prompt, to_prompt_payload
from .harness import EvalHarness
from .types import NodeGenome, PipelineGenome

# Slot-space search tips — one per candidate diversifies the proposals (the
# MIPROv2 trick reflect.PROPOSAL_TIPS uses for free-text prompts).
HYPER_TIPS: list[str] = [
    "Change one enum and write one concrete lesson into learned_failures; keep the floats.",
    "Adjust the float dials (tdd_rigor/minimalism/ambition/edge_focus); leave the enums alone.",
    "Rewrite learned_successes and learned_failures from the evidence; change nothing else.",
    "Try a different test_style and raise tdd_rigor.",
    "Be bold: change several slots at once toward what the best ancestor did.",
]

_FLOAT_SLOTS = ("minimalism", "ambition", "edge_focus", "tdd_rigor")
_MAX_LINEAGE_HOPS = 10


class HyperMutationOutcome(BaseModel):
    """What one hyper-mutation attempt did — the auditable record."""

    benchmark: str
    baseline_score: float
    candidate_count: int = 0
    best_candidate_score: float | None = None
    best_candidate_slots: dict[str, Any] | None = None
    accepted: bool = False
    challenger_id: str | None = None
    reason: str | None = None
    challenger: PipelineGenome | None = None

    def summary(self) -> dict[str, Any]:
        return self.model_dump(exclude={"challenger"})


def entry_node(genome: PipelineGenome) -> NodeGenome | None:
    for node in genome.topology.nodes:
        if node.id == genome.topology.entry_node:
            return node
    return genome.topology.nodes[0] if genome.topology.nodes else None


def slot_lineage(
    genome: PipelineGenome, all_genomes: Sequence[PipelineGenome]
) -> list[tuple[dict[str, Any], float]]:
    """(fixer slot payload, fitness) for the genome's ancestors, worst→best.

    Walks ``parent_a_id`` up to a bounded depth; ancestors without a fixer or a
    fitness score are skipped. Sorted worst→best so the meta-prompt shows the
    trajectory OPRO-style (the LLM sees what improved and avoids reversions).
    """
    by_id = {g.id: g for g in all_genomes}
    out: list[tuple[dict[str, Any], float]] = []
    current = genome.parent_a_id
    for _ in range(_MAX_LINEAGE_HOPS):
        if current is None or current not in by_id:
            break
        ancestor = by_id[current]
        node = entry_node(ancestor)
        if node is not None and node.fixer is not None and ancestor.fitness_score is not None:
            out.append((to_prompt_payload(node.fixer), ancestor.fitness_score))
        current = ancestor.parent_a_id
    out.sort(key=lambda pair: pair[1])
    return out


_SCHEMA_TEXT = (
    "Schema (every field optional — an omitted field keeps its current value):\n"
    "  strategy: one of react|plan_execute|direct\n"
    "  test_style: one of characterization|strict_tdd|property_based\n"
    "  review_pass: one of none|self_review|critic\n"
    "  risk: one of conservative|balanced|bold\n"
    "  reasoning_effort: one of low|medium|high, or null (non-reasoning model)\n"
    "  temperature: float 0..2, or null\n"
    "  minimalism, ambition, edge_focus, tdd_rigor: float 0..1\n"
    "  persona, strategy_hint, goals, codebase_standards, learned_successes, "
    "learned_failures: short strings"
)


def build_hyper_prompt(
    fixer: FixerGenome,
    benchmark: str,
    score: float,
    tip: str,
    *,
    lineage: Sequence[tuple[dict[str, Any], float]] = (),
    goal: str = "",
    preferences: str = "",
    history: Sequence[tuple[str, float]] = (),
) -> str:
    """The grounded meta-prompt: current slots + score + lineage + goal → new slots."""
    parts = [
        "You are the hyper-mutator for an evolving population of code-fixing agents. "
        "Each agent's strategy is a typed genome; you review the evidence and propose "
        "a better genome — guided design, not random mutation.",
        f"## Goal\n{goal or 'Maximize the ' + benchmark + ' score: accepted, high-composite code fixes.'}",
    ]
    if preferences:
        parts.append(f"## Operator preferences\n{preferences}")
    parts.append(f"## Current genome (JSON)\n{json.dumps(to_prompt_payload(fixer), indent=2)}")
    parts.append(f"## Evidence\nCurrent score on {benchmark}: {score:.3f}")
    if lineage:
        lines = "\n".join(f"  score={s:.3f}  {json.dumps(p)}" for p, s in lineage)
        parts.append(f"## Ancestor genomes (worst → best)\n{lines}")
    if history:
        lines = "\n".join(
            f"  score={s:.3f}  {excerpt}" for excerpt, s in sorted(history, key=lambda h: h[1])
        )
        parts.append(f"## Prior proposals for this genome (worst → best)\n{lines}")
    parts.append(_SCHEMA_TEXT)
    parts.append(
        "First diagnose why the current genome scores as it does. Then reply with ONLY a "
        "JSON object containing the fields you want to change. Ground learned_successes / "
        f"learned_failures in the evidence above — concrete lessons, not platitudes. Tip: {tip}"
    )
    return "\n\n".join(parts)


def _extract_json_object(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return data if isinstance(data, dict) else None


def parse_fixer_proposal(text: str, base: FixerGenome) -> FixerGenome | None:
    """Merge an LLM's partial slot proposal onto ``base``; None if unusable.

    Lenient where it's safe (unknown keys dropped, floats clamped into range,
    code fences tolerated) and strict where it matters (a bad enum value fails
    pydantic validation → the whole proposal is rejected — the tip-diversified
    sibling proposals are the retry mechanism). A proposal that changes nothing
    is treated as unusable too: evaluating an identical genome wastes a run.
    """
    data = _extract_json_object(text)
    if data is None:
        return None
    known = set(FixerGenome.model_fields)
    update = {k: v for k, v in data.items() if k in known}
    if not update:
        return None
    for slot in _FLOAT_SLOTS:
        if slot in update and isinstance(update[slot], (int, float)):
            update[slot] = max(0.0, min(1.0, float(update[slot])))
    if "temperature" in update and isinstance(update["temperature"], (int, float)):
        update["temperature"] = max(0.0, min(2.0, float(update["temperature"])))
    try:
        candidate = FixerGenome.model_validate({**base.model_dump(), **update})
    except ValidationError:
        return None
    return None if candidate == base else candidate


def spawn_fixer_challenger(genome: PipelineGenome, new_fixer: FixerGenome) -> PipelineGenome:
    """A child genome carrying ``new_fixer`` on its entry node — parent untouched.

    The entry node's ``system_prompt`` is re-rendered from the new slots so the
    visible prompt and the typed genome can never drift apart.
    """
    child = genome.model_copy(deep=True)
    now = datetime.now(UTC).isoformat()
    child.id = uuid.uuid4().hex[:12]
    child.name = f"hyper-{genome.id[:6]}"
    child.generation = genome.generation + 1
    child.parent_a_id = genome.id
    child.parent_b_id = None
    child.fitness_score = None
    child.eval_scores = {}
    child.harness_params = {"origin": "hyper_mutator"}
    child.created_at = now
    child.updated_at = now
    for node in child.topology.nodes:
        if node.id == child.topology.entry_node:
            node.fixer = new_fixer
            node.system_prompt = render_system_prompt(new_fixer)
            break
    return child


def _weakest(genome: PipelineGenome, benchmarks: list[str] | None) -> str | None:
    scores = {b: s for b, s in genome.eval_scores.items() if benchmarks is None or b in benchmarks}
    return min(scores, key=lambda b: scores[b]) if scores else None


async def propose_fixer_candidates(
    fixer: FixerGenome,
    benchmark: str,
    score: float,
    llm_call: Any,
    num_candidates: int,
    *,
    lineage: Sequence[tuple[dict[str, Any], float]] = (),
    goal: str = "",
    preferences: str = "",
    history: Sequence[tuple[str, float]] = (),
) -> list[FixerGenome]:
    """Ask the meta-LLM for up to ``num_candidates`` distinct slot proposals."""
    import random

    if num_candidates <= len(HYPER_TIPS):
        tips = random.sample(HYPER_TIPS, num_candidates)
    else:
        tips = HYPER_TIPS + [
            random.choice(HYPER_TIPS) for _ in range(num_candidates - len(HYPER_TIPS))
        ]
    candidates: list[FixerGenome] = []
    for tip in tips:
        prompt = build_hyper_prompt(
            fixer,
            benchmark,
            score,
            tip,
            lineage=lineage,
            goal=goal,
            preferences=preferences,
            history=history,
        )
        try:
            raw = await llm_call(prompt)
        except Exception:
            continue
        candidate = parse_fixer_proposal(str(raw), fixer)
        if candidate is not None and candidate not in candidates:
            candidates.append(candidate)
    return candidates


async def hyper_mutate(
    genome: PipelineGenome,
    harness: EvalHarness,
    llm_call: Any,
    *,
    benchmarks: list[str] | None = None,
    num_candidates: int = 2,
    accept_margin: float = 0.0,
    lineage: Sequence[tuple[dict[str, Any], float]] = (),
    goal: str = "",
    preferences: str = "",
    history: Sequence[tuple[str, float]] = (),
) -> HyperMutationOutcome | None:
    """Propose→verify one round of guided slot mutation for ``genome``.

    Returns None when the genome has no typed fixer, no usable LLM, or no stored
    score to serve as the baseline (the caller evaluates populations before
    self-improvement, so a scored genome is the normal case).
    """
    node = entry_node(genome)
    if llm_call is None or node is None or node.fixer is None:
        return None
    bench = _weakest(genome, benchmarks)
    if bench is None:
        return None
    baseline = genome.eval_scores[bench]

    candidates = await propose_fixer_candidates(
        node.fixer,
        bench,
        baseline,
        llm_call,
        num_candidates,
        lineage=lineage,
        goal=goal,
        preferences=preferences,
        history=history,
    )

    best_challenger: PipelineGenome | None = None
    best_score: float | None = None
    best_slots: dict[str, Any] | None = None
    for candidate in candidates:
        challenger = spawn_fixer_challenger(genome, candidate)
        results = await harness.evaluate_genome(challenger, [bench], llm_call)
        if not results:
            continue
        if results[0].metadata.get("stub"):
            # SPEC-202 honesty: a stub score is noise — never verify against it.
            continue
        score = results[0].score
        challenger.eval_scores[bench] = score
        if best_score is None or score > best_score:
            best_challenger, best_score, best_slots = (
                challenger,
                score,
                to_prompt_payload(candidate),
            )

    accepted = best_score is not None and best_score > baseline + accept_margin
    return HyperMutationOutcome(
        benchmark=bench,
        baseline_score=baseline,
        candidate_count=len(candidates),
        best_candidate_score=best_score,
        best_candidate_slots=best_slots,
        accepted=accepted,
        challenger_id=best_challenger.id if accepted and best_challenger else None,
        reason=None if accepted else "no_candidate_beat_baseline",
        challenger=best_challenger if accepted else None,
    )
