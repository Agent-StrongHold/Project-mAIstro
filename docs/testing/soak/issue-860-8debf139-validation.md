# Issue #860 repair checkpoint — 8debf139

## Frozen scope

- Only issue #860, branch `auto-860`, starting HEAD
  `71b67a279a002f14140df2e398af5726f48793b3`, supplied base
  `321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62`.
- Inspect existing soak runner, promotion-gate tests, production surfaces those
  tests exercise, relevant ADRs, supplied dispatch/prior failure evidence, and
  vulture gate. No PR processing or GitHub mutations.
- Candidate edits: this checkpoint; `quality/vulture-baseline.json` only if the
  instructed scan demonstrates reviewed retained identities requiring repair.
  No speculative runtime or authorization changes.
- Initial worktree clean; HEAD matches assignment. No incoming work to salvage.
- Supplied job directory contains no `check-*.log` at initial inspection.
- Prior result reports BLOCKED; it is a claim to revalidate, not acceptance proof.

## Ambiguity and assumption

No exact promotable RC artifact/configuration is identified in the lane brief.
Validate existing evidence and fail-closed behavior; do not invent RC identity
or replace the canonical Goal -> Graph -> Run -> NodeRun -> Attempt runtime.

## Progress

Dispatch acceptance criteria captured: representative workload; two application
replicas; sustained saturation/reclaim/retry/leak observation; physical-work
uniqueness; replica-resistant security/rate limits; telemetry thresholds;
active-work restart recovery; exact-RC long soak; findings classification;
hash-bound machine/human evidence. All remain unverified pending this run.

Fresh mandated vulture scan passed: 1,322 findings / 1,322 reviewed identities,
zero unclassified and never-allowlist findings. No ledger edit is justified.
Historical `98a113.../check-3.log` reports 24 schema statements vs 21 expected;
the current test already includes the three missing validation-audit columns.
A guessed prior report filename was not found and skipped; `git show --stat HEAD`
resolved the actual `issue-860-cd79be55-repair.md`, which was inspected.
The existing production middleware tests explicitly assert independent allowances
on replicas; passing those tests will reproduce a blocker, not satisfy acceptance.

## Executed validation

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1,322 reviewed identities.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`: PASS, 110 passed / 6 skipped in 2.25s. No live-database proof inferred from skipped tests.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3,301 files already formatted.

The historical schema failure is not reproducible. The current independent DDL
oracle includes the three audit columns, and production `ensure_schema` takes
its advisory lock inside the transaction before issuing upgrades. No test or
ledger repair is warranted by these results.

Read accepted ADR-081226-a66b (lifecycle), ADR-081626-f383 (fencing), and
ADR-073126-c4e1 (release provenance). Reconciliation: expiry takeover is explicitly
outside the accepted fencing contract; do not manufacture reclaim authority to
satisfy this issue. Release proof must identify the actual RC, not host-process
preflight equivalence. Canonical execution and authorization remain unchanged.

## Acceptance disposition

| Criterion | Fresh evidence / disposition |
|---|---|
| Representative release workload | **UNVERIFIED**. `m3a-load-profile.md` explicitly lacks concurrent users/Workspaces, graph fan-out, successful tool/model calls, Design/Canvas and sustained Goal reconciliation. |
| Two deployed application replicas | **UNVERIFIED**. Executed tests use separate ASGI instances, not deployed RC replicas. |
| Sustained saturation, reclaim, retries and leaks | **UNVERIFIED**. Sampler tests pass, including a real uv child; no sustained deployment load was run. |
| No duplicate physical work | **UNVERIFIED**. Admission-oracle tests do not establish physical Attempt execution uniqueness or recovery. |
| Replica-resistant rate/security/degraded behavior | **UNMET** for a shared allowance: `test_replica_selection_has_an_independent_production_allowance` passes by observing `[200, 200, 429]` independently on both replicas for the same identity, authenticated and unauthenticated. Full deployed security remains **UNVERIFIED**. |
| Complete telemetry and thresholds | **UNVERIFIED** at RC scope. Driver loop measurements are not application loop latency; sampler tests cannot establish saturation or long-window health. |
| Active-work restart/drain/fencing/recovery | **UNVERIFIED**. No production replica killed; receipt-router probe reproduces owner 200 / peer 404 through local queues. |
| Long soak of exact RC | **UNVERIFIED / BLOCKED**. `run_soak.py:744` always rejects host-process artifact equivalence. Executed CLI rejection tests include synthetic four-hour evidence and missing/null identity. |
| Findings filed/reclassified | **UNVERIFIED** for completeness/external filing. Local findings recorded; GitHub mutations prohibited. |
| Hash-bound machine/human soak evidence | **UNVERIFIED**. This starting-HEAD-bound validation report is not image/config-bound soak evidence. |

## Handoff

**BLOCKED**, not integration approval. Only this report changed; no tests added,
removed or renamed, so no inventory delta is needed. No runtime/config, gates,
grants, ledger or historical evidence changed. No develop-sync conflict exists.

Next: provide the immutable RC and supported configuration, resolve the
replica-budget contract and representative workload/recovery gaps, then run the
required >=4-hour exact-artifact soak. Repeating clean CI cannot establish these
missing criteria. No long preflight was launched merely to manufacture duration.

Progress: checked 1 issue; done 0 acceptance-complete; skipped 0 issues;
validation command failures 0. One guessed report path was not found and skipped
as recorded above. Commit this handoff locally; no remote action.

