"""Scout step: name the most impactful improvements to a module (SPEC-070126-9d37).

The point of the loop is recursive self-improvement — real growth up to a module
"v2.0", not docstring churn — so the scout acts as an R&D lead. It reads the
target's source, its existing tests, and its uncovered lines, and returns a
**ranked shortlist** of typed :class:`~maistro_evolve.improvement.ImprovementKind`
items (bug-fix → new test → assertion → feature → edge …), each naming exactly
where and what. Competitors then spread across the shortlist (complementary), and
over many runs collide on the same hot regions (competitive, best composite wins).

The type flag on each item routes everything downstream — budget tier and which
fitness signals decide promotion (see ``candidate_fitness``). A silent/garbled
scout falls back to a single generic objective so a cycle never stalls.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from maistro_evolve.improvement import ImprovementKind

LlmCall = Callable[..., dict[str, Any]]

_SCOUT_SYSTEM = (
    "You are the R&D lead for a Python module that improves itself over many "
    "rounds. You are shown the module, its existing tests, its uncovered lines, "
    "and any UNIMPLEMENTED SPEC acceptance criteria. Identify a RANKED SHORTLIST "
    "(1-3) of the highest-impact improvements, from tightening correctness to "
    "ambitious growth, using these kinds:\n"
    "  bug_fix   - the code violates its contract; name the input and the wrong "
    "vs. expected output.\n"
    "  new_test  - an evidence-based test for untested behavior; name the "
    "function, the exact case, and the expected result.\n"
    "  assertion - an existing test asserts too little; name the test and what it "
    "must additionally assert.\n"
    "  spec      - implement a specific UNIMPLEMENTED acceptance criterion (name "
    "the SPEC id and AC id); this finishes work already contracted and is the "
    "single highest-reward move when a gap exists — prefer it over inventing "
    "features.\n"
    "  backlog   - draft a NEW spec (with acceptance criteria) for a genuinely "
    "good capability idea; the disciplined alternative to shipping an unspecced "
    "feature directly — only propose this when you have a real idea worth "
    "formalizing, not busywork.\n"
    "  feature   - a genuinely better capability, API, or design for this module "
    "(v2.0); be ambitious where warranted; must ship with tests.\n"
    "  edge_case - an untested boundary/error path.\n"
    "  refactor  - a behavior-preserving clarity/DRY/complexity win.\n"
    "  perf      - a measurable performance optimization.\n"
    "  doc       - a docstring/type; FALLBACK ONLY, when nothing better is "
    "warranted and the module is already well-tested and correct.\n"
    "THE MATURITY LADDER (favor lower rungs first): correctness and "
    "verification before anything else (do not build v2.0 on unverified code); "
    "finishing a CONTRACTED spec gap outranks inventing new work of any kind; "
    "if UNCOVERED LINES is empty or short and existing tests are strong and "
    "there are NO spec gaps, the module has EARNED ambition — you MUST include "
    "one `feature` (or, if you have a genuinely new idea worth contracting "
    "first, `backlog`) item in the shortlist. Never propose features or "
    "backlog items for an under-tested module. Rank by impact. Name exactly "
    "WHERE (function/test/line, or SPEC+AC id) and WHAT, concretely enough "
    "that different implementers could each attempt the same item.\n"
    'Reply with ONLY a JSON array, each element {"kind": <one of the kinds>, '
    '"location": <function/test/line>, "instruction": <one concrete sentence>}. '
    "No prose, no code fences."
)


@dataclass(frozen=True)
class ScoutItem:
    """One improvement the scout proposes: its kind, where, and what to do."""

    kind: ImprovementKind
    location: str
    instruction: str


def _build_user_prompt(
    source: str, tests: str, uncovered: Sequence[int] | str, spec_gaps: str = ""
) -> str:
    unc = uncovered if isinstance(uncovered, str) else ", ".join(str(n) for n in uncovered)
    parts = [
        "TARGET MODULE:",
        source,
        "",
        "EXISTING TESTS:",
        tests or "(none found)",
        "",
        f"UNCOVERED LINES: {unc or '(unknown)'}",
    ]
    if spec_gaps:
        parts += ["", "UNIMPLEMENTED SPEC ACCEPTANCE CRITERIA:", spec_gaps]
    parts += ["", "Return the ranked shortlist as the specified JSON array."]
    return "\n".join(parts)


def _extract_json_array(text: str) -> list[dict[str, Any]]:
    """Pull the first JSON array out of an LLM reply (tolerating stray prose/fences)."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if not match:
            return []
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return []
    return data if isinstance(data, list) else []


def parse_shortlist(content: str, *, max_items: int = 3) -> list[ScoutItem]:
    """Parse an LLM reply into ScoutItems (lenient); at most ``max_items``."""
    items: list[ScoutItem] = []
    for entry in _extract_json_array(content):
        if not isinstance(entry, dict):
            continue
        instruction = str(entry.get("instruction", "")).strip()
        if not instruction:
            continue
        items.append(
            ScoutItem(
                kind=ImprovementKind.from_str(str(entry.get("kind", "doc"))),
                location=str(entry.get("location", "")).strip(),
                instruction=instruction,
            )
        )
        if len(items) >= max_items:
            break
    # Impact order: honour the model's ranking but keep it stable by kind priority
    # only as a tiebreak among equal positions is unnecessary — trust the model's
    # order, which already reflects the impact judgement we asked for.
    return items


def scout_shortlist(
    source: str,
    tests: str,
    uncovered: Sequence[int] | str,
    llm_call: LlmCall,
    *,
    spec_gaps: str = "",
    max_items: int = 3,
) -> list[ScoutItem]:
    """Ask ``llm_call`` for a ranked shortlist of improvements to ``source``.

    ``spec_gaps`` names any UNIMPLEMENTED acceptance criteria for this target
    (e.g. from ``spec_tracker.spec_gaps``) so the scout can propose concrete
    ``spec`` items instead of hallucinating AC ids; empty means none are known.

    Returns ``[]`` if the call errors or yields nothing usable, so the caller can
    fall back to a generic objective rather than stall the cycle.
    """
    messages = [
        {"role": "system", "content": _SCOUT_SYSTEM},
        {"role": "user", "content": _build_user_prompt(source, tests, uncovered, spec_gaps)},
    ]
    try:
        result = llm_call(messages, max_tokens=800)
    except Exception:
        return []
    content = result.get("content", "") if isinstance(result, dict) else result
    return parse_shortlist(
        content if isinstance(content, str) else str(content), max_items=max_items
    )


def scout_objective(source: str, llm_call: LlmCall, *, fallback: str) -> str:
    """Back-compat single-instruction scout: the top improvement's instruction.

    One call, parsed leniently — a JSON shortlist yields its top item's
    instruction; a plain-text reply is used verbatim as the objective; anything
    empty or errored yields ``fallback`` so a cycle never stalls.
    """
    messages = [
        {"role": "system", "content": _SCOUT_SYSTEM},
        {"role": "user", "content": _build_user_prompt(source, "", "")},
    ]
    try:
        result = llm_call(messages, max_tokens=400)
    except Exception:
        return fallback
    content = result.get("content", "") if isinstance(result, dict) else result
    text = (content if isinstance(content, str) else str(content)).strip()
    items = parse_shortlist(text, max_items=1)
    if items:
        return items[0].instruction
    return text or fallback
