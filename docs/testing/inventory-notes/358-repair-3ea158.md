---
inventory-delta:
  packages/hive-conductor/backend/tests: +0
---

# Issue 358 repair — job 3ea158

## Frozen scope and starting evidence

- Only issue #358; assigned worktree `/home/dev/Git/wt/auto-358`, branch
  `auto-358`, clean starting HEAD `6d1c267d3673f575adf502b85ae7d7aec47d956a`.
  Supplied base `cd258510bd2475073e5a397e42a5a371f3008a32` resolves.
- Scope: existing audit route/query/UI and adjacent tests; Conductor E2E
  harness; integration-scope and vulture gates; this inventory note. No
  unrelated issue work, deployment mutation, or invented CI success results.
- Inspected all seven supplied check logs and previous result artifact.
  `check-3.log` fails because the live target was initialized as `dude`, not
  suite fixture user `pmuser`. `check-6.log` uses unregistered parent inventory
  path `packages/hive-conductor/tests`. Neither proves an audit defect.
- Ambiguity: integration-scope failure has no producer detail supplied.
  Assumption: reproduce its local gate contract and validate actual Conductor
  producers in isolation; do not fabricate missing producer evidence.
- Prior notes are historical claims, not validation for this run. Existing
  retention and in-memory limitations require explicit acceptance disposition.

## Checkpoint 1 — reproduced gate contract

- Required vulture command passed: 1,383 findings, 1,383 reviewed identities,
  zero unbanked. No ledger amendment is justified by this run.
- `check-integration-scope.py --event-name merge_group` failed closed for all
  nine missing producer results. The workflow waits for actual CI checks; the
  supplied logs do not identify a failing producer. Ambiguity UNRESOLVED.
- Read package instructions and accepted ADR-068, ADR-081226-a66b and
  ADR-082226-5104. Existing SQLite State is the permitted local-state seam,
  not evidence of PostgreSQL audit coverage. No execution, authorization,
  event authority, or storage replacement is proposed.
- Production/test inspection confirms cursor limits and indexed durable seeks;
  the memory path sorts the corpus on each page. `/retention` reports
  `corpus_purge: none`; do not invent retention policy or claim closure of #325.
- The compose harness provisions a fresh service and explicitly supplies
  `HIVE_BASE_URL`; driver tests default to the unrelated host service on 8101.
  Validate a uniquely named compose project with no published ports.

## Checkpoint 2 — current executed acceptance evidence

- Ruff check and format check passed (2,680 files).
- Focused backend audit/foundation/commit-ack suites: 68 passed in 67.92s.
  Million-row migration 35.493s, first page 0.0013s, scoped page 0.0018s,
  maximum <2,800 VM instructions across 162 query combinations.
  Log: `/tmp/358-3ea158-backend.log`.
- Fresh production Dockerfile build and isolated compose API suite:
  10 passed, 13 pre-existing DAG/workspace skips. Login and live audit route
  pass. Log: `/tmp/358-3ea158-api.log`. No target on host 8101 was changed.
- Inventory gate rejected this new note's inline empty delta syntax; corrected
  to the required indented suite +0 block. No tests added or removed.

## Final evidence and acceptance disposition

- Isolated Chromium suite: **109 passed in 2.8m**, including `10b` late-response
  filter tests and `10c` eight-page incremental/window test. That test checks
  500 retained entries and at most 30 mounted rows; the volume responses are
  mocked, while test `10` separately reads the live authenticated audit route.
  Log: `/tmp/358-3ea158-ui.log`.
- Corrected inventory note passes the real registered recipes: backend 3,055
  and API E2E 23. The driver's parent `packages/hive-conductor/tests` remains
  unsupported; use the registered `.../tests/e2e` recipe, not a weakened gate.
- Backend enforces default 50 / max 200 and stable timestamp/id cursor ordering:
  executed maximum/floor, timestamp tie, malformed cursor and empty-page tests.
- Scope/filter-before-pagination: executed durable parity (including two actor
  aliases and denied scopes), route-level cross-user probes, and deterministic
  query-work checks. Production `_page_sql` applies scope in each indexed seek.
- Filters/export without full-corpus browser loading: executed route NDJSON,
  export cap/scope and browser filtered-download-link tests. No browser blob
  collection is introduced. Retention **UNVERIFIED / absent**: production
  `services/audit_query.py:79` explicitly declares no purge. The proposed
  ADR-055 does not authorize inventing a purge policy in this CI repair.
- Representative large dataset/index measurement: executed million-row test
  above, including concurrent acknowledged durable writes in a separate test.
  Cold migration remains corpus-sized; eight indexes add write/storage costs
  not benchmarked here. No PostgreSQL performance claim is made.
- Initial page cost: proven bounded for initialized durable query path only.
  `services/audit_query.py:402-403` snapshots and sorts the entire in-memory
  corpus on each page; the unqualified definition of done is **NOT MET**.
- Browser DOM/retained-entry count bounds pass. A byte-level heap envelope and
  very-long-scroll soak beyond the eight-page test remain **UNVERIFIED**.
- Integration-scope remains **UNVERIFIED** without the actual failed producer
  evidence. The aggregate script consumes results; running it with no results
  reproduces missing evidence, not the original remote failure's cause.
  Final execution with `--result hive-conductor-e2e=success --result
  hive-conductor-e2e-ui=success` (the two locally executed producers) still
  exits 1 for seven missing results: docker-build, durable-events, MinIO,
  pg17, pg18, strike-ladder, wheel-imports.
  Log: `/tmp/358-3ea158-integration.log`. No scope JSON or result was invented.

## Reproduction commands

All executed in the assigned worktree; no GitHub mutation:

```sh
uv run ruff check .
uv run ruff format --check .
uv run pytest packages/hive-conductor/backend/tests/test_audit_pagination.py packages/hive-conductor/backend/tests/test_audit_routes.py packages/hive-conductor/backend/tests/test_foundation.py packages/hive-conductor/backend/tests/test_state_commit_acknowledgement.py -x -q -s
uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests --suite packages/hive-conductor/tests/e2e
uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'
uv run python scripts/check-integration-scope.py --event-name merge_group
DOCKER_HOST=unix:///var/run/docker.sock CI=true docker compose -p auto358-3ea158 -f packages/hive-conductor/docker-compose.test.yml -f /tmp/358-3ea158-compose.yml up --build --abort-on-container-exit --exit-code-from api-tests api-tests
DOCKER_HOST=unix:///var/run/docker.sock CI=true docker compose -p auto358-3ea158 -f packages/hive-conductor/docker-compose.test.yml -f /tmp/358-3ea158-compose.yml up --build --abort-on-container-exit --exit-code-from e2e-tests e2e-tests
```

The temporary compose override contains only `services.hive.ports: !reset []`.
The production Docker build also executes the frontend build. Results above
are new evidence, not copied verification claims from previous notes.

## Handoff

Only this evidence note changed. No production, tests, gates, grants, or ledger
changed: named vulture check passes and isolated Conductor producers pass, so
there is no evidence-backed CI code fix to apply. The live driver target must
be corrected by supplying an isolated `HIVE_BASE_URL`/compose target, not by
changing credentials, suppressing assertions, or mutating the foreign service.
No develop-sync conflict exists in the supplied worktree; no fetch/merge needed.

Verdict: **NEEDS-REPAIR**, not integration approval. Next: supply the failed
integration producer logs/results; reconcile/implement retention with #325 and
resolve the in-memory page-cost gap before claiming #358 closeout. This repair
round cannot truthfully clear the prior validation-budget block or all issue
acceptance. Final ruff, format, inventory and `git diff --check` reruns passed. The
isolated compose project was stopped (containers/data preserved). Local
evidence is committed in this round; all existing work is preserved.

Progress: {checked: 1, done: 0, skipped: 0, errors: 1, next: missing integration
producer evidence and unresolved retention/in-memory acceptance}.
