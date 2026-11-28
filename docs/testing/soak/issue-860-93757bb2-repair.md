# Issue #860 — repair checkpoint (93757bb2)

## Frozen scope

- Only issue #860, branch `auto-860`, worktree `/home/dev/Git/wt/auto-860`.
- Starting HEAD `8732be62efb2996ecb523d971e51b8754e64c826`; supplied base
  `ac7370141e8e61bd6f352bca35ed0b505104aadb`. Both resolved locally;
  initial working tree was clean.
- Assigned item: reproduce exact vulture gate, inspect retained identities only
  if reported, and check existing soak acceptance tests and production wiring.
- Candidate write set: this report; `quality/vulture-baseline.json` only if
  actual scanner findings warrant its explicitly permitted amendment.
  No speculative production changes or new tests planned.
- Read set: supplied dispatch and prior result/failure log, repository
  instructions, relevant ADRs, existing soak runner/profile/tests, production
  wiring referenced by those tests, and gate/workflow definitions.
- No GitHub mutations, ref refreshes, or unrelated prior PR processing.

## Initial evidence and ambiguity

The supplied prior result is BLOCKED, not evidence of passing acceptance.
The current job directory contains no `check-*.log` at initial inspection.
The explicitly named prior failure log will be inspected instead. The writer
assignment governs; this is not the read-only verifier role.

## Executed checkpoint

The exact requested vulture command passed: 1,322 findings match 1,322
reviewed identities; zero unclassified/forbidden findings. No ledger edit is
justified. The cited historical `check-3.log` is a schema test failure (24 DDL
statements versus 21 expected), not a vulture failure. It no longer reproduces:
the current test explicitly includes all three validation audit columns.
The dispatch contains unrelated linked issues; they are evidence only and
remain outside this repair's frozen scope.

## Executed validation

All validation ran locally in the assigned worktree (600–1,200 second timeouts).

| Command | Outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | Exit 0; 1,322 reviewed identities / findings. Exact workflow arguments (`.github/workflows/vulture-ratchet.yml:82`). |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | Exit 0; 110 passed, 6 skipped. Skips are not proof. |
| `uv run ruff check .` | Exit 0; all checks passed. |
| `uv run ruff format --check .` | Exit 0; 3,301 files already formatted. |
| `uv run python scripts/check-backlog-consistency.py` | Exit 0; 168 consistent backlog items. |

The schema regression uses a fake connection: it proves ordering and fence
coverage, not concurrent PostgreSQL behavior. Its expected DDL at
`packages/maistro-core/tests/persistence/test_pg_learnings.py:175` already
includes the columns absent from the historical failure's expectation.
No runtime/test edit is justified by that stale failure. No tests added or
removed, so no inventory delta note is needed.

## Acceptance against the supplied #860 body

| Criterion | Evidence and disposition |
| --- | --- |
| Representative RC profile | **UNVERIFIED.** `docs/testing/soak/m3a-load-profile.md` defines a preflight mix but explicitly lacks multi-user/Workspace traffic, Graph fan-out, successful model/tool calls, Design/Canvas and background workloads. No designated RC artifact/config supplied. |
| Two deployed application replicas | **UNVERIFIED.** This round executed two-instance ASGI probes, not deployed replicas. |
| Sustained saturation, queue growth, lease reclaim, retries, resource leaks | **UNVERIFIED.** No sustained production run executed. |
| No duplicate physical work across schedule/task/Run/Attempt/Goal paths | **UNVERIFIED.** Admission identity and mocked probe tests do not establish physical-work uniqueness. |
| Replica-resistant security/degraded behavior | **UNVERIFIED; contrary evidence remains.** `tests/test_soak_promotion_gates.py:439` passed by observing [200, 200, 429] independently on each real middleware instance for the same identity. Local enforcement is not a shared allowance. |
| PostgreSQL/application loop/worker/RSS/FD/queue/error telemetry and thresholds | **UNVERIFIED at promotion grade.** Existing sampler tests passed, including a real child process; no production telemetry captured. Driver loop lag is not application loop lag. |
| Active-work restart, drain, fencing, recovery | **UNVERIFIED.** No live replica restart under work executed. |
| Long exact-RC soak and rerun after changes | **BLOCKED / UNVERIFIED.** `scripts/soak/run_soak.py:744` returns `ok=False` for its host-process topology; CLI regression tests reject even four-hour synthetic evidence without exact-RC equivalence. No immutable RC/config designated in the assignment. |
| Classify load findings to earliest broken invariant | **UNVERIFIED for completeness.** Backlog consistency passed; no new load run or external issue mutation performed. |
| Hash-bound machine/human promotion evidence | **UNVERIFIED.** This report is local validation evidence only, not a production image/configuration-bound soak. |

The receipt test at `tests/test_soak_promotion_gates.py:564` also passed by
observing 200 from the admitting queue and 404 from its peer through the real
task router. Production installs that router at
`packages/maistro-server/src/maistro_server/main.py:735,755` and the rate limiter
at line 648. These are reachable production components, but the ASGI tests do
not simulate the complete deployed topology or prove full acceptance.

## Architecture reconciliation and handoff

Read `AGENTS.md`, the documentation authority map, accepted
ADR-073126-c4e1 (release/versioning) and ADR-082426-82c7 (occurrence claim).
The release ADR requires promoting the artifacts validated as the RC; merely
extending host-process preflight duration cannot comply. The occurrence ADR
places uniqueness in the canonical Run store; occurrence admission proof is
not proof of physical Attempt fencing. Preserve
`Goal -> Graph -> Run -> NodeRun -> Attempt`; no alternate execution, store,
event or authorization authority was introduced.

Only this report changed. Do not amend a matching ledger or weaken promotion
checks to manufacture progress. No merge conflict was present, so the
conditional develop-sync repair was not applicable. Existing work preserved.

Residual blockers: a release-owner-designated immutable RC/configuration,
representative production workloads and long-running evidence, plus resolution
or explicit contract reconciliation of replica-local behavior. No local code
repair can manufacture that missing evidence.

Progress: checked 1 assigned issue; done 0 acceptance-complete issues; skipped 0;
validation errors 0; focused CI investigation complete. Next: supply the exact
RC/deployment contract, then execute and assess the production soak. Verdict:
**BLOCKED**, not integration approval.
