# #860 CI-repair validation — job 37b695e

## Disposition

**BLOCKED for promotion; no evidenced vulture repair is needed.** This is a
validation handoff, not a new soak or an integration approval. No production
code, tests, quality ledger, grants, or acceptance thresholds were changed.

Validated in `/home/dev/Git/wt/auto-860`, branch `auto-860`, at starting HEAD
`2915d4f374e609f01e1f01a35077a84d59c739ab` (initial worktree clean). Scope was
issue #860 and the supplied dispatch snapshot. No GitHub mutations were made.
The supplied job directory had no driver `check-*.log` files; the commands below
were executed afresh rather than relying on earlier verification claims.

## Executed checks

Raw logs are in job directory
`/home/dev/maistro/jobs/37b695e30c0c4afebc3373af2540b2ba/`.

| Command | Observed result | Log |
|---|---|---|
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | Exit 0; 1,322 reviewed identities match 1,322 findings; zero unclassified/never-allowlist findings | `worker-vulture.log` |
| `uv run ruff check .` | Exit 0 | `worker-ruff-check.log` |
| `uv run ruff format --check .` | Exit 0 | `worker-ruff-format.log` |
| `uv run pytest tests/test_soak_promotion_gates.py -x -q` | 84 passed | `worker-soak-tests.log` |
| `uv run pytest packages/maistro-server/tests/api/test_rate_limit.py -x -q` | 26 passed | `worker-rate-limit-tests.log` |
| `uv run python scripts/check-suite-inventory.py --suite tests/` | Exit 0; expected/collected 5,354; zero duplicate evidence | `worker-inventory.log` |
| `uv run python -` loading `scripts/soak/run_soak.py` and evaluating round-30 JSON | Assertion passed: failed gates are exactly `sustain_duration`, `exact_rc_artifact` | `worker-evidence-evaluation.log` |

The last check imported the driver using `importlib.util`, loaded
`docs/testing/soak/evidence/m3a-round30-shakedown.json` with `json.loads`, and
asserted `failed_promotion_checks(evidence) == ["sustain_duration", "exact_rc_artifact"]`.
Its exit 0 means the **rejection** was reproduced, not that the evidence passed.

The earlier inventory finding (5,353 expected versus 5,354 collected) is no
longer reproducible at this HEAD. No test additions or removals were made, so
there is no inventory delta to record. The explicit ledger-repair permission
is not a reason to edit an already exact ledger. The vulture output identifies
its automatically selected ratchet base as `2f56be40ad24`; that pass is not a
claim of validation against the separately supplied develop base
`35a72ff54d4f09429cf0b9349ecff7f3e9396f5d`.

## Acceptance audit

| Issue acceptance criterion | Evidence and remaining limitation |
|---|---|
| Representative users/Workspaces, request mix, Graph/node fan-out, schedules, queue, tools/models, Design/Canvas and workers | **UNVERIFIED.** `m3a-load-profile.md:167–183` explicitly records one-key traffic and missing successful tool/model/Canvas, fan-out and Goal/background workloads. The existing degraded-path profile is not a representative promotion proof. |
| At least two supported application replicas | **UNVERIFIED for the RC.** Historical evidence contains two direct replica origins, but `run_soak.py:744–755` declares the runner a host-uvicorn preflight, not the production Compose artifact. No new deployed replicas were exercised in this round. |
| Sustained saturation, queue growth, lease reclaim, retries, leaks and restart observations | **UNVERIFIED.** Round-30 evidence records 420.08 seconds (`m3a-round30-shakedown.json:217`) versus the profile's four-hour minimum. Executed evaluation rejects duration. |
| No duplicate physical work across schedule/task/Run/Attempt/Goal operations | **UNVERIFIED.** `m3a-load-profile.md:215–217` distinguishes admission deduplication from physical Attempt fencing and Goal reconciliation; the schedule probe cancels its queued Run without executing it. Passing evaluator tests cannot establish physical-work safety. |
| Rate limiting/security/degraded behavior cannot be bypassed by replica selection | **Not proven; counterexample reproduced.** `tests/test_soak_promotion_gates.py:477–526` exercises production middleware with the same IP/credential: each replica independently returns `[200, 200, 429]`. The production app installs that middleware at `packages/maistro-server/src/maistro_server/main.py:648`; `api/rate_limit.py:32–37` documents the independent N-times-limit budget. Six paths observing 429 do not prove a shared principal budget. Security/degraded behavior under a full promotion workload remains **UNVERIFIED**. |
| Complete PostgreSQL/application-loop/process/RSS/FD/queue/error telemetry with thresholds | **UNVERIFIED at promotion grade.** The existing suite exercises real child-process RSS/FD sampling, but `m3a-load-profile.md:180–183` distinguishes driver loop lag from application loop lag and leaves pool saturation/worker counts/long-window observations unverified. |
| Active-work kill/restart with drain/fencing/recovery | **UNVERIFIED.** Historical exit/rejoin and terminal Run counts do not establish physical-work fencing or absence of lost side effects; no current-artifact fault injection was executed. |
| Long-running exact RC artifact/configuration; rerun after changes | **Failed historical evidence check.** Executed evaluator returns `sustain_duration` and `exact_rc_artifact`; JSON records old head `c4f45b309fd622f2e8a4b315dad35e721d81aad3` at line 70 and `exact_rc_artifact.ok=false` at lines 220–222. No new RC soak was run. |
| Findings filed/reclassified before promotion | This local report records the remaining blockers; external filing/reclassification is **UNVERIFIED** and no issue mutation was permitted. |
| Machine/human evidence tied to exact promoted image/package/commit/config hashes | **UNVERIFIED for the promoted RC.** Historical machine-readable evidence and a human profile exist, but their preflight identity is not the selected promotion artifact. This validation note does not replace that evidence. |

## Architectural reconciliation and next action

Read repository instructions and the accepted ExecutionRuntime contract
(ADR-081426-1f7c), execution lease/fencing contract (ADR-081626-f383),
worker-authored write fencing decision (ADR-082426-e3ff), renewal/reclaim
amendment (ADR-082526-b36a), and per-principal rate-limit decision (ADR-085).
ADR-081's deployment proposal is **Proposed**, not an accepted waiver.

The canonical `Goal -> Graph -> Run -> NodeRun -> Attempt` model remains
unchanged. A schedule admission race is not physical execution proof, and a
process-local limit is not replica-selection-resistant enforcement. Resolving
those gaps must use the existing canonical execution and authentication seams,
not another scheduler, store, event authority, or authentication path.

The next implementation needs a promotion-capable runner for the selected,
immutable RC deployment, a justified representative workload, and observed
Attempt/side-effect fencing and application telemetry during the long window.
Replica-budget semantics also need resolution before claiming the issue's
replica-selection criterion. Extending this preflight's duration alone cannot
satisfy its deliberately false artifact gate. These are substantive remaining
work, not failures to repair by banking scanner rows or weakening gates.

Progress: checked 1 assigned issue; completed 1 CI-repair investigation;
0 items skipped; deterministic commands had 0 errors. Issue acceptance remains
blocked. This round commits only this evidence handoff.
