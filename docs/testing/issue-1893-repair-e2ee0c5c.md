# Issue #1893 repair evidence — e2ee0c5c

## Frozen scope

- Assigned issue: #1893 only; branch `auto-1893`.
- Starting HEAD: `6ce048f310b937f84616c9acc8ad0335037ebe6b`.
- Assigned base: `435dc1937e0407ab4de198ffcced49860bb14ad2`.
- Starting worktree clean; no incoming diff to salvage.
- Inspect existing admission codec, immutable identity types, their two test files,
  relevant ADRs, workflows, and supplied job artifacts. No new activation,
  authority, HTTP behavior, or reachability grant is authorized.
- Planned changed file: this evidence record. Change production/tests only if
  validation identifies a reproducible in-scope defect; vulture ledger amendments
  only for evidenced retained identities under the explicit repair permission.
- Supplied `check-0..4.log`: dependency sync, ruff check/format, focused tests
  (201 passed, 3 skipped), and core inventory (16466) pass. These are driver
  results, not this worker's executed validation.
- Ambiguity: the dispatch requests repair of generic CI `test: failure` without
  a failing node/traceback. Proceed by reproducing focused acceptance and named
  gates; do not guess a code fix. Prior reachability findings must be rechecked.

## Results

- Fresh exact Vulture scan passed: 1323 reviewed findings, zero unclassified.
  No vulture ledger amendment is warranted.
- Fresh `RATCHET_BASE_REV=435dc1937e0407ab4de198ffcced49860bb14ad2 uv run
  python scripts/check-ratchet-provenance.py` failed (exit 1): both admission
  modules add unauthorized unreachable identities and dispositions (169 -> 171).
  The base ref was resolved before execution. This is not a merge conflict.
- The vulture-only repair permission cannot fix that reachability prerequisite.
  No re-run or candidate grant/ledger change will be used to bypass it.
- Prior job result confirms the same blocker, but the result above is freshly
  executed. Continue bounded acceptance validation; integration remains BLOCKED.
- Fresh focused codec/identity run: 201 passed, 3 skipped (missing PG env),
  204 collected; root ruff check and format check pass (3277 files); targeted
  mypy passes (two source files). Commands used 1200-second timeouts.
- Read accepted ADR-082526-7f02 and ADR-081426-1f7c: immutable admission
  provenance and Attempt-owned execution remain authoritative. No scheduler,
  execution authority, or authorization path is added.
- An existing lane-owned `auto-1893-pg` pgvector/pg18 container is running at
  localhost:15498. Next bounded step: create a fresh job-specific disposable
  database there and run the actual migration chain and three PG contrast cases.
  Existing databases will not be truncated, downgraded, or reused.
- Fresh suite inventory passes: 16466 core nodes, zero duplicate evidence;
  shipped-surface check passes. Runtime import search finds only the codec's
  DTO import and the vulture whitelist, not a production consumer.
- PG preflight using the container's `POSTGRES_USER` failed: that environment
  variable is absent, so psql attempted role `root`. No DB was mutated. One
  final bounded connection attempt used the image's default `postgres`
  role and retrieved its local test credential without printing or committing it.

## Executed PostgreSQL evidence

The second preflight succeeded: PostgreSQL 18.6, role `postgres`, no existing
`maistro_1893_job_e2ee0c5c` database. Created that disposable database in the
existing lane container. Set `DATABASE_URL`, `MAISTRO_TEST_PG_DSN`, and
`MAISTRO_TEST_DATABASE_URL` to the same database at localhost:15498 (credential
omitted), and `MAISTRO_REQUIRE_PG_LEGS=1`.

- `uv run alembic upgrade head`: PASS, actual empty-schema chain 001 -> 062,
  including forward admission migration 055. No downgrade test was run.
- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -r s
  -o junit_family=legacy --junitxml=/tmp/issue-1893-e2ee0c5c.xml`: **204 passed,
  zero skipped**, 1.55s. Source SHA remains the assigned starting HEAD.
- Both readers reported database `maistro_1893_job_e2ee0c5c`, server
  `172.17.0.9/32:5432`. Production/raw backend PID pairs were 10289/10290
  (unbound), 10291/10293 (bound), 10294/10295 (acknowledged).
- Each PG case persisted exactly one admission row, compared all named encoded
  fields through raw and production JSON-codec pools, decoded the same DTO, and
  injected escaped-surrogate corruption into each snapshot column. Both pools
  produced typed, safely chained errors without losing header fingerprint.
- Post-test count query initially failed because it named `runs` rather than
  `canonical_runs`; this was a diagnostic SQL mistake, not a test failure.
  After reading the actual fixture table names, the corrected query passed:
  `task_idempotency`, `canonical_runs`, `canonical_node_runs`, and
  `canonical_attempts` each contain **0 rows**. The new database is retained
  for inspection; no other database was modified.

## Commands and outcomes

All validation commands used 1200-second timeouts (short metadata/SQL commands
used 120 seconds). In addition to the PG commands above:

| Command | Actual outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1323 findings, zero unclassified |
| `RATCHET_BASE_REV=435dc1937e0407ab4de198ffcced49860bb14ad2 uv run python scripts/check-ratchet-provenance.py` | FAIL, unauthorized reachability modules and dispositions |
| Focused pytest command above, initially without PG configuration | 201 passed, 3 skipped |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3277 files |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS, two files |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS, 16466 nodes |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS |
| `git diff --check` | PASS |

## Acceptance review and boundaries

| Criterion | Evidence or explicit limitation |
| --- | --- |
| Frozen/slotted header, shared decode/encode signatures and six typed error codes | Source review; header scalar mismatch, schema, format and fresh-flat-mapping tests pass |
| Strict storage UUID hex, signed timestamps and #1851 constructors | Owner/generation rejection, timestamp validation and DTO contract tests pass |
| Exact v2 snapshots and bindings | All three state round trips pass in memory and on migrated PG; independent task/receipt paired-column assertions pass |
| Legacy bound/unbound/partial, receipt-only and missing receipt evidence | Tests pass; no identity fabricated, completed_at ignored, pair without receipt remains partial rather than inventing receipt identity |
| Header survives snapshot/binding failure; unknown versions fail closed | Named expiry/fingerprint preservation, unknown-format and header mismatch tests pass; no clock or incoming fingerprint in codec |
| Strict TEXT snapshot JSON and safe errors | Duplicate/nonobject/bare-nonfinite, excessive nesting, numeric precision and surrogate failures pass; errors suppress unsafe chains and expose validated scope only |
| Tagged evidence without fingerprint recalculation | Tagged nonfinite round-trip tests pass, codec preserves stored fingerprint; no tag decoding in this layer |
| Named SQL fields and raw/production pool equivalence | Three PG cases pass with real 055 constraints, identical DB identity and independent sessions; snapshots stay TEXT |
| Model materialization via model_of/model_of_json, original-model fingerprinting and Run JSONB object INSERT | UNVERIFIED: fixtures are tagged dictionaries, not production model persistence; codec does not materialize or insert Runs |
| Explicit authorized principals, Workspace/Project, registered Graph kinds | UNVERIFIED: codec fixtures use identity strings and prove representation only, not admission authorization |
| No SQL mutation, HTTP, queue, scope utility, classifier or claim-policy change | Source review; no source changes this round. Canonical Goal -> Graph -> Run -> NodeRun -> Attempt unchanged |
| Reachable production behavior | NOT ESTABLISHED: codec explicitly inactive at admission_codec.py:49-52; source search finds no production consumer. Tests and whitelist are not runtime reachability |
| Consumer expiry replacement/409 precedence, transaction/crash/dispatch invariants | UNVERIFIED and outside B2; no fake caller or extra authority added to claim these |
| Required CI, provenance and dispatched test failure | Full CI UNVERIFIED; focused tests pass with zero skips, but exact-debt-ledger provenance fails. Supplied artifacts contain no actionable failing test traceback |
| Coordination, activation and independent integration readiness | BLOCKED; lane assignment authorizes only this bounded repair, not owner-policy decisions or production activation |

## Handoff

Changed only this evidence file. No source/test defect reproduced, so no cosmetic
repair, test addition, inventory delta, vulture-ledger change, or mutation proof
is claimed. Existing test additions already have inventory notes. Root lint,
format, scoped typecheck and suite inventory are green, but green contract tests
cannot make an inactive slice independently mergeable.

Blocking locations: `quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:612-613`; enforced by
`.github/workflows/vulture-ratchet.yml:77`. Owner prerequisite remains an
already-landed authorization under the two-merge rule or separately authorized
runtime integration. This lane may do neither. No fetch/sync was justified:
the exact assigned base resolves, and there is no merge conflict.

Progress: checked 1 issue, done 0 source repairs, skipped 0 issues, errors 1
required gate. Next: owner resolves reachability prerequisite and supplies the
actual current-head CI test failure if one remains. Verdict: **BLOCKED**.
This local commit is evidence handoff only, never integration approval.
