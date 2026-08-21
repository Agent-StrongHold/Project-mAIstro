"""Post-cutoff bug-fix tasks mined from this repository's own git history.

Implements the consumer half of SPEC-281 §4; ``scripts/generate_repo_tasks.py``
is the producer. Read that script's docstring for how a commit becomes a task —
this module is about loading a generated corpus safely and, above all, about
**not letting a contaminated task count as a clean one**.

What makes this corpus different from everything in ``third_party/``
--------------------------------------------------------------------
IFEval and BFCL are public. Assume both are in every base model's weights; the
train/holdout splits there detect the loop overfitting *through the harness*,
and can do nothing about pretraining contamination. This corpus is the only one
in the package with a real answer to that, and the answer is chronological: a
bug fixed after a model's training cutoff cannot have been memorised, because it
did not exist.

That defence is **per model, not per corpus**, which is the single most
important thing to get right here. The same task is clean for a model trained
last year and contaminated for one trained last week. So a corpus is never
"post-cutoff" on its own — it is post-cutoff *for a given model*, and every load
must name that model or its cutoff date.

Fail-closed on unknown models
-----------------------------
``load_repo_tasks`` refuses to guess. An unrecognised model raises rather than
defaulting to "probably fine", because the failure mode of guessing is silent:
you would score a model against tasks it may have trained on and read the result
as contamination-free evidence. A loud error costs one line of configuration; a
wrong cutoff invalidates every number derived from it.

Honest limits — repeated here because a home-made benchmark gets quoted
-----------------------------------------------------------------------
* ``official_comparable`` is **always False**. There is no published number to
  compare to. This measures the ability to fix bugs in *this* codebase.
* Difficulty is uncontrolled and drifts as the repo changes. Absolute scores are
  not comparable across regenerations — only genome-vs-genome within one pinned
  snapshot is meaningful.
* Small. Tens of tasks, not thousands. ``samples_evaluated`` travels with every
  result and a percentage without it is meaningless.

Not wired into any harness yet — deliberately
---------------------------------------------
This is SPEC-281 §4's **consumer half only**: it loads and validates a corpus.
There is no ``run_repo_history()``, so there is nothing to put in
``PROXY_BENCHMARKS`` or ``REAL_BENCHMARKS``, and it belongs in neither anyway —
``official_comparable`` is always False, so it is not ``real``, and it is not a
handcrafted sample set, so it is not ``proxy``. Deciding where a third tier
lives is a harness change, not a loader change.

``MODEL_CUTOFFS`` is also still empty, so ``resolve_cutoff`` refuses every
model. That is the intended direction to fail in — an unwired loader scores
nothing, where a wired one with no cutoffs would score everything as clean.

It is therefore listed in ``quality/reachability-baseline.json``. That listing
is the honest record of a staged component, not a dismissal: it should come off
the list when the runner and the tier decision land together. Stating it here
because a module whose docstring reads like a working benchmark, sitting beside
seven that are, is exactly how built-but-never-wired code gets quoted as if it
ran.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

_CORPUS = Path(__file__).parent / "corpora" / "repo_history_tasks.json"

# sha256 of the generated corpus, pinned in *code* rather than in a sidecar file.
# A sidecar sitting beside the corpus would be editable in the same diff as the
# corpus itself, which makes the check decorative — the exact flaw that let a
# backdoored IFEval grader pass `vendor_ifeval.py --check`. Pinning it here puts
# regeneration on the protected surface (`maistro_evolve/benchmarks/` is in
# SENSITIVE_PATH_PATTERNS) and makes every refresh a visible code change.
#
# Regenerate with `python3 scripts/generate_repo_tasks.py`; it prints the digest.
_CORPUS_SHA256 = "34b73f2dd46731453c12550988c23b3eb375a1c46e9bbc5320b1e0da94d36e14"

# Training cutoffs for models this repo scores against. Deliberately explicit
# and deliberately incomplete: adding a model is a decision someone makes on
# purpose, not something inferred from a model id string.
MODEL_CUTOFFS: dict[str, date] = {}


class RepoHistoryUnavailableError(RuntimeError):
    """The corpus is missing, modified, or cannot be safely interpreted."""


class ContaminationError(RuntimeError):
    """A load would have produced tasks that are not provably post-cutoff.

    Separate from ``RepoHistoryUnavailableError`` because the two demand
    different responses: an unavailable corpus is an environment problem to fix,
    while this means the *result would have been misleading* — the caller either
    supplies a cutoff or accepts that the run carries no contamination claim.
    """


@dataclass(frozen=True)
class RepoTask:
    """One fail-to-pass task. ``gold_patch`` is reference-only, never shown."""

    task_id: str
    repo_state: str
    commit_date: str
    issue_text: str
    failing_tests: tuple[str, ...]
    test_patch: str
    gold_patch: str

    @property
    def committed_on(self) -> date:
        return datetime.fromisoformat(self.commit_date).date()

    def is_post_cutoff(self, cutoff: date) -> bool:
        """True iff this task provably postdates ``cutoff``.

        Strict inequality: a task committed *on* the cutoff date is not provably
        after it, and the whole value of this corpus is that its tasks are
        provably unseen. Ties go to caution.
        """
        return self.committed_on > cutoff


def available() -> tuple[bool, str]:
    """Optional-includes probe, matching ifeval_real/bfcl_real."""
    if not _CORPUS.is_file():
        return False, (
            f"corpus missing at {_CORPUS} — generate it with "
            "`python3 scripts/generate_repo_tasks.py`"
        )
    if _CORPUS_SHA256 == "PENDING_FIRST_GENERATION":
        return False, (
            "corpus digest not yet pinned in repo_history._CORPUS_SHA256 — "
            "run the generator and paste the digest it prints"
        )
    return True, ""


def resolve_cutoff(model: str | None = None, cutoff: date | None = None) -> date:
    """Determine the training cutoff to filter against, or raise.

    Exactly one of ``model`` (looked up in ``MODEL_CUTOFFS``) or ``cutoff`` (an
    explicit override, for a model not in the table) is required. Neither
    defaults, because there is no safe default: assuming an early cutoff admits
    contaminated tasks, and assuming a late one silently empties the corpus.
    """
    if cutoff is not None:
        return cutoff
    if model is None:
        raise ContaminationError(
            "repo_history requires a model or an explicit cutoff date. Its only "
            "contamination defence is chronological, and that is meaningless "
            "without knowing what the model was trained on."
        )
    known = MODEL_CUTOFFS.get(model)
    if known is None:
        raise ContaminationError(
            f"no training cutoff recorded for model {model!r}. Add it to "
            "repo_history.MODEL_CUTOFFS or pass cutoff=date(...). Refusing to "
            "guess: scoring against tasks the model may have trained on, and "
            "reporting it as contamination-free, is the failure this corpus "
            "exists to prevent."
        )
    return known


def load_repo_tasks(
    model: str | None = None,
    *,
    cutoff: date | None = None,
    require_nonempty: bool = True,
) -> list[RepoTask]:
    """Checksum-verified tasks that provably postdate the model's cutoff.

    Raises:
        RepoHistoryUnavailableError: corpus missing or its bytes do not match
            the pinned digest.
        ContaminationError: no cutoff could be resolved, or the filter left no
            tasks (``require_nonempty``) — an empty corpus silently scoring 0.0
            would look identical to a genome that failed everything.
    """
    ok, reason = available()
    if not ok:
        raise RepoHistoryUnavailableError(reason)

    raw = _CORPUS.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != _CORPUS_SHA256:
        raise RepoHistoryUnavailableError(
            f"repo-history corpus at {_CORPUS} does not match its pinned "
            f"checksum.\n  pinned: {_CORPUS_SHA256}\n  actual: {actual}\n"
            "Regenerate with scripts/generate_repo_tasks.py and update the pin, "
            "or restore the file. Refusing to score against an unverified exam."
        )

    body: dict[str, Any] = json.loads(raw.decode("utf-8"))
    effective = resolve_cutoff(model, cutoff)
    tasks = [
        RepoTask(
            task_id=t["task_id"],
            repo_state=t["repo_state"],
            commit_date=t["commit_date"],
            issue_text=t["issue_text"],
            failing_tests=tuple(t["failing_tests"]),
            test_patch=t["test_patch"],
            gold_patch=t["gold_patch"],
        )
        for t in body.get("tasks", [])
    ]
    fresh = [t for t in tasks if t.is_post_cutoff(effective)]

    if require_nonempty and not fresh:
        raise ContaminationError(
            f"every one of the {len(tasks)} task(s) in the corpus predates the "
            f"cutoff {effective.isoformat()}, so none is provably unseen by this "
            "model. Regenerate the corpus from newer commits rather than scoring "
            "against contaminated tasks."
        )
    return fresh


def corpus_metadata() -> dict[str, Any]:
    """Provenance of the generated corpus: source commit, counts, filters.

    Exposed so a result can carry how its exam was built — which commit range,
    which size ceilings — rather than leaving a reader to assume.
    """
    if not _CORPUS.is_file():
        raise RepoHistoryUnavailableError(f"corpus missing at {_CORPUS}")
    body = json.loads(_CORPUS.read_text(encoding="utf-8"))
    return {
        "generated_from": body.get("generated_from"),
        "counts": body.get("counts", {}),
        "filters": body.get("filters", {}),
        # Never true for this corpus, under any configuration. Stated as data so
        # a consumer reading metadata uniformly cannot miss it.
        "official_comparable": False,
        "fidelity": "real",
        "contamination_defence": "chronological (post-cutoff commits)",
    }
