# Issue #860 — repair checkpoint (1a39f0d4)

## Frozen scope

Only issue #860, branch auto-860, starting HEAD
1770292f6edf786554cb47a3bf2e81e51471c4bd; supplied develop base
af799688335f9a7dba7999a05e0e13f102c6c5ae. Initial worktree clean.
No GitHub mutation, synchronization, or unrelated repair is planned.

Files in repair scope: this report; packages/maistro-core/tests/persistence/test_pg_learnings.py
and its production counterpart; scripts/soak/run_soak.py;
tests/test_soak_promotion_gates.py; quality/vulture-baseline.json only if the
required scan identifies actual retained debt; a corresponding inventory note
only if tests change. Adjacent instructions, ADRs, existing evidence and CI
configuration are read-only inspection inputs.

The assigned job directory has no check-*.log files. The supplied prior
check-3.log reports the schema-fence test expected 21 statements but observed
24. The prior result explicitly reports BLOCKED, not acceptance.
Assumption: reproduce before changing anything; do not infer scanner debt or
promotion readiness from historical claims. No merge conflict exists locally.

## Progress

- Snapshot inspected; exact starting HEAD verified; incoming edits: none.
- Reproduced current schema-fence suite: 37 passed, 6 skipped. The historical
  failure no longer reproduces; do not rewrite a passing contract blindly.
- Required vulture command passed: 1,328 findings / 1,328 reviewed identities,
  zero unclassified, zero never-allowlist. Reported trusted base 72f5dedd3db3.
  No ledger amendment is justified by this scan.
- Extracted all ten acceptance criteria from supplied dispatch evidence.
  Previous BLOCKED verdict is not assumed correct.
- Fresh validation: ruff check passed; ruff format --check passed (3,159 files);
  tests/test_soak_promotion_gates.py: 65 passed; server backpressure test: 1
  passed; backlog consistency: passed (168 items).
- Important correction to prior handoff: accepted ADR-082526-b36a defines
  TTL renewal/reclamation and its canonical execution owner. Do not describe
  reclaim as an undefined architectural contract based only on the older
  ADR-081626-f383 boundary. The missing evidence is production soak coverage,
  not permission to invent another recovery authority.

## Executed validation

All commands used `uv run` and long timeouts (1,200 seconds):

| Command | Result |
|---|---|
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 37 passed, 6 skipped; includes the reported schema-fence regression. |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | Passed; 1,328 reviewed findings, zero unclassified/never-allowlist. Matches `.github/workflows/vulture-ratchet.yml:82-85`. |
| `uv run ruff check .` | Passed. |
| `uv run ruff format --check .` | Passed; 3,159 files. |
| `uv run pytest tests/test_soak_promotion_gates.py -x -q` | 65 passed. |
| `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | 1 passed. |
| `uv run python scripts/check-backlog-consistency.py` | Passed; 168 items. |
| `uv run python` importlib evaluation of current soak runner against `docs/testing/soak/evidence/m3a-round30-shakedown.json` | Asserted rejected gates contain `sustain_duration` and `exact_rc_artifact`; exactly these two failures returned. Asserted `preflight_artifact_check()['ok'] is False`. |

The schema assertion independently includes all 24 DDL statements, including
Gauntlet columns (`test_pg_learnings.py:175-177`); production executes the
upgrade under a transaction-scoped advisory lock (`pg_learnings.py:221`).
Fake-connection tests prove the statement contract, not a live concurrent
PostgreSQL boot. The six skipped cases remain unverified here.

## Architecture and evidence boundaries

Read repository AGENTS.md and CLAUDE.md, the current profile, the adjacent
production/test seams, and ADRs 081226-a66b, 081626-f383, 082526-b36a, 081,
and 085. ADR-081 is **Proposed**, not accepted authority for a deployment waiver.
ADR-085 specifies principal-keyed rate limits; current middleware documents
process-local state (`api/rate_limit.py:31-37`) and creates an
`InMemoryRateLimiter` per instance (`api/rate_limit.py:96`). Production installs
that middleware at `maistro_server/main.py:648`.

Accepted ADR-082526-b36a supplies the later reclaim contract that the older
fencing ADR leaves open. Existing implementation includes
`Container.recover_abandoned_attempts` and `AttemptExecutionService` TTL/heartbeat
support. Static presence is not load/recovery proof. Preserve
`Goal -> Graph -> Run -> NodeRun -> Attempt`, with canonical Run-store authority;
no new scheduler, authorization path, or recovery authority was introduced.

## Acceptance review (all ten issue criteria)

| Criterion | Executed evidence / disposition |
|---|---|
| Representative concurrent users/Workspaces, fan-out, schedules, task queue, tools/models, Design/Canvas, workers | **UNVERIFIED**. Current profile's "Remaining representative-profile gaps" explicitly lists omitted surfaces and one-key traffic. No immutable RC/configuration was supplied for this round. |
| At least two production application replicas | **UNVERIFIED** on this candidate. ASGI limiter instances are not deployed replicas; current runner identifies host-uvicorn preflight. |
| Sustained saturation, queue growth, expiry/reclaim, retry, memory/descriptor/process leaks | **UNVERIFIED**. Executed historical-evidence evaluator rejects duration. No sustained production run was performed. |
| No duplicate physical work across schedule/task/Run/Attempt admission and Goal reconciliation | **UNVERIFIED**. Existing admission probe tests require canonical identities, but receipt deduplication does not prove physical-work uniqueness. Profile says the schedule probe cancels its queued Run rather than executing it. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **Not established**. Executed `tests/test_soak_promotion_gates.py:439` reproduces `[200, 200, 429]` independently on each production middleware instance for the same principal/client. Local enforcement is real, but changing replica provides another local allowance. Backpressure test passes; cluster-level non-bypass does not follow. |
| Required telemetry and explicit thresholds | **UNVERIFIED** at production grade. Sampler tests pass, including actual uv child allocation/FD growth. Profile distinguishes driver-loop lag from application-loop latency and leaves worker, pool, reclaim and long-window observations unproven. |
| Kill/restart during active work, drain/fencing/recovery without loss/duplication | **UNVERIFIED**. No active-work RC restart executed. Terminal counts/rejoin alone cannot establish physical-work recovery. |
| Long soak of exact RC artifact/configuration, rerun after changes | **UNVERIFIED**. Current `run_soak.py:730` always marks host preflight as not exact RC; executed evaluator rejects the historical round30 evidence for artifact and duration. |
| Findings filed/reclassified to earliest broken milestone invariant | **UNVERIFIED** completeness. This local report records blockers; no GitHub mutation was performed or authorized. |
| Machine/human evidence tied to exact image/package/commit/config hashes | **UNVERIFIED** for this candidate. Historical evidence is not an exact-current-RC attestation. |

## Disposition and next owner

**BLOCKED for issue acceptance**, not a reproduced vulture or schema-test failure.
No production or test edits, ledger changes, grants, gate changes, or unrelated
repairs are warranted by the observed results. Only this report changed; no test
inventory delta is needed. The inherited branch-wide diff is not certified by
these focused checks.

Next owner: supply the immutable RC artifact/configuration; define/justify the
complete production workload; reconcile the principal-budget claim with the
observed per-process enforcement; run the exact-artifact long soak and active-work
restart; collect canonical physical-work/reclaim and full telemetry evidence.
Use the existing reclaim contract rather than assuming it is absent. A longer
host emulator run cannot close the exact-artifact acceptance gap.

Progress: checked 1 issue; done 0; skipped 0; validation errors 0; blocked 1.
This report is committed locally for handoff; no push or integration approval.

