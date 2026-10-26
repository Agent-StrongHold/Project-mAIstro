# Issue #860 — repair checkpoint (job 1e702bdf)

## Frozen scope

- Issue: #860 only; writer in `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Verified starting HEAD: `59af1cc20627cba0c1176cc428e477e43c17f7b4`.
- Supplied base: `321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62`.
- Starting worktree clean; no incoming changes to salvage.
- Inputs: this job's `dispatch-context.json`, prior result
  `0843e211f34d40569a8b19cff6f06792/result.json`, and named failed
  `98a11313167b41a98a420abfda80c292/check-3.log` (if available).
- Inspect only relevant repository instructions/ADRs, soak harness/profile/tests,
  production routes reached by those tests, vulture gate/workflow/ledger and any
  identities actually reported by that gate.
- Planned edits: this checkpoint; production/test changes only if current evidence
  supports a focused repair, with an inventory note for any new tests; ledger
  amendments only for identities reported and reviewed in this CI-repair round.
- No GitHub changes, integration actions, or new execution/authorization authority.

## Initial evidence and assumptions

No `check-*.log` files were present in this job directory at initial inspection.
The prior result is BLOCKED, citing RC-equivalence rejection and independent
replica rate/receipt state. Those claims require fresh validation, not adoption
as current truth. The supplied assignment is a writer/CI-repair task; the generic
verifier-only no-edit instruction is not applied to this writer lane.

## Fresh validation checkpoint

- Exact requested vulture gate passed: 1322 findings matched 1322 reviewed
  identities; unclassified 0, never-allowlist 0. No ledger amendment is justified.
- Focused pytest passed: 118 passed, 6 skipped in 2.27s, covering learning-schema
  fencing, task concurrency backpressure, soak promotion gates and boot contract.
- Read the supplied historical `check-3.log`: failure was 24 DDL statements versus
  21 expected. That failure does not reproduce at the assigned head.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3301 files formatted.
- Deployment-claims, compose-secrets, merge-markers and suite-inventory gates:
  PASS. Inventory matched 17 suites / 31323 unique identities; collection is not
  execution of those suites.
- No production code or tests changed. No inventory delta is needed.

## Architecture checkpoint

Read `AGENTS.md`, `docs/README.md`, accepted ADR-081426-1f7c and
ADR-082526-b36a, current load profile and adjacent promotion tests. Preserve
`Goal -> Graph -> Run -> NodeRun -> Attempt`: physical work must be observed at
Attempt execution, not inferred from admission deduplication. Recovery must
respect heartbeat/lease fencing; restarting a process is not proof that other
workers' Attempts died. No alternate execution, event or authorization authority
has been introduced.

The profile explicitly describes the current harness as a host-process preflight,
not the promoted Compose artifact. The executed independent-rate-allowance and
peer-receipt tests use real middleware/router but ASGI instances, not deployed RC
replicas. Their passing results reproduce limitations rather than proving soak
acceptance. Production inspection confirms `RateLimitMiddleware` constructs its
own `InMemoryRateLimiter` (`rate_limit.py:95`) and explicitly documents N-times
aggregate limits (`rate_limit.py:32-37`). `GET /tasks/{task_id}` reads its local
queue and returns 404 if missing (`tasks.py:144-146`). These are not evidence of
physical Attempt duplication; changing them here would require an explicit
shared-budget/durable-projection design, not a speculative scanner repair.

## Acceptance matrix (all ten issue bullets)

| Criterion | Fresh evidence / disposition |
| --- | --- |
| Representative RC load profile | UNVERIFIED. `m3a-load-profile.md` documents missing concurrent users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and background-worker scope. No selected RC configuration resolves their inclusion/exclusion. |
| At least two deployed replicas | UNVERIFIED. Executed tests use two ASGI instances; no RC deployment was exercised this round. |
| Sustained saturation, queue growth, reclaim, retry, leaks | UNVERIFIED. Focused tests completed in 2.27s; no long-window live observations. |
| No duplicate physical work across replicas | UNVERIFIED. Admission probes do not execute/observe the full canonical physical Attempt boundary required by ADR-081426-1f7c. |
| Replica-selection-resistant rate/security/degraded behavior | UNVERIFIED at promotion scope. Executed `test_replica_selection_has_an_independent_production_allowance` for authenticated and unauthenticated clients reproduces [200, 200, 429] separately on each replica. Local enforcement is proven; a shared-budget interpretation of the issue is not satisfied. Resolve that contract mismatch before claiming acceptance. |
| Required telemetry and explicit thresholds | UNVERIFIED. Profile thresholds exist, but no fresh PostgreSQL contention, application-loop latency, worker/process, queue or long-window leak/error evidence was collected. Driver loop lag is not application loop lag. |
| Kill/restart during active work; drain/fencing/recovery | UNVERIFIED. No live interruption this round. Executed production-router receipt test observes owner 200 / peer 404; this establishes a visibility limitation, not proof of physical loss or recovery. |
| Long-running exact-RC soak | UNVERIFIED. `scripts/soak/run_soak.py:744-755` unconditionally rejects host-process artifact equivalence. Executed CLI tests reject missing/null/preflight artifact evidence even with a synthetic four-hour duration. Extending this runner's duration cannot prove the exact artifact. |
| Findings filed/reclassified before promotion | UNVERIFIED for external completeness. This note separates stale CI evidence, local allowance/visibility limitations, and missing release evidence. No GitHub mutation is authorized or performed. |
| Machine/human evidence bound to exact hashes | UNVERIFIED. This report binds focused checks to the assigned source HEAD, not to deployed immutable images/configuration. No new production soak evidence exists. |

## Commands executed

All validation commands ran with 1200-second timeouts and exited 0:

```text
uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'
uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q
uv run ruff check .
uv run ruff format --check .
uv run python scripts/check-deployment-claims.py
uv run python scripts/check-compose-secrets.py
uv run python scripts/check-merge-markers.py
uv run python scripts/check-suite-inventory.py
```

The vulture invocation matches both `.github/workflows/quality.yml:1079` and
`.github/workflows/vulture-ratchet.yml:82`. No ledger/grant amendment is justified
by the actual scan. The historical schema failure is already addressed by the
three validation audit columns independently expected at
`packages/maistro-core/tests/persistence/test_pg_learnings.py:175-177`.
Full package suites, database integration and a live soak were not executed.

## Final disposition / required next action

**BLOCKED — not integration approval.** Only this report changed; all inherited
work is preserved. No evidence supports a new CI repair at this head. No tests
were added, so no inventory note/count amendment is warranted. No merge conflict
exists, so no fetch/merge was needed.

Do not repeat CI-only repair rounds against this unchanged implementation to
obtain soak approval. The next work requires a selected immutable RC artifact
and normalized production configuration, supported workload scope/model gateway,
a production-topology runner observing physical Attempts and application
telemetry, and explicit resolution of rate-budget/receipt visibility limits.
Then execute the >=4-hour exact-RC soak with active-work interruption and retain
hash-bound machine/human evidence. No gate or authority was weakened to substitute
for those prerequisites.

Checkpoint: checked 1 issue; done 0 acceptance-complete issues; skipped 0 issues;
validation errors 0; next: RC prerequisites and production-path soak. Commit this
report locally; no issue closure or integration action.

