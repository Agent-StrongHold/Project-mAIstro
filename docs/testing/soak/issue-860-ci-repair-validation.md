# Issue #860 — CI-repair validation

## Frozen scope

- Assigned issue: #860 only; writer/CI-repair round.
- Worktree: `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Starting HEAD: `89d0755ed28bb1d3f379325703107378410a9f18`; clean worktree.
- Supplied base `f8cc3597be20f2d46af4063e1a3f74771ab80d05` resolves, but its comparison contains unrelated branch divergence; do not repair that divergence in this lane.
- Repair candidates frozen to `quality/vulture-baseline.json` and source identities actually reported by the requested exact-debt-ledger gate. Evidence review scope: `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`, `docs/testing/soak/`, associated inventory notes, production rate middleware/task admission, and PostgreSQL learnings tests. Read adjacent architecture/ADRs as needed; no unrelated implementation changes.
- No incoming uncommitted work to salvage.
- Job directory contains no `check-*.log` files at initial inspection. Driver checks cannot be assumed green.
- Prior result reports BLOCKED. Treat those statements as hypotheses to check, not validation results.

## Assumptions and limits

The lane requests writer behavior and explicitly permits vulture-ledger repair; the generic verifier prohibition on edits does not apply. No exact RC image/configuration is designated in the supplied brief. Do not invent an RC ref or launch a four-hour run of an arbitrary artifact. Do not change authorization, scheduling, or execution authority to make a soak pass.

## Validation

- Executed `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1,402 findings / 1,402 reviewed identities; zero unclassified and zero never-allowlist findings. No unbanked identities exist to repair or amend; leave the ledger unchanged rather than manufacture a scanner fix.
- Read repository instructions, existing profile/handoff, adjacent promotion-gate and PostgreSQL learnings tests. Accepted ADR-081426-1f7c identifies physical work by Attempt, not Run. Accepted ADR-081626-f383 distinguishes stale-writer fencing from lease-expiry takeover. ADR-085 requires principal-keyed limits without specifying a shared store. ADR-081 is Proposed. Preserve canonical authority; admission-only counts cannot prove physical-work uniqueness.
- Profile explicitly identifies host-process emulation, one API key, missing Graph/Workspace/Design/Goal coverage and lack of RC-artifact equivalence.
- `uv run ruff check .`: PASS. `uv run ruff format --check .`: PASS (2,624 files).
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py -x -q -rs`: **80 passed, 5 skipped** in 11.51 seconds. Skips require `MAISTRO_TEST_PG_DSN`; no live PostgreSQL concurrency proof is claimed. The production-middleware regression gives the same identity `[200, 200, 429]` independently on each replica. CLI regressions reject synthetic four-hour preflight evidence. The real subprocess regression observes child memory/descriptor growth; task-route regression proves retryable ceiling backpressure and readmission after a slot frees, not deployed multi-replica execution.
- `uv run python scripts/check-deployment-claims.py`: PASS.
- `uv run python scripts/check-execution-lifecycles.py`: PASS (19 classified/discovered lifecycles).
- `uv run python scripts/check-merge-markers.py`: PASS.
- `DOCKER_HOST=unix:///var/run/docker.sock docker info --format '{{.ServerVersion}}'`: PASS (29.7.2). Docker availability is not the blocker; no test database or arbitrary RC deployment was started.
- Inspected reachable production wiring: `maistro_server/main.py:478` installs `RateLimitMiddleware`; `api/rate_limit.py:72` constructs a process-local limiter for each instance. `api/tasks.py:117` maps concurrency refusal to 429. The production reference Compose declares two applications but local builds and mutable dependency tags, not a designated immutable RC.
- The prior false shared-limiter statement is already corrected in `m3a-soak-evidence.md:171`. No cosmetic re-repair is warranted. `run_soak.py:635` always rejects exact-RC equivalence and its schedule probe cancels the queued Run (`:970`) without executing physical Attempts.
- Imported the current harness with `uv run python` and evaluated the four frozen historical evidence documents through `failed_promotion_checks`. All four fail both duration and exact-RC identity: `m3a-soak-evidence.json` and `m3a-repair-validation.json` each fail seven gates; `m3a-round5-final.json` fails three (90.17 seconds); `m3a-round6-shakedown.json` fails two (90.43 seconds versus 14,400). Assertions requiring both failures passed. This is evaluation of recorded flags, not independent verification of other historical claims.
- `git diff --check`: PASS.

## Acceptance disposition

| # | Criterion | Evidence and remaining gap |
|---|---|---|
| 1 | Representative release-candidate profile | PARTIAL: profile defines request mix and thresholds, but explicitly lacks concurrent users/Workspaces, Graph fan-out, successful model/tool, Design/Canvas and Goal traffic. Applicability to the selected RC is UNVERIFIED. |
| 2 | At least two application replicas | Reference Compose inspected and declares two replicas; exact-RC deployment execution is UNVERIFIED. ASGI middleware instances are not deployment evidence. |
| 3 | Sustained saturation, queue, reclaim, retry, leaks | UNVERIFIED: evaluator rejects all historical runs; 90-second shakedowns and sampler tests cannot establish long-window behavior. |
| 4 | Exactly-once/fenced physical work and reconciliation | UNVERIFIED: the schedule probe tests admission then cancels its Run. No physical Attempt correlation or sustained Goal reconciliation proof. |
| 5 | Rate/security/degraded behavior cannot be bypassed by replica selection | NOT MET for aggregate principal allowance: executed production-middleware tests prove separate allowances on replicas. Complete security/degraded behavior under RC load is UNVERIFIED. |
| 6 | Complete resource/latency/error metrics and thresholds | PARTIAL: existing process-group sampler regression passes; profile records thresholds. Application event-loop latency, complete worker census and RC observations remain UNVERIFIED. |
| 7 | Active-work kill/restart drain/fencing/recovery | UNVERIFIED: historical process rejoin and terminal Run counts do not establish physical-work fencing or no silent loss. No restart executed this round. |
| 8 | Four-hour exact-RC artifact/configuration soak | BLOCKED: no immutable RC/configuration designated; current runner always rejects exact-RC identity. No qualifying soak executed. |
| 9 | Findings filed/reclassified to earliest broken invariant | PARTIAL: existing F11/F12 classifications identify M3-A evidence validity, not runtime duplicate-work defects. External filing is UNVERIFIED; GitHub mutations prohibited. |
| 10 | Hash-tied machine/human soak evidence | PARTIAL: historical documents exist and are rejected by the current evaluator. Qualifying exact-RC image/package/configuration evidence is UNVERIFIED. |

## Handoff

Verdict: **BLOCKED**. This is a validation checkpoint, not completion of #860 or integration approval. The previous block is not a merge conflict and cannot be resolved by a debt-ledger edit: the requested gate is already green. No production, harness, historical evidence, ledger or grant changes were made. No tests were added or changed; no inventory delta is required. Only this validation document changes in this round.

Next owner must designate immutable RC images/configuration and applicable workload surfaces, resolve the aggregate rate-limit acceptance mismatch, supply a production-topology runner with physical Attempt correlation and complete application metrics, then run at least four hours on that unchanged RC. Preserve existing evidence as preflight only; runtime/configuration changes require a new soak.

Progress: checked 1 assigned issue; done 0 (acceptance blocked); skipped 0 issues; errors 0 in executed checks; 5 explicitly skipped PostgreSQL test cases. Commit this checkpoint locally; no GitHub mutation or integration action.
