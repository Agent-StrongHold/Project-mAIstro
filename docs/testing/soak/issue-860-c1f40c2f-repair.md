# Issue #860 — bounded repair handoff (c1f40c2f)

## Scope and disposition

**BLOCKED for issue acceptance; no demonstrated vulture repair needed.**

Assigned branch/worktree: `auto-860`, `/home/dev/Git/wt/auto-860`.
Starting HEAD: `38532ce54222c5fb3f1e0ea4184f8196f5df3c21`.
Supplied base: `11376c7bef4ea7d17195b90bea8ca9a64a769bb1`.
Both references resolve; initial worktree was clean. Scope was frozen to #860,
its supplied CI-repair instruction, existing soak driver/tests/evidence,
production rate limiting/Compose wiring, and relevant governance. No remote
lists were refreshed. The supplied job directory contained no `check-*.log`
files; previous results were read but not treated as acceptance proof.

Only this report changed. Existing implementation and evidence are preserved.
No tests were added/removed, so no inventory delta is required. No ledger
amendment is justified by the actual passing scan. No gates were weakened,
and no GitHub operations were performed.

## Architecture reconciliation

Read repository instructions, documentation authority/quality guidance,
accepted ADR-081426-1f7c (runtime mechanics), ADR-081626-f383 (Attempt fencing),
ADR-085 (principal rate limiting), and proposed ADR-081 (deployment).
Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`: admission identity
counts cannot prove physical-work uniqueness. The accepted fencing ADR does
not itself establish lease-expiry takeover authority. No alternate execution,
reconciliation, or authorization path was introduced.

The documented process-local #842 limiter does not prove #860's stronger
replica-selection non-bypass criterion. The production Compose reference and
its static tests likewise do not prove a deployed exact-RC soak. Relabeling
historical emulator evidence or extending its duration cannot repair these gaps.

## Fresh validation

Commands executed in the assigned worktree with 1,200-second validation timeouts:

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  — PASS; 1,336 reviewed identities matched 1,336 findings; zero unclassified
  and zero never-allowlist findings. Provenance selected base `56332162cf63`.
  Arguments match `.github/workflows/vulture-ratchet.yml:82-85`.
- `uv run ruff check .` — PASS.
- `uv run ruff format --check .` — PASS; 3,003 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_rate_limit.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`
  — **83 passed** in 2.57 seconds. Includes real middleware replica-selection
  counterexamples for authenticated and unauthenticated identities, production
  settings/Compose contract checks, and canonical admission backpressure tests.
  These are not a live multi-replica deployment or sustained-load result.
- `uv run python scripts/check-suite-inventory.py` — PASS; 15 suites,
  27,048 unique collected identities, no duplicate evidence.
- `git diff --check 11376c7bef4ea7d17195b90bea8ca9a64a769bb1...HEAD`
  — PASS; previously reported whitespace defects were not reproduced.
- `uv run python -` imported the actual soak driver and evaluated retained
  `m3a-round6-shakedown.json`. Assertions passed: failed checks include
  `sustain_duration` and `exact_rc_artifact`; current
  `preflight_artifact_check()` returns `ok=false`, `host-uvicorn-preflight`.

Raw outputs are in the supplied job directory under `worker-*.log`.
This is fresh rejection evidence, not a newly executed production soak.

## Acceptance audit

| Criterion | Executed evidence / remaining obligation |
| --- | --- |
| Representative users/Workspaces, Graph/node, schedule, queue, model/tool, Canvas and worker profile | **UNVERIFIED**. The inspected profile explicitly documents missing surfaces at `m3a-load-profile.md:152-165`. |
| At least two application replicas | **UNVERIFIED for deployed RC**. Compose declares two services (`deploy/docker-compose.prod.yml:27-78`); passing static/ASGI tests do not boot them. |
| Sustained saturation, reclaim, retries, leaks and restart observations | **UNVERIFIED**. Evaluator rejected the retained 90.43-second run against 14,400 seconds (`evidence/m3a-round6-shakedown.json:165,221-224`). |
| No duplicate physical schedule/task/Run/Attempt work; Goal reconciliation | **UNVERIFIED**. Admission tests do not prove physical execution fencing. Profile lines 197-200 describe cancelling the occurrence probe without executing it. |
| Rate limiting/security/degraded behavior cannot be bypassed by replica selection | **Counterexample reproduced**. `tests/test_soak_promotion_gates.py:439-488` observes `[200,200,429]` independently on both replicas for the same identity. Production installs this middleware at `maistro_server/main.py:628`; `api/rate_limit.py:72-77` constructs local state. Other concurrent security/degraded claims remain **UNVERIFIED**. |
| Complete PostgreSQL, application-loop, workers, RSS/FD, queue/error telemetry and thresholds | **UNVERIFIED**. Profile lines 157-165 distinguish wrapper/process-group measurements and driver-loop latency from required application/worker evidence. |
| Active-work kill/restart drain, fencing and recovery | **UNVERIFIED**. No fresh deployed fault injection; historical process rejoin/terminal Run counts do not prove physical-work recovery. |
| Long-running exact RC artifact/configuration soak | **NOT MET by supplied evidence**. Executed evaluator rejects duration and artifact; `run_soak.py:635-646` explicitly rejects its host-process boot topology. |
| Findings filed/reclassified to earliest broken invariant | **UNVERIFIED as a complete claim**. No new load run or authorized external issue mutation occurred. |
| Machine/human evidence tied to exact promoted hashes | **UNVERIFIED**. Retained JSON names `b31c5fdaa63b40506335bbb288889e87bdb9ba0c` at line 70, not assigned HEAD, and does not establish current production image/config identity. |

## Next prerequisite

Select immutable RC images/runtime configuration and implement the missing
production-path representative workload/telemetry. Resolve the replica-selection
contract through the canonical enforcement path, then run the qualifying
four-hour soak with correlated Attempt physical-work and recovery evidence.
Do not repeat a short emulator run or cosmetic ledger edit as a substitute.

Progress: checked 1 assigned issue; done 0 acceptance-complete; skipped 0;
validation-command errors 0. This report is a local handoff, not integration
approval. Final `uv run python scripts/check-doc-links.py` passed (1,857
Markdown files, zero broken relative links); `git diff --check` passed.
