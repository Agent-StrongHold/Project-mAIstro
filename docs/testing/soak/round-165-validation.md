# Issue #860 — round 165 acceptance revalidation

## Disposition

The promotion acceptance remains unmet. No exact release-candidate image/configuration or release-owner designation was supplied in this worktree, so a production-topology soak could not truthfully be executed or represented. I did not weaken the fail-closed artifact gate or count emulator evidence as exact-RC evidence.

## Acceptance evidence

- Exact artifact and duration remain unproven: `scripts/soak/run_soak.py:74` requires 14,400 seconds; `:753-763` makes the host-process preflight report `exact_rc_artifact.ok=false`. `docs/testing/soak/m3a-load-profile.md` expressly says this harness does not run the production Compose artifact. No exact-RC four-hour run was available.
- Replica-selection rate-limit criterion remains unproven and conflicts with issue wording: `packages/maistro-server/src/maistro_server/api/rate_limit.py` documents process-local buckets and aggregate N× allowance. The accepted ADR-085 requires per-principal limiting but does not promise a cluster-wide aggregate. Resolving whether this acceptance requires cluster-wide enforcement needs policy/release-owner review; implementing Redis coordination here would change the documented contract without authorization.
- Other required workload/recovery observations are explicitly unverified in `docs/testing/soak/m3a-load-profile.md` under “Remaining representative-profile gaps”: multi-user/workspace diversity, Graph fan-out, successful tool/model calls, Canvas, sustained Goal reconciliation, pool saturation, lease reclaim, and physical Attempt fencing.
- The issue also requires filing/reclassifying load findings to the earliest broken milestone invariant. No actual production soak/findings were supplied to file or reclassify. No findings were invented.
- No `check-*.log` files were present in this job directory, so prior driver-side validation claims were not treated as evidence.

## Validation executed

- `uv run pytest tests/test_soak_promotion_gates.py -q -x` — 143 passed.
- `uv run ruff check .` — passed.
- `uv run ruff format --check .` — passed (3,533 files).
- `uv run python scripts/check-suite-inventory.py --suite tests` — passed (6,184 collected; inventory matched).
- `git diff --check` — passed before this note was added.

These checks establish local gate and repository health only, not issue acceptance. No tests were added, so no test inventory delta is required. Remaining work requires an authorized exact-RC deployment/run, sufficient production observability, and resolution of the rate-limit scope ambiguity before promotion evidence can pass.
