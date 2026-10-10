---
inventory-delta:
  packages/hive-conductor/backend/tests: +0
---

# Issue 358 repair — f540

## Frozen scope

Only issue #358, branch `auto-358`, starting head
`bf6b29784bb0b911178d47248b86e03cbbae59c2`, supplied base
`33bcd3ce28830032403e23ce82de8ccfaca2acce`. Repair the supplied
integration-scope / exact-debt-ledger failures and validate existing audit
pagination behavior. No GitHub mutations or unrelated feature changes.
Initial worktree was clean.

## Initial evidence

- Current job `check-3.log`: API smoke tests reached a deployment seeded as
  `dude`; login as harness user `pmuser` failed (4 passed, 1 skipped, 1 error).
- Prior result artifact also failed the same two API test modules; no prior
  acceptance claims are adopted.
- Assumption: use the repository's isolated service harness rather than alter
  authentication or treat foreign-deployment failure as a product regression.

## Progress

- Inspected all seven driver logs: sync/lint/format pass; audit tests 43 pass;
  backend inventory 3,210 passes; parent `packages/hive-conductor/tests`
  inventory command fails because it has no registered collection recipe.
- Named vulture command rerun: PASS, 1,371 findings / 1,371 reviewed identities,
  zero unclassified. No identity requires a ledger amendment.
- Read accepted ADR-065, ADR-068, ADR-081226-9944, ADR-082226-5104 and proposed
  ADR-055. Preserve the existing principal and State/PersistedStore seam; its
  SQLite performance is not evidence for canonical PostgreSQL persistence.
  No retention policy can be inferred from proposed ADR-055 or invented for #325.
- Production inspection confirms retention reports `corpus_purge: none` and
  the memory fallback sorts the corpus on every page. These are acceptance
  gaps, not resolved by green CI. No new authority or scheduler will be added.
- Frozen changed paths saved to the job directory's `frozen-paths.txt`; local
  merge-group classification saved as `scope.json`. Remote producer logs were
  not supplied: original integration-scope root cause remains UNRESOLVED.

## Executed validation checkpoint

Logs below are in `/home/dev/maistro/jobs/f540f1ccf39e4a9ea021278b915d75b7`.

- `uv run ruff check .` and `uv run ruff format --check .`: PASS.
- Focused audit/foundation/commit-acknowledgement backend pytest: **68 passed**
  (`repair-backend.log`). Million-row migration 87.964s; initialized first page
  0.0012s, scoped page 0.0015s; maximum measured query VM work <2,800 instructions.
- Isolated Compose project `auto358-f540`, ports reset only: API producer
  **10 passed, 13 existing skips** (`repair-api.log`). Host deployment untouched.
- Built every package using `uv build`, then ran `uv run python
  scripts/verify-wheel-imports.py --dist "$job/wheels" --python 3.12`:
  **PASS**, bare and widest-extra checks (`repair-wheel-build.log`,
  `repair-wheel-imports.log`). Existing announced Conductor/meta-package import
  exclusions are not suppressed or claimed as imports tested.
- Inventory rerun with registered backend and E2E paths: **PASS, 3,210 / 23**
  (`repair-inventory.log`). No tests added or removed.
- Full isolated Chromium producer: **FAIL** (`repair-ui.log`), including
  Design Studio selectors and PM workspace-creation timeouts. This is actual
  current local evidence, not a diagnosis of the unsupplied remote failure.
  The broad UI gate cannot be reported green. Wheel verification and inventory
  collection ran concurrently; resource contention is possible but unproven.
  Do not increase timeouts, delete assertions or alter unrelated product paths.

- Full Chromium totals: **10 failed, 109 passed, 6 did not run** in 11 minutes.
  Failing surfaces: Design Studio keyboard/navigation (2), optimistic mutations
  (3), PM feedback/optimizer workspace creation (2), template skeleton (1),
  workspace scope (1), workspace toolbar (1). Their detailed failures are in
  `repair-ui.log:301-654`; browser artifacts copied to `browser-results/`
  before the test container was recreated. No unrelated files were edited.
- Focused production-route Chromium audit run: **5 passed** in 46.3s
  (`repair-audit-ui.log`). Covers live authenticated audit read, both stale
  response races, short-page continuation, and eight-page virtualization.
  This narrow success does **not** supersede the full producer failure.
- Named integration-scope gate: **FAIL**, UI producer failure plus missing
  docker-build (`repair-integration.log`). The full docker-build job includes
  engine/PostgreSQL smoke and RSI canary checks; a Conductor image build is
  not equivalent. Full docker-build remains **UNVERIFIED**, not success.
- Stopped only project `auto358-f540`; retained container data and captured
  logs. No host deployment, branch, ledger, grant or production code changed.

## Reproduction commands

```sh
job=/home/dev/maistro/jobs/f540f1ccf39e4a9ea021278b915d75b7
uv run python scripts/check-vulture-baseline.py packages/*/src \
  --min-confidence 60 --exclude '*/third_party/*'
uv run pytest packages/hive-conductor/backend/tests/test_audit_pagination.py \
  packages/hive-conductor/backend/tests/test_audit_routes.py \
  packages/hive-conductor/backend/tests/test_foundation.py \
  packages/hive-conductor/backend/tests/test_state_commit_acknowledgement.py -x -q -s
uv run python scripts/check-suite-inventory.py \
  --suite packages/hive-conductor/backend/tests \
  --suite packages/hive-conductor/tests/e2e
DOCKER_HOST=unix:///var/run/docker.sock CI=true docker compose \
  -p auto358-f540 -f packages/hive-conductor/docker-compose.test.yml \
  -f "$job/compose-isolated.yml" --profile test up --build \
  --abort-on-container-exit --exit-code-from api-tests api-tests
# Full UI: same command with both api-tests arguments replaced by e2e-tests.
# Audit-only: use compose-audit-only.yml, --no-build and e2e-tests instead.
uv run python scripts/check-integration-scope.py --event-name merge_group \
  --scope-json "$(< "$job/scope.json")" \
  --result hive-conductor-e2e=success --result hive-conductor-e2e-ui=failure \
  --result wheel-imports=success
```

The scope-gate inputs above describe only the local producers actually run,
not remote check runs. The driver still needs a fresh isolated API target and
registered E2E inventory recipe; those job settings are outside this repository.

## Acceptance disposition

| Criterion | Executed evidence / gap |
| --- | --- |
| Bounded cursor, stable ordering, maximum size | PASS: focused backend suite, default 50 / maximum 200, timestamp ties and continuation. |
| Scope/filter before DB pagination | PASS for existing Conductor SQLite seam: SQL scope/alias/filter parity and VM-work tests; existing authenticated principal remains authority. PostgreSQL audit equivalent UNVERIFIED. |
| Incremental loading and virtualization | PASS: five focused Chromium tests, including short-page continuation and eight-page window. High-volume responses mocked; live authenticated route exercised separately. |
| Filters/export/retention without browser corpus | Filters/export pass: stale-response tests, scoped capped NDJSON, server download URL. Retention NOT MET: `backend/services/audit_query.py:79` declares no purge operation. Policy reconciliation with #325 remains required. |
| Measured representative large query/index strategy | PASS for one million SQLite rows and 162 scope/filter/cursor combinations: timings above, <2,800 VM instructions. Index write/disk amplification and PostgreSQL envelope UNVERIFIED. |
| Concurrent inserts, stability, isolation, max limit, empty, million rows | PASS: 68 backend tests, including threaded acknowledged durable writes and million-row envelope. |
| Initial page independent of total size | Only initialized durable reads proven. NOT MET unqualified: `backend/services/audit_query.py:402-403` copies/sorts the memory corpus on each page; startup migration/hydration also corpus-sized. |
| Browser memory/DOM bounded | Row-count bound proven: at most 500 retained entries and 30 mounted rows. Byte-level heap and million-row browser scroll soak UNVERIFIED. |

## Final handoff

**NEEDS-REPAIR.** Only this evidence note changed; no tests added, no cosmetic
production fix, no gate weakened, and no unjustified ledger amendment. The
supplied previous validation-budget block is not cleared. Original remote
integration failure remains UNRESOLVED; current local UI producer failures are
preserved rather than rewritten as success.

Next: assign the concrete UI producer failures to their owners, obtain remote
producer evidence, run the complete docker-build producer, and reconcile/fix
retention and memory-mode acceptance. Do not repeatedly rerun the foreign
`localhost:8101` deployment expecting harness credentials to start working.

Progress: {checked: 1, done: 0, skipped: 0, errors: 1, next: unresolved CI
producer failures and audit retention/memory-mode acceptance}.

