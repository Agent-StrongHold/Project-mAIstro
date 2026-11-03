# Issue #860 — b11e1693 validation handoff

## Frozen scope and disposition

Assigned writer repair only: branch `auto-860`, starting HEAD
`375af7f7ad0f321c042ae0f8aae4fded5db754da`, dispatch base
`2779c99a72b464f9399306dfc40e6ce82a76b59e`. Starting tree was clean.
Read the supplied dispatch's issue acceptance and prior result, repository
instructions, load profile, adjacent tests, production middleware and governing
ADRs. No supplied `check-*.log` files existed in this job directory at entry.
Prior verification claims were not treated as current evidence.

The explicit CI-repair command passed: 1342 findings matched 1342 reviewed
identities, with zero unclassified and zero never-allowlist findings. There is
no observed unbanked identity to review or remove. The scanner selected merge
base `c560d4ccad82`, distinct from the dispatch base; both are reported rather
than silently substituted. No ledger amendment, source repair, gate change or
test addition is justified by this result. Inventory delta is zero.

## Fresh validation

| Command | Executed outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS; 1342 reviewed / 1342 findings |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS; 2985 files already formatted |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | 61 passed in 2.24s, no skips |
| `git diff --check 2779c99a72b464f9399306dfc40e6ce82a76b59e...HEAD` | PASS; prior reported trailing-blank failures not reproduced |
| `uv run python scripts/check-doc-links.py` | PASS; 1828 Markdown files, zero broken relative links |
| `git diff --check` | PASS |

A fresh `uv run python` import of the current soak module evaluated retained
round-6 evidence. Assertions confirmed failed checks exactly
`['sustain_duration', 'exact_rc_artifact']`, 90.43 seconds below the 14400-second
minimum, a different evidence commit from assigned HEAD, and a false current
preflight artifact check. This executed evaluator check is not a new soak.

Production reachability was checked at `maistro_server/main.py:627`, which
installs `RateLimitMiddleware`, and `api/tasks.py:117`, which catches
`RunConcurrencyExceeded`. The production Compose file declares two application
services; boot-contract tests exercise its environment against real startup
validation but do not launch the deployment. Exact vulture arguments match
`.github/workflows/vulture-ratchet.yml:82-85`.

## Acceptance evidence and gaps

| Acceptance criterion | Evidence / verdict |
| --- | --- |
| Representative RC profile | UNVERIFIED: `m3a-load-profile.md:152-167` explicitly lacks concurrent users/Workspaces, Graph fan-out, successful tool/model calls, Canvas and Goal/worker reconciliation coverage. |
| Two deployed application replicas | UNVERIFIED: boot-contract tests pass, but rendered configuration and ASGI instances are not a deployed production RC. |
| Sustained saturation, queue growth, reclaim, retries and leaks | UNVERIFIED: retained `evidence/m3a-round6-shakedown.json:163-165,221-224` records only 90.43 seconds against 14400 seconds. No new soak executed. |
| Schedule/task/Run/Attempt admission and physical-work uniqueness; Goal reconciliation | UNVERIFIED: admission-probe tests pass but cannot establish physical-work uniqueness. Profile lines 197-201 explain the schedule probe cancels its queued Run without executing it. |
| Rate/security/degraded behavior without replica-selection bypass | NOT MET for a cluster-wide allowance: executed `tests/test_soak_promotion_gates.py:439-488` observes `[200, 200, 429]` independently on both production middleware instances for the same identity. Local enforcement/backpressure tests pass, not full concurrent security acceptance. |
| Complete telemetry and thresholds | UNVERIFIED: real wrapper/child sampler test passes; no production application-loop latency or full worker coverage, nor sustained pool/lock/queue/leak measurements. Profile lines 158-167 retain these gaps. |
| Active-work kill/restart with drain, fencing and recovery | UNVERIFIED: process rejoin and terminal Run counts do not prove no physical loss/duplication; no current deployed recovery run. |
| Long exact-RC artifact/config soak | NOT MET: `scripts/soak/run_soak.py:635-646` always rejects host-uvicorn preflight; executed CLI tests reject even synthetic four-hour preflight evidence. |
| Findings classified to earliest broken invariant | UNVERIFIED for completeness: no new load run or remote issue mutation; historical classifications do not prove current RC completeness. |
| Machine/human evidence bound to exact artifact/config hashes | UNVERIFIED for current RC: retained evidence identifies `b31c5fdaa63b40506335bbb288889e87bdb9ba0c`, not the assigned HEAD, and lacks promoted application-image/config identity. This report is validation, not soak evidence. |

## Architecture reconciliation and next action

Accepted ADR-081626-f383 makes the canonical Run store the lease/fence authority
and explicitly excludes lease-expiry takeover from its current contract.
Accepted ADR-082426-82c7 makes occurrence identity a Run-store admission claim,
not proof of physical execution. Preserve `Goal -> Graph -> Run -> NodeRun ->
Attempt`; do not add a competing scheduler or recovery authority to satisfy
issue wording. ADR-081 is Proposed, not accepted governance.

`packages/maistro-server/src/maistro_server/api/rate_limit.py:25-30,72-78`
explicitly defines process-local budgets. Resolving the non-bypass acceptance
against that release contract is prerequisite work, not a vulture repair.

**BLOCKED.** Select an immutable RC/config, complete the representative workload
and production telemetry/physical-work recovery probes, resolve rate-limit scope,
and run the required long exact-artifact soak. Repeating the already-passing
ledger repair cannot resolve these blockers. No GitHub mutations performed.
Only this handoff is changed; no historical evidence rewritten.

Progress: checked 1 assigned issue; done 0 acceptance completions; skipped 0;
errors 0 validation-command failures. Next: production-soak prerequisites, not
another speculative ledger repair. Commit this handoff locally; no push or
integration approval.
