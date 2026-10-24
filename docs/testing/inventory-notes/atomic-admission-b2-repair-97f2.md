---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 repair validation — 97f2

Only issue #1893, assigned branch/worktree `auto-1893` /
`/home/dev/Git/wt/auto-1893`. Verified clean starting HEAD
`951c5d0eab6b7e80559f6694f3a45a90f1bb589b`; supplied base
`34795962548a33f6b6f7e1234dcea201a9df96ef` resolves locally.
Frozen possible edits: admission_codec.py, test_admission_codec.py, this note,
and vulture-baseline.json only for demonstrated reviewed identity drift.
No remote enumeration, GitHub mutation, merge, activation, or other leaf work.
Job artifacts: `/home/dev/maistro/jobs/97f271450a6f4759b89266d4789db3b4/`.

## Inspection and reproduced blocker

Read repository instructions, issue body and captured dispatch evidence, prior
82da result, codec, adjacent immutable DTO/tests, production PG fixture, migration
055, and accepted ADRs 081426-1f7c, 082526-7f02, 082826-b601, 082826-d9f5.
The Goal -> Graph -> Run -> NodeRun -> Attempt spine, Attempt-owned execution
identity, immutable admission provenance, and canonical RunStore/consumer remain
unchanged. Assignment is treated as staged repair ownership, not production
activation or independent integration approval.

Historical binding finding is already repaired: admission_codec.py:290 emits
`binding.receipt_id` as bound `task_id`; `_v2_binding` checks the pair and receipt
identity against migration 055:207-210. Existing round-trip tests independently
assert both fields. No speculative source change is warranted by that report.

Fresh exact command `uv run python scripts/check-vulture-baseline.py
packages/*/src --min-confidence 60 --exclude '*/third_party/*'` passed:
1328 reviewed identities / 1328 findings, no unbanked identities. Therefore no
vulture ledger edit is justified (repair-vulture.log).

Fresh `RATCHET_BASE_REV=34795962548a33f6b6f7e1234dcea201a9df96ef uv run python
scripts/check-ratchet-provenance.py` exited **1** (repair-provenance.log):
trusted merge base af799688335f has 169 unreachable/dispositioned modules;
candidate has 171. `maistro.runs.admission_identity` and
`maistro.tasks.admission_codec` are unauthorized additions in both ledgers.
This is not vulture debt. Candidate reachability/grant edits are prohibited and
would not authorize themselves. Production import inspection confirms no codec
consumer; tests and the vulture whitelist are not runtime reachability. Wiring
another leaf or a fake caller to evade the gate is outside this repair.

Ambiguity: dispatch reports generic hosted `test: failure` without a failing
node/log. The supplied snapshot's #1945 check at
`05d3e2f799f2b0d2a194c896823bf181309a9887` instead records `test: success`
and `exact-debt-ledger: failure`, with no error text (captured-ci-summary.txt).
Those are a different head, not validation of this HEAD. The generic test
failure is **UNRESOLVED**, not a reason to guess a source repair. No earlier
verification claim is counted as current proof.

## Executed validation

All source/tests remained at starting HEAD; this inventory/handoff note is the
only repository change. Commands used long timeouts, with results retained in
the job's `repair-*` artifacts.

- Created disposable local PostgreSQL **18.6** DB `maistro_1893_97f2` after
  confirming that exact name was absent. `DATABASE_URL=postgresql:///maistro_1893_97f2
  uv run alembic upgrade head` passed through the real chain to **060**.
  No schema recreation, SQLite substitution, migration downgrade, or existing
  application DB was used.
- Set both `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` to
  `postgresql:///maistro_1893_97f2`, with `MAISTRO_REQUIRE_PG_LEGS=1`.
  `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q
  -o junit_family=legacy --junitxml=<job>/repair-focused.xml`:
  **204 passed, no skips**. `--collect-only -q` output is recorded in
  repair-focused-nodes.txt.
- Three real-DB states (unbound/bound/acknowledged) used independent
  production/raw backend PID pairs **3523765/3523766**, **3523767/3523768**,
  **3523769/3523770**, all on that DB through the local Unix socket.
  `pg_pool` was non-None and registered production `_register_json_codecs`.
  Each state asserted **1 persisted scoped row**, complete DTO equality and
  identical TEXT values through both pools; corrupt surrogate evidence was
  rejected through each reader. After focused tests SQL showed **0 rows,
  0 generations, 0 Run IDs** in task_idempotency (repair-focused-counts.log).
- Same DB environment, `uv run pytest packages/maistro-core/tests/tasks
  packages/maistro-core/tests/runs -x -q -rs`: **2118 passed, 3 skipped,
  6 warnings** in 73.32s. Skips are backend-inapplicable archive/continuation
  cases, not the codec PG legs. Warnings are aiosqlite worker callbacks after
  event-loop closure; not repaired outside scope.
- Regression sensitivity: `uv run python` replaced the encoder **in process
  only** with a wrapper assigning `task_id=None`, then invoked pytest on the
  bound/acknowledged unit round trips and the bound two-pool PG test.
  All **3 failed as expected**: two at test_admission_codec.py:134 and the PG
  INSERT at :506 with `ck_task_idempotency_v2_identity` CheckViolationError.
  Harness asserted `pytest.ExitCode.TESTS_FAILED`; no source file mutation.
  This proves the existing tests detect the historical defect rather than
  merely making encoder/decoder agree. Artifact: repair-binding-mutation.log.
- Final SQL after adjacent tests and mutation: migration **060**, **3 legacy
  rows, 0 distinct generations, 2 distinct Run IDs**, no v2 codec residue
  (repair-final-counts.log).
- `uv run ruff check .` and `uv run ruff format --check .`: passed.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py`: passed,
  2 source files.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests`: passed, **15610** nodes, delta **0**.
- `uv run python scripts/check-reachability.py`,
  `check-reachability-dispositions.py`, `check-promotion-surface.py`, and
  `check-shipped-surface-truth.py`: candidate scans passed. These do not
  negate the trusted-base provenance failure above. The exact-debt workflow
  explicitly runs provenance before vulture, so a green vulture scan alone
  does not clear that CI job.
- `git diff --check`: passed before handoff.

## Acceptance audit

| Criterion | Current executed evidence / limitation |
| --- | --- |
| Frozen/slotted header, typed immutable DTOs, fresh named flat mapping | Source inspected; focused immutable-identity tests and `test_v2_round_trip_preserves_all_snapshot_bytes` (3 states), `test_encode_returns_a_fresh_flat_mapping` passed |
| Strict storage UUID .hex, signed scalars, matched header | Owner/generation UUID, scalar mismatch, invalid scalar, missing-column and record-window tests passed |
| Typed errors; only validated hash; no snapshot/token in displayed error chains | `test_decode_error_scope_key_is_only_a_validated_hash`, owner-token and malformed/nested/lossy/non-UTF8 snapshot tests passed; parsing raises suppress unsafe chains |
| Legacy bound vs unresolved vs partial/receipt-only, no guessed identity | `test_legacy_binding_unbound_and_partial_are_distinct`, receipt-only, missing-receipt, unreadable and whitespace evidence tests passed |
| Expired legacy header carries scalars independently of full decode | `test_expired_legacy_header_does_not_invent_missing_identity`, malformed snapshot expiry and partial binding fingerprint tests passed |
| Unsupported format never falls back to legacy | `test_unknown_format_cannot_be_reinterpreted_as_legacy` passed all 7 cases |
| Preserve snapshot evidence/tags and stored fingerprint | All snapshot round trips, tagged nonfinite, exact-number and valid Unicode tests passed; source has no fingerprint recalculation |
| Reject duplicate/nonobject/bare nonfinite JSON and unsafe evidence | `test_invalid_and_duplicate_json_is_rejected`, excessive nesting, lossy numbers, predecoded values and surrogate tests passed |
| Raw and production codecs on same migrated DB, bound encoding meets SQL constraint | Three real two-pool tests passed with sessions/counts above; historical bound encoder mutation fails actual migrated CHECK |
| No new clock, assessment, claim mutation, SQL/HTTP/queue policy or execution authority | Source inspection confirms pure mapping codec and no consumer; this round changes no production code |
| model_of/model_of_json materialization, provenance encode_evidence and object-valued Run JSONB INSERT | **UNVERIFIED** by codec tests: they retain tags but do not materialize task/Run models or insert Runs |
| Authorized principals/Workspace/Project and registered Graph on positive admission | **UNVERIFIED**: these are DTO/storage tests with string identities, not production admission |
| Inclusive expiry and changed-payload 409 precedence | **UNVERIFIED**, consumer C/F2 responsibility; this codec only proves preserved scalar evidence |
| Full required hosted CI / integration acceptance | **UNVERIFIED**; generic test failure has no reproducible supplied node, and trusted-base provenance independently fails |

## Handoff

**BLOCKED.** No fresh codec failure or exact vulture mismatch supports a source
or ledger amendment. Do not add fake runtime imports, modify grants/gates, or
activate another leaf to hide the actual reachability/disposition blocker.
Needed next: owner-coordinated trusted integration/authorization for the inactive
modules, plus a concrete hosted failing-test log if `test: failure` still applies.
The issue's staged contract work and live production acceptance remain distinct.

Progress: checked **1**, validation/handoff done **1**, skipped issues **0**,
blocking gate errors **1**. Only this note changed; no new tests, inventory count
change, policy change, or GitHub mutation. Commit locally; not integration approval.
