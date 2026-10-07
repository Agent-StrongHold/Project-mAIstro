# M8-F2 research note — cross-Agent batching, prefix/KV reuse, and semantic caching

Leaf: #935. Epic: #905. Initiative: #879.

## Hypothesis

Batching independent Agent inference, reusing stable prefix or KV state, and caching semantic responses for bounded read-only cases could raise throughput and cut cost without breaking isolation or freshness.

## Canonical seam

The governed model-serving path is one seam, but it is not the only shipped one. `CostAwareRouter` in `packages/maistro-core/src/maistro/providers/router.py` selects a model when the request does not name one; a Binding pin or request-named alias outranks it. `packages/maistro-core/src/maistro/capabilities/model_chat.py` admits the call as Binding, then Invocation, then the single approved gateway provider in `packages/maistro-core/src/maistro/capabilities/providers/llm_gateway.py`. That provider is the module allowed to hold the HTTP client for governed model egress. The governed path does not share a batch, a prefix cache, or a response cache across Agents.

It is also not the only shipped egress: `quality/model-egress.json` records multiple direct model callers still awaiting governed migration, including `maistro.agents.conductor`, `maistro.events.handlers`, and `maistro_bootstrap.builders.responses_callable`. The server-backed conductor reaches `maistro.agents.conductor._call_gateway`, which posts directly to `/chat/completions` without CostAwareRouter, Binding, or Invocation. Those callers share none of the governed path's caches either.

## Record

This note does not report an experiment. Cross-agent batching / KV reuse is not evidenced against the governed canonical routing seam, and implementing it there now would be a second model-serving path for that seam. Caveat (reassessed per review): production traffic is not confined to the governed seam — the direct egress callers recorded in `quality/model-egress.json` still post outside CostAwareRouter/Binding/Invocation, so any future batching / KV-reuse work must either cover those paths as well or scope itself explicitly to the governed seam and treat the direct callers as remaining migration debt. Semantic caching on this leaf is the same situation: it is not evidenced on that seam, and this change adds no cache, feature flag, or product code.

Disposition: WATCH
