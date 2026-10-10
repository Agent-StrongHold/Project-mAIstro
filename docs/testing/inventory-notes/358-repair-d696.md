---
inventory-delta:
  packages/hive-conductor/backend/tests: +0
  packages/hive-conductor/tests/e2e: +0
---

# Issue 358 repair — d696f780

## Frozen scope

- Assigned issue: #358 only; worktree `/home/dev/Git/wt/auto-358`, branch
  `auto-358`, starting HEAD `0ccd350abdbf3128ac25fe86a471b040c3734603`,
  comparison base `9fe61e216786b95748d36ba8d75751f875b925e1` (both resolve).
- Repair targets: reported integration-scope gate, required vulture identity
  gate, audit pagination production paths and their adjacent backend/browser/API
  tests, and this inventory note. No other campaign items will be processed.
- Initial tree clean; no incoming changes to salvage.

## Initial evidence and assumptions

- Driver check-3 fails logging in as `pmuser` against a deployment configured
  for `dude`; it must not be wiped or reconfigured. Determine whether an isolated
  existing harness can execute these tests without weakening assertions.
- Driver check-4 reports 43 audit tests passed; independently re-run acceptance
  checks rather than treating that as proof.
- Driver check-6 reports no collection recipe for `packages/hive-conductor/tests`.
- Prior result artifact confirms check-3, not a production exception, caused the
  previous failed validation. Integration-scope failure detail is not supplied;
  reproduce the named gate locally against the exact supplied base.
- This is a writer repair, not integration approval. Accepted execution/authority
  ADRs remain binding; do not create a competing runtime or event store.

## Results

Checkpoint 1: required vulture command PASS: 1,378 findings / 1,378 reviewed
identities, zero unclassified or never-allowlist findings. No ledger edit is
warranted by this evidence.

Read ADR-065 (real composed harness), ADR-068 (existing authorization authority),
and ADR-082226-5104 (PostgreSQL canonical durability; existing local State seam
is not a new canonical datastore). Inspection confirms this branch queries the
existing State-backed audit namespace, not canonical PostgreSQL audit events.
No new execution or authorization authority will be introduced.

Independent audit backend validation PASS: 43 tests in 43.60s; million-row
index migration 25.023s, first page 0.0010s, scoped page 0.0007s, maximum
<2,800 VM instructions. Artifact: job directory `repair-audit.log`.

Reachable acceptance gaps remain: `audit_query.py` declares `corpus_purge:
none`, and its ephemeral path snapshots and sorts the whole corpus per page.
Retention policy remains owned by #325; do not invent a purge policy here.
The UI retains <=500 entries, but individual entry details have no byte cap.

Integration-scope is an evidence aggregator, not a source scanner. Its original
producer verdicts/logs were not supplied. A guessed workflow filename
`docker-build.yml` was not found; skipped. Locate the actual declaration among
existing workflow files; do not manufacture success results for unexecuted
producers. Prior repair's same target mismatch was already diagnosed, so no
further investigation of foreign credentials is warranted.

Checkpoint 2: Conductor API Compose producer PASS: 10 passed, 13 pre-existing
skips. Chromium Compose producer PASS: all 117 tests in 3.2m, including audit
filter-race, sentinel continuation, and eight-page retained-row/DOM assertions.
Artifacts: `repair-api.log`, `repair-ui.log` in the assigned job directory.
Both used project `auto358-d696` and a compose override removing host port
publication only. No credentials, assertions, auth policy, or gates changed.
The external localhost deployment was not touched. API skips are not evidence
for the skipped execution scenarios.

Ruff check and format-check PASS (2,689 files). No production repair is supported
by the supplied gate evidence. Docker-build includes unrelated engine/PG18
boot/restart and RSI canary checks; building Conductor is not proof of that
producer. Do not spend another repair round guessing its original failure.
The original integration producer failure remains UNRESOLVED after inspecting
the aggregate and its declarations; request its actual log for the next writer.

## Final evidence and disposition

Executed `scripts/check-integration-scope.py` for `merge_group`, using the
classifier's result for the exact initial changed-file snapshot and ONLY the
two producer successes independently earned here. FAIL: `docker-build` and
`wheel-imports` are required but missing. Artifact: `repair-integration-scope.log`.
This is a local incomplete-evidence result, **not** a reproduction or explanation
of the unspecified remote producer failure. Prior wheel/build claims were not
reused as current validation evidence.

Inventory PASS: backend 3,116 tests; Python E2E 23. The driver's parent path
`packages/hive-conductor/tests` is not a registered recipe; the correct suite
argument is `packages/hive-conductor/tests/e2e`. `git diff --check` PASS.
Isolated Compose project stopped; containers retained. No data discarded.

### Acceptance

| Criterion | Executed evidence / residual gap |
| --- | --- |
| Backend bounded cursor, stable order, maximum page | 43-test audit run: max 200, default 50, timestamp ties, contiguous cursor walks, malformed cursor rejection. |
| Scope filters before database pagination | Same run: exact indexed SQL applies actor aliases and filters before each LIMIT; durable/memory parity and HTTP principal isolation. |
| Frontend incremental loading and virtualization | 117-test Chromium run passes; audit tests exercise production component, late responses, visible sentinel continuation, and eight-page walk. |
| Filters/export/retention without full browser corpus | Scope/filter/export cap and streamed NDJSON tests pass; browser verifies filtered download URL. Retention purge is NOT IMPLEMENTED (`audit_query.py:79`); constants endpoint does not prove this criterion. |
| Measured query/index strategy | 1,000,000-row test: migration 25.023s, initial page 0.0010s, scoped page 0.0007s; <2,800 VM instructions across 162 query shapes. Existing State SQLite path only, not PostgreSQL. |
| Concurrent inserts/stable cursors/scope/max/empty/million-row tests | Executed in the 43-test audit suite, including acknowledged concurrent durable writes. |
| Initial page cost independent of total corpus | Durable steady-state indexed reads demonstrated. Unqualified criterion NOT MET: ephemeral path snapshots and sorts all rows (`audit_query.py:402-403`). |
| Browser memory/DOM bounded | Eight-page Chromium test verifies <=500 retained entries and <=30 mounted rows. Byte-level heap bound and million-row browser soak UNVERIFIED; detail fields have no byte cap. |

### Commands

```sh
uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'
uv run ruff check .
uv run ruff format --check .
uv run pytest packages/hive-conductor/backend/tests/test_audit_pagination.py packages/hive-conductor/backend/tests/test_audit_routes.py -x -q -s
uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests --suite packages/hive-conductor/tests/e2e
# Run separately, in order, for api-tests and e2e-tests:
DOCKER_HOST=unix:///var/run/docker.sock CI=true docker compose -p auto358-d696 \
  -f packages/hive-conductor/docker-compose.test.yml -f "$job/compose-isolated.yml" \
  --profile test up --build --abort-on-container-exit --exit-code-from "$service" "$service"
# job=/home/dev/maistro/jobs/d696f780aec9451e91cf28741e478024
# scope-json is the recorded classifier output in repair-scope.json:
uv run python scripts/check-integration-scope.py --event-name merge_group \
  --scope-json "$scope_json" --result hive-conductor-e2e=success \
  --result hive-conductor-e2e-ui=success
git diff --check
# Same isolated project/files: docker compose --profile test stop
```

Only this evidence note changed; no tests added/removed, no ledger amendment,
no cosmetic source repair, no gate weakening or competing authority. The prior
validation-budget block remains unresolved. Do not replay the known foreign
localhost failure again; point the validation driver at its existing isolated
Compose harness and the registered inventory suite. Obtain the actual failed
integration producer log before choosing a source repair. Retention dependency
and unconditional page-cost acceptance also require resolution.

Verdict: **NEEDS-REPAIR**, not an integration approval.
Progress: {checked: 1, done: 0, skipped: 0, errors: 1, next: original failed
integration producer evidence and unresolved #358 acceptance criteria}.
