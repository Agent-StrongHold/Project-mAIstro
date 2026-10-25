---
inventory-delta:
  packages/hive-conductor/backend/tests: 0
---

# Issue 358 repair — e4ec

## Frozen scope and starting evidence

- Only issue #358, branch `auto-358`, assigned worktree `/home/dev/Git/wt/auto-358`.
- Starting HEAD verified: `f052c517fbf57679f295211d1ceb5604d679f700`; worktree clean.
- Process the supplied job check-0 through check-6 logs, prior result JSON,
  Conductor audit service/route/UI and adjacent audit tests, PM integration test
  harness/workflow, relevant ADRs/instructions and named vulture/inventory gates.
- Candidate repair files: this note, Conductor PM integration test harness and
  its existing CI invocation, and (only for demonstrated unbanked retained
  identities) `quality/vulture-baseline.json`. Other issue work is out of scope.
- Driver check-3 fails because localhost serves an already configured deployment
  with user `dude`, whereas this test requires fresh setup for `pmuser`.
- Driver check-6 fails because `packages/hive-conductor/tests` has no inventory
  collection recipe. Do not weaken the gate or invent inventory coverage.
- Assumption: integration-scope refers to the Conductor integration workflow;
  inspect its actual invocation before deciding whether code needs repair.
- Prior result is validation-only, not acceptance proof. No merge-ready claim.

## Validation and acceptance

- Named vulture command passed: 1,373 findings, 1,373 reviewed identities,
  zero unclassified. No ledger amendment is warranted.
- Integration Scope is an aggregate of nine specialized producers, not the PM
  pytest command. The supplied artifact does not identify its failed producer.
  UNRESOLVED: aggregate failure cannot be honestly attributed to one producer
  from the provided logs. No gate/classifier edits are justified.
- Compose's intended target is a fresh isolated Hive; driver localhost is not
  that target. Focused audit route/pagination tests executed: **43 passed in
  108.78s**, including the real SQLite million-row envelope, concurrent writes,
  scope filtering, limit clamps, empty pages, capped streaming export.
- Read production audit route/query/UI and browser regressions. Retention is
  metadata only (`corpus_purge: none`), and ephemeral queries sort the corpus.
  These remain acceptance gaps; no permission to implement #325's policy here.
- Isolated Compose production builds and API producer passed: **10 passed,
  13 pre-existing skips** (34.48s). Full Chromium producer passed: **125 passed
  (7.7m)**, no retries. Audit filter races, short-page continuation, eight-page
  retained-entry/DOM bound, and real authenticated API audit read all executed.
  Logs: `/tmp/358-e4ec-api.log`, `/tmp/358-e4ec-ui.log`.
- `uv run ruff check .`: pass; `uv run ruff format --check .`: pass (2,711 files).
  `uv run python scripts/check-suite-inventory.py --suite
  packages/hive-conductor/backend/tests --suite packages/hive-conductor/tests/e2e`:
  pass (3,134 backend, 23 Python E2E). `git diff --check`: pass.
- No new tests or source edits: existing meaningful tests reproduce the actual
  production boundaries. No Vulture ledger changes: all identities already
  reviewed. Do not create a cosmetic code repair to disguise a driver mismatch.
- ADR-068 keeps existing authentication/authorization authoritative; this repair
  does not add authority. ADR-091226-1341 requires measured fail-closed integration
  evidence, so absent producer results cannot be called successful.
- ADR-082226-5104 permits existing local State usage but does not make SQLite
  the canonical durable datastore. Measurements here are of Conductor's current
  SQLite audit seam, not evidence for a PostgreSQL audit-query implementation.
  No competing Goal/Graph/Run/NodeRun/Attempt, event, or authorization authority
  is introduced.

## Final execution and acceptance

Additional measured million-row run:

```sh
uv run pytest packages/hive-conductor/backend/tests/test_audit_pagination.py::test_million_row_corpus_pages_in_bounded_time -x -q -s
```

Passed in 64.49s: index migration **44.127s**, initial page **0.0013s**,
scoped page **0.0008s**, maximum query VM instructions **<2,800** across 162
filter/scope/cursor combinations. Log: `/tmp/358-e4ec-million.log`.

Named aggregate executed honestly with only this round's producer evidence:

```sh
uv run python scripts/check-integration-scope.py --event-name pull_request \
  --result hive-conductor-e2e=success --result hive-conductor-e2e-ui=success
```

**Exit 1**: missing docker-build, durable-events, object storage (MinIO),
postgres (pg17), postgres (pg18), strike-ladder, wheel-imports. Building the
Conductor image is not the full docker-build producer. This does not diagnose
which remote merge-queue producer failed; that remains UNRESOLVED. Do not
fabricate successful producer arguments or modify the gate.

| Acceptance | Fresh evidence / limitation |
| --- | --- |
| Bounded stable cursor and maximum page | 43 passing audit backend tests, HTTP limit 200/default 50, timestamp ties, malformed and empty cursors. |
| Database authorization before pagination | Real durable parity/scoped SQL tests passed; route tests exercise authenticated principal scope. |
| Incremental loading and virtualization | 125 Chromium tests passed including short-page continuation and eight-page audit walk. |
| Filters/export/retention avoid browser corpus | Filter-race and export-link browser tests plus scoped/capped streaming backend tests passed. Retention is metadata only; purge is absent at `audit_query.py:79`, owned by #325. Criterion not fully proven. |
| Measured large-data query/index strategy | Fresh million-row measurements above, including deep/absent/scoped/filter shapes. PostgreSQL and index write/storage overhead UNVERIFIED. |
| Required regression coverage | Concurrent acknowledged writes, stable ties, scope isolation, maximum limits, empty pages and million-row tests executed successfully. |
| Initial cost independent of corpus size | Proven only for initialized durable query; ephemeral path snapshots/sorts all entries at `audit_query.py:402-403`. Startup/index migration also corpus-sized. Unqualified criterion not met. |
| Bounded browser memory/DOM | Eight-page Chromium regression proves retained count <=500 and DOM rows <=30. Heap bytes with arbitrary detail sizes and unbounded-duration scroll UNVERIFIED. |

## Reproduction and handoff

Focused backend command:

```sh
uv run pytest packages/hive-conductor/backend/tests/test_audit_pagination.py \
  packages/hive-conductor/backend/tests/test_audit_routes.py -x -q
```

Isolated producer commands (API first, then replace both `api-tests` occurrences
with `e2e-tests`); no host ports, fresh project/data, production Dockerfiles:

```sh
DOCKER_HOST=unix:///var/run/docker.sock CI=true docker compose -p auto358-e4ec \
  -f packages/hive-conductor/docker-compose.test.yml -f - up --build \
  --abort-on-container-exit --exit-code-from api-tests api-tests <<'YAML'
services:
  hive:
    ports: !reset []
YAML
```

Only this project's containers were stopped after validation; data/images
preserved. No foreign localhost deployment touched. Correct the driver's
validation target to isolated Compose and inventory suite to the registered
`packages/hive-conductor/tests/e2e`; those settings are outside this worktree.
The writer cannot repair them by weakening authentication or inventing a parent
suite recipe. The supplied validation-budget block remains unresolved until
that driver correction and remaining producer evidence are supplied.

Changed file: this evidence/inventory note only. Local commit required; no push,
PR/issue mutation or integration approval. Verdict **NEEDS-REPAIR**, not
merge-ready: retention/ephemeral-cost acceptance gaps and aggregate evidence
remain open. Next owner needs the actual remote failed-producer log, corrected
validation target, and a decision on #325 retention and ephemeral-mode bounds.

Progress: {checked: 1, done: 0, skipped: 0, errors: 1, next: remaining acceptance
and integration evidence}. No speculative source or ledger edits.
