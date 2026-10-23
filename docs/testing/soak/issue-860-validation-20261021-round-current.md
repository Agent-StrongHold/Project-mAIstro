# Issue #860 — current round validation (blocked; not promotion evidence)

Starting HEAD: `1216edddbafb0220ae5a0e617ea9df59babc8654`  
Assigned base: `5647c34bfb8be091e5935191aed37d56dca974e0`

This round checked only #860. The supplied job directory contained no
`check-*.log` files. The prior result was reviewed and treated as historical,
not as proof of current acceptance. Worktree was clean before this report.

## Fresh validation

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — PASS: 1,321 findings match 1,321 reviewed identities; zero unclassified or never-allowlisted findings. No ledger changes needed.
- `uv run ruff check .` — PASS.
- `uv run ruff format --check .` — PASS: 3,411 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py -x -q` — PASS: 84 passed in 1.57s. This validates promotion gate logic, not a production soak.
- Re-read the acceptance evidence and live runner behavior. `scripts/soak/run_soak.py` `preflight_artifact_check()` returns `ok: false` by design for this host-process preflight; the tracked profile requires 14,400 sustained seconds and says the preflight cannot certify exact-RC artifact identity. No selected RC image/configuration or four-hour run was supplied.

## Architecture reconciliation

Accepted ADR-081226-a66b defines the single `Run -> NodeRun -> Attempt` lifecycle and ADR-081626-f383 assigns lease/fencing enforcement to canonical persistence. This validation introduces no alternate scheduler, execution authority, or Goal store. ADR-073126-c4e1 describes RC tagging/soaking, but does not waive #860's exact-artifact acceptance.

## Acceptance disposition

| Criterion | Evidence / outcome |
|---|---|
| Representative release-candidate profile | **UNVERIFIED**. `docs/testing/soak/m3a-load-profile.md` explicitly lists concurrent users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas, and Goal/background reconciliation as gaps. |
| At least two application replicas | **UNVERIFIED for a selected RC**. Existing preflight evidence is not the designated production RC artifact. |
| Sustained duration and saturation/resource/recovery observations | **NOT MET**. The profile requires 14,400 seconds; no qualifying run was supplied or executed. |
| No duplicate schedule/task/Run/Attempt/Goal physical work across replicas | **UNVERIFIED**. The short gate suite does not establish sustained physical-work uniqueness or recovery. ADR-081626-f383 also states it does not yet define lease-expiry takeover. |
| Rate/security/degraded behavior cannot be bypassed through replica selection | **UNVERIFIED** by the 84-test suite as an integrated RC load claim; no replica-deployed security soak is supplied. |
| Required telemetry and thresholds | **UNVERIFIED** at RC promotion grade; no current exact-RC telemetry series supplied. |
| Kill/restart during active work proves drain/fencing/recovery | **UNVERIFIED**; no exact-RC active-work restart run supplied. |
| Long soak of exact RC artifact/configuration | **NOT MET**. The only current runner explicitly rejects exact artifact identity; no artifact/config hash manifest and 14,400-second run available. |
| Findings classified to earliest broken invariant | **UNVERIFIED** as a completed finding disposition; this round makes no external issue changes. |
| Machine/human evidence bound to exact image/package/commit/config hashes | **NOT MET** for a current RC; no candidate image/configuration soak evidence supplied. |

No production or test code was changed; no test inventory delta applies. The issue remains blocked on release-owner selection of the RC artifact/configuration and execution of the required representative, instrumented production soak. Re-running the host preflight or weakening its fail-closed gate would not satisfy acceptance.
