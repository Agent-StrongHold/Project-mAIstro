# Issue #860 — round 163 acceptance validation

## Scope and disposition

Validated the existing promotion harness, evidence, profile, and regression tests at
`c97658e133772bddcdfe1e4a6de972ce6a0f142f`. No promotion claim is made. The exact
production release-candidate image/configuration and four-hour run are not available
in this worktree, and the host-process harness intentionally cannot produce them.
Changing that fail-closed behavior would manufacture evidence, so this round records
the reproduced blockers instead of weakening a gate or treating preflight data as RC
proof.

## Reproduced evidence

- `scripts/soak/run_soak.py:753-763` unconditionally identifies host-uvicorn preflight
  and returns `ok: false` for `exact_rc_artifact`; `:74` sets a 14,400-second minimum.
  `docs/testing/soak/m3a-load-profile.md` also says the driver cannot sign promotion.
- Historical preflight artifacts under `docs/testing/soak/evidence/` show 60–420-second
  runs and `exact_rc_artifact.ok=false`. `m3a-round8-prodstack-extended.json` records
  only 1,200 seconds and says locally built images have no release-owner RC designation.
  None is an exact-RC four-hour soak.
- `packages/maistro-server/src/maistro_server/api/rate_limit.py` documents a
  process-local limiter and an aggregate N-times configured budget. This does not
  prove the acceptance requirement that replica selection cannot bypass the budget;
  the profile explicitly says its probe tests per-replica enforcement, not a
  cluster-wide budget.
- `docs/testing/soak/m3a-load-profile.md` marks user/Workspace diversity, Graph/node
  fan-out, successful tool/model calls, Design/Canvas, Goal reconciliation, worker
  counts, pool saturation, lease reclaim, and physical Attempt fencing as gaps or
  promotion blockers. Existing shakedowns do not cover them at promotion grade.
- No `check-*.log` files were supplied in the assigned job directory. Therefore no
  driver-reported verification claims were relied upon.

## Validation executed

- `uv run pytest tests/test_soak_promotion_gates.py -x -q` — 143 passed.
- `uv run ruff check scripts/soak/run_soak.py tests/test_soak_promotion_gates.py` — passed.
- `uv run ruff format --check scripts/soak/run_soak.py tests/test_soak_promotion_gates.py` — passed.
- `uv run python scripts/check-suite-inventory.py` — passed; 21 suites match inventory.

These checks establish that the guardrails/tests are healthy, not that acceptance is
met. No test or inventory delta was introduced. Remaining acceptance requires a
representative multi-replica workload on the exact release-candidate artifact,
including the listed concurrency/recovery/security observations and machine-readable
and human-readable evidence tied to that artifact. Findings must be resolved or
reclassified before promotion.
