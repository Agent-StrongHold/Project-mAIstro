# Issue #860 — repair checkpoint (9705deb9)

## Frozen scope

- Assigned issue: #860 only; branch `auto-860`, worktree `/home/dev/Git/wt/auto-860`.
- Starting HEAD verified: `e1945ba91984ee69fd491db77b2f716f1066ecff` (clean).
- Supplied base: `56332162cf636e9a1e8a7e346101803ed6ec7b1f`.
- Process the supplied dispatch snapshot only; do not refresh GitHub lists.
- File scope: existing #860 soak harness/tests/docs; explicit CI-repair exception
  for `quality/vulture-baseline.json` and genuinely dead identities demonstrated
  by the requested scanner. No other issue implementation or gate weakening.
- Role assumption: writer (explicit assigned repair), not read-only verifier.
- No `check-*.log` files were present in the supplied job directory at initial
  inspection. Earlier claims are not treated as validation.

## Progress

Initial worktree inspection complete. Exact assigned vulture command passed:
1336 findings match 1336 reviewed identities, zero unclassified/never-allowlist.
Log: `/tmp/860-vulture.log`. No ledger amendment is justified by actual evidence.
`git diff --check 56332162cf636e9a1e8a7e346101803ed6ec7b1f...HEAD` also passed;
prior whitespace findings do not reproduce. Supplied dispatch acceptance and
prior handoff read; acceptance validation and architecture review are next.
Final promotion remains unproven until executed evidence establishes it.

Fresh focused validation (all exit 0):

- `uv run ruff check .` — all checks passed.
- `uv run ruff format --check .` — 3003 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_rate_limit.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`
  — 75 passed in 2.46 seconds. Logs: `/tmp/860-{ruff-check,ruff-format,pytest}.log`.
- Exact vulture arguments match both blocking workflow definitions.

These tests reproduce independent allowances on two real production middleware
instances (anonymous and authenticated identities); they do not deploy the RC.
The production app installs this middleware at `maistro_server/main.py:628`.
Existing gate tests reject missing/null/host-preflight artifact evidence even
when a synthetic duration is four hours. No tests added; no inventory delta.

## Architecture reconciliation

Read repository instructions, documentation authority map, ADR-081 (Proposed),
ADR-096 (Accepted), and ADR-081626-f383 (Accepted). Production execution belongs
to maistro-server, not an independent Conductor executor. Attempt lease identity
and fencing belong to the canonical Run store. The accepted fencing ADR expressly
does not establish lease-expiry takeover; a soak must not invent that authority.
No change to `Goal -> Graph -> Run -> NodeRun -> Attempt`, scheduling, auth,
events, or stores is made. Prior result artifact confirms missing soak acceptance,
not a develop-sync conflict; no merge is warranted.

## Acceptance evidence

Fresh evaluation of retained round-6 evidence using the current imported
`failed_promotion_checks` returned `['sustain_duration', 'exact_rc_artifact']`.
Assertions verified both failures and that its code hash differs from HEAD.
Observed duration is 90.43 seconds; evidence HEAD is
`b31c5fdaa63b40506335bbb288889e87bdb9ba0c`. This is historical evidence, not a
new deployment run.

| Issue criterion | Evidence / disposition |
| --- | --- |
| Representative RC workload | **UNVERIFIED**: `m3a-load-profile.md:152-165` acknowledges missing user/Workspace population, Graph/tool/Canvas and reconciliation traffic. |
| Two application replicas | Historical preflight only; **UNVERIFIED for RC**. Compose defines two services, but `run_soak.py:635-646` explicitly boots host processes, not that artifact. |
| Sustained saturation/reclaim/retry/leak observations | **UNVERIFIED**: round-6 JSON `:221-225` records 90.43 seconds versus 14400 required; fresh evaluator rejects it. |
| Exactly-once/fenced physical work and Goals | **UNVERIFIED**: profile `:197-200` says the schedule probe cancels its queued Run, without physical Attempt execution or sustained Goal reconciliation. |
| Security/degraded behavior without replica-selection bypass | **Not established**: executed `test_replica_selection_has_an_independent_production_allowance` for both identity classes; each replica grants `[200, 200, 429]` independently. The production limiter is intentionally process-local (`api/rate_limit.py:25-30,72-77`). |
| Complete telemetry with thresholds | **UNVERIFIED**: profile `:157-165` distinguishes driver-loop from application-loop latency and acknowledges missing worker/reclaim observations; sampler unit coverage is not application soak telemetry. |
| Active-work kill/restart, drain/fencing/recovery | **UNVERIFIED**: historical exit/rejoin observations do not establish recovery of physical work; no fresh active-work run performed. |
| Long-running exact-RC artifact/config soak | **UNVERIFIED / BLOCKED**: current evaluator rejects both duration and artifact identity. A longer host preflight would still fail. |
| Findings classified to earliest invariant | Historical F-series human pack exists; completeness/external filing **UNVERIFIED**. No GitHub mutation performed. |
| Machine/human evidence bound to exact image/package/commit/config | Historical packs retained; **UNVERIFIED for assigned RC**. Executed hash assertion confirms mismatch; no exact production image/config proof. |

Final documentation validation: `uv run python scripts/check-doc-links.py`
passed (1852 Markdown files, zero broken links); `git diff --check` passed.

## Handoff

**BLOCKED** on release evidence, not vulture debt. Only this report changes;
source, gates, ledgers, tests and historical evidence remain untouched. No
speculative production change or cosmetic ledger churn can resolve these actual
acceptance gaps. Local commit is a handoff only, not integration approval.

Next prerequisite: select the immutable RC image/config and representative
production workload, resolve the replica-budget contract gap, and exercise that
artifact with physical-work recovery and application telemetry for the required
window. No exact RC soak was executed in this round, and no acceptance waiver
is inferred from passing focused tests.

Progress: checked 1 assigned issue, done 0 acceptance closures, skipped 0,
validation errors 0; next is the blocked exact-RC soak, not another speculative
vulture repair.
