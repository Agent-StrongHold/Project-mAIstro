# Issue #1893 repair recheck

## Follow-up at 0c5dd63a6 (job 1c318f54b86e4c1fa05104f17e642bbc)

Frozen item: #1893 only; clean assigned `auto-1893` worktree at
`0c5dd63a647dd99a9425362153014a59a25102b1`, trusted base
`2154f845347c9541016288c760f8da3f5cd2e064` (also local `origin/develop`).
No merge conflict or incoming changes. Read supplied dispatch issue/PR/check-run
evidence, prior result, repository instructions, accepted ADR-081226-a66b,
ADR-082526-7f02 and ADR-083126-5e62, codec/DTO implementations and adjacent tests.
Only this report changed; no source, test, ledger, grant, gate or activation edit.
Inventory delta is **0**; existing inventory notes remain unchanged.

### Fresh validation

Logs are under `/home/dev/maistro/jobs/1c318f54b86e4c1fa05104f17e642bbc/`.
These are this round's executions, not inherited verification claims:

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: **PASS**, 1322 reviewed identities/findings, zero unclassified (`worker-vulture.log`). No retained unbanked identity warrants the permitted Vulture amendment.
- `RATCHET_BASE_REV=2154f845347c9541016288c760f8da3f5cd2e064 uv run python scripts/check-ratchet-provenance.py`: **FAIL**, exit 1 (`worker-provenance.log:20-29`). Both admission modules and dispositions lack trusted-base authorization: 169 trusted versus 171 candidate. This remains a required exact-debt-ledger step at `.github/workflows/vulture-ratchet.yml:77`.
- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q`: **201 passed, 3 skipped**, 204 collected (`worker-focused.log`).
- `uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs packages/maistro-core/tests/extensions -x -q`: **2987 passed, 310 skipped, 6 warnings**, 3297 collected (`worker-adjacent.log`). Warnings are aiosqlite worker callbacks after event-loop closure; no codec failure reproduced.
- `uv run ruff check .` and `uv run ruff format --check .`: **PASS**, 3301 formatted files.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`: **PASS**, two source files.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: **PASS**, 16543 collected identities, no duplicate evidence (`worker-inventory.log`).
- `uv run python scripts/check-shipped-surface-truth.py`: **PASS** (`worker-surface.log`).

Driver `check-0.log` through `check-4.log` were separately inspected: sync,
lint, format and inventory passed; four-file pytest reported 324 passed and
3 skipped. Those results do not override the reproduced provenance failure.

### Acceptance and unresolved repair

Executed pure tests establish immutable DTOs, named scalar/flat mapping,
strict storage UUIDs, signed timestamps, header/row agreement, six typed safe
error dispositions, exact supported snapshot round trips, malformed JSON
rejection, tagged evidence preservation, unchanged stored fingerprint, and
bound/unbound/partial legacy distinctions without invented identity. Header
expiry/fingerprint evidence survives full-record failures. Storage assertions
at `test_admission_codec.py:134-137` independently check both binding columns;
no new pre-fix or mutation-test result is claimed this round.

**UNVERIFIED this round:** real migrated disposable PostgreSQL raw/production
pool parity and final SQL counts (all three PG legs skipped); original-model
fingerprinting before tagging and materialization via `model_of/model_of_json`;
authorized Workspace/Project/principal/registered-Graph admission and Run JSONB
object insertion; full required integration CI. Fixture tags and a fixed
fingerprint prove codec preservation, not the complete model/admission pipeline.

Production-source import search finds only codec -> identity and Vulture
whitelist -> identity. `admission_codec.py:50-53` states no runtime consumer
exists. Preserve Goal -> Graph -> Run -> NodeRun -> Attempt and immutable
admission provenance: the staged leaf cannot be made reachable by inventing a
caller or activating the later consumer. Under ADR-083126-5e62, the Vulture-only
exception does not authorize reachability grants or candidate self-approval.
No SQL mutation, HTTP mapping, queue, clock, assessment or policy change made.

Captured check-run attribution was extracted once to `worker-ci-summary.log`:
#1945 at `90d4c278e6d729d41a3f30d9f17bc65025d6f59d` has test success and
exact-debt-ledger failure; #1855 at
`3f2c79a70d9e1b0b6b6ffc99562cb35db5326828` has test failure with null output text.
Neither is the assigned HEAD. The requested assigned-head `test: failure`
remains **UNRESOLVED** without its exact failing step/traceback; no speculative
repair is justified. No additional issue was processed or remote list refreshed.

**BLOCKED**: requires a separately coordinated trusted-base prerequisite (or
separately authorized real consumer integration) and assigned-head test failure
evidence. A documentation commit preserves this handoff, not a repaired gate or
integration approval. Progress: `{checked: 1, done: 0, skipped: 0, errors: 1,
next: trusted-base prerequisite and assigned-head CI traceback}`.

## Follow-up at 51ca9942b (job f339f77787aa46398e54a68d514110e9)

Frozen scope: #1893 only, assigned clean `auto-1893` worktree, exact starting
HEAD `51ca9942b32c1da400d085be0e98cf3522e82c73`, supplied trusted base
`2154f845347c9541016288c760f8da3f5cd2e064`. No conflicting merge or incoming
uncommitted work. No remote refresh or mutation. Only this report changed.
Historical validation below is not evidence for this round.

Read repository instructions, the supplied issue body, accepted
ADR-081226-a66b, ADR-082526-7f02 and ADR-083126-5e62, codec/DTO implementations,
codec tests and exact-debt-ledger workflow. Preserve canonical
Goal -> Graph -> Run -> NodeRun -> Attempt and immutable admission provenance.
The Vulture-only repair exception does not authorize reachability grants or
consumer activation. Production import search finds only codec -> identity
and whitelist -> identity; `admission_codec.py:50-53` explicitly documents no
production consumer. A fake caller would not repair acceptance.

Fresh commands (all logs in the job directory as `worker-*.log`):

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: **PASS**, 1322 reviewed identities/findings, zero unclassified. No ledger amendment justified.
- `RATCHET_BASE_REV=2154f845347c9541016288c760f8da3f5cd2e064 uv run python scripts/check-ratchet-provenance.py`: **FAIL**, exit 1. `worker-provenance.log:20-29` rejects both admission modules and their dispositions: 169 trusted versus 171 candidate. Required by `.github/workflows/vulture-ratchet.yml:77`.
- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q`: **201 passed, 3 skipped**.
- `uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs packages/maistro-core/tests/extensions -x -q`: **2987 passed, 310 skipped, 6 warnings** in 62.51s. Warnings concern aiosqlite callbacks after event-loop closure, not a reproduced codec failure.
- `uv run ruff check .` and `uv run ruff format --check .`: **PASS**.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`: **PASS**.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: **PASS**, 16543 identities, no duplicate evidence.
- `uv run python scripts/check-shipped-surface-truth.py`: **PASS**.

Driver `check-0.log` through `check-4.log` were inspected: sync, lint, format,
inventory passed; four-file test run 324 passed, 3 skipped. Independent commands
above reproduce the blocker rather than relying on earlier reports.

Fresh acceptance audit:

- Shared immutable DTO/header interfaces, flat mapping, strict UUID hex and
  signed scalars, header/row agreement, six safe typed errors, bound/unbound/
  partial legacy distinctions, no invented identity, malformed JSON rejection,
  expiry/fingerprint header separation and unknown-format rejection: covered
  by the executed 201 pure tests and inspected implementation.
- Snapshot/tag preservation and unchanged stored fingerprint: fixture-level
  round trips pass. Actual original-model fingerprint-before-tagging,
  evidence-json materialization via model_of/model_of_json and arbitrary
  program_context model pipeline: **UNVERIFIED**, not established by hand-built
  tags or fixed fingerprint fixtures.
- Raw/production pools on a real migrated disposable PostgreSQL database:
  **UNVERIFIED this round**; all three database cases skipped. No database
  session, migration, durability or final SQL identity-count claim is made.
- Authorized principals/Workspace/Project/Graph admission and Run JSONB object
  INSERT: **UNVERIFIED**. No reachable production consumer exists for B2.
- No SQL/HTTP/queue/clock/assessment/policy or execution-authority change:
  inspected pure codec remains inactive; no source edits this round.
- Full required integration CI: **UNVERIFIED**; required provenance gate
  **FAILS**. Inventory delta **0**; no tests added and existing notes preserved.
  No new pre-fix or mutation-test evidence is claimed.

Captured CI attribution was extracted to `worker-ci-summary.log` without a
remote refresh. Captured #1945 head `90d4c278e6d729d41a3f30d9f17bc65025d6f59d`
has test success and exact-debt-ledger failure. The captured test failure is
#1855 head `3f2c79a70d9e1b0b6b6ffc99562cb35db5326828`, with null output text;
neither is this assigned HEAD. The generic `test: failure` is **UNRESOLVED**
at the assigned HEAD; its exact failing step/traceback is needed. No speculative
source or ledger edits were made to claim a repair.

**BLOCKED**: coordinated trusted-base authorization or separately approved real
consumer integration remains required; neither is allowed in this repair.
Progress: `{checked: 1, done: 0, skipped: 0, errors: 1, next: trusted-base
prerequisite and assigned-head CI traceback}`. This is a validation handoff,
not integration approval or issue closeout.

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
