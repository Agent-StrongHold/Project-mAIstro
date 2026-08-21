"""The evolvable RSI fixer strategy genome — a typed "mad-lib" (ADR-070126-6386 v2).

Layered ON TOP of the fixed, per-``ImprovementKind`` task scaffold that
``maistro_rsi.local_loop._fixer_objective`` builds — the scaffold says WHAT to do
and WHEN it's allowed to be ambitious (a FEATURE slot unlocks the big budget); this
genome tunes HOW an agent approaches that task. It never touches the task contract
(test-first discipline, "only this module and its test file", etc.), only the
strategy layered around it, so mutating it can't break the loop's safety rails.

Sixteen slots, three shapes, so a hyper-mutator can propose one coherent revision
at a time instead of rewriting free text and hoping the LLM changed the right
thing (see ``reflect.py`` for the analogous free-text predecessor this extends):

- **enums** — categorical approach choices (``strategy``, ``test_style``,
  ``review_pass``, ``risk``, ``reasoning_effort``).
- **floats** — continuous dials in [0, 1] (``temperature``, ``minimalism``,
  ``ambition``, ``edge_focus``, ``tdd_rigor``).
- **text / memory** — free-form, typically LLM-authored by the hyper-mutator from
  lineage evidence rather than randomized (``persona``, ``strategy_hint``,
  ``goals``, ``codebase_standards``, ``learned_successes``, ``learned_failures``).
  These are the hyper-mutator's canvas: it reviews scores/outcomes across a
  lineage and *writes* what it learned into these specific fields, instead of
  rewriting one undifferentiated prompt blob and hoping the right part changed.

``tdd_rigor`` is distinct from ``test_style``: ``test_style`` picks *what kind* of
test to prefer (characterization / strict red-green / property-based);
``tdd_rigor`` sets *how insistent* the agent is about writing — and strengthening
— tests at all, from pragmatic ("ship the fix, backfill coverage later") to
maximalist ("always test-first, chase coverage and assertion strength hard").

``reasoning_effort`` vs. ``temperature``: reasoning models (o-series, GPT-5,
Gemini-2.5-thinking, DeepSeek-R1, …) take a ``reasoning_effort`` level in place of
temperature/top_p/top_k (and partially max_tokens) — and typically *reject* an
explicit temperature outright. Non-reasoning models (the `code` group's Mistral
models today) still take temperature. Both fields are carried on the genome; the
LLM callable sends whichever is set, preferring ``reasoning_effort`` — see
``maistro_bootstrap.builders.responses_callable.LiteLLMCallable``.
"""

from __future__ import annotations

import json
import random
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class FixerStrategy(StrEnum):
    REACT = "react"
    PLAN_EXECUTE = "plan_execute"
    DIRECT = "direct"


class TestStyle(StrEnum):
    CHARACTERIZATION = "characterization"
    STRICT_TDD = "strict_tdd"
    PROPERTY_BASED = "property_based"


class ReviewPass(StrEnum):
    NONE = "none"
    SELF_REVIEW = "self_review"
    CRITIC = "critic"


class RiskLevel(StrEnum):
    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    BOLD = "bold"


class ReasoningEffort(StrEnum):
    """Reasoning-effort levels, forwarded as-is by the LiteLLM gateway.

    Deliberately the portable low/medium/high subset: OpenAI additionally accepts
    'minimal', but other reasoning providers validate the value server-side and
    reject it (Cerebras 400s: "Input should be 'none', 'low', 'medium' or
    'high'") — caught live when a randomly-seeded genome drew 'minimal' against a
    mixed model group. Non-reasoning deployments in a group are covered by the
    gateway's drop_params, which silently drops the whole parameter for them.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class FixerGenome(BaseModel):
    """The typed strategy layer an RSI fixer competitor runs with."""

    strategy: FixerStrategy = FixerStrategy.DIRECT
    test_style: TestStyle = TestStyle.CHARACTERIZATION
    review_pass: ReviewPass = ReviewPass.NONE
    risk: RiskLevel = RiskLevel.BALANCED
    # None ⇒ this competitor's model isn't (or isn't known to be) a reasoning
    # model; the callable falls back to ``temperature``.
    reasoning_effort: ReasoningEffort | None = None

    # Legacy/non-reasoning-model dial. Ignored by the callable whenever
    # reasoning_effort is set (sending both 400s on reasoning models).
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    minimalism: float = Field(default=0.7, ge=0.0, le=1.0)
    ambition: float = Field(default=0.3, ge=0.0, le=1.0)
    edge_focus: float = Field(default=0.3, ge=0.0, le=1.0)
    # 0 = pragmatic ("ship the fix, backfill coverage later"), 1 = maximalist
    # ("always test-first; chase coverage and assertion strength hard"). Distinct
    # from test_style (which picks the KIND of test, not how insistently to write
    # or strengthen one) — maps onto the new_test/coverage/assertion_strength
    # fitness signals (see candidate_fitness.py) this dial should lean into.
    tdd_rigor: float = Field(default=0.5, ge=0.0, le=1.0)

    persona: str = "a meticulous, pragmatic software engineer"
    strategy_hint: str = ""
    # Memory slots — the hyper-mutator's canvas (W6): it reviews lineage
    # scores/outcomes and *writes* what it learned into these specific fields,
    # rather than rewriting one undifferentiated prompt and hoping the right part
    # changed. Left blank ("") by default/random seeding; only lineage evolution
    # populates them with real evidence.
    goals: str = ""
    codebase_standards: str = ""
    learned_successes: str = ""
    learned_failures: str = ""

    @field_validator("reasoning_effort", mode="before")
    @classmethod
    def _migrate_minimal(cls, v: object) -> object:
        """Read-compat for populations persisted before 'minimal' was dropped
        from the enum: coerce it to 'low' instead of failing validation, so an
        old population.db (whose whole point is lineage across runs) stays
        loadable. New writes can only contain the portable values."""
        return "low" if v == "minimal" else v


def to_prompt_payload(fixer: FixerGenome) -> dict[str, object]:
    """The genome's slots as a structured payload — meant to be embedded in the
    system prompt as literal JSON, not paraphrased into prose. A narrative
    rewrite risks exactly the "vaguer paraphrase" failure `doc_regression.py`
    exists to catch; JSON keeps every slot's value exact and legible across
    generations. Blank memory fields are omitted so the payload stays compact."""
    payload: dict[str, object] = {
        "persona": fixer.persona,
        "strategy": fixer.strategy.value,
        "test_style": fixer.test_style.value,
        "review_pass": fixer.review_pass.value,
        "risk": fixer.risk.value,
        "tdd_rigor": fixer.tdd_rigor,
        "minimalism": fixer.minimalism,
        "ambition": fixer.ambition,
        "edge_focus": fixer.edge_focus,
    }
    if fixer.strategy_hint:
        payload["strategy_hint"] = fixer.strategy_hint
    if fixer.goals:
        payload["goals"] = fixer.goals
    if fixer.codebase_standards:
        payload["codebase_standards"] = fixer.codebase_standards
    if fixer.learned_successes:
        payload["learned_successes"] = fixer.learned_successes
    if fixer.learned_failures:
        payload["avoid"] = fixer.learned_failures
    return payload


_PREAMBLE = (
    "You are an autonomous code-fixer agent. Your configuration follows as JSON — "
    "interpret every field literally, not as a vibe: enums select a concrete "
    "approach, and floats in 0..1 are dial strengths (0 = low/minimal, "
    "1 = high/maximal). 'goals'/'codebase_standards'/'learned_successes'/'avoid' "
    "are lessons carried over from this lineage's history; treat them as facts, "
    "not suggestions."
)


def render_system_prompt(fixer: FixerGenome) -> str:
    """Render the genome as a system prompt: a short generic preamble plus its
    slots as literal JSON.

    Purely a function of the slots — deterministic, no I/O — so mutation can be
    scored by re-rendering and re-running, two genomes with the same slots always
    produce byte-identical prompts, and the payload is diffable/legible across
    generations instead of a paraphrased blob that could quietly lose precision.
    """
    return f"{_PREAMBLE}\n\n{json.dumps(to_prompt_payload(fixer), indent=2)}"


def random_fixer_genome() -> FixerGenome:
    """A randomly seeded FixerGenome — the diversity-injection baseline (mirrors
    ``diversity._random_genome``'s model/strategy/temperature seeding). Memory
    slots are left blank: they hold learned evidence, not random noise."""
    return FixerGenome(
        strategy=random.choice(list(FixerStrategy)),
        test_style=random.choice(list(TestStyle)),
        review_pass=random.choice(list(ReviewPass)),
        risk=random.choice(list(RiskLevel)),
        reasoning_effort=random.choice([None, *list(ReasoningEffort)]),
        temperature=round(random.uniform(0.0, 1.0), 2),
        minimalism=round(random.uniform(0.0, 1.0), 2),
        ambition=round(random.uniform(0.0, 1.0), 2),
        edge_focus=round(random.uniform(0.0, 1.0), 2),
        tdd_rigor=round(random.uniform(0.0, 1.0), 2),
    )
