# Issue #860 — round 32 validation disposition

Validated at `f999f177ab6bc3d87a2da17060cd8c997a929a66`. The worktree was clean before validation. No soak `check-*.log` files were present in the assigned job directory, so there were no driver check logs to inspect. This round performed validation only; it did not run a production Compose release candidate or amend the soak code/evidence.

## Executed checks

- `uv run pytest tests/test_soak_promotion_gates.py -x -q` — **84 passed**. This validates promotion evaluator contracts, not actual multi-replica RC behavior.
- `uv run ruff check .` — passed.
- `uv run ruff format --check .` — passed (3364 files).
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — passed: 1321 findings match the reviewed baseline; no unbanked identities.
- `uv run python scripts/check-suite-inventory.py` — failed collection in four `extensions/reference-gallery` suites due to missing imports (`gallery_weather_connector`, `gallery_unit_skill`, `gallery_model_adapter`, `gallery_renderer_pack`). It reports 32,371 collected identities and explicitly says not to update inventory for broken collection. No inventory baseline or test inventory note was changed.
- Re-evaluated `docs/testing/soak/evidence/m3a-round30-shakedown.json` with `failed_promotion_checks`: sustain duration is 420.08s and failed checks are `sustain_duration` and `exact_rc_artifact`; evidence identifies topology `host-uvicorn-preflight` and says it is not the exact production Compose image/configuration.

## Acceptance disposition

The issue's ten acceptance criteria remain unmet or unverified for promotion. In particular, `docs/testing/soak/m3a-load-profile.md` specifies a minimum 14,400-second promotion window and says the host-process harness cannot pass `exact_rc_artifact`; its remaining profile gaps include concurrent users/Workspaces, Graph/node fan-out, successful tool/model and Canvas work, Goal reconciliation, physical Attempt fencing, pool saturation, lease reclaim, and long-window observations. The existing multi-replica and task-admission probes do not establish those production-path properties. `packages/maistro-server/src/maistro_server/api/rate_limit.py` is process-local, and `tests/test_soak_promotion_gates.py::test_replica_selection_has_an_independent_production_allowance` explicitly demonstrates each replica retaining its own allowance, so shared per-principal cluster-wide limits are not proven.

The accepted execution contract remains `Goal -> Graph -> Run -> NodeRun -> Attempt`. ADR-082126-f69c supersedes ADR-046 and rejects a second scheduler/runtime; nothing in this validation introduces one. ADR-073126-c4e1 requires an immutable RC from `develop` to be soaked there, and a changed candidate requires a new RC.

## Disposition

No code-only repair can convert the existing host preflight artifact into exact-RC production evidence. The prior `BLOCKED` status is therefore unresolved, not waived: a release owner must designate the immutable production Compose image/configuration, run the representative multi-replica workload for at least four hours, execute the required physical-work/fault-recovery probes, and publish evidence tied to those hashes. Do not promote on the current evidence.
