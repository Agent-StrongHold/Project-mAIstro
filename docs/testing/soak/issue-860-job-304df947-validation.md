# Issue #860 validation — job `304df947ebef45dcaa702357a009821a`

## Frozen scope and starting state

Processed only assigned issue #860 on `auto-860`. Starting HEAD `e199da981c90741c2d2df0239a75dd44b44ab59d` resolves; tree was clean. The supplied driver `check-*.log` files are absent, so no driver claim is treated as evidence. The prior failure log at `/home/dev/maistro/jobs/386fe4c52da248bb84cab05885cd24e8/check-5.log` records a stale server inventory expectation of 670 versus 671 collected nodes; the current checker was rerun below rather than inferred green. No merge conflict exists.

## Fresh validation

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: **PASS**, 1,236 findings / 1,236 reviewed identities, zero unclassified and zero never-allowlist identities. No `quality/vulture-baseline.json` change is warranted.
- `uv run ruff check .`: **PASS**.
- `uv run ruff format --check .`: **PASS**, 3,573 files.
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`: **PASS**, 144 passed. One Starlette deprecation warning.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-server/tests`: **PASS**, 671 expected/collected. The existing `docs/testing/inventory-notes/860-pg-learnings-schema-fence.md` records the server suite's +1 test; this failure no longer reproduces at this head.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: **PASS**, 18,565 expected/collected.

No tests were added or changed in this validation, so no inventory delta is needed. The old driver inventory failure is resolved in the current tree; no baseline or note edit was made.

## Acceptance evidence and disposition

The current issue body requires a representative multi-replica long soak against the exact promotable RC, not a test-only substitute. Repository evidence shows a real acceptance defect: `packages/maistro-server/src/maistro_server/main.py:781` installs `RateLimitMiddleware`; `packages/maistro-server/src/maistro_server/api/rate_limit.py` holds process-local state. The freshly executed promotion-gate tests exercise that middleware but are not a deployed soak. The existing evidence pack explicitly describes independent replica allowances and missing exact-RC evidence in `docs/testing/soak/m3a-soak-evidence.md:180-222`. The host-process runner also expressly rejects promotion equivalence at `scripts/soak/run_soak.py:19` and has `exact_rc_artifact` / `sustain_duration` promotion checks at lines 782-783. No current immutable RC image/config or raw deployed evidence is present in this job snapshot.

| Acceptance criterion | Result |
| --- | --- |
| Representative users/Workspaces, request mix, Graph fan-out, schedules, tools/models, Canvas and workers | **UNVERIFIED**: no representative RC workload executed. |
| Two or more supported production replicas | **UNVERIFIED** for exact RC deployment; unit/ASGI instances are not deployed replicas. |
| Sustained saturation, queue/reclaim/retry, memory and leak observations | **UNVERIFIED**: no qualifying long-running RC soak executed. |
| No duplicate physical work; Goal reconciliation and fencing | **UNVERIFIED**: admission regressions do not demonstrate correlated physical Attempt execution under sustained load. Preserve the canonical `Goal -> Graph -> Run -> NodeRun -> Attempt` authority. |
| Rate/security/degraded behavior resistant to replica selection | **NOT MET**: real middleware's process-local allowance can be increased by selecting another replica; local tests do not establish aggregate enforcement. |
| Required DB, event-loop, worker, process, RSS, descriptor, queue and error telemetry with thresholds | **UNVERIFIED**: no complete RC telemetry series captured. |
| Kill/restart during active work proves drain/fencing/recovery | **UNVERIFIED**: no deployed active-work restart performed. |
| Long-running exact RC/configuration | **NOT MET**: no immutable RC/configuration supplied and no qualifying soak run. |
| Findings filed/reclassified before promotion | **UNVERIFIED** externally; no GitHub mutation performed. |
| Machine/human evidence hash-bound to promotion artifact | **UNVERIFIED**: no current RC evidence artifact. |

Architectural review follows accepted ADR-081226-a66b (canonical Run/NodeRun/Attempt lifecycle), ADR-081626-f383 (execution lease fencing), ADR-085 (principal-keyed rate-limit contract), and ADR-073126-c4e1 (RC is cut from `develop` and soaked before promotion). These do not waive exact artifact or physical-work evidence, and no competing scheduler, execution authority or authorization path is introduced.

**Verdict: NEEDS-REPAIR / acceptance remains blocked.** The stale inventory failure is repaired at the current base and the requested exact vulture gate is clean. The actual release acceptance gaps remain; a ledger edit or another short host preflight would not address them. Next: designate immutable RC/configuration, resolve replica-selection non-bypass at the existing enforcement boundary, and execute the >=4-hour instrumented production-topology soak with physical Attempt correlation and hash-bound evidence. This checkpoint is not promotion approval.
