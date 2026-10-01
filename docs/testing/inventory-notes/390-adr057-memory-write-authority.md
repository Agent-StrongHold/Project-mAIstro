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

## CI-repair round (head 8b56789d66b8, gates re-run locally)

The first merge-queue evaluation at 8b56789d failed six gates. Root causes, all
reproduced locally from the CI job logs and all fixed in this round:

1. The repo-root mirror suite `tests/memory/` and `tests/migrations/` construct
   the same production stores the maistro-core suites do, but the prior battery
   only ran `packages/maistro-core/tests`, so 26 bare-construction mutation
   tests and 2 PG migrations tests reached CI unguarded and failed with
   `MemoryUndeclaredModeError`. Fixed by declaring
   `exposure_mode=AGENT_MANAGED` on those constructions (same declaration the
   container makes); non-mutating `test_protocols.py` isinstance checks stay
   bare deliberately.
2. `maistro.memory` / `maistro.memory.exposure` entered the promotion-path
   import closure (types/config.py now imports the exposure-mode enum), and the
   write-authority gate is an authorization decision, so both modules are now
   PROTECTED in `maistro_rsi/sensitive_paths.py` (the capabilities/authority.py
   precedent) rather than tolerated in
   `quality/promotion-surface-baseline.json`. This clears
   `check-promotion-surface.py` (lint-and-type-check) and the
   promotion-surface trusted-base gate inside `check-ratchet-provenance.py`
   (Vulture Ratchet / exact-debt-ledger job), and with them
   `tests/test_check_promotion_surface.py`.
3. `docs/architecture/CONVERGENCE-MATRIX.md` still described the pre-#390
   reachability: Memory unreachable share moved `some` -> `few` (5/28) and the
   `(unreachable)` annotation on the `memory.exposure` authorization owner is
   dropped (the checker recomputes both from the same import graph).

Gates re-executed green locally after the fixes: `check-promotion-surface.py`,
`check-ratchet-provenance.py` (all 12 ratchets incl. promotion-surface
trusted-base and the provenance inventory), `check-vulture-baseline.py`
(1390 reviewed identities -> 1390 findings, nothing eliminated, no ledger
amendment needed), `check-shipped-surface-truth.py`,
`check-convergence-matrix.py`, `check-doc-links.py`,
`check-agent-store-writes.py`, `check-suite-inventory.py` (14 suites match);
`ruff check`/`format --check` clean on all touched files;
`tests/memory` 64 passed; `tests/migrations/test_memory_embeddings.py` +
`test_pg_store_wiring.py` 44 passed against the live migrated pgvector pg18
database; `test_check_promotion_surface.py` + `test_check_convergence_matrix.py`
+ maistro-rsi suites 889 passed; maistro-core memory/persistence 502 passed
(103 sqlite/PG skips without DSN) and `test_write_authority_conformance.py`
again 42 passed with live PG legs (alembic head 047).
