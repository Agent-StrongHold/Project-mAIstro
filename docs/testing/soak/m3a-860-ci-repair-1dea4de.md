# #860 CI-repair validation — job 1dea4de

## Frozen scope and checkpoint

Assigned issue: #860 only, branch `auto-860`, worktree
`/home/dev/Git/wt/auto-860`, starting HEAD
`5dfda3e282bcbb88dfae2e85ff44e5cad5c65f10`; supplied base
`35a72ff54d4f09429cf0b9349ecff7f3e9396f5d`. Initial worktree was clean.
Use only the supplied dispatch snapshot; no GitHub mutations or re-enumeration.

Review scope: repository instructions; the issue's ten acceptance criteria;
accepted runtime, lease/fencing and rate-limit ADRs; `scripts/soak/run_soak.py`,
`tests/test_soak_promotion_gates.py`, production rate-limit middleware and its
adjacent tests; `m3a-load-profile.md` and round-30 evidence; vulture and suite
inventory gates. Planned changed file: this handoff only unless a freshly
executed gate identifies an actual repair. No speculative ledger amendments.

The job directory contains no supplied `check-*.log` files. Prior result was
read as evidence, not trusted as validation. The requested command
`uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
was executed afresh and returned 0 (raw output `/tmp/860-1dea-vulture.log`).
There is no evidenced vulture failure to repair. Focused validation and the
acceptance audit are recorded below.

Ambiguity: dispatch requests a vulture repair but the exact requested gate
passes. Proceed with evidence-based validation, not cosmetic production or
ledger edits. No immutable RC artifact/configuration is selected in the lane
brief; do not invent one or label the preflight a promotion soak.

## Executed validation

All commands ran in the assigned worktree with long timeouts. Logs are local
`/tmp/860-1dea-<name>.log`; this committed summary preserves their results.

| Command | Observed result | Log name |
|---|---|---|
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | Exit 0: 1,322 reviewed identities match 1,322 findings; zero unclassified/never-allowlist | `vulture` |
| `uv run ruff check .` | Exit 0: all checks passed | `ruff-check` |
| `uv run ruff format --check .` | Exit 0: 3,306 files already formatted | `ruff-format` |
| `uv run pytest tests/test_soak_promotion_gates.py -x -q` | Exit 0: 84 passed | `soak-tests` |
| `uv run pytest packages/maistro-server/tests/api/test_rate_limit.py -x -q` | Exit 0: 26 passed | `rate-limit-tests` |
| `uv run python scripts/check-suite-inventory.py --suite tests/` | Exit 0: 5,354 collected, inventory matches; zero duplicate evidence | `inventory` |
| `uv run python -` importing the driver and evaluating round-30 JSON | Exit 0: rejection asserted for exactly `sustain_duration`, `exact_rc_artifact`; current preflight artifact check asserted false | `evidence-evaluation` |

The evaluator check loaded `scripts/soak/run_soak.py` with `importlib.util`,
registered its module in `sys.modules`, and called `failed_promotion_checks`
on `json.loads(Path('docs/testing/soak/evidence/m3a-round30-shakedown.json').read_text())`.
Exit 0 proves the rejection, not promotion success. The exact vulture arguments
match `.github/workflows/quality.yml:1079–1082`. Its automatically selected
ratchet base was `2f56be40ad24`, not the separately supplied develop base.
No alternative-base gate pass is claimed.

The prior 5,353-versus-5,354 inventory failure is not reproducible at this HEAD.
No tests were added or removed, so no inventory delta is needed. No production
code, ledger, grants, thresholds or evidence artifacts were changed.

## Acceptance audit (all ten issue criteria)

| Criterion | Executed evidence / remaining gap |
|---|---|
| Representative users/Workspaces, Graph/node fan-out, schedules, tools/models, Design/Canvas and workers | **UNVERIFIED.** `m3a-load-profile.md:167–183` explicitly identifies missing representative workloads; one-key degraded task traffic is not a complete promotion profile. |
| At least two supported application replicas | **UNVERIFIED for the RC.** The existing two-instance middleware test ran, but this is ASGI, not two deployed application replicas. `run_soak.py:744–755` declares host-process preflight only. |
| Sustained saturation, queue growth, reclaim, backoff, leaks and restart observations | **UNVERIFIED.** Executed evaluation rejects the historical 420.08-second window (`m3a-round30-shakedown.json:217`); no current four-hour deployment run was performed. |
| Exactly-once/fenced schedule/task/Run/Attempt/Goal physical work | **UNVERIFIED.** `m3a-load-profile.md:215–217` distinguishes one cancelled admission-probe Run from physical Attempt fencing and sustained Goal reconciliation. Passing gate tests do not prove side-effect deduplication. |
| Replica-selection-resistant rate limiting/security/degraded behavior | **Counterexample reproduced.** `tests/test_soak_promotion_gates.py:477–526` passes because the same IP/principal receives `[200,200,429]` independently on both production middleware instances. `api/rate_limit.py:32–37,94–99` implements independent local budgets; `main.py:648` installs it in the production app. This disproves a shared configured budget, not per-replica enforcement. Full security/degraded behavior under promotion load remains **UNVERIFIED**. |
| PostgreSQL, application-loop, workers/processes, RSS/FDs, queue and error telemetry with thresholds | **UNVERIFIED at promotion grade.** The existing sampler/gate tests passed, but the profile at lines 180–183 distinguishes driver lag from application-loop lag and leaves worker counts, saturation and long-window observations open. |
| Active-work kill/restart, drain/fencing/recovery | **UNVERIFIED.** No current-artifact fault injection was run; gate unit tests and historical process rejoin do not prove absence of lost or duplicated physical work. |
| Long-running exact RC/configuration and rerun after changes | **Not satisfied by supplied evidence.** Executed evaluator rejects both duration and artifact. `m3a-round30-shakedown.json:220–222` records `ok=false` for exact RC; the current runner returns the same explicit refusal. |
| Findings filed/reclassified before promotion | This committed local handoff records blockers. External filing/reclassification is **UNVERIFIED**; GitHub mutations are prohibited. |
| Machine/human evidence tied to exact promoted image/package/commit/config hashes | **UNVERIFIED.** Historical preflight evidence and the human profile exist, but no selected immutable RC deployment was supplied or exercised in this round. This note is not a soak artifact. |

## Architecture and disposition

Read the accepted ADRs: ExecutionRuntime contract (ADR-081426-1f7c), execution
lease/fencing (ADR-081626-f383), worker-authored acceptance fencing
(ADR-082426-e3ff), renewal/reclaim including the transient-renewal amendment
(ADR-082526-b36a), and per-principal rate limiting (ADR-085).

Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`. Admission uniqueness
cannot substitute for physical Attempt fencing. A process-local principal
bucket cannot substantiate a cluster-wide principal allowance. The existing
middleware explicitly documents local scope; neither that documentation nor
ADR-085 supplies a waiver for the issue's replica-selection criterion. No new
scheduler, execution authority, Goal store, event authority or authentication
path was introduced.

**BLOCKED, not merge-ready.** The requested CI repair has no reproducible
scanner failure. Actual promotion acceptance requires a selected immutable RC,
a production-capable soak runner and representative workload, observed
physical-work fencing/recovery and application telemetry, and resolution of
the replica-budget gap. Running the existing emulator longer cannot fix its
artifact mismatch. These are substantive implementation/release prerequisites,
not scanner findings to bank or gates to weaken.

Checkpoint: checked 1 issue; completed 1 bounded CI-repair investigation;
0 skipped items; 0 command errors. Issue acceptance remains blocked. Only this
handoff is changed and committed locally; no integration approval is implied.
