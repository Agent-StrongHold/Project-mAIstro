---
inventory-delta:
  formal/: +3
  packages/maistro-rsi/tests: +3
---
# Issue #882 — Invocation effect/idempotency stateful model

The formal suite gains one file, `formal/models/test_invocation_effect_idempotency.py`,
collecting three node IDs: the `InvocationEffectMachine` stateful machine
(one `runTest` node) plus two minimal-sequence `@given` properties. It
drives the real `InvocationExecutionService` over `InMemoryInvocationStore`
with generated retry/cancellation/reconciliation histories and registers
counted invariants I31 in `formal/INVARIANTS.md` (mutant-demonstrated per
the #410 evidence rules; see
`docs/research/882-invocation-effect-idempotency-stateful-testing.md`).

`packages/maistro-rsi/tests` gains `test_m8a_invocation_effect_idempotency_research.py`
(+3): the M8-A leaf's deliverable gate — note exists, disposition recorded,
prototype and counted-invariant registration pinned. It imports nothing from
`maistro`; it reads repository markdown and source text only.

CI cost: the formal file runs in the already-required `formal-conformance`
job (~4.8s at the CI profile; 44s at 1000 examples measured during the
experiment). No other suite count moved, and no dependency changed.
