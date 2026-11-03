# Issue #860 — round 151 acceptance revalidation

## Disposition

**BLOCKED.** This worktree contains no designated immutable release-candidate
artifact or matching production-Compose soak deployment. A host-process preflight
cannot meet the accepted release contract, and no evidence reviewed or executed
in this round waives an acceptance criterion. No production code or soak gates
were changed.

## Architecture and release constraints

- Accepted ADR-073126-c4e1 §6 requires an RC to be cut from `develop` and
  soaked there; a fix requires a new RC. This worktree is not a designated RC
  deployment.
- Accepted ADR-081226-a66b defines the universal execution identity as
  `Run → NodeRun → Attempt`; retries/recovery remain Attempts under the
  NodeRun. Accepted ADR-082826-d9f5 makes `RunStore` the sole record for those
  canonical entities and Graph state a projection. Queue, scheduler, or
  harness-only observations cannot establish physical-work uniqueness.
- `docs/testing/soak/m3a-load-profile.md` says the current `run_soak.py` uses
  host Uvicorn rather than the exact production Compose topology, has a 14,400
  second minimum, and explicitly lists representative traffic and physical
  fencing/recovery gaps. Its gates correctly fail the host-process preflight
  for exact-artifact identity.

## Acceptance evidence

- Representative user/Workspace, Graph fan-out, successful tool/model,
  Design/Canvas, and Goal/background reconciliation workload: **UNVERIFIED**;
  `m3a-load-profile.md` still identifies these gaps.
- At least two replicas in the supported production artifact: **UNVERIFIED**;
  historical host-process replica runs are not the promoted Compose artifact.
- Sustained load at least four hours with saturation, queues, lease/retry,
  resource, and shutdown observations: **NOT MET**. The reviewed round-109
  artifact reports 420.05 seconds.
- Cross-replica uniqueness/fencing of schedules and task/Run/Attempt admission,
  Goal reconciliation, and safe active-work restart: **UNVERIFIED as RC
  evidence**. A schedule admission claim alone is not proof of physical Attempt
  fencing/recovery.
- Rate-limit/security guarantees under replica selection: **UNVERIFIED as
  acceptance**. The profile describes process-local rate-limit state and does
  not establish that replica selection cannot increase a principal's aggregate
  allowance.
- Required PostgreSQL, application event-loop, worker/process, RSS, descriptor,
  queue, latency, and error metrics with thresholds: **PARTIAL/UNVERIFIED**;
  host-emulator measurements do not establish the exact RC runtime, and the
  profile itself notes absent worker/pool/physical recovery observations.
- Exact RC/config hashes and human-/machine-readable qualifying evidence:
  **NOT MET**. Round-109 has `exact_rc_artifact.ok=false` and identifies
  `host-uvicorn-preflight`; it also has `sustain_seconds=420.05`.
- Findings discovered under load reclassified to the earliest broken invariant:
  **UNVERIFIED**; this round ran no production soak and produced no new
  production observation to classify.

## Validation executed in this round

- `uv run pytest tests/test_soak_promotion_gates.py
  packages/maistro-server/tests/api/test_rate_limit.py
  packages/maistro-core/tests/scheduling/test_pg_admission.py -x -q` — **110
  passed, 2 skipped**, one existing Starlette deprecation warning.
- Independently inspected
  `docs/testing/soak/evidence/m3a-round109-shakedown.json`: recorded
  `sustain_seconds=420.05`, `exact_rc_artifact.ok=false`, topology
  `host-uvicorn-preflight`, clean historical head
  `5a59c724a20ef1241d57c048df90758f2c2e1e25`.
- The job directory `/home/dev/maistro/jobs/37e7e0cbe3424cae868f80b285674769`
  contains no `check-*.log` files. No CI check result is inferred from their
  absence. No soak was launched because no qualifying RC artifact/configuration
  is designated or available in this worktree.
- No test was added; suite inventory is unchanged. This is a factual
  acceptance record, not a substitute for the required production soak.

## Next required evidence

Designate an immutable RC and its exact supported production Compose/runtime
configuration, close the profile's explicitly documented coverage gaps, run the
full ≥14,400-second profile against that artifact, and publish its hash-tied
evidence. Reclassify any resulting load findings before promotion. Do not infer
readiness from the targeted regression tests above.
