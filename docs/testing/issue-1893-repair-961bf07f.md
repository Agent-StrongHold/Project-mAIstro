# Issue #1893 repair checkpoint — 961bf07f

## Frozen scope

- Assigned issue: #1893 only; branch `auto-1893`.
- Starting HEAD: `95a58983c3fcae57ae0dca154cb129aaae19b4e8`.
- Assigned develop base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Worktree was clean at entry. No incoming edits needed salvage.
- Inspect existing admission codec, identity DTOs, their two test files,
  relevant architecture/ADRs and CI scripts; change production/tests only on
  reproduced evidence. This report is the planned documentation change.
- Supplied dispatch snapshot and check-0 through check-4 are the only campaign
  evidence snapshot; no GitHub refresh or mutations.

## Initial evidence and ambiguity

Driver logs: dependency sync, lint, format and inventory pass; focused tests
report 201 passed, 3 skipped. These are driver evidence, not local reruns or
PostgreSQL durability evidence. The dispatch reports a generic CI `test:
failure` without a failing node, and a previous reachability-provenance blocker.
Assumption: validate these locally before proposing a repair; do not invent a
failure or grant. Activation and parent closeout remain outside this leaf.

## Local checkpoint

- Exact supplied base resolved successfully before use.
- CI-exact Vulture scan: exit 0 (`worker-vulture.log` in this job directory).
- `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py`: exit 1 (`worker-provenance.log`).
- Codec and test inspection confirms there is deliberately no production consumer;
  existing bound encoding already emits task_id and run_id together. No production
  modification or Vulture ledger amendment is justified by the evidence so far.
- Read accepted ADR-081226-a66b, ADR-082526-7f02, ADR-082826-b601 and
  ADR-083126-5e62. Reconciliation: preserve the canonical lifecycle and immutable
  provenance; never introduce a fake caller/activation or candidate-side grant
  to get an inactive leaf past trusted-base policy.
- Provenance failed specifically for two unauthorized modules and two unauthorized
  dispositions (169 -> 171), not Vulture. No permitted ledger repair applies.
- Captured CI extraction (`worker-captured-ci.txt`): `test` failure is on
  `3f2c79a70d9e1b0b6b6ffc99562cb35db5326828`; candidate PR snapshot
  `fcc8b437f209a35aa68a61d6f0a5387414938355` has `test` success and
  `exact-debt-ledger` failure. No current assigned-head failing test node supplied.
  Attribution of the generic failure is UNRESOLVED; no further enumeration.
- Local Ruff check and format passed (3277 files); mypy on both source modules
  passed. Source search finds only the codec's identity import and the Vulture
  whitelist, not a runtime codec consumer.
- CI command search included an unmatched workflow glob (exit 2); no validation
  claim relies on that glob. The actual `ci.yml` and `vulture-ratchet.yml` were found.

## Executed validation

All implementation/test validation used source HEAD
`95a58983c3fcae57ae0dca154cb129aaae19b4e8`; only this report differs.
Logs and the collected JUnit nodes are in the assigned job directory.

| Command | Outcome |
| --- | --- |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3277 files |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS, 2 files |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1323 reviewed identities, zero unclassified |
| `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py` | FAIL, four admission reachability/disposition findings |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS, 16466 unique nodes, zero duplicates |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS |
| `uv run alembic upgrade head` with disposable DATABASE_URL | PASS, real migration chain through 062 |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -o junit_family=legacy --junitxml=<job>/worker-focused-pg.xml` with PG environment below | **204 passed, zero skipped**, 1.44s |
| `uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs -x -q` without PG environment | **1918 passed, 310 skipped**, 48.88s; 6 aiosqlite closed-event-loop thread warnings |

Created fresh disposable DB `admission_1893_961bf07f` in the existing lane
container `auto-1893-pg` (PostgreSQL 18.6). Nonempty `DATABASE_URL`,
`MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` targeted that same DB;
`MAISTRO_REQUIRE_PG_LEGS=1` forbade the focused durability skips. Credentials
were obtained privately from container configuration, not printed or committed.
No downgrade test was run and no existing database was touched.

The three PG tests used the real production-codec fixture (non-None) and an
independent raw asyncpg pool. JUnit records the same DB/server
`172.17.0.9/32:5432` with production/raw backend pairs 37515/37516 (unbound),
37517/37518 (bound), 37519/37520 (acknowledged). Each case persisted one scoped
row, read identical TEXT snapshots from both pools, and injected escaped
surrogate corruption into each snapshot column. Final SQL: migration 062;
zero admission rows, distinct generations, distinct Run IDs; zero canonical
Runs, NodeRuns and Attempts. DB retained for inspection.

Negative regression probe, in memory only: replaced the encoder with a wrapper
setting `task_id=None`, then ran `test_v2_round_trip_preserves_all_snapshot_bytes`.
Bound and acknowledged variants failed independently at test line 134; unbound
passed (2 failed, 1 passed, 128 deselected, pytest exit 1 as expected).
`worker-binding-mutation.log` preserves evidence. No test/source file was edited.

## Acceptance evidence and limits

The following existing tests all executed in the 204-pass run. They prove the
representation/storage boundary, **not reachable authorized admission**.

| Criterion | Evidence |
| --- | --- |
| Immutable snapshots, fresh flat mapping, binding SQL shape | `test_v2_round_trip_preserves_all_snapshot_bytes` (3 states), `test_encode_returns_a_fresh_flat_mapping`; independent binding mutation above |
| Owner token storage-only strict UUID hex, no diagnostic leak | `test_owner_token_is_hex_at_storage_only`, generation-format and repr tests |
| Bound/unbound/partial legacy are distinct, never invented | `test_legacy_binding_unbound_and_partial_are_distinct`, receipt-only, missing-receipt, unreadable/whitespace legacy tests |
| Header remains usable for expired legacy evidence | `test_expired_legacy_header_does_not_invent_missing_identity`; no clock or expiry decision |
| Header expiry survives bad snapshot | `test_header_preserves_expiry_even_when_legacy_snapshot_decode_fails` |
| Header fingerprint survives partial binding | `test_header_preserves_fingerprint_even_when_legacy_binding_is_partial` |
| Unknown format fail-closed, matching scalar header and signed timestamps | `test_unknown_format_cannot_be_reinterpreted_as_legacy`, scalar mismatch and invalid-header tests |
| Tagged nonfinite context preserved without fingerprint recalculation | `test_tagged_nonfinite_snapshots_round_trip_without_fingerprint_change`, valid numeric/Unicode tests |
| Duplicate/nonobject/bare nonfinite/invalid JSON fail safely | `test_invalid_and_duplicate_json_is_rejected`, nesting, lossy-number and surrogate tests |
| Migrated raw/production pools agree on TEXT snapshots | `test_raw_and_production_pool_codecs_read_identical_text_snapshots` (3 real DB cases) |
| Required frozen/slotted header, six codes, validated error scope, #1851 constructors, named SQL mapping | Source inspection plus header/error/mapping tests and targeted mypy |
| No mutation, queue, HTTP, clock, classifier, scope-policy or authorization addition | Source inspection; this round changes documentation only. `completed_at` is never read (executed test) |
| Common quality gates | Local commands above; trusted-base provenance remains **FAILED** |

**UNVERIFIED:** authorized Workspace/Project/explicit principals/registered Graph
admission; actual-model evidence-json encoding and `model_of`/`model_of_json`
materialization; original-model fingerprint computation; Run `json_of(run)`
TEXT-to-JSONB object INSERT; consumer expiry/409 precedence (C/F2, not B2);
full unchanged integration CI; coordination/activation approval. Synthetic
identities and hand-tagged JSON in these tests cannot establish those properties.

## Blocked handoff

The actual blocker remains `quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:606-613`: two modules and their
candidate-side dispositions lack trusted-base authorization. The authorized
Vulture exception does not cover these files. No Vulture debt or codec defect
was reproduced; therefore no production, ledger, grant or gate patch is justified.
Do not activate the leaf, add fake imports or self-authorize it to bypass this.
An owner must resolve the reachability authorization using the trusted-base
workflow before another integration attempt. Obtain a current-head failing
`test` trace before assigning another speculative test repair.

Changed file: this report only. No tests/counts changed, so no new inventory-delta
note is required. Commit is an evidence handoff, not integration approval.

Progress: checked 1, done 0 repairs, skipped 0 issues, errors 1 unresolved
provenance blocker. Next: owner provenance resolution and exact current-head
CI failure evidence. No GitHub mutations, merge, fetch or activation performed.

