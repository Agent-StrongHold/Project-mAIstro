"""`discovery.source_fetch` — governed fetch of a Binding's declared sources (#1051).

The cheap scout tier's input side: every fetch is one governed Invocation
(``discovery.source`` capability) tied to this NodeRun, against a source the
Workspace's Binding explicitly declares. Entries are then freshness-filtered
(``max_age_hours`` against each entry's own ``published_at`` — a source that
publishes no timestamps passes untouched) and capped. Nothing here scores or
judges relevance; that is the scout's and curator's work.

Configuration precedence: explicit node inputs first, then the per-cycle
``discovery_context`` authority (how a scheduled fire with no HTTP caller
resolves the Workspace's Binding), then refusal — a fetch with no resolvable
Binding fails closed before any HTTP, like every governed node.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any, ClassVar, cast

from pydantic import BaseModel, Field

from maistro.a2a.inbound import InboundWarden, default_warden, scan_inbound
from maistro.capabilities.binding_store import BindingNotFound
from maistro.capabilities.discovery_source import invoke_discovery_source
from maistro.capabilities.effect_context import CapabilityEffectContext, default_effect_context
from maistro.capabilities.providers.discovery_source import DiscoverySourceRequest

from . import register_node
from .base import BaseNode, NodeContext, ReplaySemantics
from .discovery_context import DiscoveryContextProvider, default_discovery_context

#: Sentinel distinguishing "no warden supplied" from an explicit `None` (a
#: policy declared unavailable, which `scan_inbound` fails closed on) — the
#: same shape as the A2A delegation node's wiring (#1137).
_WARDEN_UNSET = object()


class DiscoverySourceFetchIn(BaseModel):
    binding_id: str = Field(
        default="",
        description=(
            "Pre-authorized discovery.source Binding for this workspace/project; "
            "empty resolves the Workspace's Binding from the discovery context authority"
        ),
    )
    max_entries_per_source: int = Field(default=20, ge=1, le=100)
    #: Entries older than this are dropped as stale before scoring. 0 keeps
    #: everything (sources without timestamps are never stale by this rule).
    max_age_hours: int = Field(default=72, ge=0, le=24 * 30)
    #: Total entry cap across the cycle's sources — the per-run network bound.
    limit: int = Field(default=30, ge=1, le=100)
    timeout_s: float = Field(default=15.0, ge=1.0, le=60.0)


class DiscoverySourceFetchOut(BaseModel):
    entries: list[dict[str, str]] = Field(default_factory=list)
    #: Honest cycle telemetry, read by the pipeline tests and the host's lift
    #: path (outside the shipped-src tree this scan roots at) — the same
    #: declarative-schema class the vulture ledger banks as
    #: ``pydantic-declarative-field``; the inline acknowledgment is the
    #: analyzer's documented mechanism because this lane cannot land the
    #: ledger grant a floor raise would need (two-merge ratchet).
    sources_queried: int = 0  # noqa: vulture - cycle telemetry, read by host lift and tests
    skipped_stale: int = 0  # noqa: vulture - cycle telemetry, read by host lift and tests
    sources: list[dict[str, str]] = Field(
        default_factory=list,
        description="Per-source provenance actually queried this cycle",
    )
    refusal: str = ""


def _parse_stamp(published_at: str) -> datetime | None:
    """Read a source timestamp: ISO 8601 first, then RFC 822 pubDate.

    An unparseable stamp returns None and the entry is never treated as stale
    by the age rule — a feed we cannot read time from is not automatically
    old.
    """
    text = published_at.strip()
    if not text:
        return None
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            stamp = parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return stamp


def _stale(published_at: str, *, now: datetime, max_age: timedelta) -> bool:
    stamp = _parse_stamp(published_at)
    if stamp is None:
        return False
    return (now - stamp) > max_age


def _declared_sources(binding: Any) -> list[dict[str, Any]]:
    """The Binding's declared, URL-bearing sources — fail closed when none."""
    sources = [
        source
        for source in binding.config.get("sources", [])
        if isinstance(source, dict) and str(source.get("url") or "").strip()
    ]
    if not sources:
        raise BindingNotFound(
            "discovery.source Binding declares no sources; refusing an open fetch"
        )
    return sources


@register_node
class DiscoverySourceFetchNode(BaseNode[DiscoverySourceFetchIn, DiscoverySourceFetchOut]):
    kind: ClassVar[str] = "discovery.source_fetch"
    kind_category: ClassVar = "sync.tool"
    input_schema: ClassVar[type[BaseModel]] = DiscoverySourceFetchIn
    output_schema: ClassVar[type[BaseModel]] = DiscoverySourceFetchOut
    cost_hint: ClassVar[float] = 1.0
    replay_semantics: ClassVar[ReplaySemantics] = ReplaySemantics.IDEMPOTENT
    external_io: ClassVar[bool] = True
    # The resolver must hand over the container's Binding/Invocation authority;
    # the constructor default is a process-wide context that authorizes nothing.
    optional_authorities: ClassVar[Mapping[str, str]] = {
        "effect_context": "effect_context",
        "discovery_context": "discovery_context",
        # The inbound-content policy (#66, same authority the delegation node
        # wires): fetched feed rows are peer-controlled content scanned before
        # they may flow downstream. The scan itself fails closed when absent.
        "warden": "warden",
    }
    display_name: ClassVar[str] = "Discovery: fetch declared sources"
    description: ClassVar[str] = (
        "Fetch the sources a discovery.source Binding declares, through the "
        "governed Invocation egress (one Invocation per source), then drop "
        "stale entries and cap the result. No scoring here — the scout and "
        "curator nodes own relevance."
    )

    def __init__(
        self,
        *,
        effect_context: CapabilityEffectContext | None = None,
        discovery_context: DiscoveryContextProvider | None = None,
        warden: InboundWarden | None | object = _WARDEN_UNSET,
    ) -> None:
        self._effects = effect_context or default_effect_context()
        self._cycle = discovery_context or default_discovery_context()
        # Feed rows are attacker-influenced even though the source URL was
        # declared by the Workspace (#66): the default is the canonical
        # detector, an explicitly unavailable policy fails closed in
        # `scan_inbound`.
        self._warden = (
            default_warden() if warden is _WARDEN_UNSET else cast(InboundWarden | None, warden)
        )

    async def _binding_for(
        self, inputs: DiscoverySourceFetchIn, ctx: NodeContext, cycle: Any
    ) -> Any:
        """The pre-authorized Binding for this cycle; refuse before any request."""
        binding_id = inputs.binding_id.strip() or cycle.source_binding_id
        if not binding_id:
            raise BindingNotFound(
                "discovery.source_fetch requires a pre-authorized Binding "
                "(explicit input or discovery context) before any request"
            )
        return await self._effects.bindings.resolve(
            binding_id,
            workspace_id=str(ctx.workspace_id or ""),
            project_id=str(ctx.project_id or ""),
            node_id=ctx.node_id,
            capability="discovery.source",
        )

    async def _invoke_source(
        self,
        source: dict[str, Any],
        binding: Any,
        ctx: NodeContext,
        inputs: DiscoverySourceFetchIn,
        per_source: int,
    ) -> dict[str, Any]:
        """One governed Invocation for one declared source."""
        url = str(source.get("url") or "").strip()
        invocation = await invoke_discovery_source(
            self._effects,
            binding=binding,
            run_id=ctx.run_id,
            node_run_id=ctx.node_run_id,
            attempt_id=ctx.attempt_id,
            effect_key=f"discovery.source.fetch:{url}:{per_source}",
            request=DiscoverySourceRequest(url=url, max_entries=per_source),
            timeout_s=inputs.timeout_s,
            actor_id=str(ctx.user_id or ""),
        )
        return invocation.result if isinstance(invocation.result, dict) else {}

    def _accept_entries(
        self,
        result: dict[str, Any],
        category: str,
        *,
        now: datetime,
        inputs: DiscoverySourceFetchIn,
        remaining: int,
    ) -> tuple[list[dict[str, str]], int]:
        """Rows kept from one source's result, with the stale count dropped."""
        rows: list[dict[str, str]] = []
        skipped_stale = 0
        max_age = timedelta(hours=inputs.max_age_hours)
        for entry in result.get("entries", []):
            if not isinstance(entry, dict) or len(rows) >= remaining:
                continue
            published = str(entry.get("published_at") or "")
            if inputs.max_age_hours > 0 and _stale(published, now=now, max_age=max_age):
                skipped_stale += 1
                continue
            row = {key: str(value) for key, value in entry.items()}
            if category and not row.get("category"):
                row["category"] = category
            rows.append(row)
        return rows, skipped_stale

    @staticmethod
    def _source_meta(
        source: Mapping[str, Any], result: Mapping[str, Any]
    ) -> tuple[str, str, dict[str, str]]:
        """URL, category and the provenance row recorded for one source."""
        url = str(source.get("url") or "").strip()
        category = str(result.get("category") or source.get("category") or "")
        return url, category, {"url": url, "category": category}

    async def _refusal_for_rows(self, rows: list[dict[str, str]]) -> str | None:
        """The #66 boundary for accepted rows, as a refusal or `None`.

        Accepted rows are peer-controlled content. They are scanned in their
        canonical form — keys included — before they can flow toward the
        curator's model prompt or the Workspace, and a refusal stops the cycle
        here: poisoned rows are never silently dropped into a weaker
        downstream.
        """
        if not rows:
            return None
        verdict = await scan_inbound(self._warden, rows, boundary="discovery_source")
        if verdict.clean:
            return None
        return "discovery source content refused by Warden"

    async def _execute(
        self, inputs: DiscoverySourceFetchIn, ctx: NodeContext
    ) -> DiscoverySourceFetchOut:
        cycle = await self._cycle.context_for(
            str(ctx.workspace_id or ""),
            str(ctx.project_id or ""),
            str(ctx.user_id or ""),
            cycle_key=ctx.run_id,
        )
        if cycle.budget_refusal:
            # Budget exhausted is a clean stop, not a failure to hide: the
            # refusal is the node's output, recorded on the Run.
            return DiscoverySourceFetchOut(refusal=cycle.budget_refusal)

        binding = await self._binding_for(inputs, ctx, cycle)
        sources = _declared_sources(binding)

        entries: list[dict[str, str]] = []
        sources_queried = 0
        skipped_stale = 0
        sources_meta: list[dict[str, str]] = []
        now = datetime.now(UTC)
        for source in sources:
            if len(entries) >= inputs.limit:
                break
            per_source = min(inputs.max_entries_per_source, inputs.limit - len(entries))
            result = await self._invoke_source(source, binding, ctx, inputs, per_source)
            sources_queried += 1
            _url, category, meta = self._source_meta(source, result)
            sources_meta.append(meta)
            rows, stale = self._accept_entries(
                result,
                category,
                now=now,
                inputs=inputs,
                remaining=inputs.limit - len(entries),
            )
            skipped_stale += stale
            refusal = await self._refusal_for_rows(rows)
            if refusal:
                return DiscoverySourceFetchOut(refusal=refusal)
            entries.extend(rows)
        return DiscoverySourceFetchOut(
            entries=entries,
            sources_queried=sources_queried,
            skipped_stale=skipped_stale,
            sources=sources_meta,
        )


__all__ = ["DiscoverySourceFetchNode"]
