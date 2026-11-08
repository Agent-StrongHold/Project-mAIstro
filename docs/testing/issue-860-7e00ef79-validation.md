# Issue #860 — assigned-round validation checkpoint

Snapshot: supplied issue #860 and dispatch context; worktree `auto-860`,
starting HEAD `5a604fb6e6ce7b03722e60c35ceaf988c60975f0`. No
`check-*.log` files were present in the supplied job directory. The prior
validation artifact was treated as a lead and the relevant evidence was
rechecked directly.

## Executed checks

- `uv run pytest tests/test_soak_promotion_gates.py -q -x` — **PASS**, 84
  tests in 1.94s.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  — **PASS**, 1321 reviewed identities and 1321 findings; no ledger amendment.
- `docker info --format '{{.ServerVersion}}'` — **PASS**, daemon 29.1.3.
  Docker availability does not designate a release candidate or its
  production configuration.
- `git status --short --branch` — clean at starting HEAD; branch is one commit
  behind `origin/develop`. No merge conflict is present, so no develop merge
  was attempted.

## Acceptance disposition

Freshly inspected `docs/testing/soak/evidence/m3a-round109-shakedown.json`:
its 420.05-second host-uvicorn run is below the 14,400-second minimum and has
`exact_rc_artifact.ok=false`. The profile and runner explicitly state this
preflight cannot attest the production Compose image/configuration. The profile
also identifies missing concurrent Workspace/Graph/Design/Canvas/Goal workloads,
application event-loop and cgroup telemetry, and physical Attempt fencing and
recovery observations. The middleware regression suite exercises the actual
production rate-limit middleware and confirms replica-local allowances; this
is counterevidence to the issue's replica-selection non-bypass criterion, not
proof that criterion passes.

Accordingly the issue remains **BLOCKED**. All production-RC/load acceptance
items remain unverified or unmet; the executed unit/gate checks do not substitute
for the required exact-artifact soak. No source or tests were changed, no test
inventory delta is needed, and no GitHub action was taken. Closing the block
requires a release-owner-designated immutable RC/configuration, resolved
cross-replica rate-limit semantics, representative workload and recovery
oracles, and a fresh >=14,400-second run with hash-bound machine and human
evidence. This checkpoint is not promotion approval.
