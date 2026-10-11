# Issue #860 — a2d20602 repair checkpoint

## Frozen scope

- Only issue #860, branch `auto-860`, starting HEAD
  `c3f5844df6377e0834a4632d7211d5c0d69f6883`, supplied base
  `435dc1937e0407ab4de198ffcced49860bb14ad2` (both resolved locally).
- Worktree started clean. No salvage patch required.
- Read-only evidence: supplied dispatch snapshot, prior result and failed log,
  repository instructions, relevant ADRs, existing soak runner/profile/tests,
  adjacent production rate/admission paths, CI gate implementation/workflow.
- Candidate writes: this report; `quality/vulture-baseline.json` only if the
  mandated exact scan demonstrates retained unbanked identities; production/test
  repair only for demonstrated issue-860 defects (with inventory note if tests
  added). No other issues or remote mutation.
- No `check-*.log` files present in this job directory at initial inspection.
- Prior result reports BLOCKED, not promotion approval. Its claims require fresh
  validation. No deployment RC designation is assumed from a historical report.

## Progress

Fresh validation (1200-second command timeout):

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1323 reviewed identities / 1323 findings,
  unclassified 0, never_allowlist 0; gate-selected base `4aa68edc0b6b`.
  No unbanked identities exist to justify ledger amendment.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  PASS, 103 passed / 6 skipped, 2.62 seconds. The supplied schema-fence
  failure did not reproduce; skips do not prove live PostgreSQL behavior.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3270 files already formatted.

The branch contains extensive historical reports and inherited changes; none
will be discarded or re-enumerated. Acceptance review is complete below.

Additional fresh commands (1200-second timeout) passed:

- `uv run python scripts/check-deployment-claims.py` — component/backend existence,
  not deployed-runtime validation.
- `uv run python scripts/check-merge-markers.py` — no tracked conflict markers.
- `uv run python scripts/check-backlog-consistency.py` — 168 items valid.
- `git diff --check` — no whitespace errors.

## Evidence and architecture reconciliation

Read the supplied issue body and latest comments from the frozen dispatch JSON,
repository `AGENTS.md`, architecture guidance, accepted ADR-081226-69ee,
ADR-081626-f383, ADR-082526-b36a and ADR-085. No new RC designation is supplied
by the assignment or the latest comments. Assumption: this is a bounded CI
repair, not authorization to designate a substitute release artifact.
Immutable RC image/configuration designation remains UNRESOLVED.

The schema test already expects the three audit columns absent from the supplied
failure (`packages/maistro-core/tests/persistence/test_pg_learnings.py:171–175`).
Production acquires the advisory lock inside its transaction before DDL
(`packages/maistro-core/src/maistro/persistence/pg_learnings.py:215–216`).
The freshly executed test checks ordered statements independently; no speculative
code or ledger repair is warranted.

`packages/maistro-server/src/maistro_server/main.py:648` installs the production
rate middleware. That middleware constructs an `InMemoryRateLimiter` at
`api/rate_limit.py:93`. The executed regression
`tests/test_soak_promotion_gates.py:439` observes 200,200,429 on **each** instance
for the same authenticated/pre-auth identity. This is real middleware behavior,
not evidence of two deployed replicas or cluster-wide non-bypass. ADR-085's
principal identity contract must remain canonical; no alternate authorization
path or guessed distributed limiter is introduced in this evidence-only repair.

ADR reconciliation: preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`.
ADR-b36a extends f383's initial deferred-reclaim boundary with TTL renewal,
heartbeat and reclamation. A promotion soak must exercise that existing lease
and recovery authority, not replace it with a second scheduler or reclaimer.

## Acceptance matrix

| Issue #860 criterion | Fresh evidence / status |
| --- | --- |
| Representative users/Workspaces, request mix, fan-out, schedules, queue, tool/model, Design/Canvas, workers | UNVERIFIED. `m3a-load-profile.md:151–170` explicitly records missing populations, successful tool/model calls, fan-out, Design/Canvas and worker observations. |
| At least two supported deployed application replicas | UNVERIFIED. Tests instantiate two middleware stacks, not the RC deployment. |
| Sustained saturation, queue growth, reclaim, retry, memory/descriptor/process leaks, shutdown/restart | UNVERIFIED. Focused regressions and skipped PostgreSQL cases are not sustained load. |
| No duplicate physical work across schedule/task/Run/Attempt/Goal paths | UNVERIFIED. `m3a-load-profile.md:193–203` says the occurrence probe cancels the queued Run without execution; admission uniqueness does not establish physical-work uniqueness. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | UNVERIFIED at the required scope. Fresh production-middleware regression reproduces independent per-replica allowances. Passing backpressure tests establish only their local HTTP contract. |
| PostgreSQL/loop/workers/RSS/descriptors/queue/errors telemetry and thresholds | UNVERIFIED for RC. The profile documents missing application-loop, worker and long-window evidence. No fresh RC series captured. |
| Active-work kill/restart proves graceful drain, fencing and recovery | UNVERIFIED. No deployed active-work fault injection performed; terminal counts alone do not prove physical recovery. |
| Long-running exact RC/config soak, rerun after runtime changes | BLOCKED / UNVERIFIED. Immutable RC/config not designated. `scripts/soak/run_soak.py:730` explicitly rejects host-process certification. Executed promotion tests preserve that fail-closed contract. |
| Findings filed/reclassified to earliest broken invariant | Local limitations recorded here; external filing UNVERIFIED. No GitHub mutation allowed or performed. |
| Machine/human evidence bound to exact image/package/commit/config hashes | UNVERIFIED for RC. This report identifies the validated source head only; historical artifacts are not recertified. |

## Disposition

**BLOCKED**, not promotion- or merge-ready. Report-only change:
`docs/testing/soak/issue-860-a2d20602-repair.md`. No test additions (inventory
delta zero), no production changes, no gate/ledger/grant edits. The exact gate
has no retained unbanked identities to amend. No merge conflict exists, so no
sync or conflict resolution is warranted. All inherited work is preserved.

Next: designate immutable RC and normalized deployment configuration, complete
representative workload and telemetry coverage, reconcile the demonstrated
per-replica allowance with the required non-bypass contract through canonical
security, then run the actual long-running soak with physical-work/recovery
observation. Repeating the already-passing stale CI failure cannot unblock this.
The broad inherited branch diff is not certified by these focused checks.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "RC designation and production-soak prerequisites"}`.
This report is the locally committed writer checkpoint, not integration approval.
