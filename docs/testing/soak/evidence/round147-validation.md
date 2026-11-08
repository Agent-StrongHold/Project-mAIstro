# Issue #860 — round 147 validation checkpoint

This checkpoint records what was independently verified in the assigned worktree at
`24919fcece31b2e635569e0ace7b13de40a5c3fc`. No production soak was started in
this validation-only checkpoint. The assigned job directory contained no
`check-*.log`; previous-run logs are referenced in that run's result artifact.

## Executed validation

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — passed; 1326 findings match the trusted baseline (not a candidate ledger change).
- `uv run python scripts/check-reachability.py` — failed; 169 unreachable modules, including newly unreachable `maistro.runs.admission_identity`.
- `uv run python scripts/check-ratchet-provenance.py` — failed; reachability ratchet moved from 168 to 169 and `maistro.runs.admission_identity` is absent from the candidate baseline and prior authorization.
- `uv run pytest packages/maistro-server/tests -q -x -k 'rate_limit or soak_promotion'` — passed, 26 passed / 554 deselected. This establishes regression coverage, not cluster-wide rate-limit semantics or an exact-RC soak.

## Acceptance status

Not promotion-ready. The current rate limiter is intentionally process-local, with
per-replica allowances (documented in `packages/maistro-server/src/maistro_server/api/rate_limit.py`), and the profile explicitly says this does not prove an aggregate budget across replicas. `docs/testing/soak/m3a-load-profile.md` also marks exact Compose RC execution, four-hour duration, representative user/Workspace + Graph/tool/Canvas workload, physical Attempt fencing/recovery, and application event-loop/worker measurements as unverified or outside the current emulator. The existing round-109 artifact reports 420.05 seconds and `exact_rc_artifact.ok=false`; it cannot meet the four-hour exact-artifact requirement.

No reachability ledger change is made: scanner output alone does not establish that the production module should be wired or that a reviewed disposition is appropriate. The accepted Attempt lease contract in `docs/adr/ADR-081626-f383-execution-lease-fencing.md` distinguishes durable execution authority from expiry/reclaim and does not permit treating admission-only probes as proof of physical execution fencing.
