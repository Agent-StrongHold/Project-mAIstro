# Issue #1893 repair recheck

## Follow-up at a58125490 (job 83fee0c236684fc69076a68b2d396ae3)

Frozen item: #1893 only, assigned `auto-1893` worktree, clean starting HEAD
`a58125490aabb7f3bf09a2dac49d5f7076bae56d`, trusted develop base
`2154f845347c9541016288c760f8da3f5cd2e064` (also the locally resolved
`origin/develop`). No sync conflict exists. No remote lists were refreshed.
The historical results below are not fresh acceptance evidence for this round.

Re-read the issue body from the supplied dispatch, repository instructions,
accepted ADR-081226-a66b, ADR-082526-7f02 and ADR-083126-5e62, codec and adjacent
contract tests, inventory and exact-debt-ledger workflow. Preserve
Goal -> Graph -> Run -> NodeRun -> Attempt and immutable admission provenance.
The Vulture-only exception cannot authorize a reachability grant or production
consumer activation. No code or ledger change is justified by the fresh results:

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: **PASS**. No unbanked retained identity to amend.
- `RATCHET_BASE_REV=2154f845347c9541016288c760f8da3f5cd2e064 uv run python scripts/check-ratchet-provenance.py`: **FAIL**, exit 1. Fresh `worker-provenance.log:20-29` rejects both new admission modules and dispositions, 169 trusted versus 171 candidate. The workflow requires this at `.github/workflows/vulture-ratchet.yml:77`.
- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q`: **201 passed, 3 skipped**. PostgreSQL legs were skipped, not durability proof. No database mutation or fresh database claim in this round.
- `uv run ruff check .`: **PASS**; `uv run ruff format --check .`: **PASS**, 3301 files.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`: **PASS**, two files.
- Production-source search still finds only codec -> identity and Vulture whitelist -> identity, not a live codec consumer. `admission_codec.py:50-53` states this boundary explicitly.

Fresh acceptance: the executed pure tests cover shared interfaces, immutable
DTOs, binding shapes, strict UUID/scalar validation, six error dispositions,
header/full-decode separation, malformed JSON rejection, tagged snapshot
preservation and unchanged stored fingerprint. They do **not** prove model
fingerprinting before tagging, model materialization, authorized production
admission, Run JSONB insertion or current database durability. Those criteria
and full required integration CI remain **UNVERIFIED**. No new test or mutation
claim; inventory delta **0**, existing inventory notes retained. Driver logs
check-0 through check-4 were inspected (focused driver result 324 passed,
3 skipped); they do not override the independently reproduced provenance failure.

Additional focused validation:

- `uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs packages/maistro-core/tests/extensions -x -q`: **2987 passed, 310 skipped, 5 warnings** in 64.31s. Warnings are aiosqlite callbacks after event-loop closure; they are not attributed to this codec or repaired speculatively.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: **PASS**, 16543 collected identities, no duplicate evidence.
- `git diff --check`: **PASS**.
- Extracted supplied check-run evidence once to `worker-ci-summary.log`: the captured #1945 head `90d4c278e6d729d41a3f30d9f17bc65025d6f59d` has test success and exact-debt-ledger failure. The failing test record is at #1855 head `3f2c79a70d9e1b0b6b6ffc99562cb35db5326828`, with no output traceback. Neither is the assigned HEAD. Generic assigned-head `test: failure` remains **UNRESOLVED**; request its exact step and traceback. No additional issue was processed.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 1, next: trusted-base prerequisite and assigned-head CI traceback}`.

Current verdict: **BLOCKED**, not a repaired implementation or merge approval.
Only this report is changed. Job-local `worker-*.log` files hold executed gate
and pytest output. Owner-coordinated trusted-base authorization or separately
approved real consumer work is still required; neither is permitted in this
repair. Do not repeat speculative codec or ledger edits to conceal that result.


## Frozen scope

- Assigned worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Starting HEAD `7ac9cff9d92ecdbe7696769f84518132d4a2f240`; supplied develop base `2154f845347c9541016288c760f8da3f5cd2e064`.
- One item: repair #1893 from the supplied dispatch snapshot. No remote mutation or activation.
- Inspect admission codec/identity, adjacent tests, relevant ADRs, existing inventory notes and CI gate definitions. Implementation changes only for reproduced failures; this report is the checkpoint file. No ledger changes except explicitly authorized reviewed Vulture identities if that scan fails.
- Ambiguity: hosted `test: failure` has no failure traceback in the assignment. Do not infer a code defect from that status. Inspect supplied captured evidence and execute focused validation.

## Initial evidence

- Clean starting worktree and exact assigned HEAD confirmed.
- Driver check-0 through check-4: dependency sync, Ruff, format and inventory passed; focused tests 324 passed, 3 skipped. Skips are not database acceptance evidence.
- Prior result reports a provenance rejection and unverified production/integration acceptance. Those claims require fresh validation.

## Reproduced blocker

- Exact requested Vulture scan passed: 1322 findings / reviewed identities, zero unclassified (`worker-vulture.log`). No ledger amendment is justified.
- `RATCHET_BASE_REV=2154f845347c9541016288c760f8da3f5cd2e064 uv run python scripts/check-ratchet-provenance.py` exited 1. `worker-provenance.log:20-29` rejects the two new unreachable admission modules and their dispositions (169 trusted, 171 candidate).
- Production-source import search finds only codec -> identity and Vulture whitelist -> identity. `admission_codec.py:50-53` explicitly states no production consumer. No fake caller will be added.
- Read accepted ADR-081226-a66b, ADR-082526-7f02 and ADR-083126-5e62: preserve canonical execution, immutable admission provenance and protected-base authorization. Reconciliation: the Vulture-only repair exception cannot authorize reachability grants, and staged DTO scope cannot authorize consumer activation.
- Missing `docs/adr/README*` from an initial documentation search: not found; skipped. Relevant actual ADR paths resolved and read.

## Fresh validation

All commands ran at the starting source SHA above; only this report changed.
Logs are under `/home/dev/maistro/jobs/e7c044a941c944afbb0d9f96db082567/worker-*`.

- Confirmed `maistro_1893_e7c044a9` absent, then `createdb maistro_1893_e7c044a9` and `DATABASE_URL=postgresql:///maistro_1893_e7c044a9 uv run alembic upgrade head`: PASS, PostgreSQL 18.6, real chain from empty through 063 (including 055).
- With both `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` set to `postgresql:///maistro_1893_e7c044a9`, and `MAISTRO_REQUIRE_PG_LEGS=1`: `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -o junit_family=legacy --junitxml=<job>/worker-focused.xml`: **204 passed, zero skipped**. Separate `--collect-only -q` saved exact node IDs in `worker-nodes.log`.
- `uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs packages/maistro-core/tests/extensions -x -q` without test DSNs: **2987 passed, 310 skipped, 6 warnings** (aiosqlite callbacks after loop closure). Skips do not establish PG behavior.
- `uv run ruff check .`, `uv run ruff format --check .`: PASS.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`: PASS.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: PASS.
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- Final direct SQL: revision 063; task_idempotency **0 rows / 0 generations / 0 Run IDs**. Disposable DB retained for inspection.
- JUnit production/raw session PIDs on that DB over Unix socket: unbound **874737/874738**, bound **874740/874741**, acknowledged **874742/874743**; each test records exactly one persisted scoped admission row. Inventory collected 16543 nodes, no duplicate evidence. Formatting checked 3301 files; scoped mypy checked two source files.
- `git diff --check`: PASS. Blocking candidate rows remain at `quality/reachability-baseline.json:131,147` and `quality/reachability-dispositions.json:612-613`.

### Captured CI attribution

Bounded inspection of the supplied snapshot, not a remote refresh, is saved in
`worker-ci-summary.log`. PR #1945's captured head `90d4c278e6d729d41a3f30d9f17bc65025d6f59d`
has **test success**, job 115325250948, and **exact-debt-ledger failure**, job
115325250289. The captured failing `test` is on #1855 at
`3f2c79a70d9e1b0b6b6ffc99562cb35db5326828`, job 111298008450, with no traceback
in the check output. #1325 and #2109 show test success. None establishes a
hosted result for this lane's starting HEAD. The assignment's generic test
failure remains **UNRESOLVED at the assigned HEAD**; request the exact failing
step/traceback rather than modify this codec speculatively. No other issue was
processed or changed.

## Acceptance audit

| Criterion | Evidence and limits |
| --- | --- |
| Exact shared interfaces; frozen/slotted header and #1851 DTOs; fresh flat encoding | Inspected codec/constructors plus 204 executed focused cases; independent task_id/run_id/receipt_id constraint assertions pass. |
| Named fields, strict storage UUID hex, signed timestamps, header/row agreement | Focused scalar/schema/UUID/header mismatch tests pass; real INSERT passes migration-055 constraint. |
| Six typed codes; validated scope only; safe errors and suppressed parsing chain | Focused corruption tests pass, including malformed JSON, duplicate keys, nonobjects, bare nonfinite, precision loss, deep nesting and surrogates; no raw snapshot/token in diagnostics. |
| Legacy bound/unbound/partial/receipt-only, no fabricated identity | Focused legacy cases pass. Both IDs without receipt evidence fail partial because #1851 binding requires a receipt; inventing one is prohibited. completed_at is not read. |
| Header expiry/fingerprint preserved before full decode; unknown formats fail closed | Named prospective header separation/unknown-format tests pass; codec takes neither clock nor incoming fingerprint. Inclusive expiry/409 assessment belongs to consumer C, not this leaf. |
| Snapshot bytes/tagged evidence and stored fingerprint retained | Canonical fixture round trips pass. Original-model fingerprint-before-tagging and model_of/model_of_json materialization remain **UNVERIFIED**; fixture tags are not evidence of that pipeline. |
| Raw/production pool TEXT equivalence on same real migrated DB | Three states (unbound/bound/acknowledged) execute with non-null pg_pool, matching server/database, distinct sessions, actual row INSERT/read and corrupt-snapshot injection; final residue 0/0/0. |
| Run JSONB object INSERT, authorized principals/Workspace/Project/registered Graph | **UNVERIFIED**: synthetic codec rows do not exercise authorized production admission or Run creation. |
| No SQL/HTTP/queue/assessment/scope change or competing execution authority | No source changes; pure mapping/DTO codec stays inactive. Reachable production acceptance is **UNVERIFIED** and cannot be manufactured by a fake import. |
| Focused tests, lint/format/mypy, inventory; unchanged required integration CI | Focused checks pass; full integration CI **UNVERIFIED**, required provenance gate **FAILS** as reproduced above. |

## Handoff

**BLOCKED.** Only `docs/implementation/issue-1893-repair-recheck.md` changes.
No tests added or modified: inventory delta 0, existing notes preserved. No
new pre-fix/mutation failure is claimed. This is a validation checkpoint, not
an implementation fix or integration approval. No gate, ledger, grant, remote,
HTTP response, traffic switch or admission-policy change was made.

Owner-coordinated trusted-base resolution or separately approved real consumer
integration is required for the two admission modules. The explicit Vulture
exception does not permit that repair. Request concrete failing hosted test
evidence before repeating a code-repair round on unchanged source/base.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 1, next: coordinated
reachability prerequisite and assigned-head failing CI traceback}`.
