# L337 round 8 — CI-log forensics close the last open question (2026-10-24)

Head entering: `ec2a26981` (round-7 handoff). Head leaving: this commit. Base: `db4d3eb09`.

Round 2 left one item explicitly un-reproduced and handed it forward: *"test job:
15× `RuntimeError('Event loop is closed')` in CI … next round should read the fresh
CI log for the failing step names before changing anything."* This round did that.

## What the actual CI logs say (read via `gh api`, job logs fetched in full)

**`test` job (run 40081189942, job 120834925096, at `976ad2f658c9`):**

- Every pytest step PASSED. The only failing step is **"Generated API types match
  the backend's OpenAPI document (#1048)"**: `git diff --exit-code -- …/types.gen.ts`
  showed the regenerated file gaining `"/v1/dag-metrics/retention"` +
  `retention_v1_dag_metrics_retention_get` (`f742ab401..8e4da0be8`) — the branch's
  retention route was never written back into the committed blob.
- The `RuntimeError('Event loop is closed')` lines are
  **`PytestUnhandledThreadExceptionWarning`s, not failures**: an `aiosqlite`
  `_connection_worker_thread` outliving a closed loop, attributed to
  `packages/maistro-server/tests/api/test_user_model_api.py::
  test_correct_mark_private_and_forget_carry_provenance` inside the PASSED
  maistro-server run (643 passed). The runner annotates any stderr traceback as
  `##[error]`, which is what every earlier excerpt actually captured. No action.

**Repaired by `aef3245a0`** (ancestor of this head, committed after that CI run):
types.gen.ts regenerated with CI's exact commands (byte-matches CI's blob), pypdf
bumped for the Container-scan trivy findings, image-lock reconciliation taught to
accept forked lock entries.

**`Container scan + SBOM + cosign` job (run 40081190169, job 120834925592):** the
only `##[error]` is trivy `--exit-code 1` on pypdf 6.21.1 (CVE-2026-115572 /
115580 / 115585, HIGH, fixed 6.21.2) — the exact finding `aef3245a0` cleared;
round-3 proved trivy exit 0 on the rebuilt images, rounds 6–7 confirmed the pin
unchanged and the merge delta free of image inputs.

## Re-proofs executed at this head (`ec2a26981`)

- Types-drift step, CI-exact: `uv run python scripts/dump-hive-openapi.py`
  (241 paths / 147 schemas — identical to CI's dump) → `npm --prefix
  packages/hive-conductor/frontend run gen:api` → `git diff --exit-code` on
  types.gen.ts: **clean, zero diff**.
- `uv run pytest packages/hive-conductor/backend/tests -q` → **4008 passed,
  25 skipped** (4033 = recorded inventory).
- `uv run python scripts/check-suite-inventory.py --suite
  packages/hive-conductor/backend/tests` → ok, 4033 identities match baseline.
- #337 acceptance files (dag history durability, durable node metrics, feedback
  route, profile durability, dag-run store/scope, thumbs protocol): **239 passed**.
- Verifier's own battery at this head: ruff check ✓, ruff format ✓, targeted
  pytest 113 passed, suite inventory ok (job `9974baf4…` check-*.log).

Acceptance criteria re-checked against source at this head: durable owners wired
in `foundation.py::_init_state` (dag_runs rehydrated before `configure_dag_run_store`,
durable metrics projection, persisted profiles/settings/registration policy);
`routes/feedback.py::_execution_identity` correlates every accepted thumb to
Run/NodeRun/Attempt (404 foreign/missing, 409 projection-only, 503 spine down);
`set_outcome_store` has the production caller `engine._wire_outcome_store` with a
failure unwind; retention/scope/pagination/deletion explicit on
`/v1/dag-runs` + `/v1/dag-metrics` (clamped limits, `require_actor_id`, documented
eviction, no ad-hoc delete); SPEC-083026-2601/2642 carry the tests front-matter.

## Residual

- Hosted CI still not observed at `ec2a26981` (no-push lane). Every failing step
  from the last observed run is fixed in-tree and re-proven locally with CI's
  exact commands; the job's post-failure skipped steps carry rounds 6–7 proofs.
- The round-6 one-time `test_restore_oracle_characterization` transient in the
  combined single-process run remains documented-not-root-caused (green on
  identical-tree rerun and in isolation; CI passed the same content).
