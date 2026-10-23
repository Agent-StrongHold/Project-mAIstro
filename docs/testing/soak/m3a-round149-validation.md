# Issue #860 — independent validation at dispatched head

Validation-only checkpoint on `auto-860`. Starting HEAD was
`e2a6b5590f8203cf1d5de226352cf3a0ede5c160`; the worktree was clean. There were
no `check-*.log` files in the assigned job directory. The branch already
contains merge commit `dd823e64` with `5647c34bfb8be091e5935191aed37d56dca974e0`
as a parent, the dispatched base, and no merge conflict is present. No source,
tests, inventory, quality ledger, or grant were changed.

Accepted ADR-081226-a66b establishes `Run -> NodeRun -> Attempt` as the
universal execution hierarchy and says recovery retries create Attempts under
the same logical NodeRun. ADR-082826-d9f5 makes `RunStore` the sole system of
record for those canonical entities; neither process counts nor queue/projection
records establish physical-work uniqueness. No competing execution lifecycle
was added.

## Fresh focused validation

- `uv run pytest tests/test_soak_promotion_gates.py -x -q` — **84 passed**.
- `uv run pytest packages/maistro-server/tests/api/test_rate_limit.py -x -q`
  — **26 passed**, one Starlette deprecation warning.
- `uv run ruff check scripts/soak/run_soak.py tests/test_soak_promotion_gates.py`
  — passed.
- `uv run ruff format --check scripts/soak/run_soak.py tests/test_soak_promotion_gates.py`
  — passed (both already formatted).
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` — 1,321 reviewed identities
  equal 1,321 findings; 0 unclassified. No ledger edit warranted.
- `git diff --check` — passed.

No tests were added, so no test-inventory delta is applicable.

## Acceptance disposition

1. Representative release-candidate workload — **UNVERIFIED**. The profile
   still identifies missing concurrent users/Workspaces, Graph fan-out,
   successful tool/model calls, Design/Canvas traffic, and background
   reconciliation traffic; it lacks an RC-specific applicability decision
   (`docs/testing/soak/m3a-load-profile.md`, “Remaining representative-profile
gaps”).
2. Two application replicas — historical production Compose observation exists,
   but it was built locally and does not identify a designated immutable RC
   (`evidence/m3a-round7-prodstack-identity.json`). No exact-RC proof.
3. Long sustained soak — **NOT MET**. The longest reviewed production-stack
   observation is 1,200 seconds, below 14,400 seconds; its evidence explicitly
   marks `sustain_duration.ok=false`
   (`evidence/m3a-round8-prodstack-extended.json`, `thresholds.checks`).
4. Uniqueness/fencing/recovery, security under replica selection, required
   telemetry, active-replica kill/restart recovery, and findings reclassification
   — **UNVERIFIED** as promotion evidence. The 1,200-second record has no
   promotion pass: its replay lists all required checks failed, including
   exact-RC, duration, admission, replica rejoin, drain, and rate limiting
   (`evidence/m3a-round8-prodstack-extended.json`, `promotion_gate_replay`).
5. Machine/human evidence tied to exact RC — **NOT MET**. Round 8 records locally
   built image IDs and states no release-owner RC designation exists; the
   current host-process preflight also fails closed for `exact_rc_artifact`
   (`scripts/soak/run_soak.py:744-750`).

Conclusion: **BLOCKED** on exact-RC representative four-hour production soak
and its falsification evidence, not on a failing targeted regression suite or
vulture finding. Existing targeted tests validate gate and rate-limit logic,
not the deployment acceptance criteria. This checkpoint does not claim
integration or promotion approval.
