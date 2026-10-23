---
inventory-delta:
  packages/hive-conductor/backend/tests: +0
---
# #358 repair checkpoint (b05d)

## Frozen scope

Only issue #358, branch `auto-358`, starting head
`9c03ce7b43c251fd4eb50f3b78362f3ce8d7de5b`, base
`c91e354f30ca1fcc21ea97e1fa1bcf1f867bf508`. Worktree initially clean.
Inspect the supplied job's seven check logs, prior result, repository instructions,
relevant ADRs, existing audit implementation/tests and integration-scope/vulture
gates. Candidate edits are this note, existing #358 audit implementation/tests,
its integration test harness, and the explicitly permitted vulture ledger only
if a reproduced gate requires it. No unrelated issues or remote operations.

## Initial evidence / assumptions

The supplied check-3.log fails login against an existing deployment configured
as `dude`, while tests require freshly seeded `pmuser`. This is not evidence of
an audit pagination defect. Reproduce acceptance in an isolated local harness;
do not reset or alter the foreign deployment or weaken assertions. The named
integration-scope failure has no diagnostic yet; inspect its local gate.
Prior verification claims are not accepted as current evidence.

## Results

- Named vulture command passes: 1,372 findings / reviewed identities, zero
  unclassified. No evidence warrants a ledger amendment.
- Integration classifier on the frozen branch/base diff enables docker_build,
  hive_e2e, wheel_imports. Named integration-scope gate exits 1: all four
  producer results missing. This is an evidence aggregator, not a standalone
  test; cannot claim remote success from local results. Actual remote producer
  diagnostic remains UNRESOLVED (none supplied); no gate edits justified.
- Supplied check-0/1/2 pass sync/lint/format; check-4 reports 43 backend tests;
  check-5 inventory 3,152. Check-6 requests unsupported inventory suite parent
  `packages/hive-conductor/tests`; actual registered suite is `tests/e2e`.
- Accepted ADR-068 and ADR-081426-1f7c read: preserve existing principal authority
  and canonical execution semantics; no new authorization/runtime path.

Inspection confirms remaining acceptance gaps: `audit_query.py` explicitly
reports no corpus purge and sorts the entire in-memory corpus per page. They
cannot be declared resolved by the pagination tests. No speculative retention
policy will be introduced in a gate-repair round. Docker is available (29.7.2).
The guessed ADR-065 durable-store filename was not found; skipped. The actual
ADR-065 is the test-harness ADR. E2E-local node_modules path absent; frontend
node_modules is present.

## Executed validation

Logs are in the supplied job directory.

- `uv run ruff check .`: pass; `uv run ruff format --check .`: pass (2,709 files).
- `uv run pytest packages/hive-conductor/backend/tests/test_audit_pagination.py
  packages/hive-conductor/backend/tests/test_audit_routes.py -x -q -s`:
  **43 passed in 185.82s** (`repair-backend.log`). Million-row migration
  136.869s; initialized first page 0.0013s; scoped page 0.0005s; maximum
  query VM instructions <2,800 across all filter/scope/cursor combinations.
  Migration was measured concurrently with the Docker build; not a dedicated
  performance machine. Warm query cost does not include startup migration.
- Fresh project `auto358-b05d`, image built from this worktree, Compose API
  suite: **10 passed, 13 existing skips** (`repair-api.log`). Login and live
  audit reads pass. Skipped DAG tests do not establish DAG behavior.
  This diagnoses the supplied foreign-target failure without changing it.
- Read accepted ADR-065 and proposed ADR-055: the latter is not an accepted
  retention policy authorizing purge implementation in this round.

Reproduction (only override: `services.hive.ports: !reset []`):

```sh
DOCKER_HOST=unix:///var/run/docker.sock CI=true docker compose \
  -p auto358-b05d -f packages/hive-conductor/docker-compose.test.yml \
  -f /home/dev/maistro/jobs/b05db7d09458463a8e10fa9dae9a2a09/compose-isolated.yml \
  up --build --abort-on-container-exit --exit-code-from api-tests api-tests
```

- Browser Compose build returned `target hive: failed to solve: Internal:
  context deadline exceeded` after exporting both images (`repair-ui.log`).
  Do not treat this infrastructure failure as an audit test result. Salvage
  the built images and execute without rebuilding if their names resolve.
- Inventory gate initially rejected this note's inline empty delta mapping;
  corrected to the required indented suite `+0` block. Recheck **passes**:
  backend 3,152; E2E 23.
- Both built image refs resolved; salvaged via the same Compose command with
  `--no-build --exit-code-from e2e-tests e2e-tests`: **exit 1**, 99 passed,
  11 failed, 15 did not run (13.2m), `repair-ui-salvage.log`. This is current
  failing producer evidence; previous rounds' green UI results do not apply.
  No more new validation lanes will be started; preserve failure evidence
  and finalize handoff rather than modify unrelated components.

## Acceptance reconciliation / final disposition

**NEEDS-REPAIR**. This commit changes only this evidence note. No production
fix is claimed. No tests added, gates weakened, ledger identities banked,
foreign data reset, or remote mutations performed.

| Criterion | Current evidence |
| --- | --- |
| Bounded cursor / stable ordering / maximum page | Executed 43-test backend suite proves default 50, maximum 200, tie ordering, cursor continuation, malformed cursor and empty-page behavior. |
| Database authorization/filter before pagination | Executed SQL parity/scope tests and million-row VM bounds; routes use existing authenticated username/id scope. |
| Incremental loading / virtualization | All five audit browser cases at `pm-workflow.spec.ts:180-307` ran successfully in the otherwise failing full UI suite: live read, two stale-filter races, short-page continuation, eight-page retained/DOM bounds. |
| Filters / export / retention without browser corpus load | Scope/filter/export cap/NDJSON tests pass, browser export href assertions pass. Retention NOT MET: `audit_query.py:79` reports no purge; policy remains #325. |
| Large dataset query/index measurements | Million-row timing/VM envelope above passes, including absent filters and deep cursors. Eight-index write/storage overhead and PostgreSQL UNVERIFIED. |
| Concurrent insert / stability / isolation / max / empty / million-row tests | Executed backend suite includes threaded acknowledged durable inserts and memory concurrency. |
| Initial page independent of corpus | Proven for initialized durable SQL only. NOT MET unqualified: `audit_query.py:402-403` snapshots and sorts all memory rows; startup also hydrates/migrates the corpus. |
| Browser memory / DOM bounded | Eight-page browser test asserts at most 500 retained entries and 30 mounted rows. Byte-level heap bound and million-row scrolling UNVERIFIED. |

### Current integration failure evidence

`repair-ui-salvage.log:257-261` lists the successful audit cases. Other UI
failures include login response timeouts (`session.ts:151`), missing Design
Studio navigation (`design-studio-truthfulness.spec.ts:340`), and the existing
PM all-pages test timing out at `pm-workflow.spec.ts:321`. Do not classify these
as fixed, or inflate timeouts without diagnosing the actual failure.
Screenshots/error contexts were preserved from the exited container to
`<job>/ui-test-results`. All project containers stopped; data and images kept.
No resource cleanup or deletion performed.

Re-ran the integration aggregator against the already-frozen scope and only
locally executed producer outcomes:

```sh
uv run python scripts/check-integration-scope.py --event-name merge_group \
  --scope-json '{"docker_build":true,"durable_events":false,"hive_e2e":true,"object_storage":false,"postgres":false,"strike_ladder":false,"wheel_imports":true}' \
  --result hive-conductor-e2e=success --result hive-conductor-e2e-ui=failure
```

Exit **1** (`repair-integration-final.log`): UI failure plus missing docker-build
and wheel-imports. The successful Conductor image build is not the separate
specialized docker-build gate. These are local results, not remote check-run
claims. The supplied remote merge-queue failure's exact diagnostic remains
UNRESOLVED; local failure is independently established. The previous repair
budget block is not cleared.

Next: inspect the saved failing UI artifacts/actual remote producer logs under
a specifically assigned CI harness repair; fix the driver's live target and
inventory suite selection; resolve #358 retention/in-memory acceptance gaps.
Do not repeat prior green claims or create another speculative ledger edit.

Progress: {checked: 1, done: 0, skipped: 0, errors: 1, next: UI producer repair
and unresolved retention/in-memory acceptance}. `git diff --check` passes.
