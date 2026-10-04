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

## Independent verification round 2 (verifier, head 6c62e18664c5 = b9db8716d + develop 33bcd3ce merge)

All executed by the verifier in this worktree at the exact head; not taken from
any prior claim:

- Gates re-run with CI's exact argv: `check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` exit 0 (1370 reviewed
  identities -> 1370 findings). Note for future rounds: a bare
  `check-vulture-baseline.py` with no path args scans trees CI does not
  (tests/, third-party surfaces) and reports hundreds of stale/new identities —
  that invocation is not the exact-debt-ledger gate and its failure is not a
  regression of this branch. `check-ratchet-provenance.py`,
  `check-shipped-surface-truth.py`, `check-promotion-surface.py`,
  `check-promotion-surface-provenance.py`, `check-convergence-matrix.py`,
  `check-reachability.py`, `check-release-consistency.py` all exit 0.
- mypy clean over all six `packages/*/src` trees (745 files); `ruff check` /
  `ruff format --check` clean (driver checks 1-2 at this head).
- `test_exposure_mode.py` + `test_write_authority_conformance.py`: 62 passed /
  98 skipped without a DSN; against a fresh pgvector pg18 container
  (`alembic upgrade head` -> 049) the same files are 76 passed / 84 skipped,
  i.e. every postgres leg executed, including the denied-write-leaves-no-state
  and undeclared-store-refuses-every-record scenarios.
- Full `packages/maistro-core/tests/memory` + `tests/persistence` +
  `test_container_episodic_store.py` with the live DSN: 1161 passed / 84
  skipped (skips are the declared-mode matrix legs assigned to other backends).
- Root mirror `tests/memory`: 64 passed. `tests/migrations/
  test_memory_embeddings.py` + `test_pg_store_wiring.py` with
  `MAISTRO_TEST_DATABASE_URL`: 44 passed.
- Root-suite gate self-checks with `RATCHET_BASE_REV=33bcd3ce2`: 204 passed
  (`test_check_promotion_surface.py`, `test_check_convergence_matrix.py`,
  `test_check_ratchet_provenance.py`, `test_check_vulture_baseline.py`,
  `test_check_release_consistency.py`, `test_check_reachability.py`).
- Code audit re-confirmed at this head: `require_write_authority` is the first
  statement of `store`/`record`/`check_auto_promotions` in all ten store
  classes; container, testing harness, hive-conductor engine and
  feedback_service all declare `exposure_mode`; the gate reads only mode,
  actor and per-block tag. No closure keyword (fixes/closes/resolves) in the
  PR body or any branch commit message.

## CI-repair round 2 (merge of develop 8c8fc8d6 at db25f6ea4)

The salvaged in-flight develop sync was completed (its sole conflict,
`container.py`, resolved to keep both the ADR-057 `exposure_mode` wiring and
develop's fourth SQLite connection for the backlog-history journal), and two
classes of regression were repaired at that head:

1. Sync-reintroduced bare store constructions. The develop syncs brought
   develop-side versions of three test files whose constructions predate the
   write-authority gate, reintroducing the exact failure class CI-repair round
   1 fixed. `test_unscoped_global_recall.py`, `test_project_global_recall.py`
   and hive's `test_optimizer_candidate_apply.py` again constructed stores
   bare and mutated them (14 + 1 + 1 failures with
   `MemoryUndeclaredModeError`). Fixed by declaring
   `exposure_mode=MemoryExposureMode.AGENT_MANAGED` at those sites — the same
   declaration the container makes. Deliberately-bare sites are untouched:
   `test_exposure_mode.py`'s reachability matrix, `test_protocols.py`'s
   isinstance checks, and the read-only (`find_similar`) construction in
   `tests/migrations/test_memory_embeddings.py`; an AST scan over every
   `**/tests/**` tree reports no other bare construction of the nine memory
   store classes.
2. The root-suite inventory double-count. The union note
   `auto-390-develop-sync-union.md` (+18) was true when written at 79b118c63
   (expected 4392, collected 4410) but the later develop syncs brought
   develop's own ledger rows for the same nodes, making expected 4441 against
   a collected 4423 that is byte-identical to develop's node set. Its
   front-matter delta is retired to +0 with the full evidence recorded in that
   note; `check-suite-inventory.py` (all-suites form) is green again.

Re-executed at db25f6ea4 + these fixes: the two exact-debt-ledger sibling
gates (`check-ratchet-provenance.py`, `check-shipped-surface-truth.py`) and
`check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
'*/third_party/*'` all exit 0 (1361 reviewed identities -> 1361 findings);
`check-suite-inventory.py` 14/14 suites match; `ruff check .` and
`ruff format --check .` clean; `test_exposure_mode.py` +
`test_write_authority_conformance.py` 62 passed / 98 skipped (PG legs skip
without a DSN); `tests/memory` 64 passed; the repaired files 15 passed /
7 skipped and 25 passed; the memory + persistence + container-episodic driver
battery 507 passed / 144 skipped.
