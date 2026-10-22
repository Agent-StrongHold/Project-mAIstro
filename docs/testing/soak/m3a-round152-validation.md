# Issue #860 — round 152 acceptance revalidation

## Disposition

**BLOCKED.** No immutable release-candidate image/configuration was designated
for this worktree. The accepted release process requires an RC cut from
`develop` and soaked there (ADR-073126-c4e1 §6); a host-process run is not
substitute evidence. No production code or soak gate was changed.

## Acceptance evidence

- Representative users/Workspaces, Graph fan-out, successful tool/model calls,
  Design/Canvas, and Goal/background reconciliation: **UNVERIFIED**. The
  documented remaining gaps in `m3a-load-profile.md` still apply.
- Two replicas of the supported production artifact: **UNVERIFIED**. Historic
  host-process instances do not establish the exact RC Compose artifact.
- At least four hours of sustained load and pool/queue/lease/retry/resource/
  shutdown observations: **NOT MET**. The retained round-109 evidence records
  420.05 seconds (see `evidence/m3a-round109-shakedown.json`).
- Cross-replica uniqueness, physical Run/Attempt fencing, security/rate-limit
  replica-selection behavior, and kill/restart recovery: **UNVERIFIED as RC
  evidence**. A schedule-claim result alone does not prove physical work.
- Required telemetry and explicit production thresholds: **PARTIAL/UNVERIFIED**
  for an exact RC runtime; the documented profile identifies missing worker,
  pool, application event-loop, and physical recovery observations.
- Hash-tied human- and machine-readable evidence for the promoted artifact:
  **NOT MET**. `scripts/soak/run_soak.py::preflight_artifact_check()` returns
  `ok: false` with topology `host-uvicorn-preflight` by design, and round-109
  records only 420.05 seconds versus the profile's 14,400-second minimum.
- Earliest-invariant classification of newly observed load findings:
  **UNVERIFIED**; no qualifying production soak was run and no new production
  observations were made.

## Validation performed

- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_rate_limit.py packages/maistro-core/tests/scheduling/test_pg_admission.py -x -q` — **110 passed, 2 skipped** (one Starlette deprecation warning).
- Inspected accepted ADR-073126-c4e1 §6, `m3a-load-profile.md`,
  `scripts/soak/run_soak.py::preflight_artifact_check()`, and the round-109
  evidence. No `check-*.log` files were present in the supplied job directory;
  no CI result is inferred from their absence.
- No soak was launched: no exact RC image/configuration was designated or
  available, and the host-process driver explicitly cannot sign promotion.

## Required next evidence

Designate an immutable RC and exact supported production Compose/runtime
configuration; complete the representative profile and telemetry/fencing gaps;
run at least 14,400 seconds against that artifact; publish hash-tied evidence;
and classify any findings against the earliest broken invariant before
promotion. Regression tests passing do not satisfy the soak acceptance.
