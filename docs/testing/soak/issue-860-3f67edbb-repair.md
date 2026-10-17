# Issue #860 repair checkpoint — 3f67edbb

## Frozen scope

Only issue #860 in `/home/dev/Git/wt/auto-860`, branch `auto-860`.
Starting HEAD: `d4d1630f2af7df9bede9c86fb69fced51e192c35`;
develop base: `ac7370141e8e61bd6f352bca35ed0b505104aadb`.
Initial worktree clean; no incoming edits to salvage.

Process the supplied CI failure and exact vulture scan, then focused soak
acceptance validation. Candidate edit files are this report and
`quality/vulture-baseline.json` only if actual scan evidence requires a
reviewed retained-identity amendment. No production or test changes are
planned without actual regression evidence; no ledger/grant guessing.
Read-only scope includes repository instructions, applicable ADRs, soak
runner/tests, CI workflows, supplied dispatch and prior result/log artifacts.
No PRs or other issues will be processed or re-enumerated.

## Initial evidence / assumptions

- Supplied prior result is BLOCKED, not accepted verification.
- Current job directory contains no `check-*.log` files at initial snapshot.
- Reported prior failure: job `98a11313167b41a98a420abfda80c292/check-3.log`.
- No exact RC artifact/configuration was designated in the assignment.
  Assume local tests can validate harness behavior only, not promotion readiness.
- Writer scope permits a local report commit; no GitHub mutations.

## Recorded validation checkpoint

- Required vulture command completed successfully: 1322 reviewed identities,
  1322 findings, zero unclassified. Log: `/tmp/860-3f67edbb-vulture.log`.
  No actual unbanked identities exist; no ledger amendment is justified.
- Read the reported prior `check-3.log`: its failure is a schema-fence assertion
  (24 DDL statements versus 21 expected), not a vulture failure. Current tests
  must be executed to determine whether this historical failure remains.
- Supplied develop base resolves locally. No merge conflict or unresolved ref.

- Fresh focused pytest: **130 passed, 6 skipped**, 2.68s. All skips require
  `MAISTRO_TEST_PG_DSN`; no live PostgreSQL acceptance is inferred.
  Command: `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-core/tests/runs/test_execution_fencing.py packages/maistro-core/tests/graph/durable_runs/test_recovery_disposition.py -x -q -rs`.
  Log: `/tmp/860-3f67edbb-tests.log`. Historical failure does not reproduce:
  the current expectation includes all three validation audit columns at
  `packages/maistro-core/tests/persistence/test_pg_learnings.py:177–179`.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS (3301 files).
- `uv run python scripts/check-ratchet-provenance.py`: PASS (53 consumers;
  two non-fatal invalid-escape SyntaxWarnings).
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- `uv run python scripts/check-backlog-consistency.py`: PASS (168 items).
- Validation commands used 1200-second timeouts. Exact vulture arguments were
  checked against `.github/workflows/vulture-ratchet.yml:82–85`.

## Architecture and acceptance boundaries

Read accepted ADR-081426-1f7c, ADR-081626-f383, ADR-082526-b36a.
The renewal/reclaim ADR extends the original fencing boundary; restarting one
worker must not take another live worker's authority. Preserve
Goal → Graph → Run → NodeRun → Attempt. No competing authority or ADR change.

Production `main.py:648` installs `RateLimitMiddleware`, whose constructor
(`packages/maistro-server/src/maistro_server/api/rate_limit.py:93`) creates
process-local allowance. Executed `tests/test_soak_promotion_gates.py:439`
observes `[200, 200, 429]` independently on both ASGI instances for one identity.
This proves local enforcement, not a replica-independent total budget.

Production `main.py:735,755` mounts the task router. Its receipt handler
(`packages/maistro-server/src/maistro_server/api/tasks.py:144`) reads the local
queue. Executed `tests/test_soak_promotion_gates.py:564` reproduces an admitting
instance's 200 and peer's 404 with a shared canonical admission spine.
Neither ASGI probe is deployed production load evidence.

`scripts/soak/run_soak.py:744` explicitly rejects exact-RC equivalence for its
host-process preflight. Passing duration and functional checks cannot override
that gate; the promotion regression suite passes with this restriction intact.

## Acceptance audit

| Criterion | Executed evidence / status |
|---|---|
| Representative RC workload | UNVERIFIED. `m3a-load-profile.md` explicitly lacks concurrent Workspaces, Graph fan-out, successful model/tool calls, Design/Canvas and sustained Goal workloads. No selected-RC applicability justification supplied. |
| At least two deployed replicas | UNVERIFIED. Executed two-instance ASGI probes only, not deployed replicas. |
| Sustained saturation, queue growth, reclaim, backoff and leaks | UNVERIFIED. No sustained production resource series collected. |
| No duplicate physical work | UNVERIFIED. Fencing/recovery regressions pass, but logical admission deduplication is not physical-effect evidence. |
| Replica-resistant security/degraded behavior | UNVERIFIED overall. Tests reproduce independent per-instance allowances; local enforcement and backpressure pass. |
| Required production telemetry and thresholds | UNVERIFIED. Profile has thresholds but no fresh production measurements; driver-loop lag is not application-loop lag. |
| Active-work kill/restart, drain and recovery | UNVERIFIED. Recovery regressions pass; no deployed active-work interruption. |
| Long exact-RC soak | UNVERIFIED. No immutable RC artifact/effective configuration designated; existing runner fails exact-RC gate intentionally. |
| Findings classified to earliest invariant | UNVERIFIED for completeness. Backlog gate passes, not a load-finding classification audit; no GitHub mutations. |
| Machine/human hash-bound soak evidence | UNVERIFIED. This source-bound validation report is not production image/package/configuration-bound soak evidence. |

## Disposition / handoff

**BLOCKED on release acceptance.** Required exact-RC selection and a
promotion-capable production load run cannot be replaced by another host
preflight or by passing unit tests. The current runner's documented minimum is
four hours, but even that duration cannot satisfy its artifact-equivalence gate.
Resolve/reconcile replica allowance and receipt limitations against the supported
production claims, then collect the missing workload, physical-effect, telemetry
and restart evidence on the designated RC. Do not weaken the gate.

Only this report changed. No new or modified tests; inventory delta not required.
No production changes, ledger amendments, grants, remote changes, or merges.
No actual CI failure remains reproduced in this round; speculative repairs would
not address evidence. The prior BLOCKED acceptance condition remains unresolved.

Progress: checked 1 issue; acceptance-complete 0; skipped 0 issues;
validation-command errors 0. Next: obtain exact RC artifact/configuration and
execute the missing production soak, not another identical local repair loop.
Local writer handoff only; no integration or release approval.
