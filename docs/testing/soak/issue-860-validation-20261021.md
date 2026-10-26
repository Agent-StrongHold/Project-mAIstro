# Issue #860 validation handoff — 2026-10-21

## Scope and checkpoint

Only issue #860 was processed on `auto-860`. Dispatched HEAD was
`bf2de5e38f730c5e767bbcdc37f75c10bdd7cb42`; `git status` was clean. The job
folder `/home/dev/maistro/jobs/b873df87d42341d79c1057ce367241b2` contains no
`check-*.log` files. The supplied prior artifact
`/home/dev/maistro/jobs/151ce069e7f2407da7cab40e0669e8e0/result.json` is not
accepted as fresh validation evidence. Fetched `origin` and merged the exact
`origin/develop` `5647c34bfb8be091e5935191aed37d56dca974e0` with no conflicts;
this reconciles the previous develop-sync block. Post-merge head:
`dd823e64b95e67bfbe44a7f535e232b659b2d8bd`.

## Fresh validation (post-merge)

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — PASS; 1,321 reviewed identities / 1,321 findings; zero unclassified and never-allowlist. No ledger change warranted.
- `uv run ruff check .` — PASS.
- `uv run ruff format --check .` — PASS; 3,411 files formatted.
- `uv run pytest tests/test_soak_promotion_gates.py -x -q` — PASS; 84 passed.
- `git diff --check` — PASS.

No tests were added or changed, so no suite inventory delta is applicable. This is local source/gate validation, not production acceptance evidence.

## Architecture reconciliation

Read `docs/README.md` and accepted ADR-062 (Graph Execution Protocol),
ADR-081626-f383 (Attempt execution lease/fencing), ADR-082426-82c7 (schedule
occurrence claims), ADR-085 (per-principal rate limiting), and
ADR-073126-c4e1 (release/versioning). Keep the canonical
`Goal -> Graph -> Run -> NodeRun -> Attempt` authority. In particular, the
accepted lease/fencing contract does not imply that a process restart proves a
physical Attempt has stopped; the soak harness must not become a competing
scheduler or execution authority. The issue's deployment-level concurrency
requirements remain applicable, but evidence must not overclaim current seam
probes.

## Acceptance audit

The following are checked against reachable harness behavior and the current
profile (`docs/testing/soak/m3a-load-profile.md`), not prior pass claims:

1. Representative supported RC profile — **UNVERIFIED**. Profile records open
   workload gaps: concurrent user/Workspace population, Graph/node fan-out,
   successful tool/model calls, Design/Canvas and Goal/background-worker
   reconciliation (profile lines 167–184, 215–220).
2. At least two production replicas — **UNVERIFIED**. Harness/middleware probes
   are not deployment evidence for two replicas of an exact RC.
3. Sustained load for saturation, queue/reclaim/retry/leaks/shutdown —
   **UNVERIFIED**. Profile requires >=14,400 seconds for a promotion soak
   (lines 141–152); no such exact-artifact run was performed here.
4. No duplicated physical work and Goal reconciliation — **UNVERIFIED**.
   Profile explicitly says the schedule admission probe cancels its queued Run
   without executing it and does not prove sustained Goal reconciliation or
   physical Attempt fencing (lines 210–220).
5. Concurrent security/degraded behavior without replica-selection bypass —
   **UNVERIFIED** for production topology. The passing gate suite is not a
   concurrent multi-replica deployment run.
6. Required telemetry and explicit thresholds — **PARTIAL / UNVERIFIED**.
   Profile defines metrics and thresholds, but no production measurement series
   was captured in this validation.
7. Kill/restart during work with drain/fencing/recovery proof — **UNVERIFIED**.
   No production replica was killed/restarted during active work in this round.
8. Long soak of exact promotable RC/config — **NOT MET**. `scripts/soak/run_soak.py:744–752`
   hard-codes `preflight_artifact_check()` to `ok: false` and
   `host-uvicorn-preflight`; duration cannot change this. Profile requires >=4h
   (`m3a-load-profile.md:141–152`). No release-owner-designated immutable RC
   artifact/configuration or exact-RC evidence was provided.
9. Findings filed/reclassified to earliest broken invariant — **UNVERIFIED**.
   No new production load findings were generated in this round.
10. Machine- and human-readable evidence bound to image/package/commit/config
    hashes — **NOT MET for RC**. This handoff and local tests are source-linked
    validation only, not an exact-RC soak evidence pack.

## Disposition

**BLOCKED for issue acceptance/promotion**, not blocked on local vulture,
formatting, or focused tests. The handoff resolves the previous develop-sync
block and records a clean local validation result. No guessed source changes,
ledger edits, acceptance waivers, or test relaxations are justified. Next
required work is release-owner designation of immutable RC artifact/config,
completion of representative production workloads and physical-effect/recovery
oracles, then the documented >=4-hour soak on that unchanged artifact/config.
