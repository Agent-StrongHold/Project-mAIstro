# Issue #860: round 14 CI repair and acceptance validation

## Frozen scope

- Assigned issue #860 only, branch `auto-860`, assigned worktree `/home/dev/Git/wt/auto-860`.
- Verified starting HEAD `0393484081918c7adbf4341d481d7314398ffb03` and base `8e8db3ad21dc7deaa5c75097e281ecbc52fd7ac5`; initial worktree clean.
- Repair file scope: `quality/vulture-baseline.json` under the explicit CI-repair exception, genuinely dead identities identified by the requested gate (if any), and this handoff. No speculative production changes or replacement soak infrastructure.
- Validation scope: existing soak harness and promotion tests, adjacent persistence/task/rate-limit tests, supported deployment configuration and relevant ADRs, historical profile/evidence. No test additions planned.
- Job snapshot: `/home/dev/maistro/jobs/977264d33ce241d79cdb982cf124e4c9` contained `events.jsonl`, `manifest.json`, `prompt.txt`, `state.json`; no `check-*.log` files were supplied. Driver successes are not assumed.
- Read the supplied prior result and round-13 handoff. Their results are historical, not fresh validation.

## Assumptions / initial findings

Writer assignment. No immutable promotion RC image/configuration is designated in the assignment. The current profile explicitly calls the harness a host-process preflight incapable of promotion signing. Historical round-6 evidence is a 90-second shakedown, not the required >=4-hour soak. The H3 shared-store overclaim in the supplied prior findings is already corrected in the current human evidence; do not make a redundant cosmetic repair. External issue filing is prohibited; classification can only be recorded locally.

## CI-repair checkpoint

Executed the exact requested Vulture command with a 1200-second timeout:

`uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`

PASS: 1402 reviewed identities -> 1402 findings, zero unclassified, zero never-allowlist findings, no candidate ledger deltas. The gate automatically selected trusted base `5ea8ef71ad6a` and candidate `039348408191`; log: job directory `writer-vulture.log`. No evidence justifies amending the ledger or deleting code. The assigned base remains `8e8db3ad21dc7deaa5c75097e281ecbc52fd7ac5`; no refs were fetched or changed.

Read repository instructions and ADR-081426-1f7c, ADR-081626-f383, ADR-085, ADR-083026-a91e (Accepted), and ADR-081 (Proposed). Canonical Goal -> Graph -> Run -> NodeRun -> Attempt ownership is unchanged. Admission uniqueness is not physical-effect fencing proof; missing measurements cannot be reported as zero. Proposed deployment guidance cannot waive the exact-RC requirement. Per-principal rate policy does not itself establish shared state: the production middleware explicitly documents independent replica allowances. No competing scheduler, store, event authority or authorization path is introduced.

## Fresh validation

Commands ran with 1200–1800 second timeouts; logs are in the job directory named above.

| Command | Result | Log |
| --- | --- | --- |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q -rs` | **102 passed, 5 skipped in 14.38s**. PostgreSQL tests skipped because `MAISTRO_TEST_PG_DSN` was not set; no live PostgreSQL claim. | `writer-pytest.log` |
| `uv run ruff check .` | PASS | `writer-ruff-check.log` |
| `uv run ruff format --check .` | PASS, 2624 files | `writer-ruff-format.log` |
| `uv run python scripts/check-suite-inventory.py --suite tests/` | PASS, 4198 tests | `writer-inventory.log` |
| `uv run python -` (import current harness; evaluate preserved round-6 JSON) | PASS: asserts 90.43 < 14400 seconds, failed gates exactly `sustain_duration` and `exact_rc_artifact`, current `preflight_artifact_check().ok == False` | `writer-evidence-check.log` |

No tests were added or modified; inventory delta is zero, so no inventory amendment is needed. Fresh evaluation of historical JSON is not a new soak.

Reachability inspection: `maistro_server/main.py:478` installs the production `RateLimitMiddleware`; lines 544 and 559 mount the task router. Executed middleware regressions include both authenticated and unauthenticated identities receiving `[200, 200, 429]` independently on each instance (`tests/test_soak_promotion_gates.py:439`). They falsify a shared allowance but are not deployed-replica load tests. The task backpressure test exercises the mounted production router through a real in-memory canonical spine, proves 429 plus Retry-After on the principal ceiling, another principal's admission, and re-admission after a slot is freed. The schema-fence test inspects transaction/SQL order using a fake connection; it does not prove concurrent PostgreSQL boot in this round.

## Acceptance disposition

| # | Criterion | Executed evidence / disposition |
| --- | --- | --- |
| 1 | Representative RC profile | PARTIAL: read `m3a-load-profile.md`; mix and thresholds exist. Its remaining-profile-gaps section acknowledges one credential, no multi-user/Workspace population, Graph fan-out, successful tool/model calls, Design/Canvas or sustained Goal/background work. RC representativeness **UNVERIFIED**. |
| 2 | At least two application replicas | `deploy/docker-compose.prod.yml:27-62` defines two services. Historical host preflight is not execution of the designated production artifact. Fresh two-RC-replica execution **UNVERIFIED**. |
| 3 | Sustained saturation, queue/reclaim/retry, memory/descriptors/processes and shutdown | **UNVERIFIED**: current evaluator rejects 90.43-second historical evidence; sampler regression observes a real child allocation/descriptor increase, not long-window application stability. |
| 4 | No duplicated physical work; schedule/task/Run/Attempt and Goal reconciliation | **UNVERIFIED**: admission-oracle regressions pass, but mocked receipts and historical one-occurrence admission cannot establish physical-effect uniqueness. Backpressure tests establish local canonical admission behavior, not cross-replica physical-work fencing. |
| 5 | Rate/security/degraded behavior cannot be bypassed by replica selection | **NOT MET** for a cluster-wide principal allowance: production middleware counterexample passes for both identity classes; independent state is documented at `rate_limit.py:25-30`. Full RC security/degraded concurrency proof **UNVERIFIED**. |
| 6 | Complete PostgreSQL/loop/worker/RSS/FD/queue/error metrics with thresholds | PARTIAL: profile thresholds and process-group sampler tests exist. Application-loop latency, long-window pool/lock/query observations and complete exact-RC resource/error series **UNVERIFIED**. Five PostgreSQL tests skipped. |
| 7 | Active-work kill/restart proves drain/fencing/recovery | **UNVERIFIED**: no new kill/restart run; historical process exit/rejoin and terminal counts do not correlate in-flight Attempts with physical effects. |
| 8 | >=4-hour soak of exact promotion RC/config; repeat after runtime changes | **BLOCKED**: no immutable promotion image/configuration designated; host runner explicitly rejects artifact equivalence (`scripts/soak/run_soak.py:635`). Historical duration is 90.43 seconds (`evidence/m3a-round6-shakedown.json:165`). |
| 9 | Load findings filed/reclassified to earliest invariant | PARTIAL: historical local dispositions preserved; F11/F12 are classified as M3-A evidence-validity defects. No new load run or new load finding claimed. External filing **UNVERIFIED**, prohibited in this lane. |
| 10 | Machine/human evidence tied to exact hashes | PARTIAL: historical hash-bearing JSON and human pack inspected and preserved. Qualifying immutable RC image/configuration and sustained evidence **UNVERIFIED**. |

## Final checkpoint / required next action

**BLOCKED; not promotion approval.** Only this handoff changed. No production code, runtime configuration, tests, raw evidence, ledger or grants changed. The explicit CI-repair gate has no remaining finding at this head; an invented ledger amendment would not resolve #860.

The release owner must designate the immutable RC/configuration, resolve the aggregate rate-limit acceptance mismatch with the owning lane, and supply representative production-path workloads plus physical-effect/fencing/recovery oracles before a new >=4-hour exact-artifact soak. Any code/runtime-config change invalidates that soak. Repeating the host preflight cannot satisfy the criterion.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: designated RC and representative production-path sustained evidence}`. CI-repair validation complete; issue #860 remains incomplete. This handoff is the local writer commit checkpoint. No GitHub mutations performed.
