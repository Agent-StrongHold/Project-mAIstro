# Issue #860 — bounded repair 4191feda

## Frozen scope

- Issue #860 only; branch `auto-860`, starting HEAD
  `aaaf6fd49e565ddf67fccb930b9b6b65c6d44f4b`; supplied base
  `af799688335f9a7dba7999a05e0e13f102c6c5ae`.
- Starting worktree clean. No salvage or develop-sync conflict.
- Use the supplied dispatch snapshot only; no GitHub mutations or new enumeration.
- Process the reported `98a11313/check-3.log` schema-fence failure first,
  the requested exact vulture gate second, and issue acceptance third.
- Candidate implementation files are `packages/maistro-core/src/maistro/persistence/pg_learnings.py`
  and its adjacent `tests/persistence/test_pg_learnings.py`; ledger changes only
  if the prescribed scan produces actual retained identities. Inventory notes
  only if tests change. This report records results even if no repair is justified.
- Current job directory has no `check-*.log` files. The supplied prior log
  reports 24 actual DDL statements versus 21 expected; prior claims are not
  treated as current validation.

## Ambiguity and assumption

The lane is a writer repair, not a read-only verifier. The exact RC artifact,
production configuration and representative workload are not specified by the
lane prompt. Do not guess them or label host-only smoke evidence as promotion
proof. Missing promotion prerequisites will remain explicit blockers.

## Validation

1. Reported schema-fence failure: **not reproducible**.
   `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`
   passed: **37 passed, 6 skipped** (PostgreSQL-dependent cases not proven).
   The current independent expectation already includes all three Gauntlet
   audit columns (`validated_evaluator_version`, `validation_run_ids`,
   `validation_content_hash`) and the 24 statements inside the transaction.
   No source/test edit is warranted by the stale 21-statement log.
2. Exact requested vulture scan: **PASS**, 1,328 findings / 1,328 reviewed
   identities; zero unclassified or never-allowlist. The gate selected trusted
   base `72f5dedd3db3`, candidate `aaaf6fd49e56`. No unbanked identities exist;
   no ledger change is warranted despite permission to amend it in this round.

## Architecture and acceptance review

Read accepted ADR-081226-a66b, ADR-081626-f383, ADR-082526-b36a and ADR-085.
Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`: Attempt leases belong
in the canonical store, with executor-owned heartbeat and fenced reclaim.
The later accepted reclaim ADR extends the earlier fencing boundary; absence
of soak proof does not mean there is no reclaim contract. ADR-081 remains
Proposed and cannot waive release acceptance. ADR-085 requires per-principal
rate limits; process-local rate counters are not evidence of a shared budget.

The current load profile explicitly describes a host-process preflight, a
minimum four-hour promotion window, and incomplete representative workload,
application-loop telemetry and physical-work recovery proof. Inspecting and
executing the existing production-seam tests next; no new scheduler or
rate-limiting authority will be introduced to paper over missing soak evidence.

## Additional executed checks

Commands ran in the assigned worktree with 1,200-second timeouts.

| Command | Outcome |
|---|---|
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | 66 passed |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS; 3,159 files already formatted |
| `uv run python scripts/check-deployment-claims.py` | PASS; static component/backend existence only |
| `uv run python scripts/check-backlog-consistency.py` | PASS; 168 items |
| `git diff --check` | PASS |

Production reachability: `maistro_server/main.py:648` installs the tested
`RateLimitMiddleware`, and lines 735/755 include the tasks router. The router
at `api/tasks.py:117` catches canonical `RunConcurrencyExceeded` and returns
429/Retry-After. Its passing test uses the real router, queue and canonical
in-memory spine, including admission after a slot is freed; it does not execute
physical work or prove multi-replica recovery.

`tests/test_soak_promotion_gates.py:439` freshly reproduces independent
production middleware allowances: the same identity gets `[200, 200, 429]`
on **each** instance, for both authenticated and unauthenticated traffic.
`api/rate_limit.py:31` documents this process-local N-times aggregate budget.
Local 429 enforcement therefore does not prove replica-selection non-bypass.

A fresh `uv run python` importlib probe loaded the current soak runner and
passed `evidence/m3a-round30-shakedown.json` to `failed_promotion_checks`:
`['sustain_duration', 'exact_rc_artifact']`. Assertions required both failures.
The same probe asserted `preflight_artifact_check()['ok'] is False`; the
current runner at `scripts/soak/run_soak.py:730` reports host-uvicorn-preflight,
not the exact production image/configuration. This is fresh rejection of
historical evidence, not a new soak.

## All acceptance criteria

| Criterion | Evidence / disposition |
|---|---|
| Representative RC workload | **UNVERIFIED**. `m3a-load-profile.md:147` explicitly lists missing concurrent users/Workspaces, Graph fan-out, successful tool/model, Design/Canvas and Goal/background workloads. Exact promotion RC/configuration not supplied. |
| At least two application replicas in supported production profile | **UNVERIFIED** for the candidate. The passing two-instance middleware tests are not deployed production replicas. |
| Sustained saturation, queue growth, expiry/reclaim, backoff and leaks | **UNVERIFIED**. Historical duration gate fails; the sampler tests do not establish a long production window. |
| No duplicate physical work across replicas, including schedules and Goal reconciliation | **UNVERIFIED**. Admission identity tests are not physical execution proof; the documented schedule probe cancels its admitted Run without executing it. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **Not proven**: independent per-replica allowances reproduced with real production middleware. Local backpressure passes; cluster-wide non-bypass remains unsatisfied. |
| Complete PostgreSQL/application-loop/worker/RSS/FD/queue/error telemetry with thresholds | **UNVERIFIED**. The profile explicitly distinguishes driver-loop lag from application-loop lag and lacks full production worker/pool/reclaim observations. |
| Kill/restart during active work proves drain/fencing/recovery | **UNVERIFIED**. No current exact-RC active-work restart was executed. Boot hygiene and receipt/terminal counts cannot prove physical-work recovery. |
| Long soak of exact RC, invalidated by code/config changes | **UNVERIFIED**. Current runner deliberately rejects host preflight; fresh historical evaluation fails artifact and duration gates. |
| Findings filed/reclassified to earliest milestone invariant | **UNVERIFIED** completeness. Blockers recorded locally; no remote filing or issue mutation authorized. |
| Publish machine/human soak evidence tied to exact image/package/commit/config hashes | **UNVERIFIED** for this promotion candidate. This report is focused validation, not a hash-bound production soak. |

## Disposition and next action

**BLOCKED for issue acceptance.** The reported CI failure is stale and the
requested vulture gate is clean. No guessed code or ledger repair is justified.
Only this report changed; inherited work remains intact. No tests were added
or changed, so no inventory delta is needed. Focused checks do not certify the
entire inherited branch. The six skipped PostgreSQL cases remain unverified.

Next action requires the selected immutable RC image and runtime configuration,
a representative workload covering the missing production surfaces, and a
promotion-capable runner. Execute at least the profile's four-hour window with
active-work restart, canonical physical-work/reclaim observations and full
telemetry, then publish hash-bound evidence. Repeating a CI-only repair cannot
satisfy this prerequisite. Do not substitute a new execution authority or weaken
the artifact/rate-limit gates.

Checkpoint: checked 1 issue; done 0; skipped 0; validation errors 0; blocked 1.
Report committed locally for handoff; no push, PR, merge or closure action.
