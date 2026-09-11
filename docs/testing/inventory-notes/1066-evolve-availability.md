---
inventory-delta:
  packages/hive-conductor/backend/tests/test_evolution_canonical_edge_cases.py: +5
---

# Issue #1066 Evolve availability and failure projection coverage

Adds coverage for stub/no-router-key and bridge-degraded availability, suppression of
an impossible background cadence, explicit unavailable cycle responses, and
projection of evaluation, battle, and finalization terminal Run failures with the
canonical run identity, status, and diagnostic.

## Review-thread disposition

- **Embedded core disabled (P1):** Evolve remains domain-state-only/degraded when
  the Engine has a StubAgentPort or no canonical Container. Startup does not
  schedule a cadence, and `POST /cycle` returns an explicit availability error;
  the legacy direct executor is not restored.
- **Canonical failure semantics (P2):** a terminal non-completed canonical Run is
  projected as a 500 execution failure containing `run_id`, terminal `status`,
  and diagnostic. It is never rewritten as service-unavailable and never
  increments `cycle_count`.
