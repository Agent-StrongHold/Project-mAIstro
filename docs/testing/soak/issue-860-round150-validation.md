# Issue #860 — round 150 validation and blocker record

## Scope and disposition

This round rechecked the issue acceptance against the current committed tree and
production-evidence contract. No promotion-grade soak can be honestly claimed
from the available evidence, and this worktree has no production RC artifact or
soak deployment to run. Therefore no acceptance criterion is waived and no
scanner-driven product change is appropriate. The issue remains blocked pending
an exact-RC deployment and an executed, complete soak.

## Evidence reviewed

- `docs/adr/ADR-073126-c4e1-release-and-versioning-process.md` (§6) says an RC
  is cut from `develop` and soaked there; a fix requires a new RC.
- `docs/adr/ADR-081626-f383-execution-lease-fencing.md` defines the canonical
  `Run → NodeRun → Attempt` execution authority and explicitly does not yet
  define lease-expiry takeover/recovery.
- `docs/testing/soak/m3a-load-profile.md` states that the current harness is a
  host-process preflight, not the production Compose artifact; a promotion run
  requires at least 14,400 seconds and cannot be signed by that harness. Its
  “Remaining representative-profile gaps” also identify missing concurrent
  Workspaces/users, Graph fan-out, successful tool/model calls, Design/Canvas,
  Goal/background-worker reconciliation, physical fencing/recovery proof, and
  long-window leak/error observations.
- The supplied round-109 artifact is a 420.05-second shakedown and therefore is
  not promotion evidence. The prior preflight result reports
  `exact_rc_artifact.ok=false`.

## Acceptance status

- Representative release-candidate workload definition: **incomplete**; the
  profile documents a partial traffic mix but explicitly lists representative
  workload gaps.
- Two application replicas and cross-replica exactly-once/fenced behavior:
  **not proven at promotion grade**; the available harness is not the exact
  production Compose artifact and does not prove physical Attempt fencing.
- Sustained pool/queue/lease/retry/resource/shutdown observations: **not
  proven**; the available 420.05-second run is shorter than the required four
  hours, and profile text records remaining unverified surfaces.
- Rate-limit/security behavior under concurrency: documented process-local
  enforcement is a per-replica budget, not proof that replica selection cannot
  increase aggregate allowance. Acceptance remains unmet.
- Exact RC/configuration soak and machine-readable/human-readable evidence:
  **not available**; there is no qualifying exact-RC, ≥14,400-second evidence
  pack in this worktree's supplied artifacts.
- Findings filing/reclassification: cannot be asserted based on this round;
  there is no new production soak finding to classify.

## Validation performed

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  — passed: 1,321 reviewed identities, 1,321 findings, zero unclassified and
  zero never-allowlist findings.
- The job directory contains no `check-*.log` files. No deterministic check
  logs were supplied to independently inspect.

No tests were added; this is a factual blocker record, not a change to the
production behavior or acceptance gates. A promotion verdict requires the
operational evidence above, not another documentation-only or emulator run.
