# Issue 860 — repair checkpoint (job 943b95d5)

## Frozen scope

- Issue #860 only; assigned branch `auto-860`, initial HEAD
  `9266923cafacf32e76d851f4eec4411572857e39`, supplied develop base
  `435dc1937e0407ab4de198ffcced49860bb14ad2`.
- Clean initial worktree; no salvage necessary. No check-*.log files supplied
  in this job directory. Supplied prior check-3.log reports 24 schema statements
  versus 21 expected; reproduce before changing code.
- Inspect/validate `scripts/soak/run_soak.py`,
  `tests/test_soak_promotion_gates.py`,
  `packages/maistro-core/src/maistro/persistence/pg_learnings.py`,
  `packages/maistro-core/tests/persistence/test_pg_learnings.py`, relevant
  ADRs, soak profile/evidence, inventory/gate configuration.
- Permitted repair targets: the schema-fence test/implementation if reproducibly
  broken; `quality/vulture-baseline.json` only for scanner-proven retained debt;
  this report and an inventory note if tests change. No other issues or remote
  mutations. No new execution authority or distributed rate limiter.

## Assumptions and initial evidence

This is a writer CI-repair round. The earlier BLOCKED result is evidence, not
proof. The exact RC artifact/configuration is not designated by the assignment;
local unit tests cannot substitute for an exact-artifact sustained soak.
The dispatch acceptance list has ten criteria, including physical-work fencing,
replica-independent security, and an exact RC long-running soak.

## Executed checkpoint

- Required CI vulture invocation: PASS, 1323 reviewed identities / 1323
  findings, zero unclassified. No ledger amendment warranted.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py
  -x -q`: 37 passed, 6 skipped (1.53s). The supplied failure is already repaired:
  the independent ordered expectation now covers all three validation audit
  columns. No schema test/production edits warranted. Skips are not live DB proof.

- `uv run ruff check .`: PASS. `uv run ruff format --check .`: PASS,
  3270 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py
  -x -q -rs`: 66 passed (2.23s). Includes real production middleware instances,
  HTTP probe fault cases, exact-artifact CLI rejection, process-group resource
  sampling and production task admission backpressure. This is not a deployed
  multi-replica soak.
- Imported the current `run_soak.py` and replayed
  `evidence/m3a-round43-shakedown.json`: 420.09 seconds versus 14400 required;
  failed gates exactly `sustain_duration` and `exact_rc_artifact`. Asserted both
  failures and the current preflight artifact refusal. Recorded historical flags
  are not independent proof of the other acceptance surfaces.
- `uv run python scripts/check-deployment-claims.py`: PASS.
- `uv run python scripts/check-execution-lifecycles.py`: PASS, 19 classified /
  discovered lifecycles.
- `git diff --check`: PASS at validation checkpoint.

## ADR reconciliation

Read ADR-081 (Proposed), ADR-085 (Accepted), ADR-081426-1f7c (Accepted) and
ADR-081626-f383 (Accepted). Physical execution identity is Attempt, not Run;
counting admissions or terminal Runs cannot establish physical-work uniqueness.
The fencing ADR explicitly leaves expiry takeover outside its current contract;
do not invent reclaim authority to satisfy issue prose. ADR-085 requires
principal-keyed rate limiting but does not specify a shared store. The observed
process-local allowances do not prove #860's replica-selection non-bypass claim.
No architecture or acceptance waiver is introduced.

## Acceptance disposition

| Criterion | Current evidence and disposition |
| --- | --- |
| Representative RC load profile | UNVERIFIED: `m3a-load-profile.md` defines preflight traffic but explicitly lacks concurrent Workspace/user population, Graph fan-out, successful model/tool calls and Design/Canvas/Goal coverage. RC applicability is not established. |
| Two application replicas | UNVERIFIED at exact-RC level: `deploy/docker-compose.prod.yml` declares two servers; no deployment was started this round. ASGI instances are not deployment proof. |
| Sustained saturation/reclaim/retry/leaks | UNVERIFIED: replayed historical 420.09-second window fails the 14400-second floor; short sampler tests cannot prove these properties. |
| Fenced physical work, admissions and reconciliation | UNVERIFIED: admission probe assertions pass, but cannot establish Attempt-level side effects or sustained Goal reconciliation. |
| Replica-independent rate/security/degraded behavior | NOT MET for aggregate principal allowance: executed `test_replica_selection_has_an_independent_production_allowance` gives the same principal/IP independent `[200, 200, 429]` responses on each middleware instance. Production `main.py:648` installs that middleware; `api/rate_limit.py:94` constructs an `InMemoryRateLimiter` per instance. Other RC-load security properties remain UNVERIFIED. |
| Complete metrics with thresholds | UNVERIFIED: process-group sampling tests pass; profile acknowledges driver-loop lag is not application-loop lag and does not prove complete worker/long-window metrics. |
| Kill/restart physical recovery | UNVERIFIED: no active-work restart executed this round; terminal Run counts/process rejoin alone are insufficient. |
| Long-running exact RC | BLOCKED: selected immutable artifact/configuration not supplied; `run_soak.py:730` rejects host-process equivalence, and the historical evidence fails both artifact and duration checks. |
| Findings filed/reclassified | UNVERIFIED externally; no GitHub mutation permitted or performed. Existing local classifications are not new filing evidence. |
| Hash-tied machine/human RC publication | UNVERIFIED: historical documents exist but the replay rejects promotion; no new qualifying RC evidence produced. |

## Handoff

Only this report changes. No tests were added or modified (inventory delta zero;
no inventory-note update necessary), no ledger/grant changes, no runtime changes,
no gate weakening, no GitHub mutations. The old failed schema expectation is
already repaired; the explicit debt gate has no unbanked identities. Neither
justifies a speculative code patch.

Verdict: BLOCKED. The previous block is not a develop sync conflict. Required
next work: select immutable RC images/configuration and representative surfaces;
resolve replica-budget semantics with the responsible owner; implement/use an
exact-topology runner with physical Attempt correlation and application metrics;
execute at least four hours on the unchanged RC. Preserve preflight evidence as
preflight only. This local checkpoint is not integration approval.

Progress: checked 1 issue; done 0 acceptance-complete issues; skipped 0 issues;
errors 0 in executed validation commands; 6 PostgreSQL-dependent tests skipped.
Commit this checkpoint locally.
