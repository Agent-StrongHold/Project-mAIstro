# Issue #860 — repair checkpoint (5c90504a)

## Frozen scope

- Issue: #860 only; assigned worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Starting HEAD: `2b3b73133439662c6fb07c3cc61d638424bbc226`; supplied base: `e46ad6708fda20f76b8915679ef701f3ddb6b7e2`.
- Worktree initially clean; no incoming edits to salvage.
- Process the reported exact-debt-ledger failure, existing soak harness/tests/evidence,
  and this checkpoint. Candidate edit scope: `quality/vulture-baseline.json` only
  if the instructed scan demonstrates reviewed retained debt; existing implicated
  production files only if genuine dead code is demonstrated; this report.
- No new issue/PR enumeration, remote mutations, scheduler/auth changes, or claimed
  release promotion. Supplied dispatch context is the frozen evidence source.

## Initial evidence and assumptions

- Current job directory contains no `check-*.log` files. Inspect the explicitly
  supplied prior `check-3.log` instead and run validation locally.
- Prior result is BLOCKED, not a sync-conflict report; no develop merge assumed.
- Missing exact-RC deployment inputs must remain an explicit acceptance blocker;
  unit tests or historical host preflight are not a substitute for a soak.

## Results

- Prescribed vulture scan executed: PASS, 1,326 findings / 1,326 reviewed
  identities, no unclassified or never-allowlist findings. No ledger amendment
  is justified; the explicit CI-repair exception is not permission to invent debt.
- Supplied prior `check-3.log` is a schema-test failure (24 statements versus
  21 expected), not a vulture failure. Recheck that exact regression next.
- Optional `docs/testing/soak/README.md` reference did not exist; skipped. The
  existing `m3a-load-profile.md` is the actual profile document.
- Dispatch's last five comments contain repeated blocked attempts, not a selected
  immutable RC/configuration. Do not repeat a short host soak as promotion proof.
- `uv sync --locked --extra dev`: PASS (`/tmp/860-5c90504a-sync.log`).
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  37 passed, 6 PostgreSQL-dependent skips (`/tmp/860-5c90504a-schema.log`). The
  independent expected-DDL list already includes the three Gauntlet columns at
  lines 175–177; no assertion weakening or new repair is necessary.
- `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q`:
  100 passed (`/tmp/860-5c90504a-focused.log`). Includes actual production
  middleware instances granting independent `[200, 200, 429]` allowances to the
  same authenticated/unauthenticated identity on each replica; this is not a live
  production deployment soak.
- `uv run ruff check .`: PASS. `uv run ruff format --check .`: PASS, 3,195 files.
  Logs: `/tmp/860-5c90504a-ruff.log`, `/tmp/860-5c90504a-format.log`.
- `uv run python scripts/check-merge-markers.py`: PASS.
- Read accepted ADRs 081426-1f7c, 081626-f383, 082526-b36a and 073126-c4e1.
  Reconciliation: renewal/reclaim extends the earlier fencing boundary; Attempt
  identity remains physical execution authority. Neither a duplicate-admission
  count nor old host-process evidence proves the immutable RC's physical work.
- An initial read omitted `api/` in the rate-limit module path; not found,
  corrected to the explicit production import in the existing test.
- `uv run python scripts/check-suite-inventory.py --suite tests/`: PASS,
  5,116 expected/collected, zero duplicate identities
  (`/tmp/860-5c90504a-inventory.log`). No tests added or removed; no inventory
  delta note needed.
- `uv run python -` importing the current `scripts/soak/run_soak.py` and applying
  `failed_promotion_checks` to preserved `m3a-round30-shakedown.json`: negative
  assertions PASS. Historical duration is 420.08 seconds versus required 14,400;
  failed checks are `sustain_duration` and `exact_rc_artifact`. Independently
  asserted current `preflight_artifact_check()['ok'] is False`. This is fresh
  evaluation of historical evidence, NOT a new soak.

## Acceptance disposition

| Criterion | Fresh evidence / remaining boundary |
| --- | --- |
| Representative RC profile | **UNVERIFIED complete.** Read `m3a-load-profile.md:145–164` and `run_soak.py:1382–1395`: single-credential preflight mix lacks concurrent Workspaces, fan-out, successful tool/model, Design/Canvas and Goal worker traffic. |
| At least two deployed application replicas | **UNVERIFIED for RC.** Boot-contract tests pass; neither those tests nor two ASGI middleware instances deploy the selected RC. |
| Sustained saturation, queues, reclaim, retries, resource leaks | **UNVERIFIED.** Current evaluator rejects historical 420.08-second duration; sampler subprocess tests pass but are not four-hour workload observations. |
| No duplicate physical work and Goal reconciliation | **UNVERIFIED.** `run_soak.py:1044–1072` explicitly cancels the admission-probe Run without execution. The admission tests cannot establish physical Attempt uniqueness or Goal reconciliation under load. |
| Security/rate/degraded behavior without replica-selection bypass | **UNVERIFIED as a complete criterion.** Executed existing test at `tests/test_soak_promotion_gates.py:439–493`: both production middleware instances grant independent allowances. `api/rate_limit.py:32–37` explicitly promises process-local state, not a shared budget. Requires contract resolution through canonical seams, not a second authorization path. |
| Complete telemetry and thresholds | **UNVERIFIED.** Process-group measurement tests pass; `run_soak.py:1420–1430` measures driver loop lag, not application loop latency. Profile acknowledges detached-worker, pool/reclaim and long-window gaps. |
| Active-work kill/restart, drain/fencing/recovery | **UNVERIFIED.** Read `run_soak.py:1436–1489`: signals/restarts processes and records HTTP counts, without an active-Attempt physical-work oracle. No new deployment restart executed. |
| Long soak of exact RC/configuration | **BLOCKED / UNVERIFIED.** Fresh evaluator rejects duration and artifact; `run_soak.py:730–741` intentionally never certifies the host preflight. No immutable RC image/configuration selected by this dispatch. |
| Findings filed/reclassified to earliest invariant | **UNVERIFIED completeness.** Existing profile lists historical findings; no GitHub mutation permitted or performed. |
| Machine/human evidence bound to exact image/package/commit/config | **UNVERIFIED for candidate.** Preserved evidence is historical; `run_soak.py:1176–1212` hashes the host preflight, not the selected promoted application image. This report is validation evidence only. |

## Handoff

Only this report changed in this round. No production code, tests, quality
ledgers, grants, or existing evidence was modified. All validation used generous
1,200-second timeouts; no live PostgreSQL schema cases or long production soak
is claimed. There is no actual remaining scanner/schema failure to repair on
this HEAD. The supplied previous failure is stale, and the previous BLOCKED
acceptance remains unresolved for the concrete reasons above.

**BLOCKED**, not integration approval. Next: owner-selected immutable RC and
runtime configuration, representative production-path workload/instrumentation,
and an active-work recovery oracle followed by the required long soak. Do not
redispatch this lane merely to rerun the already passing vulture/schema gates.
No external actions, publication, or issue closure occurred.

Progress: {checked: 1, done: 0, skipped: 0, errors: 0, next: exact-RC acceptance prerequisites}.
Local report commit checkpoints the completed validation; #860 acceptance is not done.
