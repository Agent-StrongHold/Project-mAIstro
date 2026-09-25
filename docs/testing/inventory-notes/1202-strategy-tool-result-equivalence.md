---
inventory-delta:
  packages/maistro-core/tests: +6
---
# Strategy tool-result trust-pipeline equivalence (#1202)

`packages/maistro-core/tests/agents/test_trust_pipeline_equivalence.py` adds
six collected node IDs: one test parametrized over three shipped strategies
(ReAct, Artificer, BuildersLearning — which delegates to ReAct on the
`Agent.handle` path) times two tool results (PII-bearing and prompt
injection). Each case runs `Agent.handle` with a real Warden, a real
Sentinel with an explicit permission table, and `FauxProvider`, then checks
that the tool message in the next provider request carries the same redacted
text or Sentinel refusal for every strategy, that raw tool text never reaches
the provider, that Sentinel audits exactly one pre-call and one post-call, and
that the returned and session-persisted answer is redacted. Nothing was
removed or moved.
