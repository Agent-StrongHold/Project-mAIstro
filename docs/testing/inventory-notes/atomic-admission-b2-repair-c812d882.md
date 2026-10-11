---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 repair handoff — c812d882

## Result and frozen scope

**BLOCKED; no source repair is justified by the supplied failure evidence.**
Assigned worktree/branch: `/home/dev/Git/wt/auto-1893`, `auto-1893`.
Inspected and tested source: `ffbc1540bdb88d6b20cd24b4e5ad8c2a0bd905e7`.
Trusted base: `435dc1937e0407ab4de198ffcced49860bb14ad2`, also the resolved
local `origin/develop`. Starting worktree was clean; no sync conflict exists.
Only this issue was processed. Only this handoff note changed: no tests,
production code, ledgers, grants, gates, HTTP mapping or queue policy changed.

Read repository instructions, the supplied issue/PR evidence, both admission
modules and adjacent tests, and accepted ADRs 081426-1f7c, 082526-7f02,
082826-b601 and 082826-d9f5. Reconciliation: the issue's inactive codec stage
does not authorize a new consumer or execution/store authority merely to
satisfy reachability. `Goal -> Graph -> Run -> NodeRun -> Attempt` is unchanged.

## Actual blocker and hosted-check ambiguity

Fresh CI-exact Vulture scan passes: **1323 reviewed identities / 1323 findings**.
There are no unbanked identities to amend under the Vulture-only exception.
Fresh trusted-base provenance exits **1**, rejecting both new modules:
`maistro.runs.admission_identity` and `maistro.tasks.admission_codec`.
Their candidate baseline entries (`quality/reachability-baseline.json:131,147`)
and dispositions (`quality/reachability-dispositions.json:606-613`) are absent
from the trusted base and lack previously landed authorization. This is the
required `.github/workflows/vulture-ratchet.yml:77` gate, not a Vulture defect.
Candidate-side grants, fake callers or removing the gate are not repairs.

The frozen dispatch check-runs evidence at `9922f395daa39249991f18210a6d4da68a3a76cb`
reports `test: success` (check **114346705414**) and `exact-debt-ledger: failure`
(check **114346705214**). `git diff --name-only 9922f395daa39249991f18210a6d4da68a3a76cb HEAD`
at the tested head names only the previous handoff note. No failing traceback
is supplied for the separately claimed merge-queue `test: failure`; its cause
remains **UNRESOLVED**, not repaired or explained by guessing scanner findings.
No remote refresh/mutation was performed. Full current-head hosted CI remains
**UNVERIFIED**.

## Fresh executed validation

Logs and collected nodes: `/home/dev/maistro/jobs/c812d882082d4471bd6149c3708e24c8/worker-*`.
Driver `check-0.log` through `check-4.log` were also inspected; their 201 passed /
3 skipped result is not used as PostgreSQL proof.

- `uv sync --locked --extra dev`: passed.
- `createdb maistro_1893_c812d882`, then
  `DATABASE_URL=postgresql:///maistro_1893_c812d882 uv run alembic upgrade head`:
  passed through the real **001 -> 062** chain on fresh disposable PostgreSQL
  **18.6**. No downgrade or recreated SQLite schema used.
- Exported both `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` as
  `postgresql:///maistro_1893_c812d882`, and `MAISTRO_REQUIRE_PG_LEGS=1`.
  `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py --collect-only -q`:
  **204 nodes**. Same paths with
  `-x -q -o junit_family=legacy --junitxml=<job>/worker-focused.xml`:
  **204 passed, zero skipped**.
- `uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs -x -q`
  without PG environment: **1918 passed, 310 skipped, 5 warnings** (aiosqlite
  worker callbacks after event-loop closure). Not PG or hosted-job proof.
- `uv run ruff check .`: passed; `uv run ruff format --check .`: passed,
  **3277 files**.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`:
  passed, two source files.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`:
  passed, **16466** nodes, no inventory delta or duplicate evidence.
- `uv run python scripts/check-shipped-surface-truth.py`: passed.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`:
  passed, **1323 / 1323**.
- `RATCHET_BASE_REV=435dc1937e0407ab4de198ffcced49860bb14ad2 uv run python scripts/check-ratchet-provenance.py`:
  **exit 1**, the two reachability/disposition failures above; other executed
  provenance sub-gates passed.

The real-pool tests require a non-None production pool and compare independent
raw/production database session identities. Production/raw backend PID pairs:
**498077/498078** (unbound), **498099/498101** (bound), **498102/498109**
(acknowledged), all on the dedicated DB over Unix socket. Each observes one
persisted scoped row. Tests inject escaped-surrogate corruption in each TEXT
snapshot and verify safe typed failures through both pools. Final direct SQL
counts: **0 admission rows, 0 generation IDs, 0 Run IDs**, revision **062**.
The disposable database is retained for inspection. No new regression test or
mutation was introduced, so no new pre-fix failure is claimed.

## Acceptance boundaries

- Exact immutable header and codec interfaces, strict UUID hex/signed scalars,
  fresh flat mapping, header mismatch and unsupported schema/format failures:
  source inspection and focused tests passed.
- Legacy bound/unbound/partial/receipt-only distinctions without invented
  identity, and expiry/fingerprint evidence surviving full-record errors:
  focused tests passed. No clock, incoming fingerprint or claim decision added.
- Canonical snapshot bytes/tags, duplicate/nonobject/bare nonfinite rejection,
  unsafe parse-chain suppression, numeric/Unicode corruption, owner-token
  storage representation: focused tests passed, including all ten named
  prospective issue tests and all three real PostgreSQL parametrizations.
- Physical mapping to migrated named columns (including paired `task_id` and
  `run_id`, immutable receipt identity and acknowledgement): real raw/production
  pool round trips passed; fingerprints remained unchanged.
- Production reachability: **absent**, independently confirmed by source-import
  search and provenance scan. Tests and whitelist imports are not runtime wiring.
  No SQL mutation, web serialization, live assessor or scope utility was changed.
- Evidence-json model materialization, original-model fingerprint generation,
  Run JSONB object insertion, authorized principals/Workspace/Project and valid
  registered Graph admission, live expiry/409 precedence, concurrency/crash
  invariants: **UNVERIFIED** by this codec suite. It uses synthetic storage
  identities, not authorized admission. Passing DTO tests cannot establish these.
- Independent mergeability/activation: **BLOCKED**. Owner-coordinated trusted-base
  reachability resolution or separately reviewed canonical integration is needed;
  neither is authorized by this lane's Vulture-only ledger exception.

Progress: checked 1; done 0 repairs; skipped 0; errors 1 gate. Next: resolve the
trusted-base blocker outside this lane and supply the actual failed hosted-test
traceback if further repair is requested. Do not repeat unchanged-base repair
rounds expecting Vulture edits to authorize reachability. This local commit is
an evidence handoff, not integration approval or issue closure.
