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

## Independent verification (verifier, head e597d613a4be573b7ea5a46064e82261b63ee78d)

All of the following were executed by the verifier, not taken on faith:

- `test_exposure_mode.py`: 34 passed (reachability bare-construction of all 10
  production store classes, two-actor in-memory matrix, hybrid fail-closed,
  governance no-product-identity grep).
- `test_write_authority_conformance.py` twice: without `MAISTRO_TEST_PG_DSN`
  (28 passed / 98 skipped: memory+sqlite legs) and against a live migrated
  pgvector pg18 database (fresh container, `alembic upgrade head` -> 047;
  42 passed / 84 skipped: postgres legs). Across the two runs every one of the
  nine backend x declared-mode combinations executed for all 14 scenarios.
- Full `tests/memory/` + `tests/persistence/` +
  `tests/test_container_episodic_store.py` with the live PG DSN: 1142 passed,
  84 skipped.
- hive-conductor feedback/decay/optimizer/property/topology suites: 131 passed.
- `ruff check .` and `ruff format --check .` clean; mypy clean over all six
  `packages/*/src` trees; `check-reachability`, `check-reachability-dispositions`,
  `check-reachability-dispositions-provenance`, `check-reachability-provenance`,
  `check-release-consistency` and both `check-suite-inventory` suites all OK.
- Code audit: `require_write_authority` is the first statement of every
  content-write/promote entry (`store`, `record`, `check_auto_promotions`) in
  all ten store classes; no production construction site omits
  `exposure_mode` (container, testing harness, hive-conductor engine +
  feedback_service). `mark_used`/`mark_outcome`/`reinforce`/`apply_decay`
  remain ungated by design: SPEC-062126-6a31 declares decay/consolidation
  dynamics (SPEC-062126-5d56) orthogonal to exposure mode, and usage counters
  are not actor-authored writes; KNOWN-GAPS scopes its fail-closed claim to
  the gated entries.

Recorded deviations from the accepted SPEC's letter (non-blocking for #390,
disclosed or follow-up): `AgentConfig.memory.exposure_mode` defaults to
`agent_managed` (types/config.py) rather than failing at recipe load, and no
maistro-turing recipe declares `exposure_mode` explicitly; the store-boundary
gate still refuses undeclared stores, so no production write bypasses the
decision. `memory.write.denied` events and read-path gating remain KNOWN-GAPS
residuals as documented.
