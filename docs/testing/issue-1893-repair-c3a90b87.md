# Issue #1893 repair evidence — c3a90b87

## Frozen scope and current result

Assigned worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`, starting
head `092d8068f55cce914903307a4ad1b4a9a9ca88c3`; clean initially. Process only
#1893's codec, prerequisite identity DTOs, adjacent tests and reported CI gates.
This report is the only planned edit unless executed evidence supports an
in-scope repair. No activation, GitHub mutation, grant or non-vulture ledger
change is authorized. The writer assignment allows this local report commit.

**BLOCKED, reproduced at the assigned head:**

- Required Vulture scan passes: 1,323 findings, zero unclassified.
- `RATCHET_BASE_REV=435dc1937e0407ab4de198ffcced49860bb14ad2 uv run python
  scripts/check-ratchet-provenance.py` exits 1. Both
  `maistro.runs.admission_identity` and `maistro.tasks.admission_codec` add
  unauthorized unreachable modules and dispositions (169 -> 171).
- Supplied base and local `origin/develop` resolve to the same commit. This is
  not a develop-sync conflict; merging the same base cannot authorize debt.
- A source import search finds only the codec importing its DTOs and the
  Vulture whitelist importing an identity type. Neither supplies runtime
  reachability. Codec lines 49–52 explicitly describe the staged consumer.
- CI enforces provenance at `.github/workflows/vulture-ratchet.yml:77` before
  Vulture. The vulture-only repair exception cannot authorize reachability
  ledger edits. No Vulture amendment is justified by the passing scan.

Driver logs were inspected, not accepted as new execution: sync, lint, format,
focused tests (201 passed / three PG skips) and core inventory (16,466) passed.
Prior job result/report were read as historical evidence only.

The captured check-run records contain no current-head failing test traceback.
The captured #1945 head `9922f395daa39249991f18210a6d4da68a3a76cb` has a successful
`test` check; #1855's older head has failure without summary/text. Neither proves
the assigned head's generic `test: failure` resolved. No speculative test fix.

## Independently executed focused checks

At the assigned source head, with 1,200-second command timeout:

| Command | Result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1,323 findings, zero unclassified |
| Provenance command above | FAIL, exit 1, two unauthorized identities plus dispositions |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3,277 files |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS, two files |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -r s` | 201 passed, three PG skips, 204 collected nodes |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS, 16,466 nodes, no duplicate evidence |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS |

Read the complete codec and adjacent codec/identity tests, relevant identity
constructors, accepted ADR-082526-7f02 (immutable admission provenance;
dispatch identity belongs to Attempt) and ADR-081426-1f7c (Attempt-owned runtime
mechanics). No competing execution or authorization authority is introduced.
The codec's refusal to invent a receipt for a legacy bound pair without receipt
evidence reconciles the shorthand 'both IDs is bound' with the required DTO and
explicit no-identity-invention contract.

## Real PostgreSQL evidence

Created only `maistro_1893_job_c3a90b87`, after verifying it did not exist, in
the existing lane container `auto-1893-pg` on localhost:15498. PostgreSQL reports
18.6. No previous database was reused or modified. The fixture truncates only
this newly created disposable DB; no downgrade test was run.

Set nonempty `DATABASE_URL`, `MAISTRO_TEST_PG_DSN`, and
`MAISTRO_TEST_DATABASE_URL` to that same DB, with `MAISTRO_REQUIRE_PG_LEGS=1`.
Credentials were retrieved without printing or committing them.

- `uv run alembic upgrade head`: PASS, actual empty-schema migration chain
  through 062, including 055's identity CHECK.
- Focused pytest command from the table, additionally
  `-o junit_family=legacy --junitxml=<job-dir>/worker-pg-tests.xml`: **204 passed,
  zero skipped**, 1.65s, at source SHA `092d8068f55cce914903307a4ad1b4a9a9ca88c3`.
- Actual production/raw session PID pairs: 10880/10881 (unbound), 10882/10883
  (bound), 10884/10885 (acknowledged). All report database
  `maistro_1893_job_c3a90b87`, server `172.17.0.9/32:5432`.
- Each case asserts exactly one persisted admission row, identical named-column
  mappings from both pools, and exact DTO round trip. Tests independently
  assert task_id = receipt_id when bound and both binding columns absent when
  unbound; the real INSERT also satisfies migration 055.
- Each case injects escaped surrogate corruption into each snapshot TEXT
  column. Both readers return typed safe errors, preserving header fingerprint.
- Final SQL counts: `task_idempotency`, `canonical_runs`, `canonical_node_runs`,
  and `canonical_attempts` each **0**. Disposable DB retained for inspection.
- Logs and XML retained under
  `/home/dev/maistro/jobs/c3a90b87c8924c23804ff04066d91cee/worker-{migration.log,pg-tests.log,pg-tests.xml}`.
  PG orchestration timeout 1,500 seconds; each subprocess 1,200 seconds.

## Acceptance review and limits

| Criterion | Executed evidence or explicit limitation |
| --- | --- |
| Shared interfaces, frozen/slotted header, six error codes | Source review; header mismatch/schema/format and flat fresh mapping tests pass |
| Strict UUID .hex, signed timestamps, #1851 constructors | Storage-token, scalar boundary and DTO validation tests pass |
| Immutable snapshot evidence and binding identity | Unbound/bound/acknowledged round trips pass in memory and migrated PG |
| Legacy bound/unbound/partial, receipt-only, announced-without-Run, no invented IDs | Existing legacy pairing, receipt-only, missing-receipt and unreadable-evidence tests pass; explicit absence remains absence |
| Header preserved before full decode; invalid/unknown scalar headers fail closed | Named expiry/fingerprint preservation and unsupported-format tests pass; no clock or incoming fingerprint accepted |
| Strict TEXT JSON, duplicate/nonobject/bare-nonfinite rejection, safe diagnostics | Existing malformed JSON, numeric loss, nested data and surrogate tests pass, including real TEXT corruption at both pools |
| Arbitrary permitted program_context tags; unchanged stored fingerprint | Existing tag/nonfinite and numeric/Unicode preservation tests pass; decoder neither materializes tags nor recalculates fingerprint |
| Named storage fields, fresh bound TEXT parameters, raw/production codec equivalence | Three live PG states pass against migration 055; request maps to request_snapshot, claim_token to owner_token |
| model_of/model_of_json materialization, real original-model fingerprint and Run JSONB object INSERT | UNVERIFIED: existing codec tests use tagged dictionaries, not TaskResponse/Run model persistence |
| Explicit principals, authorized Workspace/Project, registered Graph kinds | UNVERIFIED: string fixtures prove representation only, not authorization or graph admission |
| No mutation, HTTP/queue mapping, assessment, scope utility, legacy/deletion policy change | Complete codec source review; mapping-only implementation; no source change this round |
| Inclusive expiry replacement, 409 precedence, atomic claim/crash/dispatch | UNVERIFIED: future C/F2 consumer behavior, not B2 decisions or codec test guarantees |
| Canonical Goal -> Graph -> Run -> NodeRun -> Attempt model | Relevant accepted ADRs reviewed; no competing scheduler or authority introduced |
| Production reachability | NOT ESTABLISHED: import search and failing provenance gate confirm inactive contracts; test imports do not activate them |
| Focused quality gates and truthful inventory | Independently pass as recorded above; no new tests or count delta, so no inventory-note addition needed |
| Full required CI, generic reported test failure | UNVERIFIED: required provenance gate demonstrably fails; no current-head failing traceback supplied. ci.yml:573-612 assigns core suite to coverage, not test; no unrelated full-tree rerun or speculative repair |
| Coordination/activation and independent integration | BLOCKED: repair lane does not authorize activation, policy decisions or reachability grants |

## Final handoff

Only `docs/testing/issue-1893-repair-c3a90b87.md` changed this round. No
reproducible in-scope code defect was found. No new regression test, pre-fix or
mutation-failure proof is claimed; existing tests were executed, not added.
No scanner, ledger, grant or gate was changed.

Blocking locations: `quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:612-613`. Resolution requires an
already-landed trusted-base authorization under the two-merge rule, or a
separately authorized runtime integration. Neither is permitted in this lane.
Repeated codec tests or same-base merges cannot resolve that prerequisite.

Progress: checked 1 issue; done 0 code repairs; skipped 0 issues; errors 1
required gate. Next: owner resolves the reachability prerequisite and supplies
the actual current-head CI traceback if `test` still fails. Local report commit
is evidence handoff only, not integration approval. Verdict **BLOCKED**.
