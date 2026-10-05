# Issue #860 — bounded repair 32cf845a

## Frozen scope

- Issue: #860 only; branch `auto-860` in `/home/dev/Git/wt/auto-860`.
- Starting HEAD: `8b7dac89fd4badab76c66bd1963fde36a25348dc` (verified, clean).
- Assigned base: `94781cf6b708a385f33a9aafcbe9f83a481b6858` (resolved).
- Evidence snapshot: job `32cf845a4e574740a0a8c58ce7a99baf` dispatch context,
  issue body/comments and linked #1672 review evidence; no remote mutations.
- Repair targets: the exact CI vulture scan and its reported identities only,
  `quality/vulture-baseline.json` if necessary, and this handoff. Inspect existing
  `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`,
  `tests/test_prod_stack_boot_contract.py`, production rate-limit/tasks middleware,
  changed package tests, `docs/testing/soak/m3a-load-profile.md`, and round6
  evidence for acceptance. No unrelated issue implementation or new scheduler.
- No driver `check-*.log` files were present in the supplied job directory.
- Ambiguity: the dispatch repeats historical failures, but supplies no current
  failed gate log. Treat those as hypotheses; run the exact gate before edits.
- Prior result `407d760f58e345679d8123a765426289/result.json` reports BLOCKED;
  it is not accepted as fresh verification.

## Progress

The exact requested vulture command passed (exit 0): 1,338 reviewed identities,
1,338 findings, zero unclassified and zero never-allowlist findings. No unbanked
identity exists to repair or retain in this snapshot. Therefore no source or
ledger amendment is justified; the CI-repair instruction is already satisfied
without manufacturing a diff. CI's `.github/workflows/quality.yml:963-966`
uses the same invocation. `uv run ruff check .` passed; `uv run ruff format
--check .` passed (2,920 files); `git diff --check
94781cf6b708a385f33a9aafcbe9f83a481b6858...HEAD` passed. Historical whitespace
findings do not reproduce at this head.

Focused regression command passed: `uv run pytest
tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py
packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py
packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` — 92 passed,
6 skipped. In particular both authenticated and unauthenticated production
middleware counterexamples execute: exhaustion on replica 1 does not exhaust
replica 2. These tests prove a limitation, not cluster-wide enforcement.

## Architecture reconciliation

Read accepted ADR-081226-69ee (Graph/Node), ADR-081226-a66b (Run/NodeRun/Attempt),
ADR-081626-f383 (canonical lease/fencing), ADR-085 (principal rate limits), and
ADR-073126-c4e1 (exact RC promotion). ADR-081 is Proposed, not authority to waive
accepted lifecycle or release contracts. Admission deduplication is not physical
Attempt fencing. ADR-085's principal identity does not establish shared replica
budgets; the production implementation explicitly has process-local state.
No alternate scheduler, authority, store, auth path, or release waiver was added.
The existing `BACKLOG.md:267-279` records the cluster-budget decision as
`engine-116`, Accepted / `gap-spec`. Implementing a new distributed limiter in
this evidence/CI repair would bypass that unresolved contract. No GitHub filing
or issue closure was attempted.

## Fresh acceptance audit

| #860 acceptance | Evidence and result |
|---|---|
| Representative users/Workspaces, request mix, Graph/tools/Canvas/workers | PARTIAL: profile exists; `run_soak.py:1271-1290` uses one credential and a degraded task/read/health mix. `m3a-load-profile.md:152-166` explicitly lists missing coverage. RC representativeness UNVERIFIED. |
| At least two production application replicas | Compose declares two services (`deploy/docker-compose.prod.yml:25-78`); boot-contract tests pass. No production stack was started this round; live RC behavior UNVERIFIED. |
| Sustained saturation, queue, expiry/reclaim, retries, leaks | NOT MET by supplied evidence: round6 sustained 90.43 seconds against 14,400 required. Long-window behavior UNVERIFIED. |
| Exactly-once/fenced schedules/tasks/Run/Attempt/Goal work | Admission HTTP-probe regression cases pass, but historical one-occurrence claim is cancelled without executing it. Physical work and Goal reconciliation across replicas UNVERIFIED. |
| Security/rate limits/degradation cannot be bypassed by replica selection | NOT MET: both production-middleware counterexamples pass, observing `[200, 200, 429]` independently on each replica for the same identity. Middleware is installed in `maistro_server/main.py:593`. Task ceiling/backpressure regression passes; security under sustained RC load UNVERIFIED. |
| Complete telemetry with pass/fail thresholds | Process-group sampler tests execute real wrapper/child resource growth. `run_soak.py:455-493,1306-1320` samples DB and driver-loop lag, not application-loop lag or all worker lifetimes. Full RC telemetry/threshold acceptance UNVERIFIED. |
| Kill/restart during active work, drain/fencing/recovery | Historical process exit/rejoin is not physical-work recovery proof. No active-work RC kill/restart executed; UNVERIFIED. |
| Long-running exact RC artifact/configuration | NOT MET: fresh evaluator rejects historical round6 on `sustain_duration` and `exact_rc_artifact`. Current preflight artifact check returns false by construction (`run_soak.py:635-647`). |
| Findings classified to earliest broken milestone | Existing engine-116 classification inspected; `check-backlog-consistency.py` passes (168 items). No new load findings generated; completeness/earliest-invariant classification UNVERIFIED. |
| Machine/human evidence tied to exact RC hashes | Historical JSON records `b31c5fdaa63b40506335bbb288889e87bdb9ba0c`, not assigned HEAD, and lacks promoted application image evidence. Current RC evidence UNVERIFIED. |

The historical JSON was evaluated directly through the current
`failed_promotion_checks`, not accepted because its stored booleans look green.
Assertions confirmed both rejection reasons and the preflight artifact failure.
No emulator rerun was started: even four hours cannot satisfy its exact-artifact
gate. This is a runner/contract blocker, not an assertion that Docker is unavailable.

A focused rerun of `uv run pytest
packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q -rs`
passed 31 and skipped six because `MAISTRO_TEST_PG_DSN` was unset. Those six
PostgreSQL cases are explicitly UNVERIFIED, not counted as passed.

## Disposition

BLOCKED for issue #860 acceptance; requested vulture CI repair needs no change.
Only this handoff is changed. No tests added or removed, so no inventory delta
note is required. No quality ledgers/grants, production behavior or gates changed.
Next: resolve the cluster-budget contract and supply a frozen RC image/config,
a representative production-topology runner, and an actual >=4-hour RC soak
covering physical fencing, recovery, and full telemetry. Preserve existing
fail-closed promotion checks. These prerequisites are not completed by rerunning
the same short host-process shakedown.

Progress: checked 1 assigned issue, completed 0, blocked 1, skipped 0 issues;
0 validation-command errors. Final `git diff --check` passed, and status showed
only this new handoff. This report is committed locally; no push or integration
approval is implied.
