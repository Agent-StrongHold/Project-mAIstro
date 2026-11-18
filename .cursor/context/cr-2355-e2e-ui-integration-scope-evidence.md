# cr-2355 validation round — integration-scope / hive-conductor-e2e-ui evidence

Branch `cursor/m1-b-p2a-reclaim-cause-befa`, head `3e1d599485196811f48f953cfd867dd08434d15c`,
base `f8a2df966a1d0db82be5fc08a571ed4750902c88` (= current `origin/develop`; no
develop drift, `git log origin/develop ^HEAD` is empty).

## Named gate this round: integration-scope

CI log: `hive-conductor-e2e-ui is required by integration scope but concluded
failure`. The aggregator (`.github/workflows/integration-scope.yml`) fails
closed when a required specialized producer fails; it has no branch-side
logic to repair. For this diff (6 files: `runs/lifecycle.py` + maistro-core
tests + inventory note) the required set is:

```
docker-build, hive-conductor-e2e, hive-conductor-e2e-ui,
postgres (pg17), postgres (pg18), strike-ladder, wheel-imports
```

(reproduced with CI's exact scripts: `ci_base_revision.py`,
`ci_merge_group_scope.py --json <paths>`, `check-integration-scope.py
--event-name merge_group --required-json`). Only `hive-conductor-e2e-ui`
failed at this head; the other six concluded success in CI.

## Producer reproduced green locally at this exact head

`scripts/prepull-base-images.sh packages/hive-conductor/Dockerfile
packages/hive-conductor/tests/Dockerfile.playwright` then, in
`packages/hive-conductor`, CI's exact step:

```
docker compose -f docker-compose.test.yml --profile test up --build \
  --abort-on-container-exit --exit-code-from e2e-tests e2e-tests
```

Result: **245 passed, 1 flaky (rsi-polling-resilience backoff spec), exit
code 0** (5.4m). Stack torn down after (`docker compose down -v`). The CI
failure of this job at 3e1d599 was environmental (its build log shows only
npm-audit noise; `ci.yml` documents this exact job failing trunk pushes on
registry faults), not caused by the branch diff.

## Trunk-level corroboration

Dispatch check-run data: `Coverage gate (publish-set floor + diff coverage)`
fails on this head AND on the three disjoint sibling heads (PR #2360,
#2367, #2370); `hive-conductor-e2e-ui` failed/cancelled on those heads too.
Same-for-every-diff ⇒ trunk redness, not candidate redness.

## Acceptance criteria of the P2a change (#2354), verified first-hand

- Focused pytest (`test_attempt_cancellation_cause_model.py`,
  `test_m8a5_differential_reference_model_research.py`,
  `test_reclaim_attempt_lease_construction.py`,
  `test_spine_conformance.py`): **347 passed, 130 skipped**.
- Mutation binding: reverse-applying the lifecycle.py fix in a temp worktree
  (back to the P1a bare-CANCELLED writer) fails **7 of 8** tests in
  `test_reclaim_attempt_lease_construction.py` (all four refusals, the
  expired-lease RECOVERED commit, CREATED+expired, live/infinite gates).
- `check-suite-inventory.py --suite packages/maistro-core/tests`: ok,
  18443 identities; note `p2a-reclaim-attempt-lease-construction.md`
  `inventory-delta: +8` matches; no test counts changed this round.
- Vulture ledger with CI's exact args (`packages/*/src --min-confidence 60
  --exclude '*/third_party/*'`): exit 0, 1238/1238 banked.
- Radon baseline (126/126), promotion surface (ok — no new universal owner),
  reachability (exit 0), direct effects (49 sites, all dispositioned): all
  exit 0 at this head.
- `ruff check .` + `ruff format --check .`: clean.
- `quality/` untouched by the branch (diff vs base = 6 files, none under
  `quality/`); no ledger amendment needed or made.

## Residual risks

- Required hosted checks (hive-conductor-e2e-ui and the downstream
  integration-scope aggregator) stay red at 3e1d599 until CI re-runs; the
  local pass at the identical head is the repair evidence. Pushing or
  re-running is outside this worker's authority.
- Coverage gate / pip-audit / container-scan / security legs fail on trunk
  for every candidate head; repairing them is a trunk-CI round, outside
  #2355's file boundary.
