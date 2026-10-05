# Issue #860 — ea95403b repair checkpoint

## Frozen scope

- Assigned issue: #860 only; branch/worktree: `auto-860`, `/home/dev/Git/wt/auto-860`.
- Starting HEAD: `ea95403ba10db40cb05db317b25a32d8a3d5cc01`; supplied base: `1885c8eda09f16fc220d7fbc6e9cdb45a113ee8f`.
- Initial worktree clean; no incoming edits to salvage.
- Process the supplied dispatch snapshot only; no GitHub mutations or refreshes.
- File scope: this report, `quality/vulture-baseline.json` only if the exact instructed scan proves retained unbanked identities; issue-specific soak code/tests/inventory notes only if an evidenced repair requires them.
- No driver `check-*.log` files present in supplied job directory at initial inspection. Run local validation instead.
- Assumption: writer CI-repair lane, not verifier; explicitly permitted ledger amendment does not authorize weakening gates or claiming release readiness.

## Progress

- Exact requested vulture scan: exit 0; 1,338 findings match 1,338 reviewed identities, zero unclassified or never-allowlist findings. No ledger amendment is justified.
- `git diff --check 1885c8eda09f16fc220d7fbc6e9cdb45a113ee8f...HEAD`: exit 2, new blank line at EOF in `docs/testing/soak/issue-860-38e30d12-repair.md:108`. This newly evidenced file is the sole additional repair surface; remove only that trailing blank line.
- Prior result and full issue comments inspected from the supplied snapshot: repeated BLOCKED outcomes are not approvals. The issue requires a representative sustained multi-replica exact-RC soak, not merely passing harness tests. The reproduced EOF whitespace error is now repaired without altering prior evidence.
- `uv run ruff check .`: exit 0.
- `uv run ruff format --check .`: exit 0, 2,920 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_rate_limit.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`: exit 0, 75 passed in 4.05 s. Includes actual production middleware instances proving independent authenticated/unauthenticated replica allowances, fail-closed promotion checks, real child-process resource sampling and canonical admission backpressure mapping.
- `uv run python scripts/check-suite-inventory.py`: exit 0, all 14 suites match, 26,020 unique test identities, zero copied evidence.
- `uv run python scripts/check-backlog-consistency.py`: exit 0, 168 items.

## Architectural reconciliation

Read repository instructions, documentation authority map, ADR-081 (Proposed), ADR-085 (Accepted), ADR-081226-a66b (Accepted), and ADR-081626-f383 (Accepted). Canonical execution remains `Goal -> Graph -> Run -> NodeRun -> Attempt`; no scheduler, store, event or authorization path changes. The fencing ADR explicitly leaves expiry takeover undefined, so an issue demand for lease reclaim cannot justify inventing a competing authority. ADR-085 requires principal-keyed limiting; it does not establish a shared cross-replica budget or waive the issue's non-bypass requirement.

Production wiring is `packages/maistro-server/src/maistro_server/main.py:57,593` (imports and installs the tested middleware). `api/rate_limit.py:25-30,72-76` intentionally gives each process an independent allowance. The passing counterexample at `tests/test_soak_promotion_gates.py:439-488` is evidence of the unmet shared-budget claim, not a production soak or an approval.

## Final validation

- Repeated the exact vulture scan with `RATCHET_BASE_REV=1885c8eda09f16fc220d7fbc6e9cdb45a113ee8f`: exit 0, same 1,338 matched identities; resolver selects merge-base `94781cf6b708`. The dispatched ledger failure does not reproduce.
- `uv run python scripts/check-shipped-surface-truth.py`: exit 0.
- Executed the current soak evaluator via `uv run python` against historical `evidence/m3a-round6-shakedown.json`: assertions pass that failed checks are exactly `sustain_duration` and `exact_rc_artifact`, observed 90.43 seconds < 14,400 minimum, and `preflight_artifact_check()['ok']` is false. Recorded historical HEAD is `b31c5fdaa63b40506335bbb288889e87bdb9ba0c`, not the assigned head. This validates rejection, not a new soak.
- `git diff --check` and `git diff --check 1885c8eda09f16fc220d7fbc6e9cdb45a113ee8f`: exit 0 after the EOF repair.
- No runtime or test code changed, no services started, no new tests added. Existing inventory is verified unchanged; no new inventory delta note is required.

## Acceptance audit

| Issue criterion | Executed evidence / remaining gap |
| --- | --- |
| Representative RC profile | PARTIAL: reviewed `m3a-load-profile.md:46-103`; `:152-166` explicitly omits concurrent users/Workspaces, Graph/tool/Canvas and background-work coverage. Full representative profile UNVERIFIED. |
| At least two application replicas | `deploy/docker-compose.prod.yml:3-4,26,76-77` defines two replicas; historical evidence has two host processes. Two current exact-RC replicas UNVERIFIED; no new deployment run. |
| Sustained saturation, queue growth, reclaim, retries, leaks | Evaluator rejects 90.43-second historical evidence against 14,400 seconds. Long-window observations UNVERIFIED. |
| Exactly-once/fenced physical work and Goal reconciliation | Admission-oracle regressions pass. Historical schedule probe cancels its queued Run (`evidence/m3a-round6-shakedown.json:11-15`); sustained Goal reconciliation and physical Attempt deduplication UNVERIFIED. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | NOT MET for a shared principal allowance: real production middleware counterexample passes for both identity classes (`tests/test_soak_promotion_gates.py:439-488`). Local enforcement tests pass; complete RC concurrency/security behavior UNVERIFIED. |
| Full telemetry with thresholds | PARTIAL: profile thresholds reviewed and real Linux child-process sampler passes. Application event-loop latency, complete worker census and long-window RC measurements UNVERIFIED (`m3a-load-profile.md:157-166`). |
| Kill/restart during physical work with drain/fencing/recovery | Historical process exit/rejoin is not physical Attempt recovery evidence. Current production behavior UNVERIFIED. |
| Long-running exact RC artifact/config soak | NOT MET: evaluator rejects historical evidence; `scripts/soak/run_soak.py:635-647` always rejects host-process artifact equivalence. No selected immutable RC image/config or production-topology runner supplied. |
| Findings filed/reclassified before promotion | Local classification in `m3a-soak-evidence.md` reviewed; backlog consistency passes. External filing completeness UNVERIFIED. No GitHub mutations permitted or performed. |
| Publish hash-bound machine/human evidence | Historical machine/human records exist with old hashes; evaluator rejection reproduced. Current RC image/config/hash-bound soak evidence UNVERIFIED. |

## Handoff

**BLOCKED for issue #860 acceptance.** The only reproduced repair was trailing whitespace in the preceding report; the ledger needs no changes. This attempt does not supply the missing promotion runner, representative workloads, global-limit decision or four-hour production evidence. Do not repeat short emulator runs as a substitute. Next work requires an immutable RC image/config selection, a runner exercising that production topology and physical-work recovery, resolution of replica-selection semantics, and a fresh >=4-hour soak with complete telemetry. Preserve existing fail-closed gates.

Changed files: this report and `docs/testing/soak/issue-860-38e30d12-repair.md` (one blank line removed). Validation results above are from this attempt, not inherited claims. No policy, ledger, runtime or evidence artifacts changed. Commit locally only; no push, PR, closure or integration approval.

Checkpoint: checked 1 assigned issue; done 1 bounded CI diagnosis/whitespace repair; skipped 0 assigned items; errors 1 reproduced diff-check failure, repaired. Release acceptance remains blocked.
