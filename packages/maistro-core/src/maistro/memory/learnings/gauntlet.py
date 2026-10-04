"""Independent Gauntlet validation before collective knowledge promotion (M4-B2).

Local success — one Run extracting a correction, or a rising `hit_count` — is
belief, not institutional knowledge. A learning proposed for reuse beyond the
scope that learned it must first survive an *independent* evaluation: trials
executed in contexts other than the one that produced it, judged against the
frozen candidate content, and run as canonical Runs so the verdict names the
exact executions that justify promotion.

The seams, in the order a candidate meets them:

- :func:`freeze_candidate` snapshots the learning into an immutable
  :class:`GauntletCandidate` with a content hash. Evaluation judges *that*
  snapshot; if the stored row's content no longer matches the hash a verdict
  was minted for, the verdict is rejected (`frozen_content`), so a candidate
  cannot be mutated after evaluation and still promote on the old evidence.
- :class:`LearningEvaluator` executes the trials. Its contract is to run each
  trial as a canonical Run (`Goal -> Graph -> Run -> NodeRun -> Attempt`) of
  the frozen candidate content in one trial context, and to return an
  :class:`EvaluationRecord` naming each trial's Run id. Nothing here executes
  Runs itself — the canonical execution spine has one owner, and a validator
  that re-implements execution would be a competing execution authority.
- :class:`IndependentTrialsGauntlet` judges the record: producer attribution,
  independence of the evaluation set from the producing evidence, coverage
  across contexts/regimes with held-out trials, applicability of each trial to
  the candidate's declared regimes, and the success rate.
- :class:`ChainedGauntlet` composes gauntlets; every member must accept.

A rejected learning is *not* punished: its row stays `active` with every
recorded outcome intact — failure evidence is knowledge too (the anti-learning
half of the bargain) — but it cannot join the collective repertoire.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from maistro.runs.model import RunStatus
from maistro.types.memory import Learning

if TYPE_CHECKING:
    from maistro.runs.store import RunStore

#: Provenance marker every gauntlet trial Run must carry. The Gauntlet reads
#: it back off the canonical Run store, so an evaluator cannot pass off an
#: unrelated Run — one that exists and completed, but executed something else
#: entirely — as this candidate's evidence.
GAUNTLET_TRIAL_PURPOSE = "learning-gauntlet-trial"


def learning_content_hash(
    learning: str,
    trigger_keys: list[str] | tuple[str, ...],
    *,
    tool_name: str = "",
    category: str = "",
    source_query: str = "",
) -> str:
    """Hash the candidate content a Gauntlet would freeze.

    Every field that participates is part of what "this learning" means: the
    correction text, the keys that inject it, the tool it corrects, and where
    it came from. Any drift in any of them is different knowledge, and a
    verdict minted for one must not be spent on the other.
    """
    payload = json.dumps(
        {
            "learning": learning,
            "trigger_keys": list(trigger_keys),
            "tool_name": tool_name,
            "category": category,
            "source_query": source_query,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class GauntletCandidate:
    """The frozen candidate a Gauntlet evaluates.

    Built once at evaluation time by :func:`freeze_candidate`; the Gauntlet
    never reads the mutable store row again, so a candidate cannot shift
    under evaluation. `producer_run_id` is the Run whose evidence produced the
    learning (ADR-083026-e602): the evaluation set must be independent of it.
    """

    learning_id: int
    content_hash: str
    learning: str
    trigger_keys: tuple[str, ...]
    tool_name: str
    category: str
    producer_run_id: str
    #: The regimes (task types / tools) the candidate claims to apply to.
    #: Derived from the candidate's own category and tool name; a trial
    #: exercising a regime outside this set proves nothing about this
    #: candidate, and the Gauntlet rejects records containing one.
    applicability: tuple[str, ...] = ()


def freeze_candidate(learning: Learning) -> GauntletCandidate:
    """Snapshot a learning into the frozen candidate a Gauntlet evaluates."""
    applicability: list[str] = []
    for regime in (learning.category, learning.tool_name):
        if regime and regime not in applicability:
            applicability.append(regime)
    return GauntletCandidate(
        learning_id=learning.id or 0,
        content_hash=learning_content_hash(
            learning.learning,
            learning.trigger_keys,
            tool_name=learning.tool_name,
            category=learning.category,
            source_query=learning.source_query,
        ),
        learning=learning.learning,
        trigger_keys=tuple(learning.trigger_keys),
        tool_name=learning.tool_name,
        category=learning.category,
        producer_run_id=learning.run_id,
        applicability=tuple(applicability),
    )


@dataclass(frozen=True)
class TrialResult:
    """The outcome of one trial, naming the canonical Run that executed it.

    `run_id` must be the id of a canonical Run — created through the
    `Goal -> Graph -> Run` spine — that executed this trial of the frozen
    candidate content, carrying provenance the Gauntlet can bind back: the
    `GAUNTLET_TRIAL_PURPOSE` marker, the candidate's content hash, this
    context id, and the held-out flag. It is what the promoted learning will
    name as evidence, so it is recorded verbatim and never synthesized here.
    """

    context_id: str
    regime: str
    run_id: str
    success: bool
    #: True for a context the producing evidence never touched: held-out
    #: trials are how an evaluation set proves it is independent of the
    #: evidence that induced the learning, rather than re-measuring the
    #: same context that produced it.
    held_out: bool = False
    notes: str = ""


@dataclass(frozen=True)
class EvaluationRecord:
    """What an evaluator hands back: trials of one frozen candidate.

    `content_hash` must be the hash of the candidate the trials actually
    exercised. The Gauntlet compares it to the candidate it froze, so an
    evaluator that evaluated different content (or a row that mutated between
    freezing and judging) cannot spend one candidate's evidence on another.
    """

    evaluator: str
    evaluator_version: str
    content_hash: str
    trials: tuple[TrialResult, ...] = ()


@runtime_checkable
class LearningEvaluator(Protocol):
    """Runs independent trials of a frozen candidate as canonical Runs.

    Implementations own trial execution. The protocol deliberately hands back
    only records: trial execution must go through the canonical execution
    spine, and the Run ids in the returned trials are the audit trail proving
    it did.
    """

    name: str
    version: str

    async def evaluate(self, candidate: GauntletCandidate) -> EvaluationRecord:
        """Execute the trial set for this frozen candidate; return the record."""
        ...


@dataclass(frozen=True)
class GauntletVerdict:
    """A Gauntlet's decision, with the provenance a promotion records.

    On acceptance, `evaluation_run_ids` are the exact canonical Runs that
    validated the candidate, `evaluator_name`/`evaluator_version` identify the
    judge, and `content_hash` pins the frozen content that was validated. The
    promoter writes all of them onto the promoted learning, so institutional
    knowledge carries its own audit trail.
    """

    ok: bool
    reason: str = ""
    gauntlet: str = ""
    failed_checks: tuple[str, ...] = ()
    evaluation_run_ids: tuple[str, ...] = ()
    evaluator_name: str = ""
    evaluator_version: str = ""
    content_hash: str = ""


@runtime_checkable
class LearningGauntlet(Protocol):
    """An independent validator standing between local success and the repertoire."""

    name: str

    async def evaluate(self, learning: Learning) -> GauntletVerdict:
        """Judge the learning; return the verdict with its provenance."""
        ...


class IndependentTrialsGauntlet:
    """Judge an evaluation record against independence and coverage rules.

    Independent by construction: the Gauntlet freezes the candidate itself,
    hands only the frozen snapshot to the evaluator, and judges the returned
    record. It never consults `hit_count` — recall frequency says how often a
    learning was injected, not whether following it helped — and it never
    trusts the producer's own account of the learning. Nor does it trust the
    record's own account of its trials: every named Run id is resolved
    against the canonical Run store (`run_store=`) before a verdict is
    minted, and without a store the gate fails closed — unresolvable
    provenance cannot justify promotion.

    Checks (each names a failed check in the verdict):

    - `producer` — the learning names the Run that produced it. Unattributed
      knowledge cannot be validated, because there is no producing evidence
      for an evaluation set to be independent *of*.
    - `frozen_content` — the record was produced for exactly the frozen
      candidate (content hashes match).
    - `evaluator_identity` — the record self-identifies the evaluator and
      version that actually ran the trials, and they match the evaluator
      this Gauntlet dispatched to. A wrapper that delegated to a different
      runtime must not lend its own name to the promoted provenance.
    - `canonical_runs` — every trial names a Run id that resolves to a real
      Run on the canonical Run store, and no two trials share one: one Run
      cannot be two independent trials, and a fabricated, mistyped, or
      deleted id is no evidence at all.
    - `run_outcome` — each named Run reached terminal success on the spine
      (`completed`). A trial still running, failed, cancelled, or timed out
      proves nothing about the candidate.
    - `run_provenance` — each Run's provenance binds it to exactly this
      evaluation: the gauntlet-trial purpose, this candidate's frozen content
      hash, the trial's reported context, and its held-out flag. A real,
      completed Run from some other execution cannot be spent as this
      candidate's evidence.
    - `independence` — the evaluation set does not include the producing Run.
      Trials re-running the very execution that induced the learning would
      measure the producer twice, not validate the correction.
    - `held_out` — at least `min_held_out` trials ran in contexts marked
      held-out (contexts the producing evidence never touched).
    - `contexts` — at least `min_contexts` distinct trial contexts.
    - `regimes` — at least `min_regimes` distinct trial regimes.
    - `applicability` — every trial exercised a regime the candidate is
      applicable to (when the candidate declares any).
    - `min_trials` / `success_rate` — enough trials, and enough of them
      succeeded.
    """

    def __init__(
        self,
        evaluator: LearningEvaluator,
        *,
        name: str = "independent-trials",
        min_trials: int = 2,
        min_contexts: int = 2,
        min_regimes: int = 1,
        min_held_out: int = 1,
        min_success_rate: float = 0.6,
        run_store: RunStore | None = None,
    ) -> None:
        if min_trials < 1:
            raise ValueError("min_trials must be at least 1")
        if min_held_out < 1:
            raise ValueError(
                "min_held_out must be at least 1: validation without "
                "a held-out trial is the producer grading its own homework"
            )
        self.name = name
        self._evaluator = evaluator
        self._min_trials = min_trials
        self._min_contexts = min_contexts
        self._min_regimes = min_regimes
        self._min_held_out = min_held_out
        self._min_success_rate = min_success_rate
        self._run_store = run_store

    async def evaluate(self, learning: Learning) -> GauntletVerdict:
        """Freeze, evaluate, judge. One verdict names every failed check."""
        candidate = freeze_candidate(learning)
        failed: list[str] = []
        if not candidate.producer_run_id:
            failed.append("producer")

        record = await self._evaluator.evaluate(candidate)

        if record.content_hash != candidate.content_hash:
            failed.append("frozen_content")
        if (
            record.evaluator != self._evaluator.name
            or record.evaluator_version != self._evaluator.version
        ):
            failed.append("evaluator_identity")
        failed.extend(await self._run_checks(candidate, record))
        failed.extend(self._coverage_checks(candidate, record))
        failed.extend(self._efficacy_checks(record))

        if failed:
            return GauntletVerdict(
                ok=False,
                reason=f"failed: {', '.join(sorted(set(failed)))}",
                gauntlet=self.name,
                failed_checks=tuple(sorted(set(failed))),
                evaluator_name=self._evaluator.name,
                evaluator_version=self._evaluator.version,
                content_hash=candidate.content_hash,
            )
        successes = sum(1 for trial in record.trials if trial.success)
        return GauntletVerdict(
            ok=True,
            reason=(
                f"{successes}/{len(record.trials)} trials succeeded across "
                f"{len({t.context_id for t in record.trials})} contexts "
                f"({self._held_out(record)} held-out)"
            ),
            gauntlet=self.name,
            evaluation_run_ids=tuple(trial.run_id for trial in record.trials),
            evaluator_name=self._evaluator.name,
            evaluator_version=self._evaluator.version,
            content_hash=candidate.content_hash,
        )

    @staticmethod
    def _held_out(record: EvaluationRecord) -> int:
        return sum(1 for trial in record.trials if trial.held_out)

    async def _run_checks(
        self, candidate: GauntletCandidate, record: EvaluationRecord
    ) -> list[str]:
        """Provenance checks on the trial set: every trial names one distinct
        canonical Run that exists, completed, and is provenance-bound to this
        candidate — and none of them is the Run that produced the learning."""
        failed: list[str] = []
        run_ids = [trial.run_id for trial in record.trials]
        # An empty id names no Run, and one Run cannot be two independent
        # trials — hence both halves of the `or`.
        if "" in run_ids or len(set(run_ids)) != len(run_ids):
            failed.append("canonical_runs")
        if candidate.producer_run_id and candidate.producer_run_id in run_ids:
            failed.append("independence")
        failed.extend(await self._run_store_checks(candidate, record))
        return failed

    async def _run_store_checks(
        self, candidate: GauntletCandidate, record: EvaluationRecord
    ) -> list[str]:
        """Resolve every named trial Run against the canonical Run store.

        A run id in a record is a claim, not evidence: any distinct nonempty
        string would pass a shape check, letting mistyped, deleted, or
        fabricated ids promote with an audit trail that cannot be resolved.
        So each id is read back from the store and must be a completed Run
        whose provenance binds it to this candidate, this trial context, and
        the reported held-out flag. With no store configured the check fails
        closed: the gate would be certifying executions it cannot see.
        """
        failed: list[str] = []
        if self._run_store is None:
            if any(trial.run_id for trial in record.trials):
                failed.append("canonical_runs")
            return failed
        for trial in record.trials:
            if not trial.run_id:
                continue
            run = await self._run_store.get_run(trial.run_id)
            if run is None:
                failed.append("canonical_runs")
                continue
            if run.status != RunStatus.COMPLETED:
                failed.append("run_outcome")
            provenance = run.provenance if isinstance(run.provenance, dict) else {}
            if (
                provenance.get("purpose") != GAUNTLET_TRIAL_PURPOSE
                or provenance.get("gauntlet_candidate_content_hash") != candidate.content_hash
                or provenance.get("trial_context_id") != trial.context_id
                or bool(provenance.get("held_out")) != trial.held_out
            ):
                failed.append("run_provenance")
        return failed

    def _coverage_checks(self, candidate: GauntletCandidate, record: EvaluationRecord) -> list[str]:
        """Spread checks: enough held-out trials, distinct contexts and regimes,
        and no trial outside the regimes the candidate claims to apply to."""
        failed: list[str] = []
        if self._held_out(record) < self._min_held_out:
            failed.append("held_out")
        if len({trial.context_id for trial in record.trials}) < self._min_contexts:
            failed.append("contexts")
        if len({trial.regime for trial in record.trials}) < self._min_regimes:
            failed.append("regimes")
        applicable = set(candidate.applicability)
        if applicable and any(trial.regime not in applicable for trial in record.trials):
            failed.append("applicability")
        return failed

    def _efficacy_checks(self, record: EvaluationRecord) -> list[str]:
        """Outcome checks: enough trials, and enough of them succeeded."""
        failed: list[str] = []
        if len(record.trials) < self._min_trials:
            failed.append("min_trials")
        elif (
            # Unreachable with no trials: min_trials >= 1 means an empty record
            # already failed the len check above.
            sum(1 for trial in record.trials if trial.success) / len(record.trials)
            < self._min_success_rate
        ):
            failed.append("success_rate")
        return failed


@dataclass
class _ChainEvidence:
    """Mutable accumulator for ChainedGauntlet: the union of member provenance."""

    failed: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    run_ids: list[str] = field(default_factory=list)
    versions: list[str] = field(default_factory=list)
    content_hash: str = ""

    def absorb(self, verdict: GauntletVerdict, *, member_name: str, reason: str) -> None:
        """Fold one member's verdict into the chain evidence.

        A member that names no failed checks of its own still fails the chain
        under the member's name, so an opaque rejection is never silently
        dropped.
        """
        self.content_hash = self.content_hash or verdict.content_hash
        if verdict.evaluator_version and verdict.evaluator_version not in self.versions:
            self.versions.append(verdict.evaluator_version)
        self.run_ids.extend(rid for rid in verdict.evaluation_run_ids if rid not in self.run_ids)
        if not verdict.ok:
            self.failed.extend(verdict.failed_checks or (member_name,))
            self.reasons.append(reason)


class ChainedGauntlet:
    """Compose gauntlets: all must accept, failures are reported as the union."""

    def __init__(self, *members: LearningGauntlet, name: str = "gauntlet-chain") -> None:
        if not members:
            raise ValueError("a ChainedGauntlet needs at least one member gauntlet")
        self.name = name
        self._members = members

    async def evaluate(self, learning: Learning) -> GauntletVerdict:
        """Run every member; the chain passes only when each member passes."""
        merged = _ChainEvidence()
        for member in self._members:
            verdict = await member.evaluate(learning)
            merged.absorb(
                verdict, member_name=member.name, reason=f"{member.name}: {verdict.reason}"
            )
        if merged.failed:
            return GauntletVerdict(
                ok=False,
                reason="; ".join(merged.reasons),
                gauntlet=self.name,
                failed_checks=tuple(merged.failed),
                evaluation_run_ids=tuple(merged.run_ids),
                evaluator_name=self.name,
                evaluator_version="+".join(merged.versions),
                content_hash=merged.content_hash,
            )
        return GauntletVerdict(
            ok=True,
            reason="; ".join(f"{member.name}" for member in self._members),
            gauntlet=self.name,
            evaluation_run_ids=tuple(merged.run_ids),
            evaluator_name=self.name,
            evaluator_version="+".join(merged.versions),
            content_hash=merged.content_hash,
        )
