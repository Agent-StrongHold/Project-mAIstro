# Issue #860 — independent validation at dispatched head

Validation of `auto-860` at `d3847e4ce5ad89cb0511bb5d10ac91f2c94261d0`.
The assigned job directory contains no `check-*.log` files. The supplied
previous result confirms its deterministic checks passed, but its agent failed
on provider quota (not a code/test failure). No soak was run during this check.

## Architecture / evidence review

Accepted ADR-081226-a66b defines the sole execution hierarchy as
`Run -> NodeRun -> Attempt`; retries/recovery create Attempts under the same
NodeRun. Accepted ADR-082826-d9f5 makes `RunStore` the system of record. A
scheduler or queue projection cannot establish physical-work uniqueness. ADR-
046 is superseded by ADR-082126-f69c and does not authorize a parallel
scheduler or independent execution lifecycle.

`docs/testing/soak/m3a-load-profile.md` explicitly describes `run_soak.py` as a
host-process preflight rather than the supported production Compose artifact.
It also marks the missing population/Workspace, Graph fan-out, successful
tool/model, Design/Canvas and Goal/background-reconciliation workload as
representativeness gaps. Its promotion minimum is four sustained hours and its
host preflight always fails the exact-RC artifact gate. The reviewed round-109
artifact records 420.05 seconds and `exact_rc_artifact.ok=false`; even its
successful admission/schedule/rate-limit probes do not prove an RC promotion
soak or physical Attempt fencing.

## Executed validation

- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_rate_limit.py -x -q`
  — **110 passed**, one existing Starlette deprecation warning.
- The supplied prior-result record says `ruff check .`, `ruff format --check .`,
  and three focused pytest targets passed; suite-inventory checks passed.
  Those are prior-run claims, not rerun in this validation.
- No tests were added; no suite inventory delta is applicable.

## Acceptance disposition

- Representative RC workload: **UNVERIFIED**; the profile documents workload
  coverage and applicability gaps.
- Two application replicas: historical host-process probes exist, but do not
  establish the exact supported RC deployment.
- Sustained load ≥ 4 hours: **NOT MET**; reviewed evidence is 420.05 seconds.
- Cross-replica uniqueness/fencing for schedules, task/Run/Attempt admission,
  Goal reconciliation, rate limits/security, telemetry, and active-replica
  restart recovery: **UNVERIFIED as RC promotion evidence**. Targeted probes do
  not cover all of these properties in the exact RC topology.
- Exact RC artifact/config evidence and human/machine promotion pack: **NOT
  MET**; the host preflight fails closed and no release-candidate artifact was
  designated.
- Findings reclassified to earliest broken invariant: **UNVERIFIED**; no
  qualifying RC soak exists to establish its load findings.

**Disposition: BLOCKED**, not a source-code regression. Do not claim promotion
readiness from the passing targeted suite or historical short preflights. The
next evidence-producing step requires a designated immutable RC and its exact
production Compose/runtime configuration, a representative profile agreed
against that deployment, and the full four-hour multi-replica soak.
