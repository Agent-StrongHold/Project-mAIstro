# Issue #1893 repair checkpoint — job 2a6dcd54

## Frozen scope

- Assigned worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Starting HEAD `0c15d1696c0308c691e9274ce4ca0c099078c5df`; supplied base `321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62`.
- One item: issue #1893, immutable admission codec CI repair. No other issues or PRs will be processed.
- Inspection scope: `admission_codec.py`, `admission_identity.py`, adjacent task/identity tests, the two extension regression tests already changed by this branch, relevant ADRs, CI workflows, supplied job artifacts, and named gate scripts. Intended write scope: this checkpoint; production/test repair only if actual failing evidence identifies one. No reachability/grant edits authorized.
- Initial worktree clean. No incoming edits require salvage.

## Initial evidence and assumptions

Driver logs in `/home/dev/maistro/jobs/2a6dcd5490784045ac5998291c4c74f4`: check-0 dependency sync succeeds; check-1 ruff succeeds; check-2 format succeeds; check-3 reports 346 passed, 3 skipped; check-4 reports 16567 core tests matching inventory. These are supplied results, not independent execution.

Ambiguity: dispatch names `test: failure` without a failing node or CI traceback. Reproduce focused tests and specified ledger gates before choosing any repair. Earlier claims of live PG or full CI success are not treated as current proof. The previous reachability/provenance blocker must be independently checked; the vulture-only exception does not authorize changing reachability ledgers or grants.

Independent gate results: exact Vulture command passes (1322 findings, zero unclassified); no Vulture amendment is warranted. `RATCHET_BASE_REV=321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62 uv run python scripts/check-ratchet-provenance.py` fails: both admission modules are NEW unreachable modules and NEW dispositions without already-landed authorization. Local `origin/develop` resolves to that exact supplied base; no sync conflict exists. The prior job result identifies a stale extension diagnostic assertion, already repaired by the starting commit, rather than a currently demonstrated codec defect.

Neither PostgreSQL test environment variable is set. Docker has a `maistro-postgres` service on localhost:5433; no durability result claimed yet.

Architecture inspection: accepted ADR-081226-69ee retains Graph/Run/NodeRun/Attempt ownership; ADR-082526-7f02 makes admission provenance immutable rather than dispatch authority; ADR-083026-aba1 requires stating absent production callers; ADR-083126-5e62 preserves trusted-base authorization. Source search finds only the codec importing the identity DTOs and the Vulture whitelist importing an assessment alias; no production codec consumer exists. This matches the staged B2 exit constraint, but does not satisfy runtime reachability or authorize self-banking.

The physical `request` TEXT column maps to DTO `request_snapshot`; the codec uses named columns and no SQL, clock, HTTP, or queue mutation. Tests independently assert the migration-055 binding shape and safe failures for partial identities, lossy numbers, duplicate/non-object/nonfinite JSON, and Unicode corruption. Existing PG tests use synthetic envelope strings, so even a live pass will prove row transport, not authorized Workspace/Project/Graph admission or Run JSONB/model materialization. No test additions planned; inventory delta is zero. ## Independently executed validation

All results below are against the starting HEAD plus this documentation-only checkpoint.

- `uv run pytest packages/maistro-core/tests/extensions/test_cli_lock.py packages/maistro-core/tests/extensions/test_pack_contracts.py packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/tasks/test_admission_codec.py -x -q`: **346 passed, 3 skipped** (unconfigured PG).
- `uv run pytest packages/maistro-core/tests/extensions -x -q`: **1092 passed**. The supplied stale-diagnostic regression does not reproduce at the assigned starting HEAD.
- `uv run ruff check .`: pass.
- `uv run ruff format --check .`: pass, 3301 files.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`: pass, two source files.
- Created new disposable database `maistro_1893_2a6dcd54` on the existing Docker service, refusing reuse if already present. Credentials obtained privately from the local container configuration, not written to files or logs. Both required test URLs and `DATABASE_URL` targeted that database; `MAISTRO_REQUIRE_PG_LEGS=1`.
- `uv run alembic upgrade head`: pass through the real chain from empty database to **063**, including 055.
- With that environment: `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q --junitxml=/home/dev/maistro/jobs/2a6dcd5490784045ac5998291c4c74f4/admission-pg.xml -o junit_family=legacy`: **204 passed, zero skips**. PostgreSQL **18.6**; final independent SQL counts: task_idempotency **0**, canonical_runs **0**. Database retained as disposable validation evidence, no shared database migrated/truncated. No downgrade tests run.

- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: pass, **16567** collected identities, zero copied evidence. No test additions or removals, so no inventory-note delta required this round.
- `uv run python scripts/check-shipped-surface-truth.py`: pass.
- In-memory mutation (no source edit): wrapped `encode_admission_record` to force `task_id=None`, then ran `pytest.main(['packages/maistro-core/tests/tasks/test_admission_codec.py', '-q', '-k', 'test_v2_round_trip_preserves_all_snapshot_bytes'])`. Expected failure observed: **2 failed, 1 passed, 128 deselected**, bound and acknowledged cases fail at line 134, proving the storage-shape assertion detects the historical missing binding identity.

PG session evidence from the JUnit properties: database `maistro_1893_2a6dcd54`, server `172.20.0.2/32:5432`; production/raw PID pairs **296574/296575** (unbound), **296576/296577** (bound), **296578/296579** (acknowledged). Each pair read the same committed admission row, exactly one row per scope; final independent residue count zero.

## Acceptance assessment

| Criterion | Current evidence / limitation |
| --- | --- |
| Frozen/slotted validated header; six typed failure codes; only validated scope hashes; suppressed unsafe chains | Existing codec/identity tests pass; reviewed implementations. |
| Strict UUID `.hex`, signed scalar validation, header mismatch rejection and unknown format fail-closed | Existing codec tests pass at the tested HEAD. |
| Legacy bound/unbound/partial/receipt-only distinctions, no identity invention | Existing codec tests pass. A pair without receipt evidence is deliberately partial because the canonical binding requires an explicit receipt; no synthetic identity is introduced. |
| Header evidence survives bad snapshots/partial bindings; no clock, fingerprint assessment, or claim mutation | Existing header-separation tests pass; source inspection confirms separation. Actual expiry/409 consumer ordering belongs to C/F2 and is not claimed. |
| Snapshot object/duplicate/nonfinite validation, tag preservation, arbitrary context and unchanged stored fingerprint | Existing codec tests pass, including precision, nesting and Unicode failures. Materialization through actual TaskResponse/Run evidence models remains **UNVERIFIED** in this round. |
| Fresh flat named SQL mapping and migration-055 binding shape | Existing fresh-mapping tests, live two-pool INSERTs, and failing missing-task-identity mutation. Physical `request` maps to DTO `request_snapshot`; no new schema introduced. |
| Raw/production-codec TEXT reads against a real migration chain | **204 passed, zero skips**, PG18.6 / migration 063; explicit same-server and distinct-session assertions and row counts above. |
| Authorized principals/Workspace/Project/registered Graph, Run JSONB object and full production materialization | **UNVERIFIED**. Existing PG tests insert synthetic envelope identities directly and never create a canonical Run; these cannot prove admission authorization or JSONB Run persistence. |
| No SQL mutation/HTTP/queue change or production activation by B2 | No production changes this round; codec remains an inactive mapping contract with no runtime consumer. Canonical execution authority unchanged. |
| Focused tests, ruff, formatting, applicable mypy and truthful inventory | Independently passed as listed; inventory unchanged. |
| Reported CI `test: failure` | Prior artifact identifies stale extension assertion repaired at starting HEAD. Focused and complete extension suite pass now; full integration CI **UNVERIFIED**, not claimed green. |
| Vulture exact ledger and trusted-base gates | Exact Vulture passes without changes. Trusted-base reachability/disposition provenance **FAILS** for both admission modules. |
| Coordination/base/owner and activation-policy release | Worktree/base fixed by dispatch; external coordination/policy release **UNVERIFIED**, not inferred from tests. |

## Handoff / blocked resolution

Only this documentation file changed in this round. No justified additional production/test repair was found; do not create cosmetic code changes or amend a passing Vulture ledger. Prior candidate reachability ledger/disposition additions remain unauthorized relative to the supplied base. Correct resolution needs protected-base governance outside this writer's authority (separately reviewed, already-landed authorization), or separately coordinated genuine runtime integration; fake imports/exports are not a remedy and production activation is out of scope.

No fetch/merge was needed: local origin/develop already equals the exact supplied base and the worktree had no conflict. No GitHub mutations, branch deletion, gate weakening, or discarded work. Full required CI and the broader authorization/model-materialization criteria remain unproven. This staged leaf does not authorize activation or a competing execution authority.

Progress: checked 1, done 0, skipped 0, errors 1 (trusted-base provenance blocker). Next: campaign owner resolves the protected-base authorization/coordination blocker; rerun provenance and full integration acceptance afterward. Verdict: **BLOCKED**.
