---
inventory-delta:
  packages/maistro-core/tests: +72
---

# #892 generalized protocol conformance suites (M8-A12 prototype)

Bounded research prototype: the archive tier's shared conformance-suite
pattern, generalized into a contract/leg split and run unchanged against
the three production implementations of two capability-tier protocols.

New files, all under `packages/maistro-core/tests/conformance/`:

- `_invocation_contract.py` -- 12 implementation-agnostic behavior checks
  for the capability `InvocationStore` / `EffectClaimStore` protocols
  (round-trip fidelity, absence semantics, optimistic concurrency,
  admission refusal beside live/completed priors, FAILED-prior-only
  retries, history scope/span/order and tiebreak, ambiguity staleness
  predicate, atomic-claim replay/refuse/admit).
- `_approval_contract.py` -- 7 checks for the durable `ApprovalStore`
  protocol (pending round-trip with digest binding, explicit absence,
  effect-identity idempotence, duplicate-id refusal, verified actor,
  first-decision-wins, restart durability).
- `_legs.py` -- build/restart/close for each backend (in-memory, real
  aiosqlite, real asyncpg against `MAISTRO_TEST_DATABASE_URL` with the
  honest-skip discipline; namespace isolation, no truncation).
- `test_invocation_store_conformance.py` /
  `test_approval_store_conformance.py` -- the check x backend matrices (65
  run + 7 protocol-gated skips with a live PG URL) plus per-leg structure
  guards; every recorded divergence is a finding-numbered xfail
  (`strict=True` except the possibly-deliberate F3).
- `test_conformance_teeth.py` -- 8 strictness proofs: seven single-behavior
  drifts each flag exactly their check, and an honest in-memory leg
  violates exactly the recorded findings.

Net: +72 collected node IDs on `packages/maistro-core/tests`. Experiment
record, six cross-implementation findings (F1-F6), and INCUBATE disposition:
`docs/testing/conformance-suite-evidence.md`.
