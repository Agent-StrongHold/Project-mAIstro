"""Governed design model-judge — rubric dimensions scored through Invocations.

A Rubric dimension declared ``model_judge`` is not a hidden sidecar chat: for
every (thesis x dimension) this node crosses the one governed model boundary
(:class:`ModelChatEgress`), so each judge call persists a canonical Invocation
correlated to the Run/NodeRun/Attempt that asked for it
(ADR-081226-6b46), and the eval record it writes names that Invocation.

Eval records are Run evidence in the one canonical shape (#792): a
``RunEvalScore`` row on the producing Run, naming the Goal revision, the
Rubric revision, the judge NodeRun and Attempt carrying it, the dimension,
the judge identity and — for ``model_judge`` — the Invocation that produced
the score. The rows are written through the canonical ``RunStore``, and
completeness is read back from that store through
:func:`maistro.runs.eval.eval_summary`: "eval complete" is a property of
persisted evidence, never of the judge's own intention. Run/NodeRun/Attempt
stays the only execution identity — there is no second eval lifecycle for
judges (#987), and no side ledger that could disagree with the Run.

``deterministic`` dimensions keep the persona ``RubricEval.score`` spirit:
in-process, declarative-vocabulary checks, no network — and they still write
canonical eval rows (a deterministic score names no judge, which is what the
canonical record requires). ``human`` dimensions are refused loudly: they wait
on the HITL answer surface (#794), which this node is not, and silently
skipping them would dress absence up as a score.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from maistro.capabilities.binding import Binding
from maistro.capabilities.model_chat import ModelChatEgress
from maistro.capabilities.providers.llm_gateway import ModelChatRequest
from maistro.graph.nodes import register_node
from maistro.graph.nodes.base import BaseNode, NodeContext, ReplaySemantics, replay_effect_key
from maistro.personas.vocabulary import evaluate
from maistro.providers.registry import InMemoryProviderRegistry
from maistro.providers.router import CostAwareRouter
from maistro.runs.eval import eval_summary
from maistro.runs.model import EvalJudge, EvalMethod, RunEvalScore
from maistro_design.governance import (
    build_model_egress,
    extract_json_payload,
    gateway_endpoint_from_env,
    resolve_design_binding,
    scan_model_text,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from maistro.capabilities.effect_context import CapabilityEffectContext
    from maistro.providers.protocols import LLMProviderRegistry, LLMRouter
    from maistro.runs.store import RunStore

JUDGE_NODE_KIND = "design.judge"

#: The canonical scoring-method vocabulary is maistro-core's (``#792``): a
#: dimension's method is one of ``deterministic`` / ``model_judge`` / ``human``.
#: Design does not mint a second vocabulary for the same word.
JudgeMethod = EvalMethod

_DETERMINISTIC_JUDGE_IDENTITY = "deterministic:rubric-vocabulary"

#: Score (0-100) at or above which a dimension counts as passed.
_DEFAULT_PASS_THRESHOLD = 60


class HumanJudgeNotResolvedError(RuntimeError):
    """A ``human`` dimension cannot be scored by this node.

    Human judgment waits on the HITL answer surface (#794). Refusing loudly
    keeps the Run truthful: the dimension has no score yet, and a node that
    skipped it while reporting eval-complete would be recording a lie.
    """


class DesignJudgeThesis(BaseModel):
    """One thesis payload handed to the judge."""

    model_config = ConfigDict(extra="forbid")

    thesis_id: str
    title: str = ""
    summary: str = ""
    body: str = ""
    #: Where this thesis landed, when the producer recorded it (thesis slots
    #: name their own NodeRun/Attempt in their outputs).
    node_run_id: str = ""
    attempt_id: str = ""


class DesignJudgeDimension(BaseModel):
    """One rubric dimension and the method that scores it (#791 ``method``)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    method: JudgeMethod
    #: model_judge: what this dimension asks the judge to assess.
    prompt: str = ""
    #: deterministic: declarative vocabulary checks (see
    #: ``maistro.personas.vocabulary``), scored 0-100 by weight, same spirit as
    #: persona ``RubricEval.score``.
    criteria: list[dict[str, object]] = Field(default_factory=list)


class DesignEvalRecord(BaseModel):
    """One (thesis x dimension) eval record — the ``#792`` Run evidence row.

    Every record names the revisions it judged against, the NodeRun/Attempt
    that carries it, the thesis, the judge identity and — for model_judge —
    the one Invocation whose model call produced the score.
    """

    model_config = ConfigDict(extra="forbid")

    eval_id: str
    run_id: str
    node_run_id: str
    attempt_id: str
    goal_id: str
    goal_revision: int
    rubric_id: str
    rubric_revision: int
    thesis_id: str
    thesis_node_run_id: str = ""
    dimension: str
    method: JudgeMethod
    judge_identity: str
    #: Empty only for deterministic records, which had no model call to name.
    invocation_id: str = ""
    score: int = Field(ge=0, le=100)
    passed: bool
    rationale: str = ""


class DesignJudgeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    theses: list[DesignJudgeThesis] = Field(min_length=1)
    dimensions: list[DesignJudgeDimension] = Field(min_length=1)
    goal_id: str = Field(description="Canonical Goal identity the scores are for")
    goal_revision: int = Field(ge=1, description="Exact Goal revision applied")
    rubric_id: str = Field(description="Canonical Rubric identity the dimensions belong to")
    rubric_revision: int = Field(ge=1, description="Exact Rubric revision applied")
    binding_id: str = Field(
        default="",
        description="Pre-authorized model.chat Binding used by model_judge dimensions",
    )
    judge_identity: str = Field(
        default="",
        description="Stable judge identity; defaults to the model the Invocation used",
    )
    model: str = Field(default="", description="Optional model alias; a Binding pin outranks it")
    timeout_s: float = Field(default=60.0, ge=1.0, le=600.0)
    pass_threshold: int = Field(
        default=_DEFAULT_PASS_THRESHOLD,
        ge=0,
        le=100,
        description="Score (0-100) at or above which a dimension counts as passed",
    )


class DesignJudgeOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Contract fields of the wave's output envelope: read by tests and
    #: downstream consumers of the NodeRun result, not by ``packages/*/src``
    #: code, so vulture's src-only scan cannot see the uses. They carry the
    #: repo's declarative-field noqa (consistency.py precedent) rather than a
    #: ledger row, because banking new debt needs a two-merge grant this
    #: branch cannot land.
    eval_complete: bool  # noqa: V107
    records: list[DesignEvalRecord]
    model_invocations: int = Field(  # noqa: V107
        description="Invocations spent on model_judge dimensions"
    )


_JUDGE_SYSTEM_PROMPT = (
    "You are a strict rubric judge for a design pack. Score the thesis against "
    "the stated dimension. Respond with exactly one strict JSON object: "
    '{"score": <integer 0-100>, "rationale": "<one paragraph>"}. '
    "No prose outside the JSON object."
)


@register_node
class DesignJudgeNode(BaseNode[DesignJudgeIn, DesignJudgeOut]):
    """Score every (thesis x dimension) pair; one Invocation per model_judge pair.

    Fail-closed rules this node keeps:

    - no authorized Binding refuses before any dimension runs, so the judge
      Attempt records a failure instead of a half-scored thesis set;
    - malformed or Warden-blocked judge responses raise — a hostile or broken
      judge response never becomes a score;
    - every pair's score is written to the canonical ``#792`` Run store before
      ``eval_complete`` is reported, and completeness is read back from that
      store, so a node that wrote nothing cannot claim a complete evaluation;
    - ``eval_complete`` is only ``True`` when every declared dimension has a
      persisted score and every ``model_judge`` record names a non-empty
      Invocation id.
    """

    kind: ClassVar[str] = JUDGE_NODE_KIND
    kind_category: ClassVar = "sync.llm"
    input_schema: ClassVar[type[BaseModel]] = DesignJudgeIn
    output_schema: ClassVar[type[BaseModel]] = DesignJudgeOut
    cost_hint: ClassVar[float] = 3.0
    # Retry-safe through the Invocation ledger, same as the thesis slots.
    replay_semantics: ClassVar[ReplaySemantics] = ReplaySemantics.EFFECT_KEY
    external_io: ClassVar[bool] = True
    display_name: ClassVar[str] = "Design: rubric judge"
    description: ClassVar[str] = (
        "Score rubric dimensions per thesis. model_judge pairs each get one "
        "governed model Invocation; deterministic pairs score in-process; "
        "human pairs are refused until #794. Writes canonical #792 eval "
        "records naming the revisions, NodeRun/Attempt, judge identity and "
        "Invocation."
    )
    #: The canonical Run store is not optional: the ``#792`` eval rows live
    #: there, and a judge that cannot persist them has no evidence to report.
    #: The production resolver refuses to construct this kind without one.
    required_authorities: ClassVar[Mapping[str, str]] = {"run_store": "run_store"}
    optional_authorities: ClassVar[Mapping[str, str]] = {
        "effect_context": "effect_context",
        "registry": "provider_registry",
        "router": "llm_router",
    }

    def __init__(
        self,
        *,
        effect_context: CapabilityEffectContext | None = None,
        registry: LLMProviderRegistry | None = None,
        router: LLMRouter | None = None,
        run_store: RunStore | None = None,
    ) -> None:
        self._effects = effect_context or _default_effects()
        self._registry: LLMProviderRegistry = (
            registry if registry is not None else InMemoryProviderRegistry()
        )
        self._router: LLMRouter = router if router is not None else CostAwareRouter(self._registry)
        self._run_store = run_store

    def logical_effect_key(self, inputs: DesignJudgeIn, ctx: NodeContext) -> str:
        """This wave's stable logical effect identity across physical retries.

        The node declares ``EFFECT_KEY`` replay semantics, so a retry must
        reconcile with the Invocations the first Attempt recorded instead of
        dispatching a second round of model calls. The key names the whole
        wave — the theses, the dimensions and the revisions they were judged
        against — so a retry that changes any of them is new logical work,
        while a retry of the same wave replays.
        """

        return replay_effect_key(ctx, f"{JUDGE_NODE_KIND}.wave", inputs.model_dump(mode="json"))

    async def _execute(self, inputs: DesignJudgeIn, ctx: NodeContext) -> DesignJudgeOut:
        store = self._require_store()
        await self._require_admitted_goal(inputs, ctx)
        _require_distinct_dimensions(inputs.dimensions)
        _require_distinct_theses(inputs.theses)

        # Authorization is resolved once, before any dimension runs. A wave
        # with a model_judge dimension and no authorized Binding is a refusal,
        # not a partial score set.
        binding, egress = await self._authorize(inputs, ctx)

        records: list[DesignEvalRecord] = []
        invocation_count = 0
        for thesis in inputs.theses:
            for dimension in inputs.dimensions:
                record, spent = await self._score_pair(
                    inputs, ctx, thesis, dimension, binding, egress
                )
                # The canonical #792 row is persisted before the record counts
                # toward anything: an evaluation nobody can read back is not
                # evidence.
                await store.record_eval_score(_run_eval_score(record, inputs))
                records.append(record)
                invocation_count += spent

        _require_complete(inputs, records)
        if not await self._persisted_complete(inputs, ctx):
            raise RuntimeError(
                "judge wrote no complete persisted eval evidence for this Run; "
                "eval-complete is not reportable"
            )
        return DesignJudgeOut(
            eval_complete=True,
            records=records,
            model_invocations=invocation_count,
        )

    def _require_store(self) -> RunStore:
        """Fail closed rather than score into a void.

        Without the canonical Run store there is nowhere to persist the
        ``#792`` rows, so nothing this node produced would be Run evidence.
        The store is returned so the caller holds a narrowed, non-optional
        reference for the whole wave.
        """

        if self._run_store is None:
            raise RuntimeError(
                "design judge requires the canonical Run store to persist #792 eval records"
            )
        return self._run_store

    async def _authorize(
        self, inputs: DesignJudgeIn, ctx: NodeContext
    ) -> tuple[Binding | None, ModelChatEgress | None]:
        """Resolve the Binding and the egress this wave's model calls use.

        A wave with no ``model_judge`` dimension needs neither, so it resolves
        nothing and authorizes nothing.
        """

        if not any(dimension.method is EvalMethod.MODEL_JUDGE for dimension in inputs.dimensions):
            return None, None
        binding = await resolve_design_binding(self._effects, binding_id=inputs.binding_id, ctx=ctx)
        egress = build_model_egress(
            self._effects,
            registry=self._registry,
            router=self._router,
            endpoint=gateway_endpoint_from_env(inputs.timeout_s),
        )
        return binding, egress

    async def _score_pair(
        self,
        inputs: DesignJudgeIn,
        ctx: NodeContext,
        thesis: DesignJudgeThesis,
        dimension: DesignJudgeDimension,
        binding: Binding | None,
        egress: ModelChatEgress | None,
    ) -> tuple[DesignEvalRecord, int]:
        """Score one (thesis x dimension) pair; returns the record and Invocations spent."""

        if dimension.method is EvalMethod.HUMAN:
            raise HumanJudgeNotResolvedError(
                f"dimension {dimension.name!r} is human-judged and waits on the "
                "#794 HITL answer surface; this node cannot score it and will "
                "not skip it"
            )
        if dimension.method is EvalMethod.DETERMINISTIC:
            return self._deterministic_record(inputs, ctx, thesis, dimension), 0
        assert binding is not None and egress is not None
        record = await self._model_judge_record(inputs, ctx, thesis, dimension, binding, egress)
        return record, 1

    async def _require_admitted_goal(self, inputs: DesignJudgeIn, ctx: NodeContext) -> None:
        """The scores must name the Goal revision the Run was admitted for.

        The canonical ``#792`` row carries ``goal_id``/``goal_revision``; the
        only Goal revision a Run may be judged against is the one it was
        admitted with (#1572). A judge that named any other revision would
        file evidence against a Goal the Run never referenced, so a mismatch —
        or a Run admitted without a Goal binding at all — refuses.
        """

        assert self._run_store is not None
        run = await self._run_store.get_run(ctx.run_id)
        if run is None:
            raise RuntimeError(f"Run {ctx.run_id!r} is not on the canonical Run store")
        if run.goal_id is None or run.goal_revision is None:
            raise RuntimeError(
                f"Run {ctx.run_id!r} was admitted without a canonical Goal binding; "
                "a judged Run must name the Goal revision it was admitted for"
            )
        if run.goal_id != inputs.goal_id or run.goal_revision != inputs.goal_revision:
            raise ValueError(
                f"judge inputs name Goal {inputs.goal_id!r} revision {inputs.goal_revision}, "
                f"but Run {ctx.run_id!r} was admitted for Goal {run.goal_id!r} revision "
                f"{run.goal_revision}"
            )

    async def _persisted_complete(self, inputs: DesignJudgeIn, ctx: NodeContext) -> bool:
        """Whether the canonical Run store holds every requested pair score.

        Completeness is a projection of persisted rows
        (:func:`maistro.runs.eval.eval_summary`), not of this node's memory:
        a score the store never accepted is not a score. The queried ids are
        thesis-qualified (see :func:`_score_dimension_id`), so a pair the
        store never wrote cannot hide behind a sibling thesis's score.
        """

        assert self._run_store is not None
        summary = await eval_summary(
            self._run_store,
            ctx.run_id,
            rubric_id=inputs.rubric_id,
            rubric_revision=inputs.rubric_revision,
            dimension_ids=[
                _score_dimension_id(dimension.name, thesis.thesis_id)
                for thesis in inputs.theses
                for dimension in inputs.dimensions
            ],
        )
        return summary.complete

    def _deterministic_record(
        self,
        inputs: DesignJudgeIn,
        ctx: NodeContext,
        thesis: DesignJudgeThesis,
        dimension: DesignJudgeDimension,
    ) -> DesignEvalRecord:
        total_weight = sum(
            max(int(c.get("weight", 1)), 0)  # type: ignore[call-overload]  # criteria are JSON-ish dicts
            for c in dimension.criteria
        )
        earned = 0
        detail: list[str] = []
        text = "\n".join((thesis.title, thesis.summary, thesis.body))
        for criterion in dimension.criteria:
            check = {key: value for key, value in criterion.items() if key != "weight"}
            passed = evaluate(check, text, {"thesis_id": thesis.thesis_id})
            weight = max(int(criterion.get("weight", 1)), 0)  # type: ignore[call-overload]
            earned += weight if passed else 0
            detail.append(f"{criterion.get('name', 'criterion')}: {'pass' if passed else 'fail'}")
        score = int(100 * earned / total_weight) if total_weight else 0
        return DesignEvalRecord(
            eval_id=_eval_id(ctx, dimension.name, thesis.thesis_id),
            run_id=ctx.run_id,
            node_run_id=ctx.node_run_id,
            attempt_id=ctx.attempt_id,
            goal_id=inputs.goal_id,
            goal_revision=inputs.goal_revision,
            rubric_id=inputs.rubric_id,
            rubric_revision=inputs.rubric_revision,
            thesis_id=thesis.thesis_id,
            thesis_node_run_id=thesis.node_run_id,
            dimension=dimension.name,
            method=EvalMethod.DETERMINISTIC,
            judge_identity=_DETERMINISTIC_JUDGE_IDENTITY,
            invocation_id="",
            score=score,
            passed=score >= inputs.pass_threshold,
            rationale="; ".join(detail),
        )

    async def _model_judge_record(
        self,
        inputs: DesignJudgeIn,
        ctx: NodeContext,
        thesis: DesignJudgeThesis,
        dimension: DesignJudgeDimension,
        binding: Binding,
        egress: ModelChatEgress,
    ) -> DesignEvalRecord:
        request = ModelChatRequest(
            model=inputs.model,
            messages=[
                {"role": "system", "content": _JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": _judge_prompt(inputs, thesis, dimension)},
            ],
            temperature=0.0,
        )
        result = await egress.complete(
            binding=binding,
            run_id=ctx.run_id,
            node_run_id=ctx.node_run_id,
            attempt_id=ctx.attempt_id,
            effect_key=(
                f"{JUDGE_NODE_KIND}.pair:{ctx.run_id}:{ctx.node_id}:"
                f"{thesis.thesis_id}:{dimension.name}"
            ),
            request=request,
        )
        payload = extract_json_payload(
            str(_choice_text(result.body)),
            what=f"judge dimension {dimension.name!r} for thesis {thesis.thesis_id!r}",
        )
        rationale = str(payload.get("rationale", ""))
        await scan_model_text(rationale, what=f"judge rationale for dimension {dimension.name!r}")
        score = _score_from(payload, dimension=dimension.name, thesis=thesis.thesis_id)
        return DesignEvalRecord(
            eval_id=_eval_id(ctx, dimension.name, thesis.thesis_id),
            run_id=ctx.run_id,
            node_run_id=ctx.node_run_id,
            attempt_id=ctx.attempt_id,
            goal_id=inputs.goal_id,
            goal_revision=inputs.goal_revision,
            rubric_id=inputs.rubric_id,
            rubric_revision=inputs.rubric_revision,
            thesis_id=thesis.thesis_id,
            thesis_node_run_id=thesis.node_run_id,
            dimension=dimension.name,
            method=EvalMethod.MODEL_JUDGE,
            judge_identity=inputs.judge_identity or result.model,
            invocation_id=result.invocation_id,
            score=score,
            passed=score >= inputs.pass_threshold,
            rationale=rationale,
        )


def _judge_prompt(
    inputs: DesignJudgeIn, thesis: DesignJudgeThesis, dimension: DesignJudgeDimension
) -> str:
    parts = [
        f"Goal revision: {inputs.goal_revision}",
        f"Rubric revision: {inputs.rubric_revision}",
        f"Dimension: {dimension.name}",
    ]
    if dimension.prompt.strip():
        parts.append(f"Assess: {dimension.prompt}")
    thesis_text = "\n".join(part for part in (thesis.title, thesis.summary, thesis.body) if part)
    parts.append(f"Thesis {thesis.thesis_id}:\n{thesis_text}")
    return "\n\n".join(parts)


def _score_from(payload: dict[str, object], *, dimension: str, thesis: str) -> int:
    raw = payload.get("score")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(
            f"judge dimension {dimension!r} for thesis {thesis!r}: model returned no integer score"
        )
    score = int(raw)
    if not 0 <= score <= 100:
        raise ValueError(
            f"judge dimension {dimension!r} for thesis {thesis!r}: score {score} outside 0-100"
        )
    return score


def _require_distinct_dimensions(dimensions: list[DesignJudgeDimension]) -> None:
    """Refuse a rubric whose dimension names collide.

    The canonical completeness projection keys on dimension id, so two
    dimensions sharing a name would silently collapse into one score set.
    """

    names = [dimension.name for dimension in dimensions]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ValueError(f"rubric dimensions must have distinct names; repeated: {duplicates}")


def _require_distinct_theses(theses: list[DesignJudgeThesis]) -> None:
    """Refuse a wave whose thesis identities collide or are empty.

    Scores are persisted under a thesis-qualified dimension id, so two
    theses sharing an identity would silently collapse their (thesis x
    dimension) pairs into one score set, and an empty one would corrupt it.
    """

    ids = [thesis.thesis_id for thesis in theses]
    if any(not thesis_id for thesis_id in ids):
        raise ValueError("judge theses must each name a non-empty thesis_id")
    duplicates = sorted({thesis_id for thesis_id in ids if ids.count(thesis_id) > 1})
    if duplicates:
        raise ValueError(
            f"judge theses must have distinct thesis_id values; repeated: {duplicates}"
        )


def _require_complete(inputs: DesignJudgeIn, records: list[DesignEvalRecord]) -> None:
    """Refuse to report eval-complete about anything but persisted-pair evidence.

    Every declared (thesis x dimension) pair must have produced a record, and
    every model_judge record must name the Invocation that produced it. A
    record set that cannot satisfy that is a failed judge, not a complete one.
    """

    expected = len(inputs.theses) * len(inputs.dimensions)
    if len(records) != expected:
        raise RuntimeError(
            f"judge produced {len(records)} records for {expected} (thesis x dimension) pairs"
        )
    for record in records:
        if record.method is EvalMethod.MODEL_JUDGE and not record.invocation_id:
            raise RuntimeError(
                f"model_judge record for dimension {record.dimension!r} names no Invocation; "
                "eval-complete without persisted Invocation evidence is not reportable"
            )


def _eval_id(ctx: NodeContext, dimension: str, thesis_id: str) -> str:
    """A stable, spine-scoped identity for one (thesis x dimension) score.

    The Attempt is part of the identity on purpose: the canonical eval store
    is append-only, so a re-judged dimension must land as a *new* record
    rather than collide with the row the previous Attempt wrote.
    """

    return f"eval-{ctx.run_id}-{ctx.node_run_id}-{ctx.attempt_id}-{dimension}-{thesis_id}"


def _score_dimension_id(dimension: str, thesis_id: str) -> str:
    """The thesis-qualified dimension identity a score is persisted under.

    The canonical completeness projection (:func:`maistro.runs.eval.eval_summary`)
    keeps the latest record per ``dimension_id``, so scores for distinct theses
    must not share one: a bare rubric-dimension name would let a later passing
    thesis supersede — and hide — an earlier failing thesis. Qualifying the
    name with the thesis keeps every (thesis x dimension) pair its own row.
    """

    return f"{dimension}@{thesis_id}"


def _run_eval_score(record: DesignEvalRecord, inputs: DesignJudgeIn) -> RunEvalScore:
    """Project one record onto the canonical ``#792`` Run evidence row."""

    pointers = [
        f"attempt:{record.attempt_id}/evidence/{record.dimension}",
        f"thesis:{record.thesis_id}",
    ]
    if record.invocation_id:
        pointers.insert(0, f"invocation:{record.invocation_id}")
    judge = (
        EvalJudge(kind=EvalMethod.MODEL_JUDGE, identity=record.judge_identity)
        if record.method is EvalMethod.MODEL_JUDGE
        else None
    )
    return RunEvalScore(
        eval_id=record.eval_id,
        run_id=record.run_id,
        node_run_id=record.node_run_id,
        attempt_id=record.attempt_id,
        goal_id=record.goal_id,
        goal_revision=record.goal_revision,
        rubric_id=record.rubric_id,
        rubric_revision=record.rubric_revision,
        dimension_id=_score_dimension_id(record.dimension, record.thesis_id),
        raw_score=float(record.score),
        passed=record.passed,
        method=record.method,
        evidence_pointers=pointers,
        judge=judge,
        detail={
            "scale": "0-100",
            "threshold": inputs.pass_threshold,
            "thesis_id": record.thesis_id,
            "thesis_node_run_id": record.thesis_node_run_id,
            "rationale": record.rationale,
        },
    )


def _choice_text(body: dict[str, object]) -> str:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    message = first.get("message") if isinstance(first, dict) else {}
    return str((message or {}).get("content", "") or "")


def _default_effects() -> CapabilityEffectContext:
    from maistro.capabilities.effect_context import default_effect_context

    return default_effect_context()
