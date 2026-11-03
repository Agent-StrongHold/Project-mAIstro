# Issue #860 — current-round acceptance validation

This is a validation handoff, not promotion evidence. The available harness
results cannot establish the requested release-candidate soak, and no exact
production Compose soak was run in this environment.

## Executed checks

- `uv run pytest tests/test_soak_promotion_gates.py -x -q` — passed (84 tests).
  These are harness/gate tests, not sustained production-path evidence.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — passed: 1,326 reviewed identities and 1,326 findings at base `c2d7209f1dbc`; no unbanked finding reported.
- `git diff --check` — passed before this note was added.
- No `check-*.log` files were present in the assigned job directory.

## Acceptance disposition

- Representative release-candidate mix and two application replicas: **unverified**.
  `m3a-load-profile.md` describes host uvicorn preflight and explicitly lists the
  missing users/Workspaces, Graph fan-out, successful tool/model calls,
  Design/Canvas and Goal/background reconciliation workloads.
- Sustained saturation/recovery/leak observation: **unverified**. The available
  `m3a-round109-shakedown.json` records 420.05 seconds against the 14,400-second
  minimum, and `exact_rc_artifact.ok` is false for `host-uvicorn-preflight`.
- Exactly-once/fenced physical execution: **unverified**. Schedule admission
  races do not run their Run: `scripts/soak/run_soak.py` explicitly describes
  the probe as admission-only and terminalizes it as cancelled. ADR-081626-f383
  defines Attempt fencing but does not make that probe evidence of it.
- Replica-selection-resistant rate limiting: **not proven**. The regression in
  `tests/test_soak_promotion_gates.py` confirms each replica permits its own
  `[200, 200, 429]` for the same authenticated identity. The soak driver labels
  the limiter process-local with aggregate budget multiplied by replica count.
- Telemetry thresholds, active-work termination/restart fencing, finding
  reclassification and exact image/config/commit evidence: **unverified** for
  promotion. Existing host-process evidence cannot substitute for the exact RC.

## Decision

Do not represent this round as resolving #860. There is no evidence-backed
focused implementation change that can replace the missing exact-artifact,
long-duration, multi-replica operational run. ADR-081626-f383's canonical
`Goal -> Graph -> Run -> NodeRun -> Attempt` execution authority remains intact;
no alternate scheduler or execution authority was introduced.
