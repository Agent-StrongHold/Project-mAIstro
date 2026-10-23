"""ARC-AGI as the M4-G second domain: grid-induction evaluation, host-owned.

Epic #104 (M4-G) asks for "ARC-AGI-3 second-domain evaluation" — measuring the
harness against a *second* task domain (abstract grid induction) so the loop
cannot specialize to the primary coding/QA suite. This module is that
evaluation, with two scope decisions stated up front because this package
does not overclaim:

Reconciliation with SPEC-281 (status: Proposed)
-----------------------------------------------
SPEC-281 §3/§Out-of-scope excludes ARC-AGI *"on cost and addressability"* —
its numbers are about the live, interactive ARC-AGI-3 environment (~$30/task
through the official API) and about knowledge-gap benchmarks like GPQA/HLE.
The epic text (which SPEC-281 does not override — it is Proposed, not
accepted) asks for the second domain. The reconciliation implemented here:

* **Offline, deterministic, exact-match** grading over the official ARC-AGI
  *grid task format* (ARC-AGI-1/2 public corpora; any ARC-AGI-3 export
  published in this format). No paid interactive environment, no judge model,
  no container — the cost objection does not apply.
* **Addressability**: grid induction is exactly a planning/pattern-tracking/
  output-format task — a harness can help (few-shot rendering, answer-format
  enforcement, retry policy), so it belongs on the driver side of the
  addressability line, unlike GPQA's graduate chemistry.
* **Never comparable to a leaderboard number**: published ARC-AGI scores are
  on hidden evaluation sets with multi-attempt protocols. This adapter scores
  the *public* task files it is fed, so ``official_comparable`` is always
  False with the reason attached. Its valid use is the one epic #104 names:
  matched comparisons (baseline vs evolved harness, same model — see
  :mod:`maistro_evolve.lift_matrix`) within one pinned corpus snapshot.

Host-owned verdict (#852 discipline)
------------------------------------
The grader is exact structural equality between the candidate's parsed output
grid and the withheld expected grid. The candidate cannot influence the
verdict through text: a response that is not a JSON grid (including the words
"PASS" or a persuasive essay about why it passed) scores 0.0. Spoofed pass
markers are *counted* as gaming signals in ``metadata["gaming_signals"]`` so
they feed the RHAE meter (:mod:`maistro_evolve.eval_metering`) — a defeated
attempt is evidence about the candidate, not a score.

The task files are the exam: the corpus directory is validated at load (every
file must be well-formed ARC JSON with at least one train pair and at least
one test input), and the test outputs are stripped from the prompt material —
the model sees only train pairs and the test input.

Fail-closed rules
-----------------
* ``llm_call is None`` raises — no fabricated scores (SPEC-202).
* Unloadable/invalid corpus raises :class:`ArcAgiUnavailableError` — never an
  empty "perfect" or zero run.
* Unparseable candidate output is a failed attempt (0.0), counted in
  ``metadata["parse_failures"]``; a run where every response failed to parse
  reports score 0.0 with the failure count, not a quiet pass.

The corpus is not vendored in this repository (size/licensing); see
``third_party/arc_agi/README.md`` for how to vendor it. The availability probe
reports exactly that, so a real-fidelity harness skips ARC-AGI loudly instead
of silently scoring nothing.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..types import EvalResult, PipelineGenome
from .prompt_builder import build_messages, build_model_config, build_system_prompt

#: Where the vendored corpus lives. Not present by default; the probe says so.
_CORPUS_DIR = Path(__file__).parent / "third_party" / "arc_agi" / "tasks"

#: Rough per-call cost estimate for the meter; a *documented estimate*, marked
#: as such in metadata — never presented as a metered gateway number.
_ESTIMATED_COST_PER_CALL_USD = 0.002

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)

_GAMING_MARKER_HINTS = ("pass", "verdict", "score: 1")


class ArcAgiUnavailableError(RuntimeError):
    """The ARC-AGI corpus is missing or invalid. Never downgrades to proxy."""


def available() -> tuple[bool, str]:
    """Import-cheap probe: is the vendored corpus present and non-empty?"""
    if not _CORPUS_DIR.is_dir():
        return (
            False,
            f"corpus not vendored at {_CORPUS_DIR} — see "
            "benchmarks/third_party/arc_agi/README.md (ARC Prize public task files)",
        )
    if not any(_CORPUS_DIR.glob("*.json")):
        return False, f"corpus directory {_CORPUS_DIR} holds no task files"
    return True, "corpus present"


Grid = list[list[int]]


def _is_grid(value: Any) -> bool:
    """A grid is a non-empty list of equal-length rows of non-boolean ints.

    Rectangularity is part of the format: ARC grids are always rectangular, so
    a ragged "grid" is a malformed answer, and a verdict path that accepts
    one is a verdict path with a hole in it.
    """
    if not isinstance(value, list) or not value:
        return False
    widths: set[int] = set()
    for row in value:
        if not isinstance(row, list) or not row:
            return False
        if not all(isinstance(cell, int) and not isinstance(cell, bool) for cell in row):
            return False
        widths.add(len(row))
    return len(widths) == 1


def _validate_task(obj: Any, source: Path) -> dict[str, Any]:
    """Structural validation of one ARC task file; raises on anything off."""
    if not isinstance(obj, dict) or "train" not in obj or "test" not in obj:
        raise ArcAgiUnavailableError(
            f"{source.name}: not an ARC task (need 'train' and 'test' arrays)"
        )
    train = obj["train"]
    test = obj["test"]
    if not isinstance(train, list) or not train:
        raise ArcAgiUnavailableError(f"{source.name}: 'train' must be a non-empty array")
    if not isinstance(test, list) or not test:
        raise ArcAgiUnavailableError(f"{source.name}: 'test' must be a non-empty array")
    for pair in train:
        if (
            not isinstance(pair, dict)
            or not _is_grid(pair.get("input"))
            or not _is_grid(pair.get("output"))
        ):
            raise ArcAgiUnavailableError(
                f"{source.name}: train pair without well-formed input/output grids"
            )
    for entry in test:
        if not isinstance(entry, dict) or not _is_grid(entry.get("input")):
            raise ArcAgiUnavailableError(f"{source.name}: test entry without input grid")
        # The withheld answer must exist in the file (it grades the task) but
        # must never be shown to the candidate — see render_task.
        if not _is_grid(entry.get("output")):
            raise ArcAgiUnavailableError(
                f"{source.name}: test entry without expected output grid — "
                "cannot be graded, refusing to score it"
            )
    return obj


def load_arc_tasks(corpus_dir: Path | None = None) -> list[dict[str, Any]]:
    """Load and validate every ``*.json`` task under the corpus directory.

    Returns the parsed task objects in sorted-by-filename order (deterministic
    sampling follows from it). Raises :class:`ArcAgiUnavailableError` on a
    missing directory or any malformed task — one bad file indicts the corpus,
    because a task file that silently scores 0.0 for every model would drag
    matched comparisons in opposite directions for no reason the caller can
    see.
    """
    directory = corpus_dir if corpus_dir is not None else _CORPUS_DIR
    if not directory.is_dir():
        raise ArcAgiUnavailableError(f"ARC-AGI corpus directory missing: {directory}")
    files = sorted(directory.glob("*.json"))
    if not files:
        raise ArcAgiUnavailableError(f"ARC-AGI corpus directory holds no task files: {directory}")
    tasks = []
    for path in files:
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ArcAgiUnavailableError(f"{path.name}: unreadable task file ({exc})") from exc
        tasks.append(_validate_task(obj, path))
    return tasks


def render_grid(grid: Grid) -> str:
    """Render a grid compactly: space-separated digits, one row per line."""
    return "\n".join(" ".join(str(cell) for cell in row) for row in grid)


def render_task(task: dict[str, Any], max_train_pairs: int | None = None) -> str:
    """Build the user prompt for one task: train pairs, then the test input.

    The withheld test ``output`` is never rendered — it exists in the task file
    only to grade against. This function is the one place prompts are built,
    so that property has one home and one test file guarding it.
    """
    lines = [
        "You are solving an ARC-AGI style abstraction task.",
        "Study the example input/output grid pairs, deduce the transformation,",
        "and apply it to the test input.",
        "",
    ]
    train = task["train"] if max_train_pairs is None else task["train"][:max_train_pairs]
    for i, pair in enumerate(train, 1):
        lines += [
            f"Example {i} input:",
            render_grid(pair["input"]),
            "",
            f"Example {i} output:",
            render_grid(pair["output"]),
            "",
        ]
    test_input = task["test"][0]["input"]
    lines += [
        "Test input:",
        render_grid(test_input),
        "",
        "Respond with ONLY the output grid as a JSON array of arrays of "
        "integers (e.g. [[0, 1], [1, 0]]), no explanation.",
    ]
    return "\n".join(lines)


def parse_output_grid(response: str) -> Grid | None:
    """Parse the candidate's response into a grid, or None (fail-closed).

    Accepts either a fenced code block or the whole trimmed response being a
    JSON array. Anything else — prose, "PASS", a partial grid, a JSON object —
    is None, and None always scores 0.0. The parser is deliberately strict:
    it is the verdict path, and a permissive parser here is exactly the
    #852 defect class.
    """
    text = response.strip()
    if not text:
        return None
    fenced = _FENCE_RE.search(text)
    candidates = [fenced.group(1).strip()] if fenced else []
    candidates.append(text)
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if _is_grid(value):
            return value
    return None


def grade_attempt(response: str, expected: Grid) -> tuple[bool, bool]:
    """Grade one attempt: returns ``(correct, spoof_marker_detected)``.

    ``spoof_marker_detected`` is True when the response failed to parse *and*
    contains verdict-shaped text ("pass", "verdict", "score: 1") — i.e. it
    looks like an attempt to tell the grader it succeeded rather than answer.
    The attempt still scores 0.0; the signal feeds the RHAE meter.
    """
    grid = parse_output_grid(response)
    if grid is None:
        lowered = response.lower()
        spoofed = any(hint in lowered for hint in _GAMING_MARKER_HINTS)
        return False, spoofed
    return grid == expected, False


@dataclass
class _TaskOutcome:
    """What one task cost and produced, before it is folded into the run."""

    solved: bool
    parse_failures: int
    gaming_signals: int
    calls: int
    errors: int


async def _solve_task(
    task: dict[str, Any],
    llm_call: Any,
    *,
    system_prompt: str,
    model_config: dict[str, Any],
    attempts: int,
    timeout_s: float,
) -> _TaskOutcome:
    """Run one task's attempts; return what it produced and what it cost."""
    prompt = render_task(task)
    expected = task["test"][0]["output"]
    parse_failures = 0
    gaming_signals = 0
    calls = 0
    errors = 0
    for _attempt in range(attempts):
        try:
            response = await asyncio.wait_for(
                llm_call(
                    build_messages(system_prompt, prompt),
                    temperature=model_config.get("temperature", 0.2),
                    max_tokens=model_config.get("max_tokens", 2048),
                ),
                timeout=timeout_s,
            )
        except (TimeoutError, Exception):
            # House pattern (see ifeval_real): a failed call is a failed
            # attempt, counted and reported. It is never silently treated as a
            # wrong answer *and* never as a pass.
            calls += 1
            errors += 1
            continue
        calls += 1
        correct, spoofed = grade_attempt(str(response), expected)
        if spoofed:
            gaming_signals += 1
        if correct:
            return _TaskOutcome(
                solved=True,
                parse_failures=parse_failures,
                gaming_signals=gaming_signals,
                calls=calls,
                errors=errors,
            )
        if parse_output_grid(str(response)) is None:
            parse_failures += 1
    return _TaskOutcome(
        solved=False,
        parse_failures=parse_failures,
        gaming_signals=gaming_signals,
        calls=calls,
        errors=errors,
    )


async def run_arc_agi(
    genome: PipelineGenome,
    llm_call: Any,
    *,
    max_tasks: int | None = None,
    attempts: int = 2,
    timeout_s: float = 60.0,
    corpus_dir: Path | None = None,
) -> EvalResult:
    """Score ``genome`` on the vendored ARC-AGI grid corpus.

    Args:
        max_tasks: cap the task count to bound cost. Any cap marks the result
            ``sampled``.
        attempts: per-task attempts (best-of-k, official ARC scoring shape).
            The default 2 mirrors the public ARC-AGI-2 evaluation protocol.
        corpus_dir: override the corpus location (tests). Defaults to the
            vendored directory probed by :func:`available`.
    """
    if llm_call is None:
        raise ValueError(
            "run_arc_agi requires an llm_call — there is no stub/heuristic "
            "fallback (SPEC-202: never produce a fabricated score)"
        )
    if attempts < 1:
        raise ValueError(f"attempts must be >= 1, got {attempts}")

    tasks = load_arc_tasks(corpus_dir)
    total_tasks = len(tasks)
    if max_tasks is not None:
        tasks = tasks[:max_tasks]
    sampled = len(tasks) < total_tasks
    if not tasks:
        raise ArcAgiUnavailableError("ARC-AGI corpus selected zero tasks")

    start = time.monotonic()
    system_prompt = build_system_prompt(genome)
    model_config = build_model_config(genome)

    solved = 0
    parse_failures = 0
    gaming_signals = 0
    calls = 0
    errors = 0

    for task in tasks:
        outcome = await _solve_task(
            task,
            llm_call,
            system_prompt=system_prompt,
            model_config=model_config,
            attempts=attempts,
            timeout_s=timeout_s,
        )
        calls += outcome.calls
        errors += outcome.errors
        parse_failures += outcome.parse_failures
        gaming_signals += outcome.gaming_signals
        if outcome.solved:
            solved += 1

    score = solved / len(tasks)
    elapsed = time.monotonic() - start

    return EvalResult(
        benchmark="arc_agi",
        score=round(score, 4),
        cost_usd=round(calls * _ESTIMATED_COST_PER_CALL_USD, 4),
        duration_seconds=round(elapsed, 3),
        samples_evaluated=len(tasks),
        metadata={
            "fidelity": "real",
            # Never comparable to a published ARC-AGI number: public corpus,
            # not the hidden evaluation set; pin the snapshot for matched
            # comparisons instead (see module docstring).
            "official_comparable": False,
            "official_comparable_reason": "public grid corpus, not the hidden "
            "ARC-AGI evaluation set; valid only for matched same-corpus "
            "comparisons",
            "total_tasks": total_tasks,
            "sampled": sampled,
            "attempts_per_task": attempts,
            "parse_failures": parse_failures,
            # Failed calls (timeout, transport error). Counted separately from
            # parse failures: a call that never returned is not a malformed
            # answer, and conflating them would hide a broken provider behind
            # a "the model is bad at grids" story.
            "call_errors": errors,
            # Host-detected reward-hacking attempts — consumed by the RHAE
            # meter (eval_metering). Already defeated by the exact-match
            # grader; recorded, never scored.
            "gaming_signals": {"spoofed_pass_marker": gaming_signals},
            "cost_estimate": True,
        },
    )


__all__ = [
    "ArcAgiUnavailableError",
    "available",
    "grade_attempt",
    "load_arc_tasks",
    "parse_output_grid",
    "render_grid",
    "render_task",
    "run_arc_agi",
]
