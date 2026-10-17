# Issue #860 repair — a04ced3b

## Frozen scope

- Sole item: issue #860; writer in `/home/dev/Git/wt/auto-860`.
- Starting HEAD: `e6077fc7126c13baec61fa907e0dce5ea846c07d` (verified clean).
- Supplied base: `2b897bc78b68ac900cb0432fb9dc29324d96aca8`.
- Read-only evidence scope: supplied dispatch snapshot, prior result and named failed log; repository instructions, soak runner/profile/tests, relevant ADRs and quality-gate implementation/workflow.
- Candidate edit scope: this report; `quality/vulture-baseline.json` only for reproduced retained scanner identities; actual dead code identified by that scan and corresponding tests/inventory note only if needed. No unrelated issues or PRs will be processed.
- No current-job `check-*.log` files were present at initial inspection. Run validation locally rather than infer success.
- Ambiguity: assignment says CI repair but prior result is blocked on release acceptance. Proceed with scanner repair first, then explicitly distinguish CI success from unmet release acceptance. No RC artifact/configuration is specified by the assignment.

## Progress

Initial evidence: previous result reports BLOCKED, including host-process topology, insufficient soak duration and independent replica rate allowances. These are claims to recheck, not accepted verification.

The named historical `98a11313167b41a98a420abfda80c292/check-3.log` is a schema-fence test failure (24 statements versus 21 expected), not a vulture finding. Current exact vulture command exited 0; log: `worker-vulture.log` in the current job directory. No scanner-supported ledger edit is warranted (1326 findings, 1326 reviewed identities; zero unclassified/never_allowlist; checker auto-selected trusted base `e46ad6708fda`). Supplied base resolves locally. The load profile explicitly describes a non-promotable host-process preflight with representative-workload gaps.

Executed focused schema and soak/boot/backpressure suites, repository ruff lint/format checks, shipped-surface gate and ratchet-provenance gate: all exited 0. The old schema failure does not reproduce. Logs are `worker-{schema,soak-tests,ruff,format,surface,provenance}.log` in the job directory. No new tests or runtime changes are justified by these CI targets; inventory is unchanged.

## Executed validation

All commands use the assigned worktree. Logs live under
`/home/dev/maistro/jobs/a04ced3b1cc44a50a9204604f6e669cb/`.

| Command | Result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1326/1326 identities. Same arguments as `.github/workflows/vulture-ratchet.yml:82`. |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 37 passed, 6 skipped (1.53 s); skips are not database proof. |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | 74 passed (2.23 s). |
| `uv run ruff check .` | PASS. |
| `uv run ruff format --check .` | PASS, 3195 files. |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS. |
| `uv run python scripts/check-ratchet-provenance.py` | PASS, 52 quality JSON consumers; non-failing syntax/config warnings retained in log. |
| `uv run python` importing current soak evaluator and asserting rejection of `docs/testing/soak/evidence/m3a-round30-shakedown.json` | PASS: exactly `sustain_duration` and `exact_rc_artifact` fail; 420.08 seconds versus 14400 minimum. Current preflight artifact check is false. `worker-evidence.log`. This reevaluates historical evidence, not a new soak. |
| `git diff --check` | PASS. |

## Architecture and reachable behavior

Read repository instructions and the documentation authority map plus accepted
ADRs 087 (schema evolution), 081626-f383 (Attempt fencing), 082426-82c7
(occurrence admission), 085 (principal limits), and 083026-a91e (absent metrics).
No execution authority or runtime change was introduced. Preserve
`Goal -> Graph -> Run -> NodeRun -> Attempt`.

`packages/maistro-core/tests/persistence/test_pg_learnings.py:172` already
includes the three Gauntlet columns absent from the historical failing test.
Production `pg_learnings.py:216` acquires the transaction-scoped advisory lock;
the executed test independently checks the ordered DDL within the transaction.
It is not a live multi-replica database test.

`packages/maistro-server/src/maistro_server/main.py:648` installs the actual
`RateLimitMiddleware`; its implementation constructs an `InMemoryRateLimiter`
per instance (`api/rate_limit.py:93`). The executed production-middleware test
at `tests/test_soak_promotion_gates.py:439` confirms the same identity receives
`[200, 200, 429]` independently from each instance (authenticated and anonymous).
This proves local enforcement, not resistance to selecting another replica.
The documented #842 process-local scope does not waive #860's criterion.

ADR reconciliation: a unique admitted Run is not proof of unique physical work;
Attempt fencing alone does not define lease-expiry takeover. Process restart is
not reclaim proof. Driver-loop measurements cannot replace application-loop
measurements. Do not create new scheduling/security authorities to bypass those
boundaries or turn absent measurements into passing zeroes.

## Acceptance review

| #860 criterion | Current evidence and disposition |
| --- | --- |
| Representative RC load profile | **UNVERIFIED.** Profile at `docs/testing/soak/m3a-load-profile.md:152` acknowledges missing multi-user/Workspace, fan-out, successful tools/models, Design/Canvas and Goal/background-worker workloads. Selected RC inclusion/exclusion contract was not supplied. |
| At least two deployed application replicas | **UNVERIFIED for RC.** Tests use middleware instances; the runner uses host processes, not the exact deployment artifact. |
| Sustained saturation, queue growth, reclaim, retries, resource leaks and shutdown/restart | **UNVERIFIED.** Sampler tests observe real child-process resource growth, not long-window service stability. Executed historical evaluator rejects 420.08 seconds against 14400. |
| No duplicate physical work; schedule/task/Run/Attempt and Goal reconciliation | **UNVERIFIED.** Admission regressions pass, but profile at line 202 describes one raced occurrence whose queued Run is cancelled without execution; sustained traffic has no schedules. Admission uniqueness cannot prove physical execution uniqueness. |
| Effective security/degraded behavior without replica-selection bypass | **UNVERIFIED overall; contrary allowance evidence reproduced.** Actual middleware instances independently allow the same principal/client requests after the other replica exhausts its limit. Mocked ASGI routing is not deployed-RC concurrency evidence. |
| Complete telemetry with explicit thresholds | **UNVERIFIED.** Profile supplies thresholds but distinguishes driver-loop delay from application-loop delay and identifies unmeasured detached workers, saturation, reclaim and long-window resource behavior. |
| Active-work kill/restart proves drain/fencing/recovery | **UNVERIFIED.** Boot/gate tests pass, but no active physical-work drill was run here. Exit/rejoin and terminal Run counts are insufficient. |
| Long soak of exact RC artifact/config | **UNVERIFIED / BLOCKED.** `scripts/soak/run_soak.py:730` explicitly rejects its host-process topology. Tests prove even four-hour preflight evidence cannot pass. No immutable promotion RC was selected; no new soak was executed. |
| Findings filed/reclassified at earliest broken invariant | **UNVERIFIED complete.** Historical notes are not proof of complete filing; GitHub mutations are prohibited and none were performed. |
| Machine/human evidence tied to exact image/package/commit/config hashes | **UNVERIFIED for RC.** Historical JSON and narrative exist but fail the exact-artifact gate; this report is validation evidence, not a promotion evidence pack. |

## Handoff

**BLOCKED on production acceptance**, not an unresolved merge or CI failure.
The dispatched scanner and historical test failures do not reproduce, so no
ledger, gate, source, or test edit is supported. Only this report changes.
No inventory delta is needed. No GitHub mutations or develop sync performed.

Next: select the immutable RC/configuration, use a production-topology runner
with representative workloads and full telemetry, resolve the replica-selection
requirement through the canonical security boundary, then execute at least a
four-hour exact-artifact soak correlating physical work and recovery. A longer
host-process preflight cannot satisfy these criteria. Do not retry the obsolete
schema failure or manufacture a ledger amendment when the scan passes.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: production RC prerequisites}`.
The one assigned issue is explicitly blocked; focused CI verification is complete.
This local committed handoff does not approve integration or promotion.
