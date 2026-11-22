---
inventory-delta:
  packages/hive-conductor/backend/tests: +0
  packages/hive-conductor/tests/e2e: +0
---
# Issue 358 repair — job 25ae

## Frozen scope

Only issue #358, branch `auto-358`, starting HEAD
`6f77be655c898eee84c5d2ca43441163583943df`, supplied base
`430139cb729ec1bbf51a5e77ef602b8192f5d594`. Starting worktree clean.
Process the supplied integration-scope failure and explicit vulture gate repair;
inspect the existing audit query/routes/UI and adjacent tests, integration
harness/CI definition, relevant ADRs, and vulture checker/ledger. Potential edits
are restricted to evidence-backed repairs in those surfaces and this note.
No ref synchronization is indicated by the supplied failure (not a conflict).

## Initial evidence

Read job check-0 through check-6 logs and prior result artifact. Driver lint and
format passed; audit tests reported 43 passed; backend inventory passed (3128).
Check-3 failed logging in as `pmuser` to a deployment configured for `dude`.
Check-6 failed because `packages/hive-conductor/tests` has no inventory recipe.
These are not evidence of an audit pagination regression. Assumption: validate
integration against the repository's isolated harness, never mutate the foreign
deployment or bypass authentication. The supplied base comparison also includes
unrelated identity/gate changes already present at starting HEAD; preserve them
and do not widen this repair to those concerns.

## Checkpoint 1

Required vulture command independently PASS: 1,374 reviewed identities / 1,374
findings, zero unclassified. No ledger amendment justified by actual output.
Read ADR-065 and ADR-082226-5104: use existing real app wiring; do not invent a
new persistence or execution authority. Existing audit durable SQL uses State's
local seam, while ephemeral queries sort all rows and retention explicitly has
no purge. Those remain acceptance gaps, not reasons to loosen CI.

The API suite silently defaults to localhost:8101; its setup fixture can even
initialize an unrelated deployment. Investigate a safe self-contained default
using existing app lifespan, preserving explicit HIVE_BASE_URL integration mode.
This addresses the evidenced check-3 target mismatch rather than modifying the
foreign deployment. Remote integration-scope producer logs were not supplied;
its precise remote failure remains UNRESOLVED.

## Checkpoint 2

Independent audit tests: 43 PASS in 65.22s (`repair-audit.log` in the job dir).
Million-row migration 38.061s; first page 0.0011s; scoped page 0.0008s;
maximum query work <2,800 VM instructions. Reviewed route principal scoping,
streaming export, startup migration, UI capped window and adjacent tests.

An in-process replacement for the default live E2E client would change the
suite's transport contract and risk shared global runtime state. Do not silently
substitute unit/in-process coverage for E2E coverage. Keep the documented live
mode and use the existing isolated Compose harness for validation instead.

Fetched check runs read-only once for the exact assigned starting HEAD, to find
actual integration producer evidence rather than guessing at a CI code repair.
Snapshot saved to `repair-remote-checks.json` in the job directory. No GitHub
mutation. Test-health-routes and a guessed standalone E2E workflow filename were
not found; skipped. Continue only the actual workflow paths from the snapshot.

## Checkpoint 3 — named CI failure is not current at assigned HEAD

The exact-HEAD check snapshot reports `integration-scope` SUCCESS (check
110562097112, run 36919616420), plus SUCCESS for all nine specialized producers:
postgres pg17/pg18, MinIO, durable-events, strike-ladder, API/UI E2E,
wheel-imports, and docker-build. This supersedes the assumption of a currently
failing integration gate at the assigned HEAD; the unspecified merge-queue
candidate cannot be diagnosed without its exact SHA/log. A read-only request for
the successful aggregator's text log returned empty output; no log-text claim.
The snapshot also reports a separate `test` failure; it is outside the assigned
named-gate repair and is not evidence that all CI is green.

Executed independently: Ruff check and format-check PASS (2709 files); registered
inventory PASS (backend 3128, Python E2E 23). No added or removed test IDs.

Executed actual API CI producer on isolated Compose project `auto358-25ae`:
10 passed, 13 pre-existing skips in 3.37s (`repair-api.log`). Only override removes
published host ports; production authentication and assertions unchanged.
Check-3's login failure is a foreign validation target, not reproduced on the
branch image. Existing DAG/task skips are not execution acceptance evidence.
The external validation driver needs the isolated harness and registered E2E
inventory path; neither requires changing product authentication or gates.

## Checkpoint 4 — actual local integration producer failure

Full UI producer: 124 passed, 1 FAILED in 4.4m. Actual failure at
`packages/hive-conductor/tests/e2e/app-shell-loading.spec.ts:52`: the test sleeps
300ms from an unawaited navigation, then demands whoami has already started.
`App.tsx:114-116` fires both fetches before awaiting setup, but a cold script load
can outlast that arbitrary window. Audit UI cases all passed. This is new,
executed evidence within the assigned integration-scope producer repair, not a
scanner guess or a change to the audit feature's authorization path.

Focused repair: hold setup response as before, but wait for both request events
registered before navigation; release in finally. Add a delayed-script condition
to the existing case so cold startup deterministically exercises the old flaw.
Do not raise suite budgets, skip tests, add retries, or change production auth.
No additional node IDs; inventory delta stays zero.

Executed local integration evaluator with the exact remote snapshot's nine
producer results: PASS (`repair-integration-snapshot.log`). This only validates
the starting HEAD's recorded evidence; it does NOT override the new local UI
failure. Re-run that actual producer after the synchronization repair.

## Repair result

Deterministic red: adding 600ms script-delivery latency to the existing test
reproduced the false failure (`repair-ui-red.log`, old assertion now at line 59).
After request-event synchronization and finally cleanup, the entire actual UI
producer PASS: 125/125 Chromium tests in 4.0m (`repair-ui-green.log`), including
audit filter races, sentinel continuation, and eight-page retained/DOM bounds.
No suite timeout increase, skips, retries, assertion removal, production change,
or additional test IDs. Both request events must arrive while setup is blocked;
a serialized implementation still cannot satisfy that assertion.

## Acceptance assessment

| Criterion | Fresh executed evidence / gap |
| --- | --- |
| Backend bounded stable cursors and maximum page size | 43 audit tests PASS: max 200, default 50, timestamp ties and contiguous walks. |
| Authorization/scope before DB pagination | Same suite exercises production indexed SQL scope predicates before each LIMIT, backend parity and HTTP principal isolation. |
| Incremental frontend and virtualization | 125 Chromium tests PASS, including audit continuation, filter-response races and eight-page scroll. |
| Filters/export/retention without browser corpus | Filter and capped scoped NDJSON tests PASS; browser export is a download link. Retention purge is NOT IMPLEMENTED (`audit_query.py:79`), not proved by its constants endpoint; #325 remains a dependency. |
| Measured query/index strategy at scale | Million rows: migration 38.061s; first page 0.0011s; scoped page 0.0008s; 162 query shapes, max <2,800 VM instructions. SQLite State path only, not a PostgreSQL audit benchmark. |
| Concurrent inserts, stable cursors, scope isolation, maximum, empty pages, million-row envelope | All exercised in the 43-test audit run, including acknowledged durable concurrent writes. |
| Initial page cost independent of corpus | Proved after durable startup indexes only. Unqualified requirement NOT MET: ephemeral path snapshots and sorts all entries (`audit_query.py:402-403`). |
| Browser memory / DOM remains bounded | Eight-page test proves <=500 retained entries and <=30 mounted rows. Byte-level heap bound and million-row browser soak UNVERIFIED; each entry detail has no byte cap. |

## Commands / artifacts

Artifacts are under `/home/dev/maistro/jobs/25ae6d30e17a4d85b56387b8e2d23e1a`.

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1374 reviewed identities, no amendment justified.
- `uv run pytest packages/hive-conductor/backend/tests/test_audit_pagination.py packages/hive-conductor/backend/tests/test_audit_routes.py -x -q -s`: PASS, 43.
- `uv run ruff check .`; `uv run ruff format --check .`: PASS.
- `uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests --suite packages/hive-conductor/tests/e2e`: PASS, 3128 / 23.
- Read-only exact-HEAD check snapshot: `gh api repos/Agent-StrongHold/Project-mAIstro/commits/6f77be655c898eee84c5d2ca43441163583943df/check-runs`.
- `uv run python scripts/check-integration-scope.py --event-name pull_request` with the nine actual snapshot results: PASS, saved invocation/results in `repair-integration-snapshot.log`. API and UI independently reproduced locally; other producer outcomes are remote evidence, not a claimed local re-execution.
- API and UI producer commands (services run separately):
  `DOCKER_HOST=unix:///var/run/docker.sock CI=true docker compose -p auto358-25ae -f packages/hive-conductor/docker-compose.test.yml -f "$job/compose-isolated.yml" --profile test up --build --abort-on-container-exit --exit-code-from "$service" "$service"`.
  Override only removes published ports. API: 10 pass / 13 existing skips. UI: initial 124 pass / 1 fail, final 125 pass.
- Focused red uses `compose-focused.yml`: same harness, only command narrowed to the existing auth-probe test. One expected failure.

## Handoff

Only `packages/hive-conductor/tests/e2e/app-shell-loading.spec.ts` and this note
changed. Named UI producer repair is complete locally; this is not integration
approval. Existing audit acceptance gaps above mean issue #358 is **NEEDS-REPAIR**.
Do not repeat the arbitrary localhost driver validation: run its existing
isolated Compose harness and inventory `packages/hive-conductor/tests/e2e`.
Do not change credentials, invent retention policy, or introduce another store,
scheduler, execution authority, event authority, or authorization path.

Progress: {checked: 1, done: 1, skipped: 0, errors: 0, next: resolve remaining
#358 acceptance gaps and correct external validation target; exact merge-queue
candidate evidence needed if its integration gate still fails}.

Final post-edit rerun: Ruff check PASS; format-check PASS (2709); vulture PASS
(1374/1374, zero unclassified); registered inventory PASS (3128/23);
`git diff --check` PASS. Isolated Compose project stopped without deleting its
containers or data. No production, ledger, grant, workflow, or auth changes.

