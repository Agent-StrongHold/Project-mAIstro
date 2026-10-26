# Issue #860 — repair job 8df9d241

## Frozen scope

- One item: issue #860, branch `auto-860`, starting head
  `dcd07dbd56aafbda3908178a211d39644ee3abdd`, supplied base
  `af799688335f9a7dba7999a05e0e13f102c6c5ae`.
- Worktree was clean; no incoming edits to salvage.
- Repair candidates: `packages/maistro-core/tests/persistence/test_pg_learnings.py`,
  its production `pg_learnings.py`, and `quality/vulture-baseline.json` only if
  the exact CI scan identifies reviewed retained debt. Validation also covers
  existing soak promotion tests, server backpressure tests and soak runner.
- Documentation: this report and an inventory note only if test changes require it.
- No remote mutations, ref changes, unrelated ledger edits or new execution authority.

## Input evidence and assumptions

The supplied previous `check-3.log` reports 24 schema statements against a test
expectation of 21. This is historical evidence, not proof of a current failure.
The supplied prior result is BLOCKED on exact-RC soak acceptance. No `check-*.log`
files exist in this job directory at initial inspection. Assume the requested
writer role: reproduce before changing implementation or ledgers. RC identity
and representative production configuration are not supplied in the lane brief;
do not substitute host preflight evidence for them.

## Progress

The exact requested vulture scan passed: 1,328 findings and 1,328 reviewed
identities, zero unclassified/never-allowlist. Its trusted base is
`72f5dedd3db3`; candidate is `dcd07dbd56aa`. No ledger amendment is justified.
`uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`
passed (37 passed, 6 skipped). The historical failure does not reproduce:
the existing independent expectation includes the three Gauntlet columns and
all 24 schema statements. Do not remove DDL or weaken assertions to match a stale
log.

## Architecture review

Read accepted ADR-081226-a66b (canonical lifecycle), ADR-081626-f383 (Attempt
fencing), ADR-082526-b36a (later lease renewal/reclaim contract) and ADR-085
(principal rate limits). ADR-081 deployment topology remains Proposed; it cannot
waive acceptance. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt` and
canonical lease/reclaim authority. Missing soak evidence is not a missing reclaim
contract. Local rate-limit enforcement cannot be relabeled a shared budget.

## Executed validation

All commands executed in the assigned worktree with 600–1,200-second timeouts.

| Command | Result |
|---|---|
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS; 1,328 reviewed identities, no new debt |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 37 passed, 6 skipped; skipped PostgreSQL cases remain unverified |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | 66 passed |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS; 3,159 files already formatted |
| `uv run python scripts/check-deployment-claims.py` | PASS; static component/backend existence, not deployment proof |
| `uv run python scripts/check-backlog-consistency.py` | PASS; 168 items |
| `git diff --check` | PASS |

An additional `uv run python` importlib probe loaded the current
`scripts/soak/run_soak.py` and evaluated
`docs/testing/soak/evidence/m3a-round30-shakedown.json`. It returned exactly
`['sustain_duration', 'exact_rc_artifact']`; assertions required both failures.
A second assertion confirmed `preflight_artifact_check()['ok'] is False`.
No new long soak was run and no historical result is promoted to current evidence.

Production reachability checked: `main.py:648` installs `RateLimitMiddleware`,
and lines 735/755 include the tasks router. `api/tasks.py:117-125` maps
`RunConcurrencyExceeded` to 429 with Retry-After. The passing backpressure test
uses that router and the canonical in-memory execution spine, verifies distinct
principals and admission after freeing a slot; it does not simulate physical
worker recovery. The real-middleware replica-selection tests at
`tests/test_soak_promotion_gates.py:439` observe `[200, 200, 429]` independently
on each instance for the same identity (authenticated and unauthenticated).

## Every acceptance criterion

| Criterion | Current evidence and disposition |
|---|---|
| Representative RC workload | **UNVERIFIED**. `m3a-load-profile.md` documents preflight and explicitly lists missing multi-user/Workspace, Graph fan-out, successful model/tool, Design/Canvas and Goal/background workloads. No immutable promotion RC/configuration was provided. |
| At least two production replicas | **UNVERIFIED** for this candidate. ASGI middleware instances are not deployed production replicas; host-process preflight is not the Compose artifact. |
| Sustained saturation, queue growth, reclaim, backoff and leaks | **UNVERIFIED**. Historical duration gate fails. Sampler regression observes real child-process memory/FD growth, not long-window production behavior. |
| Physical-work uniqueness and Goal reconciliation | **UNVERIFIED**. Receipt identity/admission tests do not prove physical-work uniqueness; the profile's schedule race cancels its probe Run without execution and sustained mix contains no schedules. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **Not proven**. Executed production-middleware tests reproduce independent allowances. Production `api/rate_limit.py:31-37` explicitly documents process-local N-times aggregate budget. Local enforcement and backpressure pass, but cannot satisfy a cluster-wide non-bypass claim. |
| Complete telemetry with pass/fail thresholds | **UNVERIFIED**. Current profile includes preflight thresholds; driver event-loop lag is not application-loop lag, and production worker/pool/reclaim/long-window observations are missing. |
| Kill/restart during active work proves drain/fencing/recovery | **UNVERIFIED**. No current exact-RC active-work restart; boot-cleanup tests and process-rejoin/terminal counts cannot establish physical recovery. |
| Long exact-RC soak, invalidated by changes | **UNVERIFIED**. Current `run_soak.py:730` deliberately rejects host preflight. Historical artifact/duration evidence is freshly rejected. |
| Findings filed/reclassified to earliest milestone invariant | **UNVERIFIED** completeness. Local blockers recorded; no GitHub mutations are authorized or performed. |
| Machine/human evidence tied to image/package/commit/config hashes | **UNVERIFIED** for the promotion candidate. This report records focused checks, not a hash-bound production soak. |

## Disposition and checkpoint

**BLOCKED for #860 acceptance.** No current CI failure was reproduced. Only this
report changed; existing inherited work is preserved. No implementation, test,
inventory, ledger or grant changes were justified. Consequently no inventory
delta note is needed. Focused checks do not certify the entire inherited branch.

Next: obtain the selected immutable RC/configuration, complete the representative
production workload and replica-budget contract, then execute the profile's
>=4-hour exact-artifact soak with active-work restart, canonical physical-work
and reclaim observations, full telemetry and hash-bound evidence. Repeating the
same CI-only repair or another short host preflight cannot close this issue.

Checkpoint: checked 1 issue; done 0; skipped 0; validation errors 0; blocked 1.
Commit this report locally for handoff only; no push, PR, merge or closure action.
