# Issue #860 — current job validation (blocked)

Starting assigned HEAD: `3cf296982207d46f5c03a2eed4827c70daf7b6ae`.
Merged the one fetched `origin/develop` commit (`a825d0b35e5b98b74f3022c7edde488239387140`) as instructed for the branch's behind-1 state; merge was conflict-free. The supplied job directory had no `check-*.log` files, so validation below was run directly.

## Executed checks

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — PASS: 1,321 reviewed identities equal 1,321 findings; zero unclassified/never-allowlisted findings. No ledger edit warranted.
- `uv run pytest tests/test_soak_promotion_gates.py -x -q` — PASS: 84 tests. This exercises promotion-gate decisions, not production RC deployment or load.
- `uv run ruff check .` — PASS.
- `uv run ruff format --check .` — PASS: 3,413 files already formatted.

## Evidence disposition

The profile states that the host-process driver is not the promoted Compose artifact, that promotion requires at least 14,400 sustained seconds, and that the current driver always rejects exact RC identity (`docs/testing/soak/m3a-load-profile.md:16-24, 121, 148-149`). The runner implements this fail-closed condition at `scripts/soak/run_soak.py:744-754` and includes both artifact and duration in required promotion checks at `:767-779`.

The current checked-in round-109 evidence reports `sustain_seconds: 420.05`, versus `minimum_seconds: 14400` (`docs/testing/soak/evidence/m3a-round109-shakedown.json:221-224, 283-287`); `exact_rc_artifact.ok` is false there. The profile's remaining gaps explicitly include concurrent users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas, and Goal/background reconciliation (`m3a-load-profile.md:165-174`). It also states the single schedule claim probe does not establish sustained Goal reconciliation or physical Attempt fencing (`:200-207`).

The accepted [ADR-073126-c4e1](../../adr/ADR-073126-c4e1-release-and-versioning-process.md) requires an RC to be cut from `develop` and soaked there, with a new RC after a fix; it does not waive exact-artifact acceptance. [ADR-081626-f383](../../adr/ADR-081626-f383-execution-lease-fencing.md) assigns durable lease/fencing to canonical Attempt persistence and explicitly leaves expiry takeover/recovery undefined. No alternate scheduler, execution authority, or Goal store was introduced.

| Acceptance criterion | Result |
|---|---|
| Representative RC profile | UNVERIFIED; material workload gaps remain (`m3a-load-profile.md:165-174`). |
| At least two application replicas | UNVERIFIED for an exact selected RC; the current driver is a host-process preflight. |
| Sustained 4-hour load and saturation/resource/recovery observation | NOT MET; 420.05 seconds in supplied evidence, 14,400 required. |
| No duplicate physical schedule/task/Run/Attempt/Goal work | UNVERIFIED; current schedule probe and gate tests are not physical execution/recovery proof. |
| Rate limiting/security/degraded behavior under replica selection | UNVERIFIED at exact-RC integrated load grade. |
| Required telemetry and explicit thresholds | NOT proven for the exact RC and full required profile. |
| Kill/restart during active work proves drain/fencing/recovery | UNVERIFIED at exact-RC promotion grade. |
| Long soak of exact RC artifact/configuration | NOT MET; exact artifact check is fail-closed and no exact RC was supplied. |
| Findings reclassified to earliest broken invariant | UNVERIFIED as a promotion finding disposition. |
| Human/machine evidence bound to exact hashes | NOT MET for a selected exact-RC soak. |

No test or production code changed; no test inventory delta applies. No qualifying soak was started: the absence of a selected immutable RC and the runner's fail-closed artifact check mean a host preflight cannot satisfy promotion acceptance. The issue remains blocked pending exact RC selection and execution of the prescribed representative production soak.
