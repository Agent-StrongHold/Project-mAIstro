# Issue #1893 repair checkpoint — a820602f

## Frozen scope

- Assignment: issue #1893 only, branch `auto-1893`, starting HEAD
  `0c65393b699d8bafc973745810287903090100c4`, supplied base
  `ac7370141e8e61bd6f352bca35ed0b505104aadb`.
- Initially clean worktree; no incoming uncommitted work to salvage.
- Inspect existing codec, admission identity types, adjacent tests, relevant ADRs,
  CI workflows, and supplied job evidence. Candidate changes are restricted to
  evidence-supported repair of this leaf and this validation note. No new tests
  or ledger amendments are assumed necessary.
- Supplied `check-0.log` through `check-4.log`: dependency sync, Ruff, format,
  focused tests (346 passed, 3 skipped), core inventory (16567) pass.
- Prior result read: `e3db92aebccd451d9c706e3bcc234354/result.json` reports
  missing trusted-base reachability authorization and no failing test node.

## Ambiguity and assumption

The dispatch names only `test: failure`, without a failing node or traceback.
Treat supplied historical claims as unverified; run focused package validation
and exact named gates. Do not invent a scanner fix, wire production activation,
modify reachability grants, or merge an unspecified moving base. The explicit
CI exception permits reviewed Vulture ledger changes only if actual scan
findings require them. The supplied starting SHA resolves and matches HEAD.

## Executed results

- `origin/develop` resolves to the supplied base `ac7370141e8e`; no develop
  conflict or newer local base exists to merge.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  passed: 1322 reviewed findings, zero unclassified. No Vulture ledger repair
  is evidenced or needed.
- `RATCHET_BASE_REV=ac7370141e8e61bd6f352bca35ed0b505104aadb uv run python scripts/check-ratchet-provenance.py`
  failed (exit 1): two unauthorized new unreachable modules and two unauthorized
  dispositions, for `maistro.runs.admission_identity` and
  `maistro.tasks.admission_codec`. This independently reproduces the prior
  blocker. Other provenance subgates passed.
- Production-source search finds only the codec importing admission identity,
  plus the Vulture whitelist. No production consumer of the codec is present.
  The codec docstring explicitly reserves wiring for consumer leaf C.
- `docs/adr/README.md` and admission-named ADR glob: not found; skipped.

- `uv run ruff check .` and `uv run ruff format --check .`: passed (3301 files).
- `uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs packages/maistro-core/tests/extensions/test_cli_lock.py packages/maistro-core/tests/extensions/test_pack_contracts.py -x -q`:
  2064 passed, 310 skipped, 6 aiosqlite thread-cleanup warnings (49.51s).
  Skips are not durability evidence. No codec failure reproduced.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`:
  passed (two files).
- Read accepted ADR-081226-69ee and ADR-081426-1f7c. Keep canonical
  Graph/Run/NodeRun/Attempt authority and runtime mechanics separation intact.
  Issue B2 forbids production activation; do not reconcile missing reachability
  by introducing an artificial consumer. Authorization needs trusted-base
  coordination outside this repair, not a candidate-ledger edit.
- CI `test` is a multi-suite job outside the core publish-set producer; supplied
  logs have no failing node. Its full result remains UNVERIFIED here.

- `uv run python scripts/check-shipped-surface-truth.py`,
  `uv run python scripts/check-reachability.py`,
  `uv run python scripts/check-reachability-dispositions.py`, and
  `uv run python scripts/check-promotion-surface.py`: passed candidate-shape
  checks. These do not override the failed trusted-base provenance gate.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`:
  passed, 16567 nodes, zero duplicate evidence. No tests changed; inventory
  delta is zero and no inventory note amendment is needed.
- Supplied latest issue comments and PR #1945 body contain no concrete failing
  test traceback. The ambiguity remains UNRESOLVED; no repeated investigation
  or speculative unrelated repair is justified.
- `migrations/env.py`, `migrations/versions/*`, `compose.yml`: not found;
  skipped. Actual Alembic configuration resolves `alembic/env.py`.

## PostgreSQL acceptance evidence

Created only the dedicated disposable database `maistro_1893_a820602f` in the
available `maistro-postgres` container. Existing databases were not used or
modified. Credentials were obtained in memory from the container configuration,
not printed or committed. `DATABASE_URL`, `MAISTRO_TEST_DATABASE_URL`, and
`MAISTRO_TEST_PG_DSN` all targeted this database; `MAISTRO_REQUIRE_PG_LEGS=1`.

- `uv run alembic upgrade head`: passed the real empty-to-063 migration chain
  (including migration 055), PostgreSQL 18.6.
- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q --junitxml=/tmp/1893-a820602f-pg.xml -o junit_family=legacy`:
  **204 collected, 204 passed, zero skipped**, 1.40s.
- Raw and production-codec sessions were on the same database/server
  (`172.20.0.2/32`, port 5432), with distinct backend PIDs:
  unbound 385460/385461; bound 385462/385463; acknowledged 385464/385465.
  Each case asserted exactly one persisted admission row and identical TEXT
  snapshots from both pools. All three exercised corrupt escaped-surrogate
  TEXT in each snapshot column and obtained safe typed failures.
- After the suite: migration head 063; `task_idempotency` count 0 and `tasks`
  count 0. The disposable database is retained for inspection. This proves
  codec SQL mapping, not authorized admission or canonical Run creation.

### Mutation evidence

Executed an in-memory mutation (no source edits): wrapped
`encode_admission_record` to force `row['task_id'] = None`, then invoked
`pytest.main` on `test_v2_round_trip_preserves_all_snapshot_bytes`.
The bound and acknowledged variants failed at
`packages/maistro-core/tests/tasks/test_admission_codec.py:134`, while the
unbound case passed (2 failed, 1 passed, 128 deselected; expected pytest exit 1).
Thus the existing test detects the previously repaired one-sided binding
regression independently of encoder/decoder agreement. The subprocess ended;
no mutation persists in the tree.

## Acceptance accounting and handoff

- Frozen/slotted header, strict format/scalars/UUIDs, mismatched-header rejection,
  fresh flat v2 mappings: exercised by the passing codec tests.
- Legacy bound/unbound/partial distinctions, no invented identity, ignored
  `completed_at`, expiry/fingerprint evidence despite full-decode failure:
  exercised by the passing codec tests. No claim/expiry/409 decision is made.
- Invalid/duplicate/nonobject/nonfinite JSON and unsafe exception-chain
  suppression; tagged snapshots and unchanged fingerprints: codec tests pass.
- Both real pool configurations and migration-055-compatible binding encoding:
  demonstrated above, not counted from skipped tests or fake pool values.
- Immutable DTO fencing/receipt consistency: adjacent identity suite passed.
- Production model materialization (`model_of`/`model_of_json`), authorized
  Workspace/Project/Graph admission, and actual Run JSONB object insertion:
  **UNVERIFIED** by this codec-only suite; fixtures use identity strings, not
  real authorization setup. Do not call the PG codec tests admission proof.
- Reachable production consumer: absent by source inspection and scanner;
  activation is expressly outside B2. Trusted-base reachability authorization
  remains **BLOCKED**, regardless of passing candidate-shape checks.
- Full required CI and the reported generic `test: failure`: **UNVERIFIED**;
  no failing node supplied or reproduced in the bounded package validation.
- No production/test/ledger/gate changes were justified. Only this evidence
  note changed; inventory delta remains zero. `git diff --check` passed.

Disposition: **BLOCKED**. One assigned issue checked, zero repairs completed,
one blocked item, zero skipped issues. Next: owner supplies the failing CI
node/log and resolves the trusted-base reachability prerequisite through the
established coordination process. Re-dispatching the same evidence cannot
safely authorize activation or candidate grants. No GitHub mutation, merge,
rollout approval, or issue closure was performed.
