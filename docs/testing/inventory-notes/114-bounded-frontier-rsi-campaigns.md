---
inventory-delta:
  packages/maistro-rsi/tests: +46
---

# Bounded frontier-model RSI campaigns (M5-B, #114)

Adds `packages/maistro-rsi/tests/test_campaign.py` (+46) for the new
`maistro_rsi.campaign` harness and its `maistro-rsi-campaign` console script
(`maistro_rsi.campaign_cli`). One objective pool, two arms (frontier model and
cheaper-router baseline), explicit ceilings, canonical Invocation accounting,
mechanical stops.

The tests pin each acceptance criterion from the issue against the shipped
paths, not against test doubles of the seams that matter: every dispatched
call is asserted to be a real `maistro.capabilities.invocation.Invocation`
admitted into an `InMemoryInvocationStore` and charged exactly once through
`CanonicalInvocationUsageRecorder` onto a real `InMemoryQuotaTracker`
(track-1..2, including the terminalization-retry no-double-charge and the
#718 rule that missing provider usage reads as absent evidence, never a
measured zero — track-4). Mechanical stopping is pinned both at the loop
level (spend/token/call-count/wall-clock/objective ceilings each refuse new
work: stop-1..5) and inside the dispatch seam (`BudgetState.admit_call`
raises on a spent budget: stop-6), with the arm-independence property — one
arm's exhausted budget neither erases nor truncates the other arm's record —
asserted explicitly. The comparison criterion is pinned structurally: both
arms' attempt logs must cover the identical objective ids in order before
any win/loss/delta is computed (compare-1..4), and a frontier arm scoring
below its peer is recorded as that arm's regression. Reporting is pinned by
a JSON round-trip of the whole `CampaignReport` artifact (report-1), so the
recorded progress/cost/attempts/regressions/intervention fields survive
serialization.

Two rejections the harness enforces are also pinned: an unbounded campaign
policy never becomes enforcement (`ensure_bounded` refuses wherever a budget
is kept, ceiling-1..2) and out-of-scope pool entries are refused at admission
without consuming model budget (ceiling-3, with `scope_refusals` surfaced on
the report). The transport adapter (`gateway_model_call`) is tested against a
stubbed `make_gateway_llm_call` to prove reported usage and the served model
version survive the `on_response` capture into the canonical Invocation —
the seam that would otherwise silently degrade to zero-token rows. CLI-level
tests cover flag parsing, the ceilings mapping, and the refusal to dispatch
without a configured gateway.

No existing suite changed count; this is additive coverage on new modules.
