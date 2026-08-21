from __future__ import annotations

import time
from typing import Any

from ..types import EvalResult, PipelineGenome
from .executable_terminal import (
    HOLDOUT_TASKS,
    TRAINING_TASKS,
    build_executable_terminal_prompt,
    evaluate_executable_terminal_response,
)
from .prompt_builder import build_messages, build_model_config, build_system_prompt

_TASKS = TRAINING_TASKS + HOLDOUT_TASKS

# Split membership is resolved by task id, not by list position, so that tests
# (and any caller) can monkeypatch ``_TASKS`` to a subset and still get a
# correctly-attributed per-split breakdown.
_HOLDOUT_IDS = frozenset(t.id for t in HOLDOUT_TASKS)


async def run_terminalbench(genome: PipelineGenome, llm_call: Any) -> EvalResult:
    """Score terminal-task responses by actually verifying end filesystem state.

    Proxy-tier (SPEC-202): a small handcrafted task set, not the official
    Terminal-Bench corpus. But the check is genuine — each task defines
    initial files and an exact expected end state (including "no unexpected
    files"), verified in a scratch tempdir
    (``executable_terminal.evaluate_executable_terminal_response``), not
    scored by matching keywords against a proposed shell command. This
    replaces the previous ``TERMINALBENCH_SAMPLES`` keyword-matcher, whose
    samples had no verifiable state at all and included tasks (kill a live
    process, curl a URL, `docker ps`) that cannot run in this harness's
    network-disabled, container-free execution model anyway.

    **The train/holdout split is reported, not enforced.** ``_TASKS`` is the
    union of ``TRAINING_TASKS`` and ``HOLDOUT_TASKS``, so the headline ``score``
    is the combined average and the holdout is *not* held out from the
    optimizer's fitness signal — with 3 training tasks it is too thin to drive
    a cycle on its own. What this function guarantees is *observability*:
    ``metadata["train_score"]`` and ``metadata["holdout_score"]`` are computed
    and reported separately, so training-up-while-holdout-is-flat — the
    signature of memorizing the corpus rather than getting better at terminal
    work — is visible in the result rather than averaged away. The reported
    ``generalization_gap`` is that difference.

    Consequences for anything consuming this result:

    * The combined ``score`` must not pay a capability bonus. It is contaminated
      by construction: the loop can see every task it is scored on. Only a
      holdout scored by a supervisor the loop cannot reach is bonus-eligible.
    * ``metadata["errors"]`` counts tasks whose ``llm_call`` raised. Those
      contribute 0.0 to the average exactly as a genuine failure does, so a
      degraded gateway is indistinguishable from a bad genome in ``score``
      alone — check this count before reading a score drop as a regression.
    """
    if llm_call is None:
        raise ValueError(
            "run_terminalbench requires an llm_call — there is no stub/heuristic "
            "fallback (SPEC-202: never produce a fabricated score)"
        )

    start = time.monotonic()
    system_prompt = build_system_prompt(genome)
    model_config = build_model_config(genome)

    total_score = 0.0
    evaluated = 0
    total_cost = 0.0
    errors = 0
    failures: list[dict[str, Any]] = []
    # split name -> [summed score, count]
    splits: dict[str, list[float]] = {"train": [0.0, 0.0], "holdout": [0.0, 0.0]}

    for task in _TASKS:
        split = "holdout" if task.id in _HOLDOUT_IDS else "train"
        messages = build_messages(system_prompt, build_executable_terminal_prompt(task))
        try:
            response = await llm_call(
                messages,
                temperature=model_config.get("temperature", 0.1),
                max_tokens=model_config.get("max_tokens", 1024),
            )
            total_cost += 0.001
            result = evaluate_executable_terminal_response(task, response)
            total_score += result.score
            evaluated += 1
            splits[split][0] += result.score
            splits[split][1] += 1
            if not result.passed and len(failures) < 5:
                failures.append(
                    {
                        "id": task.id,
                        "split": split,
                        "error": result.error,
                        "mismatches": list(result.mismatches),
                    }
                )
        except (TimeoutError, Exception) as exc:
            evaluated += 1
            errors += 1
            splits[split][1] += 1
            if len(failures) < 5:
                failures.append({"id": task.id, "split": split, "error": f"error: {exc}"})

    avg_score = total_score / max(evaluated, 1)
    elapsed = time.monotonic() - start

    def _split_score(name: str) -> float | None:
        summed, count = splits[name]
        return round(summed / count, 4) if count else None

    train_score = _split_score("train")
    holdout_score = _split_score("holdout")
    gap = (
        round(train_score - holdout_score, 4)
        if train_score is not None and holdout_score is not None
        else None
    )

    return EvalResult(
        benchmark="proxy_terminalbench",
        score=round(avg_score, 4),
        cost_usd=round(total_cost, 4),
        duration_seconds=round(elapsed, 3),
        samples_evaluated=evaluated,
        metadata={
            "total_samples": len(_TASKS),
            "fidelity": "proxy",
            "check": "verified_filesystem_state",
            # The headline score is train+holdout combined, so it is not
            # bonus-eligible. See the docstring.
            "split": "combined",
            "train_score": train_score,
            "train_samples": int(splits["train"][1]),
            "holdout_score": holdout_score,
            "holdout_samples": int(splits["holdout"][1]),
            # train >> holdout is the memorization signature. None when either
            # split was empty (e.g. a caller narrowed _TASKS to one split).
            "generalization_gap": gap,
            "errors": errors,
            "failures": failures,
        },
    )
