# Issue #1893 repair verification — job 6d13fba1

## Frozen scope and initial checkpoint

- Assigned worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Verified starting HEAD `69dbd8478acce55e598a906c3ee73b6476807cb5`; clean worktree.
- Dispatch base `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Process only issue #1893 and its existing codec, identity DTOs, adjacent tests,
  workflow gates, and this verification report. No new integration/activation.
- Snapshot source: supplied job `dispatch-context.json`; no remote mutations or
  re-enumeration. Existing history and prior notes are evidence, not test results.
- Ambiguity: the assignment names a generic CI `test: failure` without its failing
  node. Reproduce focused tests and inspect supplied logs before proposing repair.
- Prior reachability authorization blocker must be reproduced; this lane cannot
  authorize new reachability debt or change gates. Vulture ledger permission is
  limited to actual reviewed findings from the specified command.

## Initial executed results

- Driver logs check-0..4: dependency check, Ruff and format pass; focused tests
  201 passed / 3 skipped; core suite inventory 16466. These are driver evidence,
  not proof of live PostgreSQL behavior.
- Local `origin/develop` resolves to the exact dispatched base above.
- Independently ran the exact assigned Vulture command: PASS, 1323 reviewed
  findings, zero unclassified. No Vulture ledger amendment is justified.
- `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run
  python scripts/check-ratchet-provenance.py`: FAIL, exit 1. Both admission
  modules have new unreachable-module rows and new dispositions without
  trusted-base authorization. Other provenance checks passed.
- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q`:
  201 passed, 3 skipped (PG), 204 collected. No reported test failure reproduced.

The reproduced blocker is not a develop-sync conflict. No grant, ledger or
activation bypass is permitted; do not make speculative production changes.
No production changes or test additions at this checkpoint.

## Focused validation and architectural review

- Read accepted ADR-081226-9944 (canonical hierarchy), ADR-082526-7f02
  (Attempt-owned dispatch and immutable admission provenance), and
  ADR-083126-5e62 (trusted-base quality authority). Reconciliation: preserve
  `Goal -> Graph -> Run -> NodeRun -> Attempt`; do not wire an inactive leaf or
  change quality policy merely to satisfy a gate.
- Inspected both full source modules and both focused test files. Source import
  search finds no production consumer of the codec; the codec imports the DTOs
  and the Vulture whitelist imports an enum. These do not establish reachability.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3277 files formatted.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py`: PASS.
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests`: PASS, 16466 nodes, zero duplicate evidence.
- `uv run pytest packages/maistro-core/tests/tasks
  packages/maistro-core/tests/runs -x -q`: 1918 passed, 310 skipped,
  4 aiosqlite closed-event-loop worker-thread warnings. Skips are not durability
  evidence. Generic CI test failure remains unreproduced.
- Local PostgreSQL reports 18.6; checked that dedicated database
  `maistro_1893_6d13fba1` does not exist before creating it for live validation.

## Live PostgreSQL result

Executed on the starting source SHA, with only this report added:

```sh
createdb maistro_1893_6d13fba1
DATABASE_URL=postgresql:///maistro_1893_6d13fba1 uv run alembic upgrade head
MAISTRO_TEST_PG_DSN=postgresql:///maistro_1893_6d13fba1 \
MAISTRO_TEST_DATABASE_URL=postgresql:///maistro_1893_6d13fba1 \
MAISTRO_REQUIRE_PG_LEGS=1 uv run pytest \
  packages/maistro-core/tests/tasks/test_admission_codec.py \
  packages/maistro-core/tests/runs/test_root_admission_identity.py \
  -x -q -o junit_family=legacy --junitxml=/tmp/1893-6d13fba1-live.xml
```

- PASS: empty dedicated DB migrated through the real chain 001->062; checked
  `alembic_version = 062`. No SQLite schema substitute or mocked pool.
- PASS: **204 passed, zero skipped**, including all three real two-pool cases.
- Recorded production/raw backend PID pairs: unbound 4080821/4080822,
  bound 4080823/4080824, acknowledged 4080825/4080826. All sessions name the
  same database over local Unix sockets; each case recorded one persisted row.
- Injected boundary: escaped-surrogate TEXT stored separately in request,
  receipt and provenance columns; both pools reject each corruption through
  the typed codec while preserving header fingerprint evidence.
- Final SQL counts: task_idempotency=0, canonical_runs=0,
  canonical_node_runs=0, canonical_attempts=0. Database retained for inspection.
- No destructive downgrade test or new mutation/pre-fix comparison was run.
  Earlier mutation claims are not reasserted as this round's evidence.

## Acceptance accounting

| Criterion | Executed evidence or limit |
| --- | --- |
| Frozen/slotted header and exact interfaces; signed scalar and strict UUID hex decoding | Source inspection, scoped mypy and focused header/generation/owner rejection tests PASS |
| Immutable records or explicit typed errors, no invented legacy identity | Bound, unbound, receipt-only, missing-receipt and partial legacy tests PASS |
| Header/full-record separation and scalar mismatch rejection | Expiry/fingerprint preservation and mismatch tests PASS; no clock or assessment in codec |
| Unknown formats fail closed; strict TEXT object JSON; sanitized errors | Unknown-format, duplicate/nonobject/nonfinite, precision, nesting, Unicode and safe-error tests PASS |
| Fresh flat named-column encoding; three snapshots and owner storage mapping | In-memory and three live PG state round-trips PASS; independent binding-column assertions at test_admission_codec.py:134-137 |
| Tagged program_context survives without fingerprint recalculation | Tagged-nonfinite round-trip tests PASS; codec preserves tags and stored fingerprint |
| Raw and production codec pools on real migrated schema | 204 focused tests PASS with mandatory PG legs, distinct sessions and zero residue as above |
| Materialization via model_of/model_of_json; Run JSONB payload is an object | UNVERIFIED: inactive codec neither materializes task/Run models nor inserts Run payloads |
| Explicit authorized principals, Workspace/Project and registered Graph kinds | UNVERIFIED for production admission: codec fixtures use identity strings, not authorization or Graph admission |
| No live assessment, mutation, queue, HTTP or authorization-policy change | Pure codec source inspected; report-only change in this round |
| Focused tests, Ruff, format, scoped mypy and truthful inventory | PASS; no tests added or removed, so no inventory-delta note needed |
| Full unchanged integration CI and trusted-base policy | NOT PROVEN: full integration battery not run; exact-debt-ledger provenance FAILS |
| Reported CI test failure repaired | UNRESOLVED: focused and adjacent suites pass; supplied logs contain no failing test traceback |

## Final disposition and handoff

**BLOCKED.** Actual failure: `quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:606-613` introduce the two inactive
modules without trusted-base authorization. `.github/workflows/vulture-ratchet.yml:77`
requires the failing provenance gate. ADR-083126-5e62 does not permit candidate
bookkeeping to approve itself. The explicit Vulture repair permission does not
extend to reachability grants, and Vulture has no unclassified findings anyway.

No evidence supports an implementation patch in this round. No fake consumer,
ledger change, grant change, gate weakening, GitHub mutation or activation was
introduced. Next: owner-governed trusted-base resolution of reachability debt
and the exact failing CI test traceback if the generic test failure persists.
This report does not claim integration, rollout or issue-closeout readiness.

Changed file: `docs/testing/issue-1893-repair-6d13fba1.md` only.
`git diff --check`: PASS. Commit the report locally; leave the worktree clean.
Progress: checked=1, done=0, skipped=0, errors=1 (unresolved provenance blocker).

