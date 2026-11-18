# PR #2372 — actions/download-artifact v7 → v8 verification evidence

Lane CR2372, head `d5fb0d44377d` (dependabot commit), merge-base `157c3f615b`,
develop base `d0e8e235a896`. Verified 2026-11-17.

## Scope of the change

`git diff 157c3f615b..HEAD` = exactly one commit touching
`.github/workflows/mutation-nightly.yml`: three `actions/download-artifact@v7`
→ `@v8` bumps (lines 100, 180, 184). No other files. The 128-file diff against
`d0e8e235a896` is develop history behind the merge-base, not part of the PR.

## Acceptance evidence

1. **Inputs used are valid in v8.** Fetched the live v8 `action.yml`
   (raw.githubusercontent.com/actions/download-artifact/v8.0.2/action.yml):
   `name`, `path`, `pattern`, `merge-multiple` all exist with unchanged
   semantics; runtime is `node24`. The two breaking changes per the release
   notes (ESM migration; digest-mismatch defaulting to `error`) are
   caller-transparent here — the workflow uploads via
   `actions/upload-artifact@v7` (zip-backed), so v8's Content-Type check still
   decompresses normally. `skip-decompress`/`digest-mismatch` overrides are not
   needed.
2. **Repo-wide consistency.** After the bump every
   `actions/download-artifact` reference in tracked workflows is `@v8`
   (mutation-nightly.yml ×3; release.yml ×4 and quality.yml ×1 were already
   v8). All `upload-artifact` pins remain `@v7`. No `@v7` download refs remain.
3. **Workflow lint gate (CI-exact).** actionlint v1.7.7 + shellcheck 0.10.0,
   the exact ci.yml invocation (`/tmp/actionlint -no-color -oneline -shellcheck`),
   exits 0 over the whole tree.
4. **YAML validity.** All 31 `.github/workflows/*.yml` parse with
   `yaml.safe_load`.
5. **Python gates (driver checks re-run locally):** `uv sync --locked
   --extra dev` (exit 0), `uv run ruff check .` (exit 0), `uv run ruff format
   --check .` (3562 files already formatted).
6. **Gates that parse workflows / assert on these actions:**
   `pytest tests/test_check_workflow_inventory.py` 53 passed;
   `tests/test_check_license_inventory.py` +
   `tests/test_check_workflow_inventory.py` + `tests/test_check_compliance.py`
   228 passed (the license-inventory assertion is version-agnostic:
   `startswith("actions/download-artifact@")`);
   `tests/test_mutation_targets.py` 35 passed.

## Attribution of previously RED gates

The RED gates listed in the lane brief (docker-build, docker-rebuild-compare,
postgres/pg, MinIO, hive-conductor e2e/compose, durable-events,
integration-scope, compliance registry, cross-product-parity,
lint-and-type-check) exercise services and packages this PR cannot affect: its
only file is a workflow that runs "on a schedule or on demand; never on pull
requests" (mutation-nightly.yml header). They are infra/environment failures on
the develop tip the PR merges into, not regressions introduced by the version
bump. Everything locally runnable about this change is green (points 3–6).

No code change was required; this note is the only artifact of the repair pass.

## Round 2 (2026-11-18, head `34c0da9fa488`): gates-ran pending — root cause found and repaired

The prior "RED gates attributed to the develop tip" attribution was wrong for
the actual merge-queue blocker. Captured evidence at this head (dispatch
context, 2026-11-18T01:47:35Z): **all 78 check-runs are success or
skipped-for-scope** — including docker-build, postgres pg17/pg18, MinIO,
compose-durability, integration-scope, lint-and-type-check, compliance
registry, cross-product-parity. The only non-success is the repo-custom
`gates-ran` commit status: 10 publisher runs, all `pending` — "Required
execution evidence is still arriving" (runs 44065183567…44071220285,
2026-11-17T10:29–11:08Z).

CI-exact replay (`scripts/check-gates-ran.py --check-runs <captured 78>
--require-complete --base-branch develop --event-name pull_request
--changed-files <measured envelope ['.github/workflows/mutation-nightly.yml']>):
exit 2 — `not present yet (1): Mutation gate (changed critical lines)`.
Appending one synthetic successful mutation-gate check-run to the same payload
flips the replay to `ok: all 72 required check(s) ran on this head` (exit 0).
The absent producer is the sole blocker; the service gates are not involved.

Root cause: `mutation.yml`'s `pull_request.paths` filter never named
`.github/workflows/mutation-nightly.yml`, so a PR touching only that file does
not trigger the mutation workflow, while `check-required-checks.py` keeps its
row in the required evidence set on every PR — exactly the #2120 class
(`b6dcf485bb`), whose fix added `quality/image-pins.json` but missed the
nightly sibling. Repair (additive, follows the reviewed precedent; no gate
weakened): `.github/workflows/mutation-nightly.yml` joins the paths list, so
this PR class produces real zero-overlap mutation evidence instead of
permanent absence.

Round-2 validation: evaluator replays above; `tests/test_mutation_targets.py`
36 passed (new `TestNightlyWorkflowEditsReachTheGate` pin parses the YAML and
fails on the pre-fix workflow content — regression demonstrated, exit 1 on
HEAD's file); `tests/test_check_gates_ran.py`
+ `tests/test_gates_ran_publisher_contract.py`
+ `tests/test_gates_ran_merge_group_scope.py` + `tests/test_mutation_pr_gate.py`
119 passed; `check-required-checks.py` / `check-workflow-inventory.py` /
`check-workflow-write-safety.py` / `check-suite-inventory.py` (delta declared
in `docs/testing/inventory-notes/cr-2372-mutation-gate-nightly-path.md`) all
exit 0; `ruff check .` and `ruff format --check .` pass. Inventory delta:
`tests/` +1 (4117 → 4118 expected).
