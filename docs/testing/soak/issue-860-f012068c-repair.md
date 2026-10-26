# Issue #860 — f012068c repair checkpoint

## Frozen scope

- Assigned issue: #860 only; branch `auto-860`.
- Starting HEAD: `50cf86c4dc03a6458250695f8587930eeab08a98`.
- Supplied develop base: `8c8fc8d6706a0837bd991c4e92138bf4d776ac9e`.
- Initial worktree clean; no incoming edits to salvage.
- Inspect existing soak profile/evidence, harness, adjacent tests, production rate
  limiter, relevant ADRs, and CI vulture gate. Modify this report; amend
  `quality/vulture-baseline.json` or genuinely dead source only if the required
  scan produces actionable findings. No other issue or authority changes.
- Job directory snapshot contains `events.jsonl`, `manifest.json`, `prompt.txt`,
  `state.json`; no driver `check-*.log` files are available.
- Prior result was BLOCKED, not acceptance evidence. Revalidate rather than
  assume its Docker, limiter, or gate claims still hold.

## Ambiguity / assumption

This is the assigned writer repair round (including the explicit ledger repair
exception), not a read-only verifier round. A missing exact RC promotion target
must not be guessed. Existing host-process evidence cannot certify a Compose RC.

## Progress

- Required CI scan executed: `uv run python scripts/check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — PASS:
  1361 findings / 1361 reviewed identities, zero unclassified or never-allowlist.
  CI workflow arguments match. No ledger amendment is justified.
- `DOCKER_HOST=unix:///var/run/docker.sock timeout 90 docker info` — exit 1,
  cannot connect to daemon. Production deployment soak remains blocked.
- Read repository instructions and accepted lease-fencing, recurrence and
  rate-limiting ADRs. Preserve canonical Goal → Graph → Run → NodeRun → Attempt;
  schedule admission is not physical-work uniqueness. ADR-085 principal-keyed
  limits do not imply a shared cluster budget. Production middleware explicitly
  implements independent allowances (`rate_limit.py:25–30,74`). No new scheduler,
  execution authority, auth path or distributed limiter is introduced here.
- `uv run ruff check .` — PASS.
- `uv run ruff format --check .` — PASS, 2802 files already formatted.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py
  tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py
  -x -q -rs` — **88 passed, 5 skipped in 2.80s**. Skips at
  `test_pg_learnings.py:766,877,896,906,917` require `MAISTRO_TEST_PG_DSN`.
  No live PostgreSQL concurrency validation is claimed.
- Executed a `uv run python` audit importing the current
  `failed_promotion_checks` over the four existing evidence packs named in the
  prior handoff: `m3a-soak-evidence.json`, `m3a-repair-validation.json`,
  `m3a-round5-final.json`, `m3a-round6-shakedown.json`. All four fail both
  `sustain_duration` and `exact_rc_artifact`; assertions passed. Round 5/6
  record 90.17/90.43 seconds, not 14400. Earlier packs lack the duration field.

All validation used 1200-second tool timeouts except the bounded Docker check.
The middleware tests execute the production limiter and credential resolver on
independent ASGI applications: the same authenticated or unauthenticated
identity receives `[200, 200, 429]` on **each** replica
(`tests/test_soak_promotion_gates.py:439–488`). This is a meaningful local
counterexample to the shared-budget claim, not an RC traffic soak. Historical
H3 wording is already corrected in `m3a-soak-evidence.md:171`; no further
cosmetic rewrite is warranted.

## Acceptance evidence

| Criterion | Current assessment |
| --- | --- |
| Representative release-candidate profile | PARTIAL / UNVERIFIED. Profile defines health/task/receipt/metrics traffic and thresholds; its remaining-gaps section explicitly lacks concurrent Workspaces, fan-out, successful model/tool calls, Canvas/Design and Goal/background reconciliation. RC-specific inclusion/exclusion remains unresolved. |
| Two application replicas | UNVERIFIED under deployed load. Production Compose defines both services; boot-contract tests passed, but Docker daemon is unreachable. |
| Sustained saturation, queue growth, reclaim, retries, leaks and restart | UNVERIFIED. Executed four-pack audit rejects duration evidence; unit tests cannot establish long-window observations. |
| No duplicate physical work across admissions, Attempts, schedules and Goals | UNVERIFIED. Admission-oracle tests passed, but the documented schedule probe cancels its queued Run without physical execution. It cannot prove Attempt fencing or Goal reconciliation. |
| Security/rate/degraded behavior without replica-selection bypass | NOT MET for shared allowance. Executed production-middleware tests reproduce fresh allowances on another replica. Security/degraded behavior under the RC load remains UNVERIFIED. |
| Complete telemetry with pass/fail thresholds | PARTIAL / UNVERIFIED. Sampler regression passed, but no RC application-loop latency, PostgreSQL contention, worker/resource/queue/error time series was captured. Driver-loop lag is not application-loop lag. |
| Active-work kill/restart with drain, fencing and recovery | UNVERIFIED. No deployment failure injection ran; historical process exit/rejoin is not physical Attempt recovery proof. |
| Long-running exact RC artifact/configuration | NOT MET. Four-pack audit fails artifact and duration gates. `run_soak.py:635–645` explicitly identifies host-uvicorn preflight, not the promoted Compose artifact. No immutable RC target was supplied. |
| Findings filed/reclassified at earliest invariant | PARTIAL / external filing UNVERIFIED. Existing F11/F12 records classify harness defects at M3-A evidence validity; no new load run or external filing occurred. GitHub mutations are prohibited. |
| Human/machine evidence tied to exact hashes | PARTIAL / promotion evidence UNVERIFIED. Historical packs exist, but none passes the current artifact/duration gates. This report is validation evidence, not a promotion signature. |

## Handoff

**BLOCKED.** Only this report changed. No source, configuration, historical
results, ledger or tests changed; no inventory delta is needed. The explicit
vulture-repair request produced no unbanked identities, so modifying the ledger
would be unjustified. No sync conflict exists and no remote mutation occurred.

Next: provide a reachable deployment runtime and immutable RC image/configuration,
resolve the replica-selection acceptance mismatch through canonical enforcement,
and complete representative workloads/telemetry before executing a ≥14400-second
RC soak with active-work failure injection and physical Attempt/fence correlation.
Any subsequent code/runtime-config change requires a fresh qualifying soak.
This local commit is a blocked handoff, not integration approval.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "#860 deployment runtime, RC identity, non-bypass and qualifying soak"}`.
