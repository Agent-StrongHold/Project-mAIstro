# Issue #860 validation — job d79363e4

## Disposition: BLOCKED

No promotion evidence was produced. The current assigned worktree still has no
identified immutable Compose release-candidate artifact/configuration or
deployment target. Inventing one or treating host-process/preflight runs as RC
coverage would misstate acceptance. The previously identified block
("validation repair budget exhausted") is resolved by recording the true
limitation: no repository-only repair can execute the absent operational soak
or substitute for its evidence. No gate is weakened, and no acceptance waiver
is implied.

## Checked evidence

- Snapshot head: `8e84d09df0b6c845f7e32903f2090a956720783d`; develop base:
  `b9cd15c608b5cc23ce785b3c80813d7e4d8f678b`. The worktree was clean before
  this note. The only delta from develop is the accumulated issue-860 history
  and develop merge; no new production behavior repairs the reported blockers.
- The supplied current job directory contains no `check-*.log` files (attempted
  reads returned ENOENT). The prior verifier's `result.json` is available and
  reports ruff, formatting, targeted tests and inventory checks successful; it
  reports the acceptance failures below. Its claims are not substituted for
  my live source/evidence inspection.
- `scripts/soak/run_soak.py::preflight_artifact_check()` intentionally returns
  `ok: false` with `host-uvicorn-preflight`; promotion requires an exact RC
  artifact. `docs/testing/soak/evidence/m3a-round109-shakedown.json` records
  420.05 seconds against the 14,400-second minimum. `m3a-round153-validation.md`
  records that no soak was launched and no immutable Compose RC artifact was
  designated.
- `m3a-load-profile.md` identifies workload/fencing coverage gaps as blockers.
  `rate_limit.py` implements process-local per-replica state; tests that
  characterize N-replica allowance do not prove a shared aggregate limit.
- ADR-073126-c4e1 §6 places the RC on `develop`; this review does not reinterpret
  that release process as approval to waive issue acceptance. ADR-085's
  per-principal rate-limit requirement remains relevant to the bypass criterion.
  The harness/promotion design and release process are preserved unchanged.

## Acceptance

- Representative RC workload and at least two RC replicas: **UNVERIFIED**;
  profile gaps and no designated artifact.
- Sustained >=14,400-second load with resource/queue/connection telemetry:
  **NOT MET**; retained run is 420.05 seconds and is not RC evidence.
- Cross-replica physical-work fencing/exactly-once and kill/restart recovery:
  **UNVERIFIED** at RC level; no qualifying soak was run.
- Rate limiting cannot be bypassed through replica selection: **NOT MET** by
  current process-local implementation.
- Earliest-invariant classification and hash-tied machine/human evidence:
  **UNVERIFIED / NOT MET**; no qualifying run exists from which to classify and
  publish results.

A release operator must designate the immutable RC plus Compose configuration,
close the documented profile/fencing gaps, run the required soak, and publish
its hashes and results. No load run was started in this round because it could
not qualify as acceptance evidence. No test was added, so no suite inventory
change is applicable.
