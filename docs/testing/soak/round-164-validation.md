# Issue #860 — round 164 acceptance revalidation

## Scope and disposition

Revalidated the promotion gate and existing evidence at `5ae3607aabc46cd6cce507279c8441801f6e04b8` after the develop merge. No production-RC soak is claimed. The issue's promotion acceptance remains unmet; changing fail-closed gates or treating emulator evidence as exact-RC proof would manufacture evidence.

## Acceptance findings

- The profile requires at least 14,400 seconds and exact production Compose artifact identity (`docs/testing/soak/m3a-load-profile.md`, Artifact Identity and Soak duration sections). `scripts/soak/run_soak.py:74` sets the minimum; `:752-763` explicitly fails `exact_rc_artifact` for the host-process preflight. Historical evidence is not a current exact-RC four-hour run.
- The rate limiter is process-local (`packages/maistro-server/src/maistro_server/api/rate_limit.py`); per-replica burst tests cannot establish that replica selection cannot increase a principal's allowance. The profile explicitly distinguishes this from a cluster-wide budget.
- The profile's remaining representative-profile gaps include population/workspace diversity, Graph/node fan-out, successful tool/model calls, Design/Canvas and Goal/background reconciliation. Pool saturation, lease reclaim and physical Attempt fencing are likewise not evidenced at promotion grade.
- The issue's promotion evidence additionally requires the exact RC topology and sustained concurrency/recovery evidence. None was available to execute in this worktree; no release-owner RC artifact or production run was supplied.
- The assigned job directory contained no `check-*.log` files. Driver-side verification claims were therefore not relied upon.

## Validation executed at this head

- `uv run pytest tests/test_soak_promotion_gates.py -q -x` — 143 passed.
- `uv run ruff check scripts/soak/run_soak.py tests/test_soak_promotion_gates.py` — passed.
- `uv run ruff format --check scripts/soak/run_soak.py tests/test_soak_promotion_gates.py` — passed.
- `uv run python scripts/check-suite-inventory.py --suite tests` — passed; 6,184 collected tests, inventory matched.

These prove existing gate/regression health only, not the promotion acceptance. No test was added and no inventory delta was needed. Verdict remains NEEDS-REPAIR pending exact-RC four-hour execution plus resolution/reclassification of the stated blockers.
