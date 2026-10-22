---
inventory-delta:
  packages/maistro-design/tests: +39
---
# Versioned creative artifact state inventory

Issue #780 adds `packages/maistro-design/tests/test_artifact_versions.py`
(+39 collected node IDs, all marked `contract: behavioral` and traced to
SPEC-092826-a780/AC-1..AC-9; +20 in the initial round, +2 store-promise tests,
+17 guard/edge-contract tests in the diff-coverage round below). The tests
drive the real
`PgArtifactVersionStore` against SQLite file databases, including
close-and-reopen cycles, because the criteria are about what survives:
prior AI/human versions with distinct provenance, locks, guidance, and
per-branch control state across a refresh/reconnect or process restart.
No existing node IDs were removed or renamed.

## Migration renumbering during the origin/develop sync (this merge)

The branch originally introduced the versioned-artifact schema as alembic
revision `047`; `origin/develop` independently took `047` for
`capability_binding_revocations` (#1133). In the develop-sync merge the
branch's migration is renumbered to `048` (`down_revision = "047"`). The
`through 047` mentions below are historical evidence records gathered while
the migration carried that number; the schema itself is unchanged.

## CI-repair round: integration-scope sync (job dc11871447764a0cab62209a2625503d,
final head a5ef4560c)

The merge-queue `integration-scope` gate failed with an orphan-rebuild
"corrupt patch at line 527031": the branch's diff was computed against a
develop base that had moved 31 commits ahead. Repair: salvaged the four
uncommitted files left by the provider-timeout job (SPEC front-matter refs,
AC markers, migration-chain tests), then merged `origin/develop` twice
(77b2dd94c, a5ef4560c), renumbering this branch's migration to `048` in the
resolution. Executed evidence at the final head:

- `ci_base_revision.py` / `ci_merge_group_scope.py` /
  `check-integration-scope.py` merge-group sequence → exit 0, scope
  `{docker_build, postgres, wheel_imports}` required.
- Orphan rebuild simulation: `git diff origin/develop...HEAD` (3429-line
  patch) applied cleanly onto a fresh `origin/develop` checkout
  (`git apply --check` and apply both succeeded).
- `alembic` ScriptDirectory heads → `['048']` (single linear head).
- `pytest packages/maistro-design/tests` → 373 passed; `pytest tests/migrations`
  → 19 passed, 81 skipped; design suite inventory → ok.
- `ruff check .` / `ruff format --check .` → clean; `uv sync --locked` → ok.
- `check-vulture-baseline` → exit 0; `tools/lint_lifecycle.py` → pass;
  `maistro_registry.cli lint . --strict` → 416 files clean;
  `check-execution-lifecycles` → 19/19; `check-doc-links` → ok;
  `check-durable-table-inventory` → 81 tables declared.

## Independent verification record (job e1159b024b074099b9264c209f586f98, head d3f3aa468419)

Executed by the verifier (not trusted from the implement phase):

- `uv run pytest packages/maistro-design/tests/test_artifact_versions.py -x -q` → 20 passed.
- `uv run pytest packages/maistro-design/tests -q` → 371 passed (matches recorded inventory).
- `uv run ruff check .` → clean. `scripts/check-suite-inventory.py`,
  `scripts/check-execution-lifecycles.py` (19 classified → 19 discovered),
  `scripts/check-durable-table-inventory.py` (74 tables), `scripts/check-doc-links.py`,
  `scripts/check-vulture-baseline.py` → all pass at this head.
- Real-Postgres smoke (pgvector:pg17, `alembic upgrade head` through 047, then
  `PgArtifactVersionStore` end-to-end): three-version provenance chain, version-lock
  refusal + explicit release, decision-digest constraint, durable guidance via
  `agent_inputs`, branch-control projection of canonical `RunStatus`, and
  first-writer-wins via the real UNIQUE constraint — all passed.

Scope notes (documented, not hidden): browser-refresh projection and a
product-surface E2E are not reachable at this base (#775/#777 not landed);
SPEC-092826-a780 records a Reconciliation paragraph — forward-compatible
`brief_ref`/decision-digest inputs, not a deferral record — and AC-9's
mixed-control scenario is proven at store/service level
(`TestOneMixedControlProject`). Backend durability and the mixed-control
scenario are proven at store/service level.

### Finding (confirmed, needs repair)

`CreativeArtifactService.record_generation` (packages/maistro-design/src/maistro_design/versions.py)
never calls `_assert_not_locked`, unlike every other write path. Demonstrated
against real Postgres: a decision lock placed on a not-yet-started lineage does
not stop the first `record_generation` from landing v1 citing that decision with
a contradicting digest — no `ArtifactLockConflict`, while an identical manual
edit or refinement is refused. Version/region/branch locks are structurally
unreachable for a fresh lineage (they require an existing version/tip), so the
window is decision locks only, but it contradicts the spec Goals bullet "Locks
(version/region/decision/branch) are checked before every write" and the module
docstring "Every write checks the branch's active locks first".

## Repair record (job 4d7e250f72524359a0de4ce9f8c4727f, head 615bb73da7d0)

- The confirmed `record_generation` gap above is **fixed** (commit 615bb73da:
  the write path now checks branch/decision locks and refuses with
  `ArtifactLockConflict`). Re-proven live against real Postgres
  (pgvector:pg17, `alembic upgrade head` through 047): a decision lock on a
  not-yet-started lineage refuses the first `record_generation` citing that
  decision with a contradicting digest. A fresh 14-check live-PG smoke of
  AC-1..AC-9 (three-version provenance chain, version-lock refusal + release,
  decision-digest both directions, guidance durability + `agent_inputs`,
  fork, reopen projection, branch-lock conflict, shared export, mixed-control)
  passed 14/14 on this head.
- exact-debt-ledger: the production-only Vulture scan (`packages/*/src`) saw
  12 new identities in `versions.py` (`ControlMode.COLLABORATIVE` + 11
  `CreativeArtifactService` methods). All 12 are live contract surface —
  exercised by this file's 22 tests and waiting on #774/#777 consumers — so
  per the repo's `_vulture_*_usage` TYPE_CHECKING precedent (e1f16ddae,
  632c24c78: banking alone cannot pass the trusted-base ratchet and would
  misrecord contract surface as dead debt), a documented non-executing
  reference block keeps them visible to the scan. Bare-name matching marks
  `maistro-core` `memory/learnings/approval.py::reject` used as collateral,
  so that one reviewed ledger identity was pruned from
  `quality/vulture-baseline.json` (1402 → 1401). The gate exits 0:
  1402 reviewed identities -> 1401 findings, 0 unclassified.
- Correction to an earlier draft of this bullet: it claimed the
  `IntegrityError` translation below was "pre-existing at the merge base,
  out of repair scope". That was wrong — `version_store.py` does not exist
  at a3f6b3c (or at 9fb68e47); the file and the defect were both introduced
  by this PR's own commit 4f4f8ccc0, so the defect was in repair scope. It
  is fixed in the round recorded below.
- Re-validated on this head: `uv run ruff check .`, `uv run ruff format
  --check .`, `uv run pytest packages/maistro-design/tests -q` (371 passed),
  `check-durable-table-inventory.py` (74 tables),
  `check-execution-lifecycles.py`, `check-ratchet-provenance.py`,
  `check-shipped-surface-truth.py` — all pass.

## Repair record (job e138177b676a426ab86e3d08bb8dfc66, head bbb9b58999…)

- `PgArtifactVersionStore.append_version` no longer translates *every*
  `IntegrityError` to `ArtifactVersionExistsError`. The handler now reads the
  driver's constraint code (`pgcode` on asyncpg, `sqlite_errorname` on
  sqlite3, both normalized to SQLSTATE): a real unique violation (23505) still
  raises `ArtifactVersionExistsError` (first-writer-wins race backstop), and
  any other integrity failure — e.g. the `design_artifact_versions_project_id_fkey`
  violation for a missing parent `design_projects` row (23503) — raises
  `ArtifactVersionError` naming the constraint class, never a false "already
  exists".
- Two tests added to `TestTheStoreKeepsItsPromises` (the +2 above): the UNIQUE
  hit a pre-check misses (org is not in the key) still reads as the
  supersession conflict, and an orphan-project FK insert (SQLite FK enabled,
  parent table + seeded row) raises `ArtifactVersionError` with SQLSTATE 23503
  in the message, is not `ArtifactVersionExistsError`, and the same version
  lands once the parent row exists.
- Re-proven live against real Postgres (pgvector:pg17, `alembic upgrade head`
  through 047), probe 3/3: orphan project → `ArtifactVersionError ... (SQLSTATE
  23503)`; duplicate slot via pre-check → `ArtifactVersionExistsError`; UNIQUE
  race backstop through the except branch → `ArtifactVersionExistsError`.
- Prior-round note fixes: the "out of repair scope" claim is corrected (see
  above), and the scope note no longer claims SPEC-092826 records a deferral —
  the spec records a Reconciliation paragraph; the product-surface E2E remains
  out of reach at this base, and AC-9 stands proven at store/service level.
- Validated on this head: `uv run ruff check .`, `uv run ruff format --check
  .`, `uv run pytest packages/maistro-design/tests -q` (373 passed),
  `check-suite-inventory.py`, `check-vulture-baseline.py` (production-only
  scan, gate green), `check-durable-table-inventory.py`,
  `check-execution-lifecycles.py`.

## Verification record (job f8c74827e9b74e429ce73c1e2de52b7c, head 1ccf5b689bfe)

Independent re-verification of the e138 repair claims — nothing trusted from
the prior round, all re-executed:

- `uv run pytest packages/maistro-design/tests -q` → 373 passed; the nine
  AC test classes (`TestOneArtifactThreeVersionsWithProvenance`,
  `TestLockingAnAcceptedArtifact`, `TestLockingASharedDecision`,
  `TestGuidanceIsDurableProjectInput`, `TestForkWithoutErasing`,
  `TestControlAndLocksSurviveRestart`, `TestConflictsAreSurfacedNeverSilent`,
  `TestManualAndAgentShareOneRepresentation`, `TestOneMixedControlProject`)
  re-run explicitly → 15 passed.
- `uv run ruff check .` and `uv run ruff format --check .` → clean.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → exit 0, 1402 reviewed →
  1401 findings, 0 unbanked (no ledger amendment required). Plus
  `check-durable-table-inventory.py` (74 tables),
  `check-execution-lifecycles.py` (19), `check-doc-links.py`,
  `check-suite-inventory.py` (14 suites) → all pass.
- Fresh live-PG probe (new pgvector:pg17 container, `alembic upgrade head`
  through 047) against `PgArtifactVersionStore.append_version` at this head,
  3/3: orphan `design_projects` id → `ArtifactVersionError … (SQLSTATE
  23503)`, not `ArtifactVersionExistsError`; UNIQUE hit the pre-check misses
  (different org, same `(project, lineage, version)` slot) →
  `ArtifactVersionExistsError` through the except branch; duplicate slot via
  pre-check → `ArtifactVersionExistsError`.
- Git evidence re-checked: `git cat-file -e` → `version_store.py` absent at
  a3f6b3c and 9fb68e47, introduced by 4f4f8ccc0 (so the repair-scope
  correction above is right); SPEC-092826-a780 line 64 is a Reconciliation
  paragraph (forward-compatible `brief_ref`/decision-digest), not a deferral
  record — matching the corrected scope note.
- Still out of reach at this base, unchanged: product-surface E2E and
  browser-refresh projection (#774/#775/#777 not landed); AC-9 remains
  proven at store/service level only.

## Develop-sync + re-verification record (job eee7b58cdaaa4b7d8bd78209ab54bdab, merge head 3451d65e0)

Prior round timed out before running checks; nothing was trusted from it.
`origin/develop` (0fb3dc69e: #1671 state-commit acknowledgement, #1662 SIGTERM
drain, #1665 installer-function gate) was merged into `auto-780` — clean merge,
and `git diff 0abc50460..3451d65e0 -- <lane surfaces>` is empty, so none of this
lane's files changed in the sync. Everything below re-executed at the merged
head:

- `uv run pytest packages/maistro-design/tests -q` → 373 passed; the nine AC
  classes re-run explicitly → 15 passed.
- `uv run ruff check .` and `uv run ruff format --check .` → clean.
- `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` → exit 0 against base 0fb3dc69ed95, 1402 reviewed → 1401
  findings, 0 unbanked (no ledger amendment needed this round).
  `check-durable-table-inventory.py`, `check-execution-lifecycles.py`,
  `check-doc-links.py`, `check-suite-inventory.py`,
  `check-ratchet-provenance.py`, `check-shipped-surface-truth.py` → all pass.
- Develop-side suites sanity-checked in the merged tree:
  `tests/test_check_install_functions.py` → 22 passed;
  `packages/maistro-server/tests/test_sigterm_shutdown.py` → 3 passed.
- Fresh live-PG probe (pgvector:pg17 on 127.0.0.1:15780, `alembic upgrade
  head` through 047, asyncpg session factory) against
  `PgArtifactVersionStore.append_version`, 3/3 at the merged head: orphan
  `design_projects` id → `ArtifactVersionError … (SQLSTATE 23503)`, not
  `ArtifactVersionExistsError`; duplicate slot via pre-check →
  `ArtifactVersionExistsError`; cross-org UNIQUE hit the pre-check misses →
  `ArtifactVersionExistsError` through the except branch.
- Scope, unchanged and stated plainly: product-surface E2E and browser-refresh
  projection remain out of reach at this base (#774/#775/#777 not landed);
  AC-9 stands proven at store/service level (`TestOneMixedControlProject`).

## CI-repair round: Gate C (canonical clean install) local proof (job e8bc3d9b, merge head f8e7402f)

The merge-queue evaluation reported `Gate C — canonical clean install` as
`in_progress` — the gate had not completed when the evaluation sampled it, so
this round re-proved the whole gate contract locally at the merged head
instead of trusting a stale/absent verdict. A prior interrupted round left an
untracked `gatec-compose.override-tmp.yml` (auto780c-`*` container renames and
shifted host ports) used to coexist with a live canonical
`project-maistro` stack on the shared rootless daemon; that file is salvage,
backed up to the job directory.

- Clean state proven: `.env`/`.maistro-install` removed (prior Oct 2 copies
  backed up first), `docker compose -p auto-780 down -v` no-op, then the
  documented path `./install.sh --skip-wizard --no-cli --no-open` with
  `MAISTRO_SKIP_WIZARD=1 MAISTRO_INSTALL_CLI=0 MAISTRO_OPEN_BROWSER=0
  MAISTRO_START_STACK=1 MAISTRO_PORT=18000 HIVE_PORT=18101` and
  `MAISTRO_INSTALL_PLAN_DIR=/tmp/gatec-auto780-plan`.
- Override mechanism: a `compose.override.yml` placed in the plan dir is
  appended by `install.sh`'s own `compose_files()` hook. The salvage override
  failed its first attempt with `Bind for 127.0.0.1:5433 failed` because
  compose **merges** `ports` sequences across files, so the base file's
  hardcoded `5433`/`3100` bindings survived alongside the shifted ones; the
  plan-dir copy now tags the postgres/litellm/langfuse `ports:` blocks with
  compose's `!override` merge tag, and `docker compose config` shows exactly
  one published port per service (18000/18101/14000/13100/15433).
- `install.sh` exit 0 (source-build delivery; engine + hive images built).
- Gate C assertions, all green at the first probe:
  `/health/live` (engine), `/health/ready` (engine), `/health/ready`
  (conductor), `SELECT version_num FROM alembic_version` → `051` matching
  `^[0-9a-z_]+$` (the branch chain head, so 049 design_artifact_versions,
  050 creative_briefs, and the renumbered 051 eval migration all applied on a
  fresh cluster), re-curl of both ready endpoints, and the engine image
  digest recorded to the gate's candidate artifact format.
- Teardown: `docker compose -p auto-780 down -v --remove-orphans`; the
  canonical stack on the same daemon was untouched throughout.
- Gate battery re-run at this head: `check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → exit 0 (1368 reviewed →
  1367 findings, 0 unbanked; no ledger amendment needed);
  `ruff check .` / `ruff format --check .` clean;
  `packages/maistro-design/tests` → 483 passed +1 skipped, AC classes
  (`test_artifact_versions.py` + `test_creative_brief.py`) → 68 passed;
  `tests/migrations` against an isolated pgvector:pg18 on 127.0.0.1:15436 →
  100 passed; `check-suite-inventory.py --suite packages/maistro-design/tests`
  → 484 collected, inventory matches.

## Independent re-verification + Gate C re-proof at the recorded head (job
## 3891a5fa7f4f4f7d9c07d35e72e3bba8, head 6e24cc7ad05b)

Nothing from the rounds above was trusted: every check re-executed at
6e24cc7ad (the docs-only child of merge head f8e7402f — `git diff
f8e7402f..HEAD` touches only this note, so install inputs are bit-identical).
The prior round's salvage (`gatec-compose.override-tmp.yml`, still untracked
in the worktree by agreement, plus the `.env`/`.maistro-install` left by the
f8e7402f run) was backed up to the job plan dir
(`/tmp/gatec-auto780-plan-3891/prior-state/`) before Gate C's own clean-state
step removed them.

- Battery: `ruff check .` / `ruff format --check .` clean;
  `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` exit 0 (1368 reviewed → 1367 findings, 0 unbanked, no
  ledger amendment); `pytest packages/maistro-design/tests -q` → 483 passed
  +1 skipped; AC classes (`test_artifact_versions.py` + `test_creative_brief.py`)
  → 68 passed; `pytest tests/migrations` (no DB) → 19 passed, 81 skipped;
  `alembic heads` → single head `051`; `check-suite-inventory.py --suite
  packages/maistro-design/tests` → ok (484).
- Gate C re-run at this head through the documented path, coexisting with the
  live canonical `project-maistro` stack on the shared daemon: clean starting
  state proven (`.env`/`.maistro-install` absent after backup), plan-dir
  `compose.override.yml` = salvage file with `!override` on all five
  `ports:` blocks, `docker compose config` shows exactly one published port
  per service (18000/18101/14000/13100/15433) and auto780c-`*` container
  names, project `auto-780`. `install.sh --skip-wizard --no-cli --no-open`
  → exit 0; `/health/live`, engine `/health/ready`, conductor `/health/ready`
  all green; `SELECT version_num FROM alembic_version` → `051` matching
  `^[0-9a-z_]+$`; engine digest `sha256:2a4d500e7f3806e1…` recorded;
  `down -v --remove-orphans` removed every auto-780 resource; the canonical
  stack stayed healthy throughout.
- Environment finding, recorded because it produced noisy output: the shared
  rootless docker daemon restarted twice during this round (02:35:21,
  02:40:21 CDT, while another party actively replaced canonical-stack
  containers). Two full `pytest tests/migrations` runs against a live
  pgvector:pg18 died mid-suite with asyncpg `CancelledError` connection
  timeouts at exactly those restarts; the container is killed and `--rm`
  removes it. With the daemon stable, the lane's migration surfaces re-ran
  green against live PG18 (`test_capability_invocation_effect_index_migration.py`
  + `test_migration_chain.py` → 15 passed in 51.5s), and Gate C itself proved
  the whole 001→051 chain applies on a fresh cluster. The full-suite live run
  (100 tests) remains proven from the f8e7402f round; this round's partial
  live-PG evidence is 15/15 lane surfaces + the fresh-cluster chain, not the
  full 100.

## Diff-coverage repair round (job 01f40729a912494f9f4316c24f14d6bb, head 20f897a24 + this round's commit)

The merge-queue quality gate failed on per-file diff coverage: of the changed
lines in the three measured files, `__init__.py` scored 50% lines (the
`PgArtifactVersionStore` lazy-re-export branch was never imported through the
package), `version_store.py` 61.1% branch arcs and `versions.py` 75.0% branch
arcs against the 90/80 floors. Every flagged arc was a real, reachable
contract — none was dead code. This round adds 17 tests that exercise them:

- The generation-time lock sweep (`record_generation`): a branch lock placed
  before any work exists (only `store.add_lock` can create one — `lock_branch`
  requires a tip) blocks first generation; a decision lock placed before any
  work refuses a first generation citing a contradicting digest, and honours
  the locked digest or no citation at all; a stale region row does not block
  first generation; a decision lock that names no decision blocks nothing
  (`_assert_not_locked` path); `lock_branch` on an empty lineage names the
  problem; `covers_address` governance is by address and scope, including the
  non-region and addressless locks no service path can produce.
- Store edges: an accepted version cannot return to draft; releasing an
  unknown lock and superseding unknown guidance are errors; `active_guidance`
  scopes project-wide vs per-branch; `set_control` updates the durable row in
  place; a manual edit must name its author.
- Driver-independent row helpers (`_as_datetime`, `_as_json_dict`,
  `_integrity_code`): datetime/ISO-string timestamps, empty/JSON-text/dict
  payloads, and the asyncpg-`pgcode` / sqlite3-`sqlite_errorname` → SQLSTATE
  mapping including the unknown and cause-less fall-throughs; plus the
  package re-export identity for `PgArtifactVersionStore`.

Executed evidence at this round's head:

- `uv run pytest packages/maistro-design/tests -q` → 540 passed, 1 skipped
  (39 in `test_artifact_versions.py`, was 22 test functions / 524 suite IDs).
- `coverage run --branch --source=packages/maistro-design/src/maistro_design`
  over the design suite, appended with the maistro-core producers from
  `quality.yml`'s coverage-unit job (full core suite) — then
  `scripts/check-diff-coverage.py coverage.xml --base 15157c6f2` → exit 0,
  "every measured file this change touches is at or above 90% lines / 80%
  branch arcs". Before the repair the same gate printed `FAIL: 3 file(s)
  below the diff-coverage floor` with exactly the numbers above.
- `pytest tests/migrations` against a real pgvector:pg18
  (`MAISTRO_TEST_DATABASE_URL` set) → 15/15 passed; `alembic upgrade head`
  on a freshly created database applies 049 (#780) → 050 → 051 cleanly.
- `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` → exit 0 (1359 reviewed → 1358 findings, 0 unclassified;
  no ledger amendment needed — the new tests are test code, outside the scan).
- `ruff check .` / `ruff format --check .` clean; `check-suite-inventory.py`
  ok with this note's updated delta.

Re-executed independently by repair job 0d6c2bbc2e1b (same working tree,
before committing), with identical outcomes for every runnable item: design
suite 540 passed / 1 skipped (39 collected in `test_artifact_versions.py`);
core producer 11,345 passed with only the `unreachable_server` environment
failure described below; combined core+design coverage at `--base 15157c6f2`
→ `ok: every measured file this change touches is at or above 90% lines /
80% branch arcs` (4 changed measured files, 6 exempt by declaration);
vulture exit 0 (1359 → 1358); ruff, `check-suite-inventory.py`,
`check-durable-table-inventory.py` and `check-ratchet-provenance.py` all
exit 0. The raw-socket repro below was re-confirmed (connect to
127.0.0.1:1 hangs past 5s instead of ECONNREFUSED). The live-PG migration
leg was NOT re-run in that job — the Docker daemon was unreachable — and
remains evidenced by the `pytest tests/migrations` 15/15 run above plus the
earlier rounds' fresh-cluster chain; the pending diff touches neither
migrations nor their tests.

Environment note, for the next reader: on this WSL host a TCP connect to
127.0.0.1:1 is silently dropped (rootless-docker/WSL networking), so
`test_an_unreachable_server_is_an_error_not_a_fallback` spends ~60s in asyncpg
retries and CI's `--timeout=30` kills it when run under load here. A raw
socket connect reproduces the drop on any branch, so the failure is a host
networking artifact, not a candidate regression; the test passes on CI
runners (instant ECONNREFUSED) and passes locally without the timeout flag.
