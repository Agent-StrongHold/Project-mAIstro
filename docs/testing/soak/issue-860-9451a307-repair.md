# Issue #860 — repair job 9451a307

## Frozen scope

- Issue #860 only; branch `auto-860`, starting head `ccabb0b073c4af03d46acac3dfa6acda4b8ec8cb`, supplied base `28614700bd9ab0223eac06924a204af4a5cc25d9`.
- Initial worktree clean; no incoming edits to salvage.
- Inspect supplied dispatch context, prior result and failure log, repository instructions, relevant ADRs, `scripts/soak/run_soak.py`, adjacent soak tests, production rate-limit middleware, and the exact vulture gate/workflow.
- Candidate writes limited to this handoff, `quality/vulture-baseline.json` if actual reviewed scanner findings require the explicitly authorized repair, and genuinely dead identities identified by that scan. No speculative changes or new execution authority.
- No `check-*.log` files present in current job directory at initial snapshot. Prior result says BLOCKED; independently validate rather than adopt its claims.
- Ambiguity: this is a writer repair (not read-only verifier), as explicitly assigned. No exact release candidate deployment is specified; do not treat local host-process tests as deployment acceptance.

## Progress

- Confirmed assigned worktree/head and read previous result, actual historical failure, captured issue body and linked draft PR body.
- `uv sync --locked --extra dev`: PASS (`/tmp/860-9451-sync.log`).
- Exact requested vulture gate: PASS, 1,328 reviewed identities/findings, zero unclassified or never-allowlist (`/tmp/860-9451-vulture.log`). No actual ledger finding warrants an amendment.
- Historical `98a11313/check-3.log` is a schema test mismatch (24 actual versus 21 expected DDL statements), not a vulture failure. Fresh reproduction passes: `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` -> 37 passed, 6 skipped (`/tmp/860-9451-schema.log`). The current test independently lists the three audit-column upgrades at lines 173–177; no repair is justified.
- Focused soak/boot/gitleaks/backpressure/rate tests -> 108 passed (`/tmp/860-9451-acceptance.log`). PostgreSQL-dependent schema skips are not live database acceptance.
- Read accepted ADR-032, ADR-062 (including the retired entry-point warning), and ADR-081626-f383. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`; durable lease fencing is not a blanket exactly-once physical-effects guarantee.
- Profile review confirms explicit representative-traffic/telemetry/recovery gaps at `docs/testing/soak/m3a-load-profile.md:153-172`. Tests alone cannot close the exact-RC production acceptance.

## Additional executed validation

All validation ran locally with 1,200-second command timeouts. Log paths below
are local artifacts; results are recorded here for durable handoff.

| Command | Outcome |
| --- | --- |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py tests/test_gitleaksignore_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q` | 108 passed; `/tmp/860-9451-acceptance.log` |
| `uv run ruff check .` | PASS; `/tmp/860-9451-ruff.log` |
| `uv run ruff format --check .` | PASS, 3,151 files; `/tmp/860-9451-format.log` |
| `uv run python scripts/check-suite-inventory.py` | PASS, 17 suites, 28,959 unique identities, zero duplicate evidence; `/tmp/860-9451-inventory.log` |
| `uv run python scripts/check-merge-markers.py` | PASS; `/tmp/860-9451-markers.log` |
| `uv run python -` importing current soak evaluator and asserting rejection of historical round-30 JSON | PASS: duration 420.08 versus 14,400 seconds; failed checks `sustain_duration`, `exact_rc_artifact`; `/tmp/860-9451-evidence.log` |

The vulture command used exactly CI's arguments in
`.github/workflows/vulture-ratchet.yml:82-86`. No ledger, grant or gate change
is needed. No tests were added or changed, hence no inventory delta.

## Acceptance review

| Captured issue criterion | Fresh evidence and disposition |
| --- | --- |
| Representative RC load profile | **UNVERIFIED.** The profile explicitly excludes users/Workspaces, fan-out, successful tool/model traffic, Design/Canvas and sustained Goal reconciliation (`m3a-load-profile.md:153-172`). No selected RC justifies those omissions. |
| At least two production application replicas | **UNVERIFIED live.** Executed ASGI tests use two production middleware instances, not two immutable RC deployments. |
| Sustained saturation, growth, lease expiry/reclaim, retry/backoff, leaks and shutdown | **UNVERIFIED.** No sustained production run this round; unit tests and 420-second historical traffic cannot establish long-window properties. |
| Physical-work deduplication across schedule/task/Run/Attempt and Goal reconciliation | **UNVERIFIED.** Receipt identity/admission is not a physical-work oracle. Profile's occurrence probe cancels the queued Run rather than executing its Attempt (`m3a-load-profile.md:199-211`). |
| Rate/security/degradation effective without replica-selection bypass | **NOT PROVEN.** Freshly executed `tests/test_soak_promotion_gates.py:439-488` demonstrates independent allowances for the same credentialed or pre-auth identity. Production `main.py:648` installs this middleware; `api/rate_limit.py:95-100` constructs a process-local limiter. No deployed security soak performed. |
| PostgreSQL, application-loop, worker/process/RSS/FD, queue/error/timeout metrics and thresholds | **UNVERIFIED at promotion grade.** Profile admits driver-loop rather than application-loop measurement and missing sustained observations (`m3a-load-profile.md:153-172`). |
| Kill/restart during active work with drain/fencing/recovery | **UNVERIFIED.** No live active Attempt killed/recovered; process rejoin alone is not no-loss/no-duplication proof. |
| Long exact-RC/config soak, repeated after changes | **NOT MET by evaluated evidence.** Executed evaluator rejects historical round 30 (420.08 < 14,400 seconds); current host-process driver always rejects exact-artifact equivalence (`run_soak.py:730-741`). |
| Findings filed/reclassified at earliest broken invariant | **UNVERIFIED for completeness.** Historical findings preserved; no GitHub mutations permitted or performed. |
| Publish machine/human evidence bound to exact image/package/commit/config | **UNVERIFIED for promotion.** Historical JSON fails exact-RC gate; this file records repair validation, not new production evidence. |

## Disposition and next action

**BLOCKED for issue acceptance.** The supplied failure is stale, and the exact
ledger gate is green; inventing a code or ledger repair would not address actual
evidence. Accepted lease ADRs govern execution authority/stale-writer rejection,
not a blanket exactly-once side-effect promise. Do not weaken the issue's
physical-work observation requirement or reinterpret local rate limiting as a
cluster-wide budget. No competing scheduler, store or authorization path added.

Only this handoff file changes in this round. No production code, tests, runtime
configuration, historical evidence or ledgers changed. The remaining work needs
an explicitly selected immutable RC/configuration, representative workloads and
physical-work/telemetry oracles, resolution of the replica-selection requirement,
and an at-least-four-hour production soak. Do not repeat a deterministic-only
repair lane expecting it to supply that evidence.

Progress: {checked: 1, done: 0, skipped: 0, errors: 0,
next: exact-RC production acceptance prerequisites}. Commit locally; no push or
integration approval.
