# Issue #860 repair assessment — 2d6caa98

## Outcome: blocked; no promotion claim

The dispatch-provided prior run remains decisive: `docs/testing/soak/evidence/m3a-round109-shakedown.json` reports 420.05 seconds, below the 14,400-second minimum. The same evidence reports an unsuccessful `exact_rc_artifact` check. The existing runner explicitly returns a failed artifact check for its host-process mode (`scripts/soak/run_soak.py:744-754`) and the profile says only an exact production Compose artifact can produce promotion evidence (`docs/testing/soak/m3a-load-profile.md`, “Supported topology under test” and “Soak duration requirement”). Increasing the host run duration would not fix artifact identity.

The profile itself records material gaps: no concurrent user/Workspace population, Graph/node fan-out, successful tool/model calls, Design/Canvas operations, or Goal/background-worker reconciliation; sustained schedule traffic, physical Attempt fencing, application event-loop lag, lease reclaim, and worker counts are not proven (`docs/testing/soak/m3a-load-profile.md`, “Remaining representative-profile gaps” and “Round-2 amendments”). The acceptance list therefore remains unverified. This repair round did not claim a four-hour exact-RC run and did not alter any gate to manufacture a pass.

## Architecture/production behavior review

- `packages/maistro-server/src/maistro_server/api/rate_limit.py` documents and implements a process-local `InMemoryRateLimiter`. Each replica independently enforces its configured budget; aggregate allowance scales with replica count. This is an explicit per-process contract, not a cluster-wide limit. See also accepted ADR-085 (`docs/adr/ADR-085-cost-quota-rate-limiting.md`). Replica-selection resistance cannot be asserted as cluster-wide behavior.
- The soak runner is an evidence harness, not an execution authority. Its canonical admission probes exercise existing services; no scheduler or alternate Goal/Run authority was introduced.
- No new tests were added; this is an evidence/handoff note only.

## Validation executed

- `uv run ruff check scripts/soak/run_soak.py packages/maistro-server/src/maistro_server/api/rate_limit.py` — passed.
- `uv run ruff format --check scripts/soak/run_soak.py packages/maistro-server/src/maistro_server/api/rate_limit.py` — passed.
- `uv run python -m py_compile scripts/soak/run_soak.py packages/maistro-server/src/maistro_server/api/rate_limit.py` — passed.
- `uv run pytest packages/maistro-server/tests/api/test_rate_limit.py -x -q` — 26 passed (one existing Starlette deprecation warning). This validates middleware unit/integration behavior, not multi-replica or soak acceptance.
- No `check-*.log` files were present in the supplied job directory; no deterministic driver checks could be independently inspected.

## Required next evidence

Run a supported production Compose deployment with immutable image/config identity and complete representative workload for at least four hours; capture all profile telemetry and thresholds, replica drain/kill/restart, cross-replica work fencing/recovery and findings triage. Until then #860 is not promotion-ready. Rate-limit aggregate semantics remain per ADR-085 unless a separately accepted contract changes them.
