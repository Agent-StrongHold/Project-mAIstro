# Issue #860 — repair job 9e134b27

## Frozen scope and initial state

- Assigned item only: #860 on `auto-860`, starting at
  `eac01d2ea68e1094c9859bf2e022cc986617abd0`; supplied base
  `4df9dd9bde4c6d03fccd1466cf9d6827a8fd4aa8` resolves locally.
- Initial worktree is clean; no incoming uncommitted work to salvage.
- Process only existing #860 soak evidence/profile/harness/tests, their changed
  production seams (`pg_learnings.py`, server `tasks.py`), and the explicitly
  requested exact-debt-ledger gate. Potential edits are this report and
  `quality/vulture-baseline.json`; expand only to identities actually reported
  by that gate, documenting them before editing.
- Read repository `AGENTS.md`, `CLAUDE.md`, and the supplied prior result.
- Job directory contains no driver `check-*.log` files. Assumption: this is the
  writer repair lane, so execute local checks rather than infer green results.
- Prior result says BLOCKED; independently check its acceptance claims. Do not
  fabricate a four-hour RC soak or substitute host-process tests for one.

## Progress

- Requested Vulture command executed successfully (exit 0): 1371 reviewed
  identities / 1371 findings, unclassified=0, never_allowlist=0, trusted base
  `4df9dd9bde4c`, candidate `eac01d2ea68e`. No unbanked/stale identities were
  reported. No ledger amendment or dead-code deletion is justified by this scan.
- Inspected the existing profile, human evidence, production Compose topology,
  production rate-limit middleware, soak regression tests and ledger checker.
  The old shared-limiter claim is already corrected. The regression explicitly
  asserts independent allowances on two production middleware instances.
- Read ADR-085 (Accepted), ADR-081 (Proposed, not accepted authority),
  ADR-081626-f383, ADR-082426-82c7, ADR-082826-b601 and ADR-083126-5e62.
  Reconciliation: occurrence admission uniqueness is not physical execution
  uniqueness; preserve the canonical Run/NodeRun/Attempt consumer and fence.
  Per-principal rate-limiting does not demonstrate shared replica budgets.
  Do not invent a scheduler, authorization path or acceptance waiver.

## Executed validation

- `uv run ruff check .` — exit 0, all checks passed.
- `uv run ruff format --check .` — exit 0, 2720 files already formatted.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q -rs`
  — exit 0, **88 passed, 5 skipped** (7.29 s). The five PostgreSQL integration
  cases require `MAISTRO_TEST_PG_DSN`; no migrated test DSN was configured.
  Passing tests include the real child-process RSS/descriptor sampler,
  real production middleware instances showing independent replica allowances,
  route-to-canonical-spine backpressure/retry behavior, and preflight artifact
  rejection. Mock HTTP gate tests are not live multi-replica execution proof.
- `DOCKER_HOST=unix:///var/run/docker.sock docker info --format '{{.ServerVersion}}'`
  — exit 0, Docker 29.7.2 available. Docker availability is not the blocker:
  no immutable selected RC image/configuration is supplied, and the existing
  driver does not execute production Compose. A further short emulator run
  would not prove the missing criterion.
- Production wiring confirmed at `maistro_server/main.py:588`: the app installs
  the same `RateLimitMiddleware` exercised by the replica-allowance test.

- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests --suite packages/maistro-server/tests --suite tests/`
  — exit 0: collected counts match (11958 / 485 / 4320 respectively).
- `uv run python scripts/check-security-inventory.py` — exit 0: 59 cited paths,
  23 inventory rows and 2 counted claims match; this does not validate all prose.
- `uv run python - <<'PY' ... PY` imported `scripts/soak/run_soak.py` and
  evaluated the frozen four JSON packs with `failed_promotion_checks`, asserting
  `sustain_duration` and `exact_rc_artifact` occur in every failure list:
  - `m3a-soak-evidence.json`: both absent-duration/artifact failures plus rate,
    failover, nonterminal, admission-availability and drain failures.
  - `m3a-repair-validation.json`: both failures plus task admission, failover,
    nonterminal, admission-availability and drain failures.
  - `m3a-round5-final.json`: 90.17 s; rate, duration and artifact failures.
  - `m3a-round6-shakedown.json`: 90.43 s; duration and artifact failures.
  Exit 0 means the rejection assertions held, **not** that any pack passed.

## Acceptance audit (all ten supplied criteria)

| Criterion | Executed evidence / disposition |
|---|---|
| Representative concurrent users/Workspaces and request/execution mix | PARTIAL: inspected `m3a-load-profile.md`; it documents a one-key degraded preflight and explicitly lists absent Graph fan-out, successful tools/models, Design/Canvas and Goal/background workloads. Representative RC coverage UNVERIFIED. |
| At least two application replicas | Production Compose declares both services; boot-contract tests pass. Historical host-process records are not an exact-RC deployment. Production multi-replica exercise UNVERIFIED in this round. |
| Sustained saturation, queue growth, reclaim, retries, leak and shutdown observations | UNVERIFIED: all four packs rejected by the current evaluator; no qualifying long-window observations. |
| Schedule/task/Run/Attempt physical uniqueness and Goal reconciliation | UNVERIFIED: admission-oracle tests pass, but one occurrence admission/cancel and terminal Run counts do not prove physical-work fencing or sustained Goal reconciliation. ADR occurrence claims and Attempt fencing remain distinct. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | NOT MET: executed `test_replica_selection_has_an_independent_production_allowance` for both identity classes. Each production middleware instance accepts two requests then returns 429; exhausting replica 1 leaves replica 2's allowance intact (`tests/test_soak_promotion_gates.py:482-486`). `maistro_server/main.py:588` installs that middleware; `api/rate_limit.py:25-30` documents the N-times budget. Full RC security/degraded behavior UNVERIFIED. |
| All requested telemetry with explicit pass/fail thresholds | PARTIAL: profile has thresholds and sampler tests pass, including a real uv child. Historical wrapper-only RSS/FD values are already marked invalid. Application event-loop latency, complete worker counts and long-window saturation/leak data remain UNVERIFIED; driver-loop lag is not app-loop lag. |
| Active-work replica kill/restart with fencing/recovery | UNVERIFIED: historical process exit/rejoin is not correlated physical Attempt recovery. Static nginx policy tests do not prove a live drain. |
| Long-running exact RC artifact/config soak; rerun after changes | NOT MET: `run_soak.py:635-645` deliberately rejects host-process artifact identity. Round 6 records 90.43 s versus 14400 s (`m3a-round6-shakedown.json:221-224`), at historical head `b31c5fdaa`, not the assigned head. No qualifying RC soak executed. |
| Findings filed/reclassified at earliest milestone invariant | PARTIAL: existing human evidence records local M3-A evidence-validity classifications. External filing UNVERIFIED; GitHub mutations prohibited. No new runtime finding or external filing claimed. |
| Machine/human evidence bound to exact hashes | PARTIAL: historical JSON/Markdown exists, but is preflight-only at old hashes. Exact RC image/config/package identity and qualifying soak evidence UNVERIFIED. |

## Handoff and residual risks

**BLOCKED, not promotion-ready.** This round independently verified the requested
CI gate already passes and the earlier rate-limit documentation correction is
present. It found no evidence justifying a ledger change or speculative runtime
repair. Only this report is changed; existing code, tests, inventory notes,
quality ledger and raw evidence are preserved. No tests were added or removed,
so no inventory delta is required.

To unblock #860, the release owner must select the immutable RC image and full
runtime configuration, resolve the replica-selection allowance requirement, and
provide a production-topology runner covering the missing workload/telemetry and
physical-work recovery oracles. Execute at least four hours on that artifact and
configuration, re-soaking after any code/runtime-config changes. Do not spend
another four hours on the current emulator expecting promotion evidence.

No GitHub mutation, integration action or issue closure performed. This report
is the local commit checkpoint; the assigned issue remains unresolved.

Progress: checked=1, done=0, skipped=0, errors=0; next=RC selection and production
soak implementation/execution, not another Vulture ledger rebank.
