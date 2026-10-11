# Issue #1893 repair validation — 67e08fc7

## Frozen scope

- Assigned worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Starting HEAD `55ca145703839f92966d14f917b13474dda4ea9a`; supplied develop
  base `435dc1937e0407ab4de198ffcced49860bb14ad2`. Initial worktree clean.
- One item: issue #1893 B2 immutable admission codec, prerequisite identity
  types, their existing tests, and the reported `test`/exact-debt-ledger failures.
- Inspect existing codec/identity modules, adjacent tests, applicable ADRs,
  supplied dispatch/check logs, and CI gate definitions. Only this report and
  evidence-driven repairs to those assigned surfaces are candidates for edits.
- No GitHub mutations, activation, policy selection, reachability grants or
  non-vulture ledger changes. No new work items or re-enumeration of dispatch.

## Initial evidence and assumptions

The supplied driver logs report dependency sync, ruff check/format, 201 passing
focused tests with three skipped PostgreSQL legs, and a passing core inventory
(16,466 collected nodes). Skipped legs are not durability evidence. Prior results
are historical claims, not results of this run.

The dispatch calls this a writer repair; the verifier-only no-edit instruction
is therefore not applicable. The issue explicitly forbids activation of the
staged codec. Any missing runtime reachability must not be papered over with
fake callers or unauthorized baseline changes. Previous blockage concerns
reachability provenance, not an established develop merge conflict; do not merge
or fetch unrelated moving state speculatively.

## Reproduced blocker

- Exact required Vulture command passed: 1,323 findings, zero unclassified.
  No vulture amendment is supported by the scan.
- `RATCHET_BASE_REV=435dc1937e0407ab4de198ffcced49860bb14ad2 uv run python
  scripts/check-ratchet-provenance.py` failed (exit 1): both admission modules
  introduce unauthorized unreachable identities and dispositions (169 -> 171).
  `origin/develop` resolves to that same supplied base. This is not a merge
  conflict and a same-base sync cannot fix it.
- No runtime activation or reachability grant is authorized in this lane. The
  vulture-only exception does not permit editing reachability ledgers. Integration
  remains BLOCKED; continue only bounded existing acceptance validation.

## Focused results

- Root `uv run ruff check .` and `uv run ruff format --check .` pass (3,277
  formatted files); targeted mypy passes on the two source files.
- Focused codec/identity pytest: 201 passed, three PostgreSQL skips, 204 nodes.
- Core suite inventory passes (16,466 nodes, no duplicate evidence);
  shipped-surface truth passes.
- Read accepted ADR-082526-7f02 (immutable admission provenance; dispatch identity
  belongs to Attempt) and ADR-081426-1f7c (runtime mechanics are Attempt-owned).
  No competing authority or scheduler is introduced. An initially guessed ADR
  filename was not found; skipped and read the actual matching filename.
- Source import search finds only the codec's DTO import and the vulture
  whitelist, not a production consumer. These contract tests cannot establish
  production admission, transaction, dispatch, or authorization behavior.
- `test` in `.github/workflows/ci.yml:573-612` does not run these core tests;
  their canonical producer is coverage. The generic `test: failure` supplied
  here lacks a failing node/traceback. Full unrelated suites are not rerun or
  changed speculatively.
- Existing lane container `auto-1893-pg` is running PostgreSQL 18.6 at
  localhost:15498. Preflight confirmed the job-specific disposable database
  `maistro_1893_job_67e08fc7` does not exist. Next: create it, migrate the actual
  chain, and execute the existing PG legs; no existing DB will be truncated.

## Real PostgreSQL acceptance

At source HEAD `55ca145703839f92966d14f917b13474dda4ea9a`, created only
`maistro_1893_job_67e08fc7` in the existing lane container. Set `DATABASE_URL`,
`MAISTRO_TEST_PG_DSN`, and `MAISTRO_TEST_DATABASE_URL` to this same database;
`MAISTRO_REQUIRE_PG_LEGS=1`. Credential retrieved from the container environment
without printing or committing it.

- `uv run alembic upgrade head`: PASS, empty-schema chain 001 -> 062, including
  migration 055. No destructive downgrade/migration-chain test was run.
- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -r s
  -o junit_family=legacy --junitxml=/tmp/issue-1893-67e08fc7.xml`: **204 passed,
  zero skipped**, 1.57s.
- Both raw and production pools reported database `maistro_1893_job_67e08fc7`,
  server `172.17.0.9/32:5432`. Production/raw PID pairs: 10560/10561 (unbound),
  10562/10563 (bound), 10564/10565 (acknowledged).
- Each case independently verified one persisted admission row, identical named
  column values across pools, and exact DTO round trip. Bound records satisfied
  migration 055's paired identity CHECK. The existing tests injected escaped
  surrogate corruption into each snapshot TEXT column; both readers returned
  typed errors with suppressed chains while header fingerprint survived.
- Final SQL counts: `task_idempotency`, `canonical_runs`, `canonical_node_runs`,
  and `canonical_attempts` each **0**. Job database retained for inspection.

## Acceptance review

| Criterion | Evidence / limitation |
| --- | --- |
| Frozen/slotted header and shared interfaces; six typed error codes | Source review of admission_codec.py; header mismatch/schema/format and fresh mapping tests pass |
| Strict UUID .hex at storage, signed timestamps, #1851 constructors | UUID/token, scalar, DTO immutability and variant tests pass |
| v2 snapshot bytes and immutable binding identity | Unbound/bound/acknowledged round trips pass in memory and migrated PG; task_id/receipt_id/run_id asserted independently of decoder |
| Legacy bound/unresolved/partial distinctions without invented identity | Existing bound, missing-pair, receipt-only, absent-receipt, malformed and completed_at tests pass; bound pair without receipt remains partial because DTO cannot invent a receipt |
| Header/full-decode separation | Named expiry/fingerprint preservation tests pass despite malformed snapshots or partial binding; unknown formats fail closed |
| Strict TEXT JSON, nonobject/duplicate/bare-nonfinite rejection, safe diagnostics | Existing malformed, lossy-numeric, excessive-nesting and surrogate tests pass; error scope validated and unsafe chains suppressed |
| Tagged program_context evidence and unchanged fingerprint | Existing tag-preservation/nonfinite tests pass; codec does not materialize tags or recompute fingerprints |
| Named SQL fields; raw/production codec equivalence | All three actual PG legs pass; snapshots are TEXT, request maps to request_snapshot, tokens use claim_token |
| model_of/model_of_json materialization, original-model fingerprint, Run JSONB object persistence | UNVERIFIED: these tests use tagged dictionaries, not real TaskResponse/Run model persistence; codec itself does not materialize or INSERT Runs |
| Authorized principals, Workspace/Project and registered Graph kinds | UNVERIFIED: fixture identity strings establish representation only, not authorization or graph admission |
| No SQL/queue/HTTP mutation, clock, classifier, scope utility or policy change | Source review; codec only decodes/encodes mappings and no source changed this round |
| Canonical execution/authorization model | Accepted ADRs reviewed; no competing scheduler, execution, event, Goal or authorization authority added |
| Reachable production behavior | NOT ESTABLISHED: admission_codec.py:49-52 explicitly inactive; only DTO and whitelist imports found. Contract tests are not runtime reachability |
| Inclusive-expiry replacement and 409 precedence; crash/dispatch guarantees | UNVERIFIED, consumer C/F2 responsibility, not B2 codec decisions |
| Inventory and focused quality gates | Core inventory 16,466 passes; root lint/format and targeted mypy pass; no test addition or count change this round |
| Full required CI and generic reported test failure | UNVERIFIED: focused acceptance passes, but provenance demonstrably fails; no actionable current-head test traceback supplied |
| Coordination/activation/independent integration readiness | BLOCKED: lane assignment permits bounded repair only, not activation or parent owner-policy choices |

## Commands and outcomes

All validation commands used 1,200-second timeouts; combined PG orchestration
used 1,500 seconds with 1,200 seconds per subprocess.

| Command | Result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1,323 findings, zero unclassified |
| `RATCHET_BASE_REV=435dc1937e0407ab4de198ffcced49860bb14ad2 uv run python scripts/check-ratchet-provenance.py` | FAIL (exit 1), two unauthorized reachability identities and dispositions |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3,277 files |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS, two source files |
| Focused pytest command above without PG env | 201 passed, three skipped |
| Focused pytest command above with required PG env | 204 passed, zero skipped |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS, 16,466 nodes |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS |
| `git diff --check` | PASS |

## Handoff

Changed only `docs/testing/issue-1893-repair-67e08fc7.md`. No reproducible
in-scope source/test defect was found, so no cosmetic repair, new test, inventory
delta, mutation proof, or vulture amendment is claimed. No gates were weakened.

Required blocker: `quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:612-613`, enforced by
`.github/workflows/vulture-ratchet.yml:77`. Needs an already-landed authorization
under the two-merge rule or separately authorized runtime integration. Neither
is permitted in this lane; no same-base merge can substitute for that decision.

Progress: checked 1 issue; done 0 code repairs; skipped 0 issues; errors 1
required gate. Next: owner resolves the reachability prerequisite and supplies
the actual CI test traceback if `test` remains red. Verdict **BLOCKED**. This
local documentation commit is an evidence handoff, not integration approval.
