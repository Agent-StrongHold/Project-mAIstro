# Issue #860 repair-lane validation — job `3f8608e9`

## Scope and result

Rechecked the assigned issue against the release profile, the soak driver,
existing soak evidence, and accepted ADR-081626-f383 (durable Attempt fencing)
and ADR-082126-f69c (schedules admit canonical Runs). This validation does not
claim that promotion acceptance is met.

The assigned job directory has no `check-*.log` files. The supplied round-109
evidence is historical and does not match this head: it records a 420.05-second
host-uvicorn preflight, while the profile requires at least 14,400 seconds on
the exact RC Compose artifact. The preflight's production-artifact check is
hard-coded to `ok: false` (`scripts/soak/run_soak.py`, `preflight_artifact_check`),
so extending that host-process run cannot produce promotion evidence.

## Executed validation

- `uv run pytest tests/test_soak_promotion_gates.py -x -q`: **84 passed**.
- `uv run pytest tests/test_soak_promotion_gates.py -k replica_selection_has_an_independent_production_allowance -x -q`:
  **2 passed**. These tests reproduce that each server replica has a separate
  in-memory rate-limit allowance; this confirms a same-principal replica
  selection bypass of an aggregate limit, not acceptance of anti-bypass.
- `uv run ruff check scripts/soak/run_soak.py tests/test_soak_promotion_gates.py`:
  passed.
- `uv run ruff format --check scripts/soak/run_soak.py tests/test_soak_promotion_gates.py`:
  passed.
- `uv run python scripts/soak/run_soak.py --help`: passed; CLI is available,
  but this does not execute a soak.
- Evaluated `m3a-round109-shakedown.json` through the current driver functions:
  observed `sustain_seconds=420.05`, `preflight_artifact_check().ok=false`, and
  `failed_promotion_checks` returned `['sustain_duration', 'exact_rc_artifact']`.
- `git merge --no-edit origin/develop`: completed without conflict, incorporating
  the current `origin/develop` head `a9fdec4cb40a62ada3e897448eabc81f2410135a`.

No tests were added; no test-inventory delta is required.

## Acceptance disposition

- Representative concurrent users/Workspaces, request mix, graph/node fan-out,
  successful tool/model calls, Design/Canvas activity, and background work:
  **UNVERIFIED**. `docs/testing/soak/m3a-load-profile.md` expressly lists these
  gaps in the existing preflight.
- Two production application replicas under the supported RC topology:
  **UNVERIFIED**. Historical host-process replicas are not the exact production
  Compose artifact/configuration.
- Sustained saturation, queue/lease behavior, memory/descriptor/process leaks,
  and telemetry at the required duration: **UNVERIFIED**. The supplied 420.05 s
  run is shorter than 14,400 s and does not provide production telemetry for all
  required dimensions.
- Exactly-once schedule, task/Run/Attempt admission and Goal reconciliation,
  including no duplicate physical work: **UNVERIFIED** at production acceptance
  grade. Existing schedule probe demonstrates an admission claim but cancels
  its queued Run rather than exercising physical execution/fencing; ADR fencing
  contract does not itself prove live multi-replica recovery.
- Rate limiting/security under replica selection: **NOT SATISFIED** for an
  aggregate same-principal limit; the two focused tests demonstrate independent
  per-replica in-memory allowances. No cluster-shared budget was demonstrated.
- Exact RC artifact, four-hour soak, active-work kill/restart with drain/fencing,
  and machine-readable evidence tied to image/config hashes: **UNVERIFIED**.
- Filing/reclassification of any newly observed load findings before promotion:
  **UNVERIFIED**; no new production soak findings were generated in this run.

This round is therefore **BLOCKED for promotion acceptance**. Do not infer
release readiness from the green harness tests or from prior preflight runs.
A separate production-capable execution must run the immutable RC artifact for
the complete profile and resolve the observed replica-local rate-limit bypass
before the criteria can pass.
