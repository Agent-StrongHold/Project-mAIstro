# Issue #1893 repair — be69a279

## Frozen scope and initial checkpoint

- Assigned worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Starting HEAD `414c65e52cf2dfcdade18e5ddf7186bebea1b0c0`; supplied develop base
  `3c761d14db944a727fa0744444bc67cfe36d49f7`. Initial worktree clean.
- Process only issue #1893: existing admission codec/identity implementations,
  their two focused test files, relevant architecture and CI gates, and this report.
  No GitHub refresh/mutation, production activation, or unrelated fixes.
- Supplied job `be69a27964a740108d26c84537449fbf`: inspected dispatch issue body,
  check-0 through check-4 logs, and prior result `b9006f92150f470ab923d055790f4f08`.
  Driver recorded dependency sync, Ruff lint/format, 201 passed / 3 skipped focused
  tests, and suite inventory pass. Those are driver evidence, not new executions.
- Ambiguity: dispatch labels `test: failure` without a traceback. Assume no code
  repair is justified until reproduced. Prior result reports unauthorized
  reachability entries; only the vulture ledger exception is authorized this round.
- No tests added; inventory delta is zero. Validation and final disposition follow.

## Reproduced blocker

Fresh execution with a 1200-second timeout:

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1323 reviewed identities / findings, zero unclassified. No Vulture amendment is warranted.
- `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py`: FAIL (exit 1). Both `maistro.runs.admission_identity` and `maistro.tasks.admission_codec` are new unreachable modules and new dispositions not authorized by the trusted base. `origin/develop` independently resolves to the supplied base.
- CI requires that provenance command at `.github/workflows/vulture-ratchet.yml:77`. Existing offending entries are in `quality/reachability-baseline.json` and `quality/reachability-dispositions.json`; candidate banking cannot authorize them.

Read accepted ADRs 081226-a66b, 082526-7f02, and 083126-5e62. Reconciliation: preserve the canonical execution hierarchy and immutable admission provenance; never manufacture a consumer or weaken a trusted-base gate. The Vulture-only repair exception does not authorize reachability grants/dispositions. This is not a develop-sync conflict. No remote refresh or merge is justified by that conditional instruction.

## Fresh validation

Source under test is starting HEAD `414c65e52cf2dfcdade18e5ddf7186bebea1b0c0`;
this round changes only this report. Commands used 1200-second timeouts.

| Command | Result |
| --- | --- |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3277 files |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS, 2 files |
| `uv run pytest packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/tasks/test_admission_codec.py -x -q -rs` | 201 passed, 3 skipped (PG not configured); not durability evidence |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS, 16466 collected identities, no duplicate evidence |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS |

Fresh dedicated database, not a reused/shared test database:

```sh
createdb maistro_1893_be69a279
DATABASE_URL=postgresql:///maistro_1893_be69a279 uv run alembic upgrade head
MAISTRO_TEST_PG_DSN=postgresql:///maistro_1893_be69a279 \
MAISTRO_TEST_DATABASE_URL=postgresql:///maistro_1893_be69a279 \
MAISTRO_REQUIRE_PG_LEGS=1 uv run pytest \
  packages/maistro-core/tests/runs/test_root_admission_identity.py \
  packages/maistro-core/tests/tasks/test_admission_codec.py -x -q -rs \
  --junitxml=/home/dev/maistro/jobs/be69a27964a740108d26c84537449fbf/worker-live-pg.xml \
  -o junit_family=legacy
```

PostgreSQL 18.6: real migration chain from empty through **062** passed,
including migration 055. **204 collected, 204 passed, zero skipped**, 1.43s.
`worker-migrations.log`, `worker-live-pg.log`, and `worker-live-pg.xml` are in the
supplied job directory. No downgrade test was run. The disposable DB is retained.
The production fixture registers `_register_json_codecs`, and the test requires
non-null `pg_pool`; a distinct raw pool reads identical named TEXT columns.

| State | Production PID | Raw PID | Persisted admission rows |
| --- | --- | --- | --- |
| unbound | 1595022 | 1595023 | 1 |
| bound | 1595024 | 1595025 | 1 |
| acknowledged | 1595026 | 1595027 | 1 |

Both pools reported database `maistro_1893_be69a279`, Unix sockets (address/port
NULL), and distinct PIDs. Actual INSERTs satisfied the migrated v2 binding CHECK.
Each live case additionally injected escaped-surrogate corruption into each
snapshot column and checked sanitized typed errors through both pools.
Final SQL verification: revision 062, and zero rows in each of `task_idempotency`,
`canonical_runs`, `canonical_projects`, `canonical_project_memberships`.

## Acceptance accounting and limits

| Criterion | Evidence / limitation |
| --- | --- |
| Frozen/slotted scalar header, exact public signatures, six decode codes, strict UUID hex and signed timestamp validation | Implementation and adjacent tests inspected; focused 204/204 pass. |
| Header/record separation, mismatch rejection, unknown format fail-closed | Executed header scalar mismatch, expiry/fingerprint preservation, and unknown-format tests; all pass. No clock or incoming fingerprint is accepted. |
| Legacy bound/unbound/partial and receipt-only evidence, no invented identity | Executed legacy tests pass, including bound pair without receipt failing partial rather than fabricating identity, and ignored `completed_at`. |
| Strict JSON TEXT, duplicate/nonobject/bare nonfinite rejection; safe scope/errors | Executed malformed snapshot, Unicode, nesting, numeric-loss, and scalar tests pass; unsafe exception context is suppressed. |
| Fresh flat encode mapping, immutable snapshots, no fingerprint recomputation, owner token hex only at storage | Three-state pure and live round trips and owner-token tests pass. Source emits both binding columns from the existing binding. |
| Evidence tags and arbitrary program_context survive real model serialization/materialization | Handwritten tags survive codec tests, but actual `evidence_json` plus `model_of`/`model_of_json`, original-model fingerprinting and arbitrary model evidence are UNVERIFIED by these fixtures. |
| Both pool codecs, real migrated schema, non-skipped durability | Proven above, 204/204 with matching database identities and real INSERT/SELECT operations. |
| Governed explicit principals, authorized Workspace/Project, registered Graph; Run JSONB object rather than string | UNVERIFIED: fixture identities are strings, not authorized admission. The tests do not insert a Run payload. |
| No SQL mutation, HTTP mapping, queue/claim/assessment/scope-policy change by codec | Source remains a pure DTO/mapping layer. This round adds only this report; no new execution or authorization authority. Replacement/409 ordering remains C/F2 evidence, not B2. |
| Production reachability | NOT proven: source search finds only codec-to-identity and Vulture whitelist imports. `admission_codec.py:50-53` explicitly documents no production consumer. No fake caller added. |
| Unchanged full required integration CI | NOT proven: required provenance fails. The scoped core tests do not establish the separate `test` job in `.github/workflows/ci.yml:496,574-615`; full integration CI was not run. Reported `test: failure` remains UNRESOLVED without an assigned-head traceback. |
| Pre-fix/mutation evidence | No code/test repair this round, so no new pre-fix or mutation claim. Existing malformed-storage injections executed as described above. |
| Ownership coordination and activation policy | External prerequisites UNVERIFIED; no activation or merge authority inferred. |

## Final disposition

**BLOCKED.** Actual failed command: trusted-base provenance gate, exit 1, for
`quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:612-613`. Fix requires an owner-approved
reachability authorization already landed on the trusted base, or separately
coordinated real consumer integration. Neither is authorized in this repair lane.
No ledger/grant/gate/source/test changes are justified by the reproduced evidence.

Only changed file: this report. No inventory-note amendment needed (zero test
changes). Commit the report locally as a blocked handoff, not integration approval.

Progress: checked 1 issue; done 0 repairs; skipped 0 issues; errors 1 required gate.
Next: owner resolves trusted-base reachability authorization/integration and supplies
an assigned-head `test` failure traceback. Re-dispatching the unchanged blocker or
amending Vulture cannot resolve it.
