# Issue #860 repair — d97abc74

## Frozen scope

- Issue: #860 only; branch `auto-860` in `/home/dev/Git/wt/auto-860`.
- Starting head: `dfd9c14f0eb767db7c2b1659756e5cee98241533`.
- Base: `b1f17b8d6246d347f617fb2c0b969e6798e0152b`.
- Worktree was clean. No salvage patch needed.
- Inputs: supplied dispatch-context.json, prior result 3a45bbe4, historical
  98a11313/check-3.log. Current job directory contained no check-*.log files.
- Review scope: existing soak runner and promotion tests, load profile, applicable
  ADRs, pg_learnings schema fence/test, server task backpressure/test, required
  vulture checker/ledger and CI configuration. No other issue or PR is processed.
- Editable scope: this report; reviewed vulture identities only if the required
  scan produces actionable findings; the above runtime/tests only if reproduced
  failures justify repairs (with inventory notes for test additions).

## Initial evidence and assumption

The historical check-3.log failed on 24 schema statements versus 21 expected.
The preceding result says this no longer reproduces; that claim is not accepted
without fresh execution. This is a writer CI-repair round, not a request to alter
runtime authority or claim production promotion. Existing evidence is preserved.

## Recorded progress

Required exact vulture scan PASS: 1332 reviewed identities / 1332 findings,
zero unclassified and zero forbidden. No ledger amendment is warranted: there
are no new retained identities to bank and no demonstrated dead-code repair.
The dispatch issue body has ten acceptance criteria. Its long-running exact-RC
requirement cannot be replaced by host-process preflight or static/unit checks.
Fresh schema module execution: 37 passed, 6 skipped. Current expected DDL
already includes all three Gauntlet audit columns at
`packages/maistro-core/tests/persistence/test_pg_learnings.py:175-177`.
The historical 24-versus-21 failure does not reproduce; no test repair warranted.

Focused soak/boot/gitleaks/backpressure execution: 82 passed. Repository lint,
format, suite inventory, and backlog checks also passed. See command table below.

Accepted ADR-081226-69ee keeps Graph/Run/NodeRun/Attempt canonical;
ADR-081626-f383 assigns fencing to the Run store and explicitly excludes implicit
lease-expiry takeover. ADR-085 requires principal-keyed rate limiting. The issue
cannot authorize a competing execution/reclaim authority or turn per-replica
limits into proof of a shared principal budget. No runtime authority is changed.

## Executed commands

Validation commands used 1200-second timeouts in the assigned worktree.

| Command | Outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1332/1332 identities; exact `.github/workflows/quality.yml:1013` invocation. |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 37 passed, 6 skipped; skipped integration tests are not live PostgreSQL proof. |
| `uv run ruff check .` | PASS. |
| `uv run ruff format --check .` | PASS, 3105 files formatted. |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py tests/test_gitleaksignore_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | 82 passed. |
| `uv run python scripts/check-suite-inventory.py` | PASS, 17 suites / 28182 unique identities / no duplicates. |
| `uv run python scripts/check-backlog-consistency.py` | PASS, 168 items. |
| `uv run python -` loading current soak module and preserved `m3a-round6-shakedown.json` | Asserted failed gates include `sustain_duration` and `exact_rc_artifact`; observed 90.43 seconds versus 14400 minimum. Asserted current `preflight_artifact_check()['ok'] is False`. |

## All acceptance criteria

| Criterion | Fresh review / executed evidence |
| --- | --- |
| Representative RC load profile | UNVERIFIED. `m3a-load-profile.md:153-172` documents missing concurrent users/Workspaces, fan-out, successful model/tool calls, Design/Canvas and background reconciliation. No immutable RC/profile selection established. |
| Two production application replicas | UNVERIFIED. `deploy/docker-compose.prod.yml:26-78` declares two services; executed ASGI tests are not live production containers. |
| Sustained saturation, queues, reclaim, retries and leaks | UNVERIFIED. Current evaluator rejects preserved 90.43-second evidence; sampler/unit tests do not establish sustained observations. Lease-expiry authority must respect the accepted ADR boundary. |
| No duplicate physical work for schedules/tasks/Runs/Attempts/Goals | UNVERIFIED. Existing backpressure tests use the canonical spine but do not execute physical work; profile explicitly says its schedule probe cancels the queued Run. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | NOT MET for aggregate principal allowance. Executed `tests/test_soak_promotion_gates.py:439-488` verifies the same identity receives `[200,200,429]` independently from each production middleware instance. `api/rate_limit.py:72` constructs a local limiter, registered at `maistro_server/main.py:648`. Sustained security/degraded proof remains UNVERIFIED. |
| Complete telemetry with thresholds | UNVERIFIED. Profile admits driver loop lag is not application loop lag and required worker/pool/reclaim/leak observations remain incomplete. Passing accounting tests do not supply production measurements. |
| Kill/restart during active work with drain/fencing/recovery | UNVERIFIED. Boot-cleanup regression tests passed; no new live active-Attempt recovery experiment ran. |
| Long-running exact RC/configuration soak | NOT MET by evaluated evidence: duration and artifact gates fail. `scripts/soak/run_soak.py:730-741` rejects host-process preflight as exact production Compose evidence even at longer duration. |
| Findings filed/reclassified before promotion | UNVERIFIED. Backlog consistency passes but does not establish external filing completeness; GitHub mutations are prohibited. |
| Machine/human evidence bound to image/package/commit/config hashes | UNVERIFIED for production soak. Existing preflight artifacts are preserved; this report is validation evidence only. |

## Disposition

**BLOCKED** for issue acceptance, not a reproduced CI defect. Only this report
changed. No production, test, inventory, ledger, grant or gate edits are warranted.
No tests added, so no inventory-delta note is required. No new soak was run:
the available runner cannot attest the requested RC artifact, and another short
preflight would not resolve that blocker.

Next action is release/architecture input: select immutable RC image/config and
representative workload applicability, reconcile aggregate rate-budget expectations,
and provide physical-work/recovery oracles. Then implement/run the exact production
profile for at least four hours with complete telemetry and hash-bound evidence.
Do not redispatch the stale schema failure or request speculative ledger changes.

Progress: {checked: 1, done: 0, skipped: 0, errors: 0,
next: exact-RC acceptance prerequisites}. Validation/handoff complete; issue not
complete. Local commit is documentation only, not integration approval.
