"""BFCL at the ``real`` fidelity tier: the official Python-AST corpus and checker.

The second benchmark to reach ``real`` (SPEC-202), following the pattern set by
``ifeval_real.py`` — read that module's docstring for the shared rationale
(vendoring over runtime fetch, load-time checksums, ``official_comparable``,
error accounting). This docstring covers only what is BFCL-specific.

What "real" means here, precisely
---------------------------------
The **Python AST track** of BFCL v4: ``simple_python`` (400), ``multiple``
(200), ``parallel`` (200), ``parallel_multiple`` (200) — 1,000 instances with the
official ``possible_answer`` ground truth, graded by the official
``ast_checker`` vendored from the ``bfcl-eval`` package (pinned wheel; see
``scripts/vendor_bfcl.py``). Grading is deterministic structure comparison — no
model execution, no judge, no container — which is why BFCL was the second
benchmark worth making real rather than the fifth.

It is *not* all of BFCL. The live/multi-turn/agentic/web-search tracks and the
java/js corpora are out of scope: they need vendor-API replay, stateful
execution environments, or tree-sitter parsing of model output. So
``official_comparable`` here means "these per-category accuracies were produced
by the official checker over the full official corpora for these categories" —
comparable to the leaderboard's *per-category AST columns*, never to a model's
overall BFCL score. The headline ``score`` is the instance-weighted accuracy
across the four categories, which is our aggregate, not a leaderboard column;
the per-category numbers in metadata are the comparable ones.

Division of labour — who is being measured for what
---------------------------------------------------
The *response format* is ours; the *verdict* is theirs. The genome answers with
a JSON array of ``{"name": ..., "arguments": {...}}`` calls, which this adapter
converts to the checker's decoded form. An unparseable response is scored
invalid — the same treatment the official harness gives output its decoders
cannot parse. One deliberate harshness: our shim grants no ``.``→``_``
function-name accommodation to any model (see
``third_party/bfcl/_model_config_shim.py``), so scores can only be equal or
lower than the same answers would receive upstream, never higher.

Contamination note (same shape as IFEval's, different weight): BFCL data is
public, so assume it is in base-model weights. Function-calling is *partially*
constraint-like — the model must still emit arguments matching the specific
schema and question — but memorized (question, call) pairs help more here than
memorized IFEval prompts do, because the answer IS the artifact. The enforced
train/holdout split (~20% by id hash, every category on both sides) is what
makes harness-level overfitting visible; it cannot address pretraining
contamination, and a capability bonus paid on the holdout should weight BFCL
gains below IFEval gains for exactly that reason.
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

_DATA_DIR = Path(__file__).parent / "third_party" / "bfcl" / "data"

# Category name -> (prompt-file sha256, possible_answer-file sha256), duplicated
# from scripts/vendor_bfcl.py so loading fails closed even without the script.
# The corpus is the exam; if its bytes are not the pinned bytes, the score is
# not the score we think it is.
_CATEGORY_SHA256: dict[str, tuple[str, str]] = {
    "simple_python": (
        "82dd63ba502eb2520c6b5d1d9a5c4b590e03ff261565175561f6228a367d1991",
        "90cd5bc653690ee8e459b5b3f3fc9458606f7f3fcbf795bb51b7dc581f8c86dc",
    ),
    "multiple": (
        "aef168155ebd74b7ac2401198b201343bc7d16d7a3d7e0d4e6d8ee82c6969b2a",
        "244e00ce9395df948bcafc7bee64e8f9c87ef70887587d83cae45b13699f3047",
    ),
    "parallel": (
        "19f51a82eff42e5d62541aa500115a056eb78f437c2ba1f10415fd7c8e5dda84",
        "8a6aa19c1adddc6a5a2f7e40f9dbf30cc7e95815e7b830c90589ab318229e0f0",
    ),
    "parallel_multiple": (
        "8863ea8433239f55c5f016154cf0830853c89f693c6ea270396a2fa121960579",
        "5ebf24f458c1f16300c05505d83d6f0a1b68b79be273a033febd0d4f840507e3",
    ),
}

_EXPECTED_COUNTS = {
    "simple_python": 400,
    "multiple": 200,
    "parallel": 200,
    "parallel_multiple": 200,
}

_HOLDOUT_PCT = 20
_MAX_FAILURE_TRACES = 5

_RESPONSE_INSTRUCTIONS = """\
You are given a task and a set of available functions. Decide which function(s) \
to call and with which arguments to complete the task.

Available functions (JSON schemas):
{functions}

Task: {question}

Respond with ONLY a JSON array of function calls, no prose, in the form:
[{{"name": "<function_name>", "arguments": {{"<param>": <value>, ...}}}}]
Use one object per call. If the task requires several calls, include several \
objects. Use exact function and parameter names from the schemas."""


class BFCLUnavailableError(RuntimeError):
    """The real BFCL adapter cannot run, and must not silently downgrade."""


def available() -> tuple[bool, str]:
    """Can the real BFCL adapter run in this environment? ``(ok, reason)``.

    Same optional-includes contract as ``ifeval_real.available`` (see its
    docstring for the availability-vs-integrity distinction). BFCL's vendored
    checker is stdlib-only, so in practice this only fails when the vendored
    tree itself is missing — there is no extra to install.
    """
    for category in _CATEGORY_SHA256:
        for path in (
            _DATA_DIR / f"BFCL_v4_{category}.json",
            _DATA_DIR / "possible_answer" / f"BFCL_v4_{category}.json",
        ):
            if not path.is_file():
                return (
                    False,
                    f"corpus file missing at {path} — run `python3 scripts/vendor_bfcl.py`",
                )
    try:
        from .third_party.bfcl.ast_checker import ast_checker  # noqa: F401
    except ImportError as exc:
        return False, f"vendored checker broken ({exc}) — run `python3 scripts/vendor_bfcl.py`"
    return True, ""


def _verified_lines(path: Path, expected_sha: str) -> list[dict[str, Any]]:
    if not path.is_file():
        raise BFCLUnavailableError(
            f"official BFCL file missing at {path}. "
            "Run `python3 scripts/vendor_bfcl.py` to restore it."
        )
    raw = path.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected_sha:
        raise BFCLUnavailableError(
            f"official BFCL file at {path} does not match its pinned checksum.\n"
            f"  pinned: {expected_sha}\n  actual: {actual}\n"
            "The exam has been modified. Refusing to score against it — restore "
            "with `python3 scripts/vendor_bfcl.py`."
        )
    return [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]


def bfcl_split_of(instance_id: str) -> Split:
    """Deterministic train/holdout assignment, hashed for the same reasons as
    IFEval's ``split_of``: stable under reordering, and uncorrelated with the
    corpus's own id ordering."""
    digest = hashlib.sha256(f"bfcl:{instance_id}".encode()).digest()
    return "holdout" if digest[0] % 100 < _HOLDOUT_PCT else "train"


def load_bfcl_corpus(split: Split = "all") -> list[dict[str, Any]]:
    """The 1,000 Python-AST instances, checksum-verified on every load.

    Each returned record carries ``category``, the prompt record fields, and
    ``ground_truth`` joined from the official possible_answer file. Load-time
    verification, not just CI: the corpus sits on the RSI loop's own writable
    tree (see ``ifeval_real.load_corpus``).
    """
    records: list[dict[str, Any]] = []
    for category, (prompt_sha, answer_sha) in _CATEGORY_SHA256.items():
        prompts = _verified_lines(_DATA_DIR / f"BFCL_v4_{category}.json", prompt_sha)
        answers = _verified_lines(
            _DATA_DIR / "possible_answer" / f"BFCL_v4_{category}.json", answer_sha
        )
        if len(prompts) != _EXPECTED_COUNTS[category]:
            raise BFCLUnavailableError(
                f"expected {_EXPECTED_COUNTS[category]} {category} instances, found {len(prompts)}"
            )
        by_id = {a["id"]: a for a in answers}
        for p in prompts:
            answer = by_id.get(p["id"])
            if answer is None:
                raise BFCLUnavailableError(f"{p['id']}: no ground truth in possible_answer file")
            records.append({**p, "category": category, "ground_truth": answer["ground_truth"]})
    if split == "all":
        return records
    return [r for r in records if bfcl_split_of(r["id"]) == split]


def _checker() -> tuple[Any, Any]:
    """Import the vendored official checker (stdlib-only; no extra needed)."""
    try:
        from .third_party.bfcl.ast_checker import ast_checker
        from .third_party.bfcl.enums import Language
    except ImportError as exc:  # pragma: no cover - only on a broken tree
        raise BFCLUnavailableError(
            f"{exc}\n\nThe vendored BFCL checker is missing or broken. "
            "Run `python3 scripts/vendor_bfcl.py` to restore it."
        ) from exc
    return ast_checker, Language


def parse_tool_calls(response: str) -> list[dict[str, Any]] | None:
    """Parse the genome's JSON response into the checker's decoded form.

    Returns ``[{name: arguments}, ...]`` or ``None`` if unusable. Adapter-side
    code (ours): it defines the response *format*, not the verdict. Tolerates a
    fenced code block because models add them; anything beyond that is the
    genome's problem — the official harness likewise scores undecodable output
    as wrong rather than repairing it.
    """
    text = response.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        body = [ln for ln in lines[1:] if not ln.strip().startswith("```")]
        text = "\n".join(body).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict):
        data = [data]  # a bare single call is unambiguous; accept it
    if not isinstance(data, list) or not data:
        return None
    decoded: list[dict[str, Any]] = []
    for call in data:
        if (
            not isinstance(call, dict)
            or not isinstance(call.get("name"), str)
            or not isinstance(call.get("arguments"), dict)
        ):
            return None
        decoded.append({call["name"]: call["arguments"]})
    return decoded


@dataclass
class _Totals:
    valid: int = 0
    errors: int = 0
    unparseable: int = 0
    cost_usd: float = 0.0
    by_category: dict[str, list[int]] = field(default_factory=dict)  # cat -> [valid, seen]
    failure_traces: list[dict[str, Any]] = field(default_factory=list)

    def see(self, category: str, ok: bool) -> None:
        bucket = self.by_category.setdefault(category, [0, 0])
        bucket[1] += 1
        if ok:
            bucket[0] += 1
            self.valid += 1

    def trace(self, record: dict[str, Any], error_type: str, detail: Any) -> None:
        if len(self.failure_traces) < _MAX_FAILURE_TRACES:
            self.failure_traces.append(
                {
                    "id": record["id"],
                    "category": record["category"],
                    "error_type": error_type,
                    "detail": detail,
                }
            )


async def run_bfcl_real(
    genome: PipelineGenome,
    llm_call: Any,
    *,
    split: Split = "train",
    max_prompts: int | None = None,
    concurrency: int = 8,
    timeout_s: float = 60.0,
) -> EvalResult:
    """Score ``genome`` on the official BFCL Python-AST track.

    Same contract as ``run_ifeval_real``: ``split="train"`` is what the loop's
    fitness may see, ``"holdout"`` is the supervisor's, ``"all"`` is the only
    split whose per-category numbers are official-comparable; ``max_prompts``
    bounds cost and disqualifies comparability; errors are counted, never
    hidden; sampling is deterministic.
    """
    if llm_call is None:
        raise ValueError(
            "run_bfcl_real requires an llm_call — there is no stub/heuristic "
            "fallback (SPEC-202: never produce a fabricated score)"
        )
    if concurrency < 1:
        raise ValueError(f"concurrency must be >= 1, got {concurrency}")

    ast_checker, language = _checker()
    available = load_bfcl_corpus(split)
    records = _sample(available, max_prompts)
    sampled = len(records) < len(available)
    if not records:
        raise BFCLUnavailableError(f"BFCL split {split!r} selected zero instances")

    start = time.monotonic()
    system_prompt = build_system_prompt(genome)
    model_config = build_model_config(genome)
    semaphore = asyncio.Semaphore(concurrency)

    async def fetch(record: dict[str, Any]) -> tuple[dict[str, Any], str | None, str | None]:
        prompt = _RESPONSE_INSTRUCTIONS.format(
            functions=json.dumps(record["function"], indent=2),
            question=record["question"][0][0]["content"],
        )
        async with semaphore:
            try:
                response = await asyncio.wait_for(
                    llm_call(
                        build_messages(system_prompt, prompt),
                        temperature=model_config.get("temperature", 0.1),
                        max_tokens=model_config.get("max_tokens", 2048),
                    ),
                    timeout=timeout_s,
                )
                return record, str(response), None
            except (TimeoutError, Exception) as exc:
                return record, None, f"{type(exc).__name__}: {exc}"

    responses = await asyncio.gather(*(fetch(r) for r in records))

    totals = _Totals()
    for record, response, error in responses:
        if error is not None:
            totals.errors += 1
            totals.see(record["category"], False)
            totals.trace(record, "adapter:llm_error", error)
            continue
        totals.cost_usd += 0.001
        decoded = parse_tool_calls(response or "")
        if decoded is None:
            totals.unparseable += 1
            totals.see(record["category"], False)
            totals.trace(record, "adapter:unparseable_response", (response or "")[:200])
            continue
        verdict = ast_checker(
            record["function"],
            decoded,
            record["ground_truth"],
            language.PYTHON,
            record["category"],
            "maistro-genome",
        )
        ok = bool(verdict["valid"])
        totals.see(record["category"], ok)
        if not ok:
            totals.trace(record, verdict.get("error_type", "unknown"), verdict.get("error"))

    n = len(records)
    elapsed = time.monotonic() - start
    per_category = {
        cat: round(valid / seen, 4) if seen else None
        for cat, (valid, seen) in sorted(totals.by_category.items())
    }

    return EvalResult(
        benchmark="bfcl",
        score=round(totals.valid / n, 4),
        cost_usd=round(totals.cost_usd, 4),
        duration_seconds=round(elapsed, 3),
        samples_evaluated=n,
        metadata={
            "fidelity": "real",
            "check": "official_bfcl_ast_checker",
            "grader": "bfcl-eval 2026.3.23 ast_checker (vendored, pinned, no-accommodation shim)",
            "track": "python_ast",
            "total_samples": n,
            "corpus_size": sum(_EXPECTED_COUNTS.values()),
            "split": split,
            # The leaderboard-comparable numbers: per-category accuracy under
            # the official checker. The headline `score` is our instance-
            # weighted aggregate of these, not a leaderboard column.
            "accuracy_by_category": per_category,
            "sampled": sampled,
            "requested_prompts": max_prompts,
            "official_comparable": split == "all" and not sampled and totals.errors == 0,
            "errors": totals.errors,
            # Counted apart from checker rejections: a genome that reasons well
            # but formats badly needs a different fix (prompt/format slot) than
            # one that picks wrong functions, and reflection can only act on
            # the distinction if the result carries it.
            "unparseable_responses": totals.unparseable,
            "failures": totals.failure_traces,
        },
    )


def _sample(records: list[dict[str, Any]], max_prompts: int | None) -> list[dict[str, Any]]:
    """Deterministic subsample, hash-ordered — same reasoning as ifeval_real."""
    if max_prompts is None or max_prompts >= len(records):
        return records
    ordered = sorted(records, key=lambda r: hashlib.sha256(f"pick:{r['id']}".encode()).digest())
    return ordered[:max_prompts]
