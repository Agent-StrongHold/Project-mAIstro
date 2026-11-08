# Issue #860 — round 31 validation disposition

Validated on `37767efa35c3cd14c9553a156ccb8200dc6fcdf7` (starting worktree was clean). This is a verification disposition, not a promotion soak or acceptance waiver.

## Fresh checks

- `uv run pytest tests/test_soak_promotion_gates.py -x -q` — **84 passed**. These are promotion-gate contract tests; they do not exercise deployed replicas or prove a production load window.
- `uv run python -c "import json; from scripts.soak.run_soak import failed_promotion_checks; p='docs/testing/soak/evidence/m3a-round30-shakedown.json'; e=json.load(open(p)); print(json.dumps({'sustain_seconds':e.get('sustain_seconds'),'failed_promotion_checks':failed_promotion_checks(e),'exact_rc_artifact':e.get('thresholds',{}).get('checks',{}).get('exact_rc_artifact')}, sort_keys=True))"` — **failed gates reproduced**: 420.08 seconds; `sustain_duration` and `exact_rc_artifact`. The artifact explicitly identifies `host-uvicorn-preflight`, not the promoted production Compose image/config.
- `uv run ruff check .` — passed.
- `uv run ruff format --check .` — passed (3364 files).
- `uv run python scripts/check-suite-inventory.py` — **failed collection**, four `extensions/reference-gallery` suites cannot import their package modules (`gallery_weather_connector`, `gallery_unit_skill`, `gallery_model_adapter`, `gallery_renderer_pack`). The script reports 32,371 collected identities but instructs not to update inventory for broken collection. No inventory baseline or delta was changed.
- Initial guessed test path `packages/maistro-server/tests/test_soak_promotion_gates.py` was not found; the actual root suite was then run as recorded above.

## Acceptance status

1. Representative release-candidate load profile — **UNVERIFIED**: `docs/testing/soak/m3a-load-profile.md` still identifies user/Workspace population, Graph fan-out, successful model/tool, Canvas, and Goal/background work as gaps.
2. At least two deployed application replicas — **UNVERIFIED**: preflight and ASGI tests are not deployment of the selected immutable RC.
3. Sustained saturation, queue/reclaim/retry/leak/shutdown observations — **UNVERIFIED**: round-30 window is 420.08 seconds, below the required 14,400 seconds; no promotion-grade long-window run was executed.
4. Schedule/task/Run/Attempt/Goal physical-work uniqueness — **UNVERIFIED**: schedule claim evidence cancels the probe Run without physical execution; targeted gate tests do not establish physical Attempt fencing or Goal reconciliation.
5. Rate/security/degraded behavior cannot be bypassed by replica selection — **NOT PROVEN**. The load profile documents process-local rate budgets (aggregate allowance scales with replica count); enforcing a local 429 on each replica does not prove a shared principal budget or non-bypass under replica selection.
6. Required telemetry and explicit thresholds — **PARTIAL/UNVERIFIED**: historic preflight records sampler series and thresholds, but not a complete selected-RC production time series including the required application-loop/worker/reclaim and long-window observations.
7. Active-work replica kill/restart and drain/fencing/recovery — **UNVERIFIED** at RC scope; no selected RC physical Attempt was killed and followed through canonical recovery in this validation.
8. Long soak of exact RC/configuration — **NOT MET**: fresh evaluator rejects both `sustain_duration` and `exact_rc_artifact` for round 30.
9. Findings classified to earliest broken milestone invariant — **UNVERIFIED for completeness**: this validation produced no new production-load findings; no external filing was performed.
10. Machine- and human-readable evidence tied to exact promoted image/package/commit/config — **NOT MET for promotion**: historical evidence is tied to a source head but explicitly fails exact-RC identity; no qualifying RC artifact was designated or exercised.

## Disposition

No code or test changes can honestly turn the extant preflight evidence into the required production RC proof. Do not promote on this evidence. A release owner must designate the immutable RC/configuration, execute the representative multi-replica ≥14,400-second workload and fault/recovery checks, and capture the required evidence. The accepted execution contracts remain `Goal -> Graph -> Run -> NodeRun -> Attempt`; this note introduces no execution authority or scheduler.
