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
