---
inventory-delta:
  packages/hive-conductor/backend/tests: +0
  packages/hive-conductor/tests/e2e: +0
---

# Issue 358 repair, job 0bf5

## Frozen scope

Only issue #358 on branch auto-358, starting at
0b601a81c60d43981104767b1b4330f838a62a70; supplied comparison base
3082279f186de4778e9a98bd5fa2fef20db46eb2. Initial worktree clean.
Process the supplied integration-scope failure and exact-debt-ledger gate,
then validate existing audit implementation and acceptance tests. Candidate
repair files: audit service/routes/frontend and their existing tests,
`quality/vulture-baseline.json` if the requested gate identifies retained debt,
and this note. Do not alter unrelated RSI work or shared deployment data.

## Initial evidence / assumptions

Read current job check-0 through check-6 and prior result/check-3.
Both check-3 failures authenticate `pmuser` against a deployment configured
for `dude`; do not weaken authentication or skip this failure. Validate with
an isolated fresh test deployment instead. check-6 uses an unsupported
inventory recipe (`packages/hive-conductor/tests`), not an application failure.
check-4 reports 43 passes, to be independently verified.
The supplied base comparison includes unrelated RSI differences; no sync
conflict was reported, so assume this is a CI repair rather than an instruction
to merge develop. Preserve unrelated files. Integration-scope's actual command
must be located before claiming it passes.

## Results

Checkpoint 1: required Vulture command passed: 1,374 findings/reviewed
identities, zero unclassified; no ledger change justified. Focused audit
pytest independently passed 43 tests in 54.82s (`repair-audit.log` in job).
Million-row index migration 31.984s; initialized first page 0.0012s, scoped
page 0.0008s, maximum query VM instructions <2,800.

Read query/routes/UI and integration gate source. Integration-scope consumes
producer verdicts; supplied logs do not identify a failed remote producer.
Original remote failure attribution remains UNRESOLVED, not an excuse to
manufacture successful results. Existing production gaps remain: ephemeral
path sorts the corpus and retention declares `corpus_purge: none` (#325).
No speculative production change for those policy ambiguities in this CI round.
Two guessed ADR filenames were not found; skipped those filenames and resolved
the actual paths from the directory before further reading.

Checkpoint 2: read accepted ADR-065, ADR-068, ADR-082226-5104 and proposed
ADR-055. Preserve the existing State/JsonStore read seam; do not establish a
new datastore, event authority, authorization path, or execution lifecycle.
ADR-055's proposed retention values are not authority to invent a purge policy.
The audit query benchmark is for Conductor's existing local State, not evidence
of PostgreSQL audit-query performance.

Built and ran the actual Compose API producer in isolated project
`auto358-0bf5`, with published ports reset (no host deployment mutations):
**10 passed, 13 pre-existing skips**, including login and audit trail
(`repair-api.log`). This resolves the supplied check-3 environment mismatch
for this run; it does not prove the original remote integration failure fixed.
Read CI producer wiring; full docker-build includes engine/PG18 restart and
RSI canary builds, not just the Conductor image. Do not label a Conductor-only
build as successful docker-build.

Checkpoint 3: full Chromium producer **failed**, 116 passed / 1 failed in
4.9m. All five audit browser cases passed. Failure is
`packages/hive-conductor/tests/e2e/app-shell-loading.spec.ts:52`: after its
300ms wait, `whoamiRequestedWhileSetupStatusPending` was false. Evidence:
`repair-ui.log:264-284`. No retries, weakening, or unrelated app-shell edits.

`uv run ruff check .` and `uv run ruff format --check .` passed (2,709 files).
`git diff --check` passed. Guessed inventory script `check-test-inventory.py`
was not found; skipped and resolved actual `scripts/check-suite-inventory.py`.

Executed the named integration aggregate fail-closed because no actual remote
scope JSON was supplied:
`uv run python scripts/check-integration-scope.py --event-name merge_group
--result hive-conductor-e2e=success --result hive-conductor-e2e-ui=failure`.
**Exit 1**, UI failed; other required producer results missing (docker-build,
wheel-imports, both PostgreSQL versions, object storage, durable-events,
strike-ladder). This is honest local evidence, not a reconstruction of the
remote merge candidate. Original integration failure remains unresolved.
Stop starting new producer work; preserve artifacts and finalize handoff.

Checkpoint 4: copied browser screenshots/error context to job
`ui-failure-results/`; stopped only project `auto358-0bf5`, preserving containers
and data. Inventory check passed: backend 3,128, Python E2E 23. No tests added
or removed and no shared inventory/quality ledger edited.

## Commands / reproduction

All artifacts below are in
`/home/dev/maistro/jobs/0bf5dae817324f07a920d65a4af9e042`.

```sh
uv run python scripts/check-vulture-baseline.py packages/*/src \
  --min-confidence 60 --exclude '*/third_party/*'
# PASS: 1,374 reviewed identities, zero unclassified.
uv run pytest packages/hive-conductor/backend/tests/test_audit_pagination.py \
  packages/hive-conductor/backend/tests/test_audit_routes.py -x -q -s
# PASS: 43 tests; repair-audit.log.
uv run ruff check .
uv run ruff format --check .
# Both PASS.
uv run python scripts/check-suite-inventory.py \
  --suite packages/hive-conductor/backend/tests \
  --suite packages/hive-conductor/tests/e2e
# PASS: repair-inventory.log. Use registered e2e path, NOT its parent.
```

For each of `api-tests` and `e2e-tests`, executed:

```sh
job=/home/dev/maistro/jobs/0bf5dae817324f07a920d65a4af9e042
DOCKER_HOST=unix:///var/run/docker.sock CI=true docker compose \
  -p auto358-0bf5 -f packages/hive-conductor/docker-compose.test.yml \
  -f "$job/compose-isolated.yml" up --build --abort-on-container-exit \
  --exit-code-from <service> <service>
```

The isolation override only sets `hive.ports: !reset []`; services still use
`http://hive:8101` with original auth/settings and test commands.
API exit 0, UI exit 1. Do not repeat the host-port pytest command against the
foreign deployment. Do not substitute successful audit-only browser tests for
the full UI producer's failed result.

## Acceptance evidence and residual risks

| Acceptance / done criterion | Independently executed evidence |
| --- | --- |
| Bounded cursor, stable order, maximum page | 43 backend tests pass: default 50, cap 200, floor 1, ties including production `Z` timestamps, malformed cursors. |
| Scope before DB pagination | Durable SQL parity and bounded-VM scenarios pass; HTTP tests verify admin/own-scope isolation including detail/export. |
| Incremental loading and virtualization | All five audit cases passed in the full browser run: real API read, two stale-filter races, continuously visible sentinel, eight-page cursor walk. |
| Filters/export/retention without browser corpus | Filtered export link, scoped NDJSON and 10,000-entry cap pass. Retention metadata is bounded, but actual purge remains absent (`audit_query.py:79`); retention operation acceptance **UNVERIFIED** pending #325 policy. |
| Representative large-data query/index measurements | Million SQLite rows: migration 31.984s, first initialized page 0.0012s, scoped page 0.0008s; 162 filter/scope/cursor combinations, <2,800 maximum VM instructions. PostgreSQL and index disk/write amplification **UNVERIFIED**. |
| Concurrent inserts, cursor stability, isolation, maximum, empty, million-row tests | Executed all existing audit tests, including real durable writer acknowledgements during a cursor walk; 43 pass. |
| Initial-page cost independent of total size | Proven only for initialized durable reads. Not met without qualification: ephemeral path snapshots/sorts entire corpus (`audit_query.py:402-403`); startup migration/hydration is corpus-sized. |
| Browser memory/DOM bounded | Eight-page browser test proves <=500 retained entries and <=30 mounted rows. Byte-level heap bounds and very-long-scroll behavior **UNVERIFIED**; detail payload sizes are not capped here. |

## Handoff

Only changed file this round: this evidence/inventory note. No production
repair was justified by the supplied foreign-deployment failure or the green
Vulture gate. The new full-browser failure is outside the frozen audit files;
do not claim this note fixes it. No new tests were warranted for a note-only
change; existing meaningful backend and browser tests were executed above.

**NEEDS-REPAIR**, not integration approval. Next owner needs the actual remote
integration producer results/scope, an authorized app-shell failure repair,
and resolution/qualification of retention and ephemeral performance criteria.
Do not restart this lane solely against the same foreign host deployment.

Progress: {checked: 1, done: 0, skipped: 0, errors: 1, next: integration producer
failure repair and remaining acceptance gaps}. Local commit required; no push,
merge, branch deletion, issue closure, gate weakening or GitHub mutation.

