---
inventory-delta:
  packages/maistro-core/tests: +145
---

Issue #390 wires ADR-057 memory write-authority enforcement into every
production memory store and adds the acceptance evidence for it.

`test_write_authority_conformance.py` adds the matrix: learnings, episodic and
outcomes stores, each over nine backend x declared-mode combinations, asserting
that an undeclared mode refuses every mutation fail-closed, agent-actor writes
under `system_managed` are denied with the store state provably untouched (no
partial durable state), system actors write under every mode, and promotions
under `system_managed` leave statuses unchanged. The PostgreSQL legs run
against a live migrated database when `MAISTRO_TEST_PG_DSN` is set and skip
otherwise, matching the conformance-suite contract.

`test_exposure_mode.py` gains the SPEC-062126-6a31 store-level classes: the
reachability suite constructs every production store class bare (both SQL
stores without a database, since the gate precedes all I/O) and asserts the
first mutation raises `MemoryUndeclaredModeError`; the two-actor in-memory
matrix; the hybrid fail-closed case; and the governance test that no line in
`maistro.memory` or the memory persistence stores names a product and the mode
decision together (ADR-057's no-product-identity rule, previously grep-only).

The remaining delta is mechanical: every pre-existing test that constructs a
store now declares its exposure mode explicitly (`agent_managed`), which is the
same declaration the container makes from `AgentConfig.memory.exposure_mode`.
No test was deleted; the count moves only upward.
