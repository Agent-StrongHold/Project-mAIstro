"""`discovery.curate` — the stronger curator tier (#1051).

Reduces and ranks the scout's candidate set with Persona + user-model + Goal/
Workspace context. Two strategies, chosen explicitly per node:

- **``model``** (default) — one governed completion through the model egress
  (same Binding/Invocation door as ``llm.summarize``): the small candidate
  set plus the cycle's context notes go out once, and a strict JSON verdict
  comes back. A candidate the model declines to score, or scores
  unparsably, is **dropped, never guessed** — an unparsable verdict must not
  fabricate relevance.
- **``lexical``** — deterministic overlap scoring against the context notes
  and scout-matched topics, for deployments without model bindings and for
  tests. The strategy used is recorded on every curated item, so a surfaced
  item never hides which judgment produced it.

Either way every curated item carries its own ``explain`` evidence — matched
topics, the context notes it matched, the curator's one-line reason — which
is what a surfaced item later shows when the user asks "why are you showing
me this?". Nothing here writes memory: curated items are sourced evidence on
the Run record, and only the canonical consolidation path may ever promote
them into durable user-model truth.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, ClassVar, cast

from pydantic import BaseModel, Field

from maistro.a2a.inbound import InboundWarden, default_warden, scan_inbound
from maistro.capabilities.binding_store import BindingNotFound
from maistro.capabilities.effect_context import CapabilityEffectContext, default_effect_context
from maistro.capabilities.model_chat import MODEL_CHAT_CAPABILITY, ModelChatEgress
from maistro.capabilities.providers.llm_gateway import GatewayEndpoint, ModelChatRequest
from maistro.providers.registry import InMemoryProviderRegistry
from maistro.providers.router import CostAwareRouter

from . import register_node
from .base import BaseNode, NodeContext, ReplaySemantics, replay_effect_key
from .discovery_context import DiscoveryContextProvider, default_discovery_context
from .discovery_scout import ScoutedCandidate

#: Sentinel distinguishing "no warden supplied" from an explicit `None` (a
#: policy declared unavailable, which `scan_inbound` fails closed on) — the
#: same shape as the A2A delegation node's wiring (#1137).
_WARDEN_UNSET = object()

#: The honest refusal channel for a completion the Warden refused: the same
#: `refused:` strategy shape the budget refusal uses, so a surfaced set can
#: never quietly omit that the curator's answer was blocked.
_WARDEN_REFUSAL = "refused:curator completion refused by Warden"

if TYPE_CHECKING:
    from maistro.providers.protocols import LLMProviderRegistry, LLMRouter

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


class DiscoveryCurateIn(BaseModel):
    candidates: list[ScoutedCandidate] = Field(default_factory=list)
    #: Persona hints, durable user-model statements, current Goal titles —
    #: one line each, produced by the host at cycle start from canonical
    #: services. The curator never reads those stores directly.
    context_notes: list[str] = Field(default_factory=list)
    strategy: str = Field(default="model", description="model | lexical")
    model: str = Field(
        default="gemini-3.1-flash",
        description="Model alias on the LLM gateway (the stronger curator tier)",
    )
    binding_id: str = Field(
        default="",
        description="Pre-authorized model.chat Binding; empty resolves from the discovery context",
    )
    max_surfaced: int = Field(default=3, ge=1, le=10)
    min_confidence: float = Field(default=0.3, ge=0.0, le=1.0)
    timeout_s: float = Field(default=30.0, ge=1.0, le=120.0)


class CuratedItem(BaseModel):
    fingerprint: str
    entry_id: str = ""
    url: str = ""
    title: str = ""
    summary: str = ""
    category: str = ""
    source_url: str = ""
    published_at: str = ""
    expires_at: str = ""
    relevance: float
    novelty: float
    confidence: float
    score: float
    strategy: str
    explain: str = ""
    matched_topics: list[str] = Field(default_factory=list)
    #: Structured context evidence (which Persona/user-model/Goal notes
    #: matched) and the curator's own stamp — surfaced-item payload fields
    #: read by the pipeline tests and the host's lift path (outside the
    #: shipped-src tree this scan roots at), the same declarative-schema
    #: class the vulture ledger banks as ``pydantic-declarative-field``. The
    #: inline acknowledgment is the analyzer's documented mechanism because
    #: this lane cannot land the ledger grant a floor raise would need
    #: (two-merge ratchet).
    matched_context: list[str] = Field(default_factory=list)  # noqa: vulture - surfaced evidence, read by host lift and tests
    run_id: str = ""
    curated_at: str = ""  # noqa: vulture - curator stamp, read by host lift and tests


class DiscoveryCurateOut(BaseModel):
    items: list[CuratedItem] = Field(default_factory=list)
    #: Honest cycle telemetry — see ``DiscoveryScoutOut`` for the
    #: serialization-only rationale and the inline acknowledgment.
    dropped_unparsable: int = 0  # noqa: vulture - cycle telemetry, read by host lift and tests
    dropped_low_confidence: int = 0  # noqa: vulture - cycle telemetry, read by host lift and tests
    strategy: str = ""


def _lexical_matches(candidate: ScoutedCandidate, notes: list[str]) -> tuple[float, list[str]]:
    """Deterministic context overlap: which notes' salient words appear."""
    text = " ".join(filter(None, (candidate.title, candidate.summary, candidate.category))).lower()
    matched: list[str] = []
    hits = 0
    for note in notes:
        words = [w for w in re.findall(r"[a-z0-9]{4,}", note.lower()) if len(w) >= 4]
        if not words:
            continue
        overlap = sum(1 for w in set(words) if w in text)
        if overlap and overlap / len(set(words)) >= 0.2:
            matched.append(note[:160])
            hits += overlap
    return min(1.0, hits / 8.0), matched


def _parse_verdicts(raw: str) -> dict[str, dict[str, Any]]:
    """Strict-ish JSON verdict read: the first JSON object in the completion."""
    match = _JSON_BLOCK_RE.search(raw)
    if match is None:
        return {}
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    if isinstance(parsed, dict):
        items = parsed.get("candidates") if isinstance(parsed.get("candidates"), list) else None
        if items is None:
            return {}
        out: dict[str, dict[str, Any]] = {}
        for row in items:
            if isinstance(row, dict) and isinstance(row.get("fingerprint"), str):
                out[row["fingerprint"]] = row
        return out
    return {}


def _score_triple(verdict: dict[str, Any]) -> tuple[float, float, float, str] | None:
    def _clamp(name: str) -> float | None:
        value = verdict.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        if not 0.0 <= float(value) <= 1.0:
            return None
        return float(value)

    relevance = _clamp("relevance")
    novelty = _clamp("novelty")
    confidence = _clamp("confidence")
    if relevance is None or novelty is None or confidence is None:
        return None
    reason = str(verdict.get("reason") or "").strip()
    return relevance, novelty, confidence, reason


def _refusal_out(cycle: Any) -> DiscoveryCurateOut | None:
    """The honest refusal output when the host closed this cycle's budget."""
    if cycle.budget_refusal:
        return DiscoveryCurateOut(strategy="refused:" + cycle.budget_refusal)
    return None


def _empty_out(inputs: DiscoveryCurateIn) -> DiscoveryCurateOut | None:
    """Nothing survived the scout: no curator spend, honestly empty."""
    if inputs.candidates:
        return None
    out = DiscoveryCurateOut()
    out.strategy = inputs.strategy.strip().lower() or "model"
    return out


def _merged_notes(inputs: DiscoveryCurateIn, cycle: Any) -> list[str]:
    return list(dict.fromkeys([*inputs.context_notes, *cycle.context_notes]))


def _validated_strategy(inputs: DiscoveryCurateIn) -> str:
    strategy = inputs.strategy.strip().lower() or "model"
    if strategy not in {"model", "lexical"}:
        raise ValueError(f"discovery.curate strategy must be model|lexical, got {strategy!r}")
    return strategy


def _apply_cap(out: DiscoveryCurateOut, inputs: DiscoveryCurateIn, cycle: Any) -> None:
    """Cap the surfaced set; the Workspace's budget may narrow, never widen."""
    cap = inputs.max_surfaced
    if cycle.max_surfaced > 0:
        cap = min(cap, cycle.max_surfaced)
    out.items = sorted(out.items, key=lambda i: (-i.score, -i.confidence, i.fingerprint))[:cap]


@register_node
class DiscoveryCurateNode(BaseNode[DiscoveryCurateIn, DiscoveryCurateOut]):
    kind: ClassVar[str] = "discovery.curate"
    kind_category: ClassVar = "sync.llm"
    input_schema: ClassVar[type[BaseModel]] = DiscoveryCurateIn
    output_schema: ClassVar[type[BaseModel]] = DiscoveryCurateOut
    cost_hint: ClassVar[float] = 3.0  # billable LLM call (model strategy)
    replay_semantics: ClassVar[ReplaySemantics] = ReplaySemantics.EFFECT_KEY
    external_io: ClassVar[bool] = True
    optional_authorities: ClassVar[Mapping[str, str]] = {
        "effect_context": "effect_context",
        "registry": "provider_registry",
        "router": "llm_router",
        "discovery_context": "discovery_context",
        # The output policy (#66, same authority the delegation node wires):
        # the curator's completion is model output re-entering product
        # context and is scanned before any verdict folds. The scan itself
        # fails closed when absent.
        "warden": "warden",
    }
    display_name: ClassVar[str] = "Discovery: curate candidates"
    description: ClassVar[str] = (
        "Rank/reduce scouted candidates into a small surfaced set using "
        "Persona + user-model + Goal context notes. Model strategy runs one "
        "governed completion; lexical strategy is deterministic. Every item "
        "keeps inspectable relevance evidence."
    )

    def __init__(
        self,
        *,
        effect_context: CapabilityEffectContext | None = None,
        registry: LLMProviderRegistry | None = None,
        router: LLMRouter | None = None,
        discovery_context: DiscoveryContextProvider | None = None,
        warden: InboundWarden | None | object = _WARDEN_UNSET,
    ) -> None:
        self._effects = effect_context or default_effect_context()
        self._registry: LLMProviderRegistry = (
            registry if registry is not None else InMemoryProviderRegistry()
        )
        self._router: LLMRouter = router if router is not None else CostAwareRouter(self._registry)
        self._cycle = discovery_context or default_discovery_context()
        # A completion is untrusted model output even though this node asked
        # for it (#66/#1202): the default is the canonical detector, an
        # explicitly unavailable policy fails closed in `scan_inbound`.
        self._warden = (
            default_warden() if warden is _WARDEN_UNSET else cast(InboundWarden | None, warden)
        )

    def logical_effect_key(self, inputs: DiscoveryCurateIn, ctx: NodeContext) -> str | None:
        return replay_effect_key(
            ctx, "discovery.curate.rank", {"inputs": inputs.model_dump(mode="json")}
        )

    async def _execute(self, inputs: DiscoveryCurateIn, ctx: NodeContext) -> DiscoveryCurateOut:
        cycle = await self._cycle.context_for(
            str(ctx.workspace_id or ""),
            str(ctx.project_id or ""),
            str(ctx.user_id or ""),
            cycle_key=ctx.run_id,
        )
        refused = _refusal_out(cycle)
        if refused is not None:
            return refused
        empty = _empty_out(inputs)
        if empty is not None:
            return empty

        notes = _merged_notes(inputs, cycle)
        strategy = _validated_strategy(inputs)
        curated_at = str(ctx.metadata.get("cycle_curated_at") or "")
        if strategy == "model":
            out = await self._curate_model(inputs, ctx, notes, cycle, curated_at)
            # A Warden-refused completion is the node's honest refusal
            # output; it must not be re-labelled as a `model` result by the
            # strategy stamp below.
            if out.strategy.startswith("refused:"):
                return out
        else:
            out = self._curate_lexical(inputs, notes, ctx.run_id, curated_at)

        _apply_cap(out, inputs, cycle)
        out.strategy = strategy
        return out

    # -- lexical ------------------------------------------------------------

    def _curate_lexical(
        self, inputs: DiscoveryCurateIn, notes: list[str], run_id: str, curated_at: str
    ) -> DiscoveryCurateOut:
        items: list[CuratedItem] = []
        dropped_low_confidence = 0
        for candidate in inputs.candidates:
            relevance, matched_notes = _lexical_matches(candidate, notes)
            confidence = round(min(1.0, 0.4 + 0.4 * len(candidate.matched_topics)), 4)
            if relevance <= 0.0 or confidence < inputs.min_confidence:
                dropped_low_confidence += 1
                continue
            evidence = (
                [f"matched watch topics: {', '.join(candidate.matched_topics)}"]
                if (candidate.matched_topics)
                else []
            )
            evidence.extend(f"context: {note}" for note in matched_notes[:3])
            items.append(
                CuratedItem(
                    fingerprint=candidate.fingerprint,
                    entry_id=candidate.entry_id,
                    url=candidate.url,
                    title=candidate.title,
                    summary=candidate.summary,
                    category=candidate.category,
                    source_url=candidate.source_url,
                    published_at=candidate.published_at,
                    expires_at=candidate.expires_at,
                    relevance=round(relevance, 4),
                    novelty=1.0,
                    confidence=confidence,
                    score=round(0.6 * relevance + 0.2 + 0.2 * confidence, 4),
                    strategy="lexical",
                    explain="; ".join(evidence)
                    or "no stronger-than-topic evidence; lexical match only",
                    matched_topics=list(candidate.matched_topics),
                    matched_context=matched_notes[:3],
                    run_id=run_id,
                    curated_at=curated_at,
                )
            )
        return DiscoveryCurateOut(items=items, dropped_low_confidence=dropped_low_confidence)

    # -- model --------------------------------------------------------------

    async def _authorized_binding(self, inputs: DiscoveryCurateIn, ctx: NodeContext) -> Any:
        binding_id = inputs.binding_id.strip()
        if not binding_id:
            cycle = await self._cycle.context_for(
                str(ctx.workspace_id or ""),
                str(ctx.project_id or ""),
                str(ctx.user_id or ""),
                cycle_key=ctx.run_id,
            )
            binding_id = cycle.curator_binding_id
        if not binding_id:
            raise BindingNotFound(
                "discovery.curate model strategy requires a pre-authorized model.chat "
                "Binding (explicit input or discovery context)"
            )
        return await self._effects.bindings.resolve(
            binding_id,
            workspace_id=str(ctx.workspace_id or ""),
            project_id=str(ctx.project_id or ""),
            node_id=ctx.node_id,
            capability=MODEL_CHAT_CAPABILITY,
        )

    def _gateway_endpoint(self, timeout_s: float) -> GatewayEndpoint:
        from maistro.graph.nodes.llm_summarize import _gateway_endpoint

        return _gateway_endpoint(timeout_s=timeout_s)

    async def _curate_model(
        self,
        inputs: DiscoveryCurateIn,
        ctx: NodeContext,
        notes: list[str],
        cycle: Any,
        curated_at: str,
    ) -> DiscoveryCurateOut:
        binding = await self._authorized_binding(inputs, ctx)
        prompt_candidates = [
            {
                "fingerprint": c.fingerprint,
                "title": c.title[:200],
                "summary": c.summary[:300],
                "category": c.category,
                "source": c.source_url,
                "published_at": c.published_at,
                "matched_topics": c.matched_topics,
            }
            for c in inputs.candidates
        ]
        system = (
            "You curate proactive discoveries for one user's Workspace. Score each "
            "candidate against the provided context notes (the Persona, the durable "
            "user model, and current Goals/Workspace activity). Respond with ONLY a "
            'JSON object: {"candidates": [{"fingerprint": str, "relevance": 0..1, '
            '"novelty": 0..1, "confidence": 0..1, "reason": str}]}. Score every '
            "candidate you can judge; omit one you cannot. Reasons must cite the "
            "specific note or topic that makes the item relevant, without asserting "
            "facts the context does not support."
        )
        user_payload = json.dumps({"context_notes": notes, "candidates": prompt_candidates})
        egress = ModelChatEgress(
            self._effects,
            registry=self._registry,
            router=self._router,
            endpoint=self._gateway_endpoint(inputs.timeout_s),
        )
        result = await egress.complete(
            binding=binding,
            run_id=ctx.run_id,
            node_run_id=ctx.node_run_id,
            attempt_id=ctx.attempt_id,
            effect_key=replay_effect_key(ctx, "discovery.curate.complete", {"model": inputs.model}),
            request=ModelChatRequest(
                model=inputs.model or (cycle.curator_model if cycle else "") or "gemini-3.1-flash",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_payload},
                ],
                temperature=0.1,
                max_tokens=2048,
            ),
            actor_id=str(ctx.user_id or ""),
        )
        raw = (result.body.get("choices", [{}])[0].get("message", {}) or {}).get("content", "")
        raw = str(raw or "")
        # The completion is untrusted model output re-entering product
        # context (#66/#1202's final-answer class): it is scanned before any
        # verdict folds, and a refusal surfaces nothing from it — an
        # injected "reason" must not ride a curated item into the Workspace.
        verdict = await scan_inbound(self._warden, raw, boundary="discovery_curator_output")
        if not verdict.clean:
            return DiscoveryCurateOut(strategy=_WARDEN_REFUSAL)
        return self._fold_verdicts(inputs, raw, ctx.run_id, curated_at)

    def _fold_verdicts(
        self, inputs: DiscoveryCurateIn, raw: str, run_id: str, curated_at: str
    ) -> DiscoveryCurateOut:
        verdicts = _parse_verdicts(raw)
        items: list[CuratedItem] = []
        dropped_unparsable = 0
        dropped_low_confidence = 0
        for candidate in inputs.candidates:
            verdict = verdicts.get(candidate.fingerprint)
            if verdict is None:
                dropped_unparsable += 1
                continue
            triple = _score_triple(verdict)
            if triple is None:
                dropped_unparsable += 1
                continue
            relevance, novelty, confidence, reason = triple
            if confidence < inputs.min_confidence:
                dropped_low_confidence += 1
                continue
            evidence = (
                [f"matched watch topics: {', '.join(candidate.matched_topics)}"]
                if (candidate.matched_topics)
                else []
            )
            if reason:
                evidence.append(f"curator: {reason[:300]}")
            items.append(
                CuratedItem(
                    fingerprint=candidate.fingerprint,
                    entry_id=candidate.entry_id,
                    url=candidate.url,
                    title=candidate.title,
                    summary=candidate.summary,
                    category=candidate.category,
                    source_url=candidate.source_url,
                    published_at=candidate.published_at,
                    expires_at=candidate.expires_at,
                    relevance=round(relevance, 4),
                    novelty=round(novelty, 4),
                    confidence=round(confidence, 4),
                    score=round(0.5 * relevance + 0.3 * novelty + 0.2 * confidence, 4),
                    strategy="model",
                    explain="; ".join(evidence),
                    matched_topics=list(candidate.matched_topics),
                    run_id=run_id,
                    curated_at=curated_at,
                )
            )
        return DiscoveryCurateOut(
            items=items,
            dropped_unparsable=dropped_unparsable,
            dropped_low_confidence=dropped_low_confidence,
        )


__all__ = ["CuratedItem", "DiscoveryCurateNode"]
