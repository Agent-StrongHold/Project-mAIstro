# Issue #1893 repair — ebc72482

## Frozen scope

- Assigned worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Starting head `54e3c724e29786569de9821ce74cca1b00e7368a`;
  supplied develop base `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Single item: #1893, using the supplied dispatch-context.json snapshot;
  no GitHub mutations or refreshed issue/PR enumeration.
- Inspect existing admission codec, identity types, their two focused tests,
  adjacent runtime/schema/ADRs, CI workflows, and supplied check logs.
- Run focused validation and the named Vulture/provenance gates. Only repair
  demonstrated defects within the assignment; retain existing work.
- Initial status: clean, exact starting head verified. No salvage needed.

## Ambiguity and constraints

The dispatch reports `test: failure` without a current failing node/traceback.
Treat it as unverified until reproduced, not justification for speculative edits.
The earlier reachability blocker requires separate trusted-base authorization;
this repair permits Vulture ledger amendments only, not reachability grant edits.
Production activation and new runtime consumers are explicitly out of scope.

## Results

- Supplied driver logs read: sync, Ruff lint/format and inventory pass;
  focused tests show 201 passed and 3 PostgreSQL skips, not durability proof.
- Fresh exact Vulture command passed: 1323 reviewed identities/findings,
  zero unclassified. No evidence supports a Vulture ledger amendment.
- Fresh trusted-base provenance command FAILED (exit 1) against the resolved
  supplied base: both admission modules are NEW unreachable modules and NEW
  dispositions without already-landed authorization. Other sub-gates passed.
  Logs: `/tmp/1893-ebc-vulture.log`, `/tmp/1893-ebc-provenance.log`.
- Source inspection confirms the codec is a staged mapping/DTO conversion
  module, not a production consumer. No new runtime wiring is authorized.

- Fresh root Ruff lint/format passed (3277 files); targeted mypy passed for
  both source modules.
- Read complete codec, identity types, both test files, and accepted ADRs
  ADR-081226-a66b, ADR-081626-f383 and ADR-082226-5104. DTO ownership tests
  do not establish execution fencing or an alternate admission authority.
- Production-source search finds only the codec importing the DTO and a
  Vulture whitelist import; there is no reachable runtime consumer.
- CI `test` job (`.github/workflows/ci.yml:574-612`) deliberately excludes
  core tests. Its generic failure cannot be attributed to this leaf without
  the actual failing step/node/traceback. Full hosted CI remains UNVERIFIED.
- Existing lane-local PostgreSQL container verified: `auto-1893-pg`,
  `pgvector/pgvector:pg18`, localhost port 15498. The fixture truncates tables;
  use only a newly created job-specific disposable DB for validation.

- Verified PostgreSQL 18.6 and absence of DB `maistro_1893_ebc72482`, then
  created only that disposable DB. Fresh `uv run alembic upgrade head` passed
  the real 001→062 chain. Nonempty DATABASE_URL, MAISTRO_TEST_PG_DSN and
  MAISTRO_TEST_DATABASE_URL all targeted it; MAISTRO_REQUIRE_PG_LEGS=1.
- Fresh focused tests: **204 collected, 204 passed, zero skips**. Real raw
  and production-codec pools passed all three storage states. Independent
  final SQL: revision 062, **0 task_idempotency rows, 0 canonical_runs rows**.
  DB retained, no shared database changed, no downgrade tests performed.
  Logs: `/tmp/1893-ebc-migration.log`, `/tmp/1893-ebc-focused.log`;
  node/session evidence: `/tmp/1893-ebc-focused.xml`.

- Adjacent runs/tasks smoke passed: **1918 passed, 310 skipped, 5 warnings**
  (51.53s). No PG DSNs for this wider run; skipped tests prove no durability.
  Warnings are existing aiosqlite worker threads encountering closed event
  loops in test_sqlite_store; not evidence against the codec.
- Suite inventory passed: 16466 nodes, no duplicate evidence. Shipped-surface,
  candidate reachability (1396 modules / 171 unreachable), dispositions
  (50 groups) and promotion surface (74 tolerated modules) passed. These
  candidate-ledger passes do not override trusted-base provenance failure.
- `git diff --check` passed. No source, tests, inventory, whitelist, ledgers,
  grants, gates, or runtime consumers changed. No new tests or mutation run;
  no inventory-delta note required for this documentation-only round.

## Commands and acceptance evidence

All source validation ran against unchanged source SHA
`54e3c724e29786569de9821ce74cca1b00e7368a`.

```sh
uv run ruff check .
uv run ruff format --check .
uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py
uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'
RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py
# With the disposable DB environment described above:
uv run alembic upgrade head
uv run pytest packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/tasks/test_admission_codec.py -x -q -o junit_family=legacy --junitxml=/tmp/1893-ebc-focused.xml
# Without that DB environment:
REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest packages/maistro-core/tests/runs packages/maistro-core/tests/tasks -x -q --timeout=60
uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests
uv run python scripts/check-shipped-surface-truth.py
uv run python scripts/check-reachability.py
uv run python scripts/check-reachability-dispositions.py
uv run python scripts/check-promotion-surface.py
git diff --check
```

All above passed except the provenance command (exit 1).

| Criterion | Executed evidence / limitation |
| --- | --- |
| Exact frozen/slotted header and shared typed interfaces | Source inspected; scalar/header mismatch, supported formats, missing columns and DTO validation tests passed. |
| Strict UUID .hex at storage, signed timestamps, #1851 constructors | Owner/generation UUID and invalid timestamp/variant tests passed. Owner token omitted from repr. |
| Fresh flat SQL mapping and snapshots | Three-state round trip and fresh-mapping tests passed; independent binding assertions and live migration-055 CHECK accepted bound task_id=receipt_id plus run_id. Physical request TEXT maps to DTO request_snapshot. |
| Legacy bound/unbound/partial and no invented identity | Legacy tests passed, including receipt-only and pair-without-receipt failures. Reconciliation: #1851 AdmissionBinding requires receipt evidence; missing receipt is partial, not fabricated. |
| Header survives invalid snapshot/partial binding | Named expiry/fingerprint tests passed. No clock or incoming fingerprint accepted. Consumer expiry/409 precedence remains C/F2 responsibility and UNVERIFIED here. |
| Unknown schema/format, strict JSON, safe errors | Unsupported-format, missing-schema, duplicate/nonobject/nonfinite, lossy number, nesting and Unicode corruption tests passed. Error tests verify safe messages and suppressed context. |
| Snapshot/fingerprint preservation | Tagged nonfinite, exact numeric and valid Unicode tests passed without fingerprint recalculation. Actual original-model fingerprinting and model_of/model_of_json materialization are UNVERIFIED: fixtures manually construct tags. |
| Raw/production codec contrast on migrated PostgreSQL | Three real pool tests passed, 204 total tests with no skips. Sessions 22262/22263 (unbound), 22264/22265 (bound), 22266/22267 (acknowledged), same DB/server `maistro_1893_ebc72482`, `172.17.0.9/32:5432`; one stored row per state, zero final residue. Escaped surrogate corruption injected into each snapshot TEXT column rejected via both pools. |
| Authorized principals, Workspace/Project and valid Graph kinds | UNVERIFIED: these are low-level identity/storage fixtures, not authorization or admission tests. |
| Run json_of INSERT text::jsonb produces an object | UNVERIFIED: this suite does not persist a Run. |
| No activation, SQL mutation, HTTP, queue, _assess, scope or policy changes | Entire codec inspected: mapping/DTO conversion only; this round changes only this report. Canonical Goal → Graph → Run → NodeRun → Attempt remains unchanged. |
| Unchanged required CI; no policy changes to make inactive modules green | BLOCKED: existing unauthorized reachability additions fail trusted-base provenance. Full required hosted CI and reported generic test failure are UNVERIFIED. |
| Coordinated staged readiness versus activation | Assignment's branch/base retained; no new ownership, integration approval, activation, merge, push or issue closure. |

## Handoff / residual blockers

Only changed file: `docs/testing/issue-1893-repair-ebc72482.md`.

The fresh failure is at `quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:612-613`: two inactive modules and
associated dispositions have no already-landed trusted-base authorization.
It is not a Vulture defect or a develop-sync conflict. The Vulture-only
exception cannot authorize edits to those ledgers. Separate prerequisite
approval/landing or separately authorized real consumer integration is needed;
this worker cannot manufacture either and must preserve the staged work.

Request the current CI failing step/node/traceback before assigning another
`test: failure` repair. Repeated green codec checks do not identify that failure
and repeated documentation-only runs do not resolve the authorization blocker.

Progress: checked 1 issue, done 0 code repairs, skipped 0 issues, errors 1
required provenance gate. Next: external authorization prerequisite and actual
CI failure evidence. **BLOCKED**, documentation handoff only; commit locally.

