# Issue #1893 repair — job 855fbd0e

## Frozen scope

- Assigned worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Starting head `19579a27dac74931abf6d675f9344d896a3f7e27`;
  supplied develop base `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- One item: issue #1893. Inspect its admission codec, prerequisite identity
  types, adjacent tests, relevant ADRs and CI gates. No other issues or PRs
  will be processed. Planned change: this evidence report; code/test changes
  only if a scoped reproducible defect is found.
- Initial worktree clean; no incoming diff to salvage.
- Driver logs read: dependency sync, Ruff check/format and suite inventory
  passed; focused tests reported 201 passed, 3 skipped. These are driver
  observations, not independent PostgreSQL acceptance evidence.
- Prior result read: job 407df2a4 reported a trusted-base reachability
  authorization failure. Its claimed database results are not assumed true.
- Ambiguity: supplied `test: failure` has no current-head traceback in the
  assignment. Inspect captured check evidence; do not guess a code repair.
- Scope reconciliation: this is a staged codec leaf, not authorization to
  wire a consumer or activate production admission. The exception for
  vulture ledger repair does not authorize reachability grants/baselines.

## Validation

- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1323 reviewed
  findings, zero unclassified. No evidence justifies a vulture ledger edit.
- `RATCHET_BASE_REV=origin/develop uv run python
  scripts/check-ratchet-provenance.py`: FAIL (exit 1). The resolved local
  `origin/develop` equals the supplied base. Both admission modules are new
  unreachable modules and new dispositions without trusted-base authorization.
  Other subgates pass. This is a reproduced policy blocker, not a sync conflict;
  no gate, grant, baseline or production wiring will be changed to bypass it.
- Codec and tests inspected: header/full decoding are separated; binding
  encoding carries both task and run identity; PostgreSQL tests require two
  independently configured pools. Runtime activation is explicitly absent.
- Independently executed `uv run ruff check .` and `uv run ruff format
  --check .`: PASS (3277 Python files formatted).
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py`: PASS.
- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q`:
  201 passed, 3 skipped (204 collected). Skips are the three real-PG cases;
  they are not durability proof.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests`: PASS, 16466 nodes, no duplicate evidence.
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- Read accepted ADR-081226-9944 (canonical hierarchy), ADR-082526-7f02
  (immutable admission provenance, Attempt-owned dispatch identity) and
  ADR-083126-5e62 (candidate evidence is not authorization). No new execution
  or authorization authority is introduced; a passing isolated codec test
  cannot establish runtime admission.
- Captured check evidence inspected: PR #1945's captured `fcc8b437f209`
  check named `test` passed. The captured failing `test` belongs to #1855's
  `3f2c79a70d9e`, with no traceback in the check output. A failing test at
  assigned head remains UNRESOLVED; no speculative code repair is justified.
- Production-source import search found only the codec importing its DTOs and
  the Vulture whitelist importing the assessment enum; no runtime codec caller.
- Created dedicated disposable DB `maistro_1893_855fbd0e`. Initial migration
  invocation used the wrong variable, `MAISTRO_DATABASE_URL`, and failed with
  `ConfigError: No database configured` before database migration. Correct
  production variable is `DATABASE_URL`; the corrected invocation passed.
- `DATABASE_URL=postgresql:///maistro_1893_855fbd0e uv run alembic upgrade
  head`: PASS, real chain from empty DB through 062 on PostgreSQL 18.6.
- With both `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` set to
  `postgresql:///maistro_1893_855fbd0e`, and `MAISTRO_REQUIRE_PG_LEGS=1`, ran
  the same two focused files with `-x -q -o junit_family=legacy
  --junitxml=/tmp/1893-855fbd0e-live.xml`: **204 passed, zero skipped**.
  Production/raw backend PID pairs were 3961181/3961182 (unbound),
  3961183/3961184 (bound), 3961185/3961187 (acknowledged). All sessions used
  the dedicated local Unix-socket DB; each case asserted one persisted
  admission row. Final SQL counts: admission=0, runs=0, node_runs=0,
  attempts=0; migration revision=062. DB retained for inspection.
- `uv run pytest packages/maistro-core/tests/tasks
  packages/maistro-core/tests/runs -x -q`: 1918 passed, 310 skipped,
  5 warnings (aiosqlite worker threads encountering closed event loops).
  This broader run had no PG environment; it is not additional PG evidence.
- Process-local mutation via `uv run python` replaced encoded `task_id`
  with None and invoked the existing `[bound]` round-trip test through
  `pytest.main`. It failed as expected at `test_admission_codec.py:134`;
  the harness asserted TESTS_FAILED and exited 0. No files mutated.

## Acceptance accounting

All executed code evidence is at starting head; this repair changes only
this report. The 204 focused nodes include all ten prospective test names.

| Criterion | Evidence / limit |
| --- | --- |
| Frozen/slotted header, exact codec interfaces and named columns | Source inspection of codec; scoped mypy and header mismatch/schema tests pass |
| UUID .hex only at storage, signed timestamps, constructor invariants | Owner-token, generation, scalar and v2/legacy rejection tests pass |
| Full DTO or explicit typed failure, no invented identity | Legacy bound/unbound/partial, receipt-only, missing receipt, unreadable identity and unknown-format tests pass |
| Valid header independent of full decoding | Expiry/fingerprint preservation and scalar mismatch tests pass; no clock or request fingerprint input |
| Fresh flat encoding and v2 binding constraint | Three-state round-trips pass in memory and against migration-055 CHECK; mutation correctly fails |
| Strict snapshot object JSON and safe errors | Duplicate/non-object/nonfinite, deep nesting, numeric loss, surrogate and scope-hygiene tests pass |
| Tagged evidence, unchanged fingerprint | Tagged nonfinite and Unicode/numeric snapshot round-trips pass; tags retained, not materialized twice |
| Production model materialization and Run JSONB object shape | UNVERIFIED: B2 has no model-materializing consumer or Run INSERT; codec-only tests do not prove this integration contract |
| Raw and production pools over migrated TEXT schema | Three live PG cases pass on one dedicated DB; production fixture uses registered JSON codecs |
| Explicit principals, authorized Workspace/Project and registered Graphs | UNVERIFIED for admission: test DTOs use identity strings, not authorized admission calls |
| No assessment, clock, SQL mutation, HTTP/queue change or activation | Source inspection and production import search; report-only repair preserves staged status |
| Inventory, lint, format and applicable typing | Independent checks pass; no tests added or removed, so no inventory delta needed |
| Full unchanged integration CI and trusted quality policy | NOT PROVEN: provenance gate fails; full required integration CI not run |
| Reported `test: failure` resolved at assigned head | UNRESOLVED: captured failure belongs to another head; focused and adjacent tests pass |

## Disposition and handoff

**BLOCKED.** No scoped failing behavior justifies changing implementation or
Vulture identities. Reachability authorization is absent from the resolved
trusted base; this worker cannot amend reachability policy or land a grant.
The owner must resolve the staged-leaf/mergeability policy through the governed
process, then supply the authorized base. Separately, supply the current-head
failing test traceback if a test repair is still requested. No fetch/sync was
needed or attempted: the observed failure is not a develop merge conflict.
No GitHub mutation, activation, baseline/grant edit or issue closure occurred.

Changed file: `docs/testing/issue-1893-repair-855fbd0e.md` only.
Progress: checked=1, done=0, skipped=0, errors=1 (unresolved provenance gate);
next=owner-authorized prerequisite and current-head CI evidence. Commit this
report locally and leave the worktree clean.
