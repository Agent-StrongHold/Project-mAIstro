# M8-F2 research note — cross-Agent batching, prefix/KV reuse, and semantic caching

Leaf: #935. Epic: #905. Initiative: #879.

## Hypothesis

Batching independent Agent inference, reusing stable prefix or KV state, and caching semantic responses for bounded read-only cases could raise throughput and cut cost without breaking isolation or freshness.

## Canonical seam

Shipped model calls already have one routing and serving path. `CostAwareRouter` in `packages/maistro-core/src/maistro/providers/router.py` selects a model. `packages/maistro-core/src/maistro/capabilities/model_chat.py` admits the call as Binding, then Invocation, then the single approved gateway provider in `packages/maistro-core/src/maistro/capabilities/providers/llm_gateway.py`. That provider is the module allowed to hold the HTTP client for model egress. The path does not share a batch, a prefix cache, or a response cache across Agents.

## Record

This note does not report an experiment. Cross-agent batching / KV reuse is not evidenced against MAIstro's canonical routing seam, and implementing it now would be a second model-serving path. Semantic caching on this leaf is the same situation: it is not evidenced on that seam, and this change adds no cache, feature flag, or product code.

Disposition: WATCH
