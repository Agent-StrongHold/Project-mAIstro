"""IFEval at the ``real`` fidelity tier: the official corpus, the official grader.

This is the first benchmark in this package that can honestly claim ``real``
(SPEC-202) — the 541-prompt published corpus, scored by Google Research's own
verifier, reporting the four numbers the paper reports. Everything else in
``benchmarks/`` is ``proxy``: genuine checks at handcrafted scale.

Why IFEval was the right one to make real first
-----------------------------------------------
It needs no container, no sandbox, no reference solutions, and no judge model.
The grader is deterministic Python over the response text. So the entire cost of
"real" here is 541 LLM calls — no infrastructure at all — which is why the
containment review put it ahead of SWE-bench in the staging order despite
SWE-bench carrying more weight.

It is also the benchmark where pretraining contamination matters least, and this
is worth being precise about rather than hand-waving. IFEval has been public
since 2023, so assume the corpus is in every base model's weights. For a
knowledge benchmark that would be fatal: memorizing the answer *is* the task.
Here the task is mechanical constraint satisfaction — "write 300+ words", "use no
commas", "end with this exact phrase". Having memorized the prompt does not help
you avoid commas. The grader counts commas in the response you actually
produced. Contamination inflates a knowledge benchmark; it barely moves this one.

What the split does and does not defend against
-----------------------------------------------
``split="train"`` and ``split="holdout"`` partition the 541 deterministically by
prompt key. This does **not** defend against pretraining contamination (nothing
can, for a public corpus — see above). It defends against a different and, for a
self-improving loop, more pressing failure: the loop overfitting *this corpus*
via the harness — special-casing prompts, tuning to the exact sample mix, or
discovering a grader quirk. The loop's fitness sees ``train`` only; the
supervisor scores ``holdout``. Train rising while holdout stays flat is the
signature, exactly as in ``terminalbench``.

Honest limits, so nobody over-reads a number from this module
------------------------------------------------------------
* **A sampled run is not the official score.** ``max_prompts`` exists because 541
  calls costs real money, but any sampled result carries ``sampled: True`` and
  ``requested_prompts`` in metadata. Only a full, unsampled, unsplit run over all
  541 prompts is comparable to a published IFEval number, and that combination
  reports ``official_comparable: True``. Nothing else does.
* **A split run is not the official score either**, for the same reason — it
  covers a subset. ``official_comparable`` is False for any split other than
  ``"all"``.
* **The four metrics are not interchangeable.** Papers quote different ones.
  ``score`` is prompt-level strict, the strictest and most commonly headlined of
  the four; all four are in metadata so a comparison can use whichever the source
  it is being compared against used.
* **Errors are counted, not hidden.** A failed ``llm_call`` scores zero, which is
  indistinguishable in the average from a response that followed no
  instructions. ``metadata["errors"]`` is the only way to tell a degraded gateway
  from a degraded genome.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from ..types import EvalResult, PipelineGenome
from .prompt_builder import build_messages, build_model_config, build_system_prompt

Split = Literal["all", "train", "holdout"]

_CORPUS = Path(__file__).parent / "third_party" / "ifeval" / "data" / "input_data.jsonl"

# Pinned in scripts/vendor_ifeval.py; duplicated here so loading fails closed
# even if the vendoring script is absent. The corpus is the exam — if its bytes
# are not the bytes we pinned, the score is not the score we think it is.
_CORPUS_SHA256 = "67ffeee0fcb87c317c5b08a2de85557b4a7e96ada6178aa645b4954fe4b53d49"
_EXPECTED_PROMPTS = 541

# Fraction of prompts assigned to the holdout. 20% of 541 is ~108 prompts, which
# is enough for a holdout mean to be worth reading while leaving ~433 for the
# training signal.
_HOLDOUT_PCT = 20

_DEPS_HINT = (
    "The official IFEval verifier needs its real dependencies: install the "
    "extra (`uv pip install 'maistro-evolve[ifeval]'`) and pre-fetch the nltk "
    "tokenizer (`python3 -c \"import nltk; nltk.download('punkt'); nltk.download('punkt_tab')\"`). They are "
    "not shimmed away on purpose — an approximate grader must not be labelled "
    "'real'. See the NOTICE in benchmarks/third_party/ifeval/."
)

_MAX_FAILURE_TRACES = 5


class IFEvalUnavailableError(RuntimeError):
    """The real IFEval adapter cannot run, and must not silently downgrade.

    Raised rather than falling back to the proxy runner or to a partial grader.
    A caller that asked for ``real`` and got ``proxy`` without being told would
    make exactly the mistake SPEC-202's two-tier model exists to prevent.
    """


def available() -> tuple[bool, str]:
    """Can the real IFEval adapter run in this environment? ``(ok, reason)``.

    Real benchmarks are **optional includes**: a machine without the ``ifeval``
    extra installed simply doesn't get this benchmark considered — the harness
    skips it at registration, loudly, and everything else still works. A
    machine with the resources and the deps runs it. The probe checks
    *availability* (deps present, corpus present), not *integrity* — a corpus
    that is present but tampered with still probes available and then fails
    hard at load time, which is the correct severity ordering: "can't run" is
    an environment fact to route around; "exam was edited" is an alarm that
    must never be routed around.
    """
    if not _CORPUS.is_file():
        return False, f"corpus missing at {_CORPUS} — run `python3 scripts/vendor_ifeval.py`"
    try:
        from .third_party.ifeval import evaluation_lib  # noqa: F401
    except ImportError as exc:
        return False, (
            f"grader dependencies missing ({exc}) — install with "
            "`uv pip install 'maistro-evolve[ifeval]'`"
        )
    try:
        import nltk

        # BOTH are required, and `punkt` alone is the trap. Since nltk 3.9 the
        # pickle loader resolves through `punkt_tab`, so
        # `nltk.data.load("nltk:tokenizers/punkt/english.pickle")` — the exact
        # call the vendored grader makes — raises LookupError('punkt_tab') on a
        # machine that downloaded only `punkt`. Verified against nltk 3.10.
        #
        # Probing both here is what keeps that failure cheap. The grader runs
        # *after* every LLM call, so a missing resource discovered at grade time
        # burns the entire cost of the run (541 calls) and returns nothing.
        for resource in ("tokenizers/punkt", "tokenizers/punkt_tab"):
            nltk.data.find(resource)
    except LookupError as exc:
        missing = str(exc).split("Resource")[-1].split("not found")[0].strip().strip("'[93m ")
        return False, (
            f"nltk tokenizer data missing ({missing or 'punkt/punkt_tab'}) — pre-fetch with "
            "`python3 -c \"import nltk; nltk.download('punkt'); nltk.download('punkt_tab')\"`. "
            "Both are needed: since nltk 3.9 the punkt pickle loader resolves "
            "through punkt_tab. The scoring container is network-denied, so it "
            "cannot self-download."
        )
    except ImportError as exc:  # pragma: no cover - caught by the import above
        return False, f"nltk unavailable ({exc})"
    return True, ""


def load_corpus(split: Split = "all") -> list[dict[str, Any]]:
    """The official 541 prompts, checksum-verified, optionally split.

    Verifying the checksum on every load is deliberate and cheap (207 KB). The
    corpus sits on the RSI loop's own writable tree, and ``vendor_ifeval.py
    --check`` only runs in CI — a candidate that appends easy prompts or deletes
    hard ones between CI runs would otherwise raise its own score with no diff
    to review. This makes the exam tamper-evident at score time.
    """
    if not _CORPUS.is_file():
        raise IFEvalUnavailableError(
            f"official IFEval corpus missing at {_CORPUS}. "
            "Run `python3 scripts/vendor_ifeval.py` to restore it."
        )
    raw = _CORPUS.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != _CORPUS_SHA256:
        raise IFEvalUnavailableError(
            f"official IFEval corpus at {_CORPUS} does not match its pinned "
            f"checksum.\n  pinned: {_CORPUS_SHA256}\n  actual: {actual}\n"
            "The exam has been modified. Refusing to score against it — restore "
            "with `python3 scripts/vendor_ifeval.py`."
        )
    records = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    if len(records) != _EXPECTED_PROMPTS:
        raise IFEvalUnavailableError(
            f"expected {_EXPECTED_PROMPTS} IFEval prompts, found {len(records)}"
        )
    if split == "all":
        return records
    return [r for r in records if split_of(r["key"]) == split]


def split_of(key: int) -> Split:
    """Deterministic train/holdout assignment for one prompt key.

    Hashed rather than sliced by index so the assignment does not shift if
    upstream reorders the file, and so it carries no relationship to the corpus's
    own ordering (the file is grouped by prompt family, so a positional split
    would put whole instruction types entirely on one side).
    """
    digest = hashlib.sha256(f"ifeval:{key}".encode()).digest()
    return "holdout" if digest[0] % 100 < _HOLDOUT_PCT else "train"


def _grader() -> Any:
    """Import the vendored official grader, or explain precisely what is missing."""
    try:
        from .third_party.ifeval import evaluation_lib
    except ImportError as exc:
        raise IFEvalUnavailableError(f"{exc}\n\n{_DEPS_HINT}") from exc
    return evaluation_lib


def _sample(records: list[dict[str, Any]], max_prompts: int | None) -> list[dict[str, Any]]:
    """Deterministic subsample. Sorted by key hash, not random.

    Unseeded sampling would make two runs of the same genome incomparable, which
    is fatal for a fitness signal — the difference between cycles has to be the
    genome, not the draw.
    """
    if max_prompts is None or max_prompts >= len(records):
        return records
    ordered = sorted(records, key=lambda r: hashlib.sha256(f"pick:{r['key']}".encode()).digest())
    return ordered[:max_prompts]


@dataclass(frozen=True)
class _Verdict:
    """One prompt's official verdicts, both strictness levels."""

    prompt_strict: bool
    prompt_loose: bool
    inst_strict: list[bool]
    inst_loose: list[bool]
    # Instruction ids the response failed under STRICT grading — the actionable
    # signal for reflective prompt evolution. "You keep failing
    # punctuation:no_comma" is a usable critique; "you scored 0.62" is not.
    failed_instructions: list[str]


def _grade(evaluation_lib: Any, record: dict[str, Any], response: str) -> _Verdict:
    """Run both official verdict functions over one prompt/response pair."""
    inp = evaluation_lib.InputExample(
        key=record["key"],
        instruction_id_list=record["instruction_id_list"],
        prompt=record["prompt"],
        kwargs=record["kwargs"],
    )
    prompt_to_response = {record["prompt"]: response}
    strict_out = evaluation_lib.test_instruction_following_strict(inp, prompt_to_response)
    loose_out = evaluation_lib.test_instruction_following_loose(inp, prompt_to_response)
    return _Verdict(
        prompt_strict=bool(strict_out.follow_all_instructions),
        prompt_loose=bool(loose_out.follow_all_instructions),
        inst_strict=list(strict_out.follow_instruction_list),
        inst_loose=list(loose_out.follow_instruction_list),
        failed_instructions=[
            iid
            for iid, ok in zip(
                record["instruction_id_list"], strict_out.follow_instruction_list, strict=True
            )
            if not ok
        ],
    )


@dataclass
class _Totals:
    """Running totals across one run's graded responses."""

    prompt_strict: int = 0
    prompt_loose: int = 0
    inst_strict_ok: int = 0
    inst_loose_ok: int = 0
    inst_total: int = 0
    errors: int = 0
    grader_errors: int = 0
    cost_usd: float = 0.0
    failures_by_instruction: dict[str, list[int]] = field(default_factory=dict)
    failure_traces: list[dict[str, Any]] = field(default_factory=list)


def _aggregate(
    evaluation_lib: Any,
    responses: list[tuple[dict[str, Any], str | None, str | None]],
) -> _Totals:
    """Grade every response and accumulate the four official metrics.

    Note that ``inst_total`` counts instructions from *errored* prompts too. That
    is deliberate: an error means the response followed none of them, and
    excluding it would quietly raise instruction-level accuracy when the gateway
    misbehaves — a degraded run would look like a better one.

    Grader exceptions are caught per prompt rather than allowed to propagate.
    Grading happens *after* every LLM call, so one unhandled grader error threw
    away a fully paid-for run (541 calls) and returned nothing — the worst
    possible failure mode, since the money is spent either way. The realistic
    trigger is a missing nltk resource, which ``available()`` now pre-checks;
    this is the backstop for whatever it doesn't anticipate. Such prompts score
    zero and are counted in ``grader_errors``, kept distinct from ``errors``
    (gateway) and from genuine failures, because "the grader broke" and "the
    model was wrong" call for completely different responses.
    """
    t = _Totals()
    for record, response, error in responses:
        t.inst_total += len(record["instruction_id_list"])
        if error is not None:
            t.errors += 1
            if len(t.failure_traces) < _MAX_FAILURE_TRACES:
                t.failure_traces.append(
                    {"key": record["key"], "error": error, "failed_instructions": []}
                )
            continue
        t.cost_usd += 0.001

        try:
            verdict = _grade(evaluation_lib, record, response or "")
        except Exception as exc:
            t.grader_errors += 1
            if len(t.failure_traces) < _MAX_FAILURE_TRACES:
                t.failure_traces.append(
                    {
                        "key": record["key"],
                        "error": f"grader failed: {type(exc).__name__}: {exc}",
                        "failed_instructions": [],
                    }
                )
            continue
        t.prompt_strict += int(verdict.prompt_strict)
        t.prompt_loose += int(verdict.prompt_loose)
        t.inst_strict_ok += sum(verdict.inst_strict)
        t.inst_loose_ok += sum(verdict.inst_loose)

        for iid in verdict.failed_instructions:
            t.failures_by_instruction.setdefault(iid, []).append(record["key"])
        if verdict.failed_instructions and len(t.failure_traces) < _MAX_FAILURE_TRACES:
            t.failure_traces.append(
                {
                    "key": record["key"],
                    "failed_instructions": verdict.failed_instructions,
                    "response_excerpt": (response or "")[:200],
                }
            )
    return t


async def run_ifeval_real(
    genome: PipelineGenome,
    llm_call: Any,
    *,
    split: Split = "train",
    max_prompts: int | None = None,
    concurrency: int = 8,
    timeout_s: float = 60.0,
) -> EvalResult:
    """Score ``genome`` on official IFEval with the official verifier.

    Args:
        split: ``"train"`` (default — what the loop's fitness may see),
            ``"holdout"`` (supervisor only), or ``"all"`` (the only value that
            can produce a number comparable to a published score).
        max_prompts: cap the prompt count to bound cost. Any cap marks the
            result ``sampled`` and disqualifies it from ``official_comparable``.
        concurrency: in-flight ``llm_call``s. 541 sequential calls is ~20
            minutes; 8 in flight is a few minutes without hammering a gateway.

    Raises:
        IFEvalUnavailableError: the corpus is missing/modified or the grader's
            dependencies are absent. Never downgrades to ``proxy`` silently.
        ValueError: ``llm_call`` is None — consistent with every proxy runner
            (SPEC-202: never produce a fabricated score).
    """
    if llm_call is None:
        raise ValueError(
            "run_ifeval_real requires an llm_call — there is no stub/heuristic "
            "fallback (SPEC-202: never produce a fabricated score)"
        )
    if concurrency < 1:
        raise ValueError(f"concurrency must be >= 1, got {concurrency}")

    evaluation_lib = _grader()
    # Load once. `load_corpus` re-reads and re-hashes the file on every call by
    # design, so calling it twice (once to sample, once to decide `sampled`)
    # would double that work for no benefit.
    available = load_corpus(split)
    records = _sample(available, max_prompts)
    sampled = len(records) < len(available)
    if not records:
        raise IFEvalUnavailableError(f"IFEval split {split!r} selected zero prompts")

    start = time.monotonic()
    system_prompt = build_system_prompt(genome)
    model_config = build_model_config(genome)
    semaphore = asyncio.Semaphore(concurrency)

    async def fetch(record: dict[str, Any]) -> tuple[dict[str, Any], str | None, str | None]:
        """Returns (record, response, error). Exactly one of response/error is set."""
        async with semaphore:
            try:
                response = await asyncio.wait_for(
                    llm_call(
                        build_messages(system_prompt, record["prompt"]),
                        temperature=model_config.get("temperature", 0.3),
                        max_tokens=model_config.get("max_tokens", 2048),
                    ),
                    timeout=timeout_s,
                )
                return record, str(response), None
            except (TimeoutError, Exception) as exc:
                return record, None, f"{type(exc).__name__}: {exc}"

    responses = await asyncio.gather(*(fetch(r) for r in records))

    totals = _aggregate(evaluation_lib, responses)
    prompt_strict = totals.prompt_strict
    prompt_loose = totals.prompt_loose
    inst_strict_ok = totals.inst_strict_ok
    inst_loose_ok = totals.inst_loose_ok
    inst_total = totals.inst_total
    errors = totals.errors
    total_cost = totals.cost_usd
    per_instruction_failures = totals.failures_by_instruction
    failures = totals.failure_traces

    n_prompts = len(records)
    elapsed = time.monotonic() - start

    return EvalResult(
        benchmark="ifeval",
        # Prompt-level strict: every instruction in the prompt satisfied, no
        # response-cleanup allowance. The strictest of the four.
        score=round(prompt_strict / n_prompts, 4),
        cost_usd=round(total_cost, 4),
        duration_seconds=round(elapsed, 3),
        samples_evaluated=n_prompts,
        metadata={
            "fidelity": "real",
            "check": "official_ifeval_verifier",
            "grader": "google-research/instruction_following_eval (vendored, pinned)",
            "total_samples": n_prompts,
            "split": split,
            "corpus_size": _EXPECTED_PROMPTS,
            # The four numbers IFEval papers report. Which one a source quoted
            # matters when comparing, so all four travel together.
            "prompt_level_strict": round(prompt_strict / n_prompts, 4),
            "prompt_level_loose": round(prompt_loose / n_prompts, 4),
            "instruction_level_strict": round(inst_strict_ok / max(inst_total, 1), 4),
            "instruction_level_loose": round(inst_loose_ok / max(inst_total, 1), 4),
            "instructions_evaluated": inst_total,
            "sampled": sampled,
            "requested_prompts": max_prompts,
            # True only for a full run over the whole corpus. Any split or
            # sample covers a subset and is not a published-score comparable.
            "official_comparable": (
                split == "all" and not sampled and errors == 0 and totals.grader_errors == 0
            ),
            "errors": errors,
            # Grader failures, distinct from gateway failures above and from
            # genuine wrong answers. Non-zero means the score understates the
            # genome: those prompts counted as zero without being graded.
            "grader_errors": totals.grader_errors,
            "failures_by_instruction": {
                iid: len(keys) for iid, keys in sorted(per_instruction_failures.items())
            },
            "failures": failures,
        },
    )
