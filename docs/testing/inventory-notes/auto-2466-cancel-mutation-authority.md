---
inventory-delta:
  packages/hive-conductor/backend/tests: +6
---

# #2466 Conductor DAG-run cancellation clears the canonical mutation boundary

`routes/dag_runs.py::cancel_run` authorized cancellation with the **read**
seam only (`visible_run_detail`, which admits every Workspace member per
#1152) and then called `RunExecutionService.cancel_run` directly — so an
ordinary peer member could cancel another principal's live Run, and a
projection row in Workspace X delegated cancellation of a canonical Run filed
in Workspace Y. The fix resolves the canonical target and clears the shared
`RunStoreBoundary.require_run_mutation` gate (initiator or Workspace
administrator — the same rule maistro-server's `/v1/runs/{id}/cancel` answers
through, pinned there by
`test_task_workspace_scope.py::test_cancel_stays_with_the_initiator_or_an_administrator`),
then refuses a projection row whose canonical link is filed in another
Workspace (the write-side twin of `_overlay`'s attribution rule). Every
refusal is the seam's no-enumeration 404, raised before any Run/NodeRun/Attempt
transition or provider signal.

+6 collected node IDs on `packages/hive-conductor/backend/tests`
(`test_dag_run_cancel_authorization.py`), each driving the shipped route
handler against a real `InMemoryRunStore` with the provider parked mid-flight
so denial is proven against the physical path (transition spy on
`transition_run` + provider-unwind witness), not merely the response code:

1. member B reads initiating member A's Run but cannot cancel it — 404,
   word-for-word the unknown-id refusal, no durable fence attempted, provider
   never unwound, Run/NodeRun/Attempt untouched;
2. the initiator cancels through the projection id and a Workspace
   administrator (never initiated) through the direct canonical id — both
   physically stop the parked provider — while the peer is refused at every
   altitude between the two successes;
3. a projection row visible in Workspace X linked to a live Run in Workspace
   Y lets neither an X-only caller nor even the Run's own initiator cancel
   through the row, while the initiator's direct canonical id still works;
4. a nonmember outsider and an unknown id are refused identically against the
   canonical Run's own id (regression guard; already true before the fix);
5. an unstarted engine (`get_engine()` raising RuntimeError) answers the
   documented "canonical execution spine unavailable" 503 before any target
   resolution or boundary construction — the same deployment answer the
   missing run store gets, pinned because a boot failure must not be
   mistaken for a cancellation attempt (repair round: this path was the
   diff-coverage gate's uncovered `dag_runs.py` lines 119–120);
6. a member whose Workspace membership is revoked between the read and the
   cancel is refused with the one 404, word-for-word the unknown-id answer,
   nothing mutated — the mutation gate re-checks the live membership at
   mutation time, so a grant that expired between the two decisions cannot
   ride the earlier read answer through (the issue's "revoked ...
   indistinguishable" case).

No production file outside `packages/hive-conductor/backend` changes; the
maistro-server cancel route and `RunStoreBoundary` are consumed, not edited.

## Repair-round validation evidence (head `274cb919bd`, 2026-11-22)

Executed locally in `~/Git/wt/auto-2466` (uv-managed env), replacing the
earlier round's missing commit with recorded outcomes:

- green-after: `uv run pytest packages/hive-conductor/backend/tests/
test_dag_run_cancel_authorization.py -q` → **4 passed**.
- red-before: the same test file copied unmodified into a detached scratch
  worktree at base `33ac30c5f1` → **3 failed, 1 passed** — the member-B
  cancellation, the peer-between-successes case, and the cross-Workspace
  projection delegation all `DID NOT RAISE HTTPException` on the pre-fix
  route; the outsider/unknown-id case passes at base as disclosed above
  (regression guard). Scratch worktree removed afterwards; this worktree
  untouched.
- adjacent cancel family: `test_dag_run_cancel_route.py` +
  `test_dag_run_scope.py` + `test_chat_launched_dag_cancel.py` +
  `test_dag_run_projection_authority.py` → **74 passed**.
- shared-rule counterpart: `uv run pytest
  packages/maistro-server/tests/api/test_task_workspace_scope.py -q` →
  **13 passed**, including
  `test_cancel_stays_with_the_initiator_or_an_administrator` (the
  maistro-server half of the divergence guard).
- full changed package: `uv run pytest packages/hive-conductor/backend/tests
  -q` → **4296 passed, 29 skipped** (= the 4325 collected identities the
  inventory records below).
- lint gates: `uv run ruff check .` → clean; `uv run ruff format --check .`
  → 3618 files already formatted.
- `uv run python scripts/check-suite-inventory.py` (CI's exact arguments) →
  **ok: 21 suite(s) match the recorded inventory**.
- production-surface check: the fixed route is the only non-test caller of
  `RunExecutionService.cancel_run` under `packages/hive-conductor/backend` —
  no second Conductor cancellation path bypasses the gate.

## Repair round 2 (head `f6307c0291`, 2026-11-22): CI failures reproduced and fixed

CI at `f6307c0291` failed exactly two checks; both were reproduced locally
from the actual job logs, and both were content defects of this branch (not
runner noise):

1. **`test` job — OpenAPI generated-types step.** The rewritten cancel-route
   docstring flows into the OpenAPI `description`, so
   `npm run gen:api` regenerates `types.gen.ts` with the new text and
   `git diff --exit-code -- types.gen.ts` failed — the committed generated
   file predated the docstring. Repair: regenerated
   `packages/hive-conductor/frontend/src/api/types.gen.ts` in place
   (`npm ci && npm run gen:api`); the resulting diff (`9272c6dc3..dd91aa233`)
   is byte-identical to the diff CI's failing step printed.
2. **Coverage gate — diff coverage.** `scripts/check-diff-coverage.py` over
   CI's own producer recipe scored `dag_runs.py` at **88.9% of 18 changed
   lines (need 90%); uncovered 119, 120** — the new
   `except RuntimeError → 503` branch for an unstarted engine had no test.
   Repair: added `test_an_unstarted_engine_refuses_the_cancel_with_503`
   (inventory delta +4 → +5), pinning the documented 503 with the projection
   row still visible, refusal raised before any target resolution or boundary
   construction.

Post-repair evidence (all in this worktree, CI's exact arguments where they
exist):

- `uv run pytest packages/hive-conductor/backend/tests -q --timeout=30` →
  **4298 passed, 29 skipped** (= 4327 collected identities = 2937 baseline
  + 1390 of note deltas across the branch history).
- `uv run coverage run --branch --source=packages/hive-conductor/backend -m
  pytest packages/hive-conductor/backend/tests --timeout=30 -q` then
  `uv run python scripts/check-diff-coverage.py coverage.xml --base ae1cb3b17…`
  → **ok: every measured file at or above 90% lines / 80% branch arcs**
  (gate exit 0).
- red-before re-verified at scratch worktree `33ac30c5f1`: the test file →
  **3 failed, 1 passed** (member-B cancel, peer-between-successes,
  cross-Workspace delegation all `DID NOT RAISE HTTPException`; outsider
  guard passes at base as disclosed); scratch worktree removed after.
- `uv run python scripts/check-suite-inventory.py` → **ok: 21 suite(s)
  match the recorded inventory** (4326).
- `uv run ruff check .` → clean; `uv run ruff format --check .` → all files
  already formatted.
- `uv run python scripts/dump-hive-openapi.py` → byte-identical
  `openapi.json` (250 paths, 152 schemas; clean `git status` afterwards),
  and regenerated `types.gen.ts` matches it.
- CI's `test` job had **no other failing step**: job log shows the OpenAPI
  types diff as the only `##[error]` step (maistro-server/turing/design/ext
  suites, root `tests/`, hive frontend build, canvas frontend all green);
  the branch-independence root-suite test that fails locally does so only on
  this machine's stale **gitignored** `quality/ac-state.json` artifact
  (`.gitignore:88`, absent from every fresh CI checkout, where the same
  step passed).

## Develop-sync round (merge 204f292488 into auto-1036, head ec78da65f2)

develop landed the parallel #2471 WIP of this same repair. The merge
resolution keeps both sides' semantics in `cancel_run`: the wired
reader-triple gate with the degraded embedded-authority bridge and the
`EmbeddedRuntimeUnavailable` → 503 translation (this branch), plus develop's
unstarted-engine guard (`get_engine()` `RuntimeError` → 503) and its
gate-resolved cancel target (`run.run_id`). The merged docstring flows into
the OpenAPI description, so `types.gen.ts` was regenerated from the merged
backend. No test was removed: this branch's
`test_dag_run_cancel_route.py` scenarios and develop's
`test_dag_run_cancel_authorization.py` (+6, the delta recorded above) both
run unchanged — 21 cancel-route tests, all green.

Evidence at head ec78da65f2 (CI's exact arguments where they exist):

- `uv run pytest packages/hive-conductor/backend/tests --timeout=30 -q` →
  **4307 passed, 28 skipped**; re-run three times, same result (one earlier
  local run flaked once in
  `test_registration_policy.py::TestInvitations::test_concurrent_open_registration_claims_username_once`,
  a pre-existing develop test that passes 10/10 in isolation — same
  overloaded-host signature CI's own green runs annotate as
  `PytestUnhandledThreadExceptionWarning` noise, not a branch defect).
- `uv run coverage run --branch --source=packages/hive-conductor/backend -m
  pytest packages/hive-conductor/backend/tests --timeout=30 -q` (4307 passed)
  then `coverage xml` + `uv run python scripts/check-diff-coverage.py
  coverage.xml --base origin/develop` → **ok**; scope report: 1 measured
  (`routes/dag_runs.py`, file totals 97.25% lines / 93.75% branch arcs over
  the whole file — the changed-line audit passed the 90/80 floors), 1 exempt
  (`test_dag_run_cancel_route.py`, test code is evidence).
- `uv run python scripts/check-suite-inventory.py` → **ok: 21 suite(s)
  match the recorded inventory** (hive backend suite: 4335).
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → **1221 reviewed
  identities → 1221 findings** (ledger unchanged).
- `uv run ruff check .` → clean; `uv run ruff format --check .` → 3622 files
  already formatted.
- gen:api parity (CI's exact three commands): `dump-hive-openapi.py` +
  `npm run gen:api` + `git diff --exit-code -- types.gen.ts` → **no diff**.
- `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest
  packages/maistro-server/tests/api/test_task_workspace_scope.py -q` →
  **13 passed** (the canonical `require_run_mutation` rule this route
  answers through, unchanged).
