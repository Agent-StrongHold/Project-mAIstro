# Issue #860 — bounded repair, job 45fa65cf

## Frozen scope

Only issue #860, assigned worktree `/home/dev/Git/wt/auto-860`, starting
HEAD `6e1de8acb9c7ba66c034d959df15c653af300b58`, supplied base
`321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62`. Initial worktree was clean.
No GitHub changes or integration approval.

Process sequentially:
1. Reproduce the supplied `98a113.../check-3.log` schema-fence failure; inspect
   `packages/maistro-core/src/maistro/persistence/pg_learnings.py` and
   `packages/maistro-core/tests/persistence/test_pg_learnings.py`.
2. Run the requested exact vulture scan; inspect/amend only identities actually
   reported, in `quality/vulture-baseline.json` if retained debt requires it.
3. Validate existing #860 soak acceptance tests and fail-closed promotion path
   in `tests/test_soak_promotion_gates.py` and `scripts/soak/run_soak.py`;
   record remaining acceptance gaps, run formatting/lint/relevant gates, commit.

Conditional edit scope: the above files, this report, and an inventory note
if test coverage changes. Architecture/ADRs and adjacent tests are read-only
context. No scheduler, execution authority or authorization changes planned.

## Initial evidence and assumptions

The supplied prior result is BLOCKED, not proof of present behavior. Its claimed
limitations will be rechecked. The current job directory has no `check-*.log`
files at start; the explicitly supplied earlier check log was read. It reports
24 schema DDL calls versus 21 expected. Assumption: investigate the current
schema test rather than replaying stale repairs. Exact RC selection is unresolved
in the assignment; do not invent an artifact or relabel a local harness as RC.

## Results

1. Historical schema-fence failure is **not reproducible** at the assigned HEAD:
   `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`
   passed (37 passed, 6 skipped). The current expectation already includes the
   three Gauntlet validation audit columns, matching the 24 production DDL
   calls. No schema/test edit is justified by the old log. PostgreSQL integration
   cases were skipped; this command is not concurrent database evidence.

2. Exact CI vulture gate passed:
   `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
   reports 1322 findings / 1322 reviewed identities, zero unclassified and zero
   never-allowlist findings. Its resolved base is the supplied `321cbdb8fe9b`.
   There are no reported identities to remove or bank; no ledger amendment is
   warranted. The command matches `.github/workflows/vulture-ratchet.yml`.

3. Focused soak and production-route regression command passed:
   `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q`
   (99 passed). This exercises the production limiter and task router, plus
   the CLI's exact-artifact failure check with synthetic evidence. It is not a
   deployed soak. The same principal gets `[200, 200, 429]` on each independent
   limiter; a task receipt is 200 on its admitting queue and 404 on its peer.
   These are reproduced limitations, not proof of global enforcement or receipt
   durability. No test was added or changed.

Read accepted ADR-081426-1f7c (physical execution identity is Attempt),
ADR-081626-f383 (canonical store owns execution leases/fencing), and
ADR-082526-b36a (renewal and expiry reclamation). Admission deduplication cannot
substitute for physical-work uniqueness. Preserve
`Goal -> Graph -> Run -> NodeRun -> Attempt`. ADR-081 remains Proposed and
cannot authorize an acceptance waiver. No new execution or authorization path.

## Final validation

All validation commands used 1200-second timeouts. In addition to the two pytest
commands and exact vulture command above:

| Command | Outcome |
| --- | --- |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3301 files already formatted |
| `uv run python scripts/check-ratchet-provenance.py` | PASS, 53 quality JSON consumers covered; nonfatal invalid-escape SyntaxWarnings |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS |

The latter two commands are the other gates in the exact-debt-ledger CI job.
No ledger/grant edits and no gate changes. No added/modified tests, hence no
inventory delta. Only this validation/handoff report changed.

## Reachable behavior and acceptance

The production application installs `RateLimitMiddleware` at
`packages/maistro-server/src/maistro_server/main.py:648`; it constructs an
`InMemoryRateLimiter` at `api/rate_limit.py:93`. Production task routes are
mounted at `main.py:735` and `main.py:755`; `api/tasks.py:145` reads the queue
and returns 404 when the receipt is absent. The freshly executed tests at
`tests/test_soak_promotion_gates.py:439` and `:569` exercise those implementations,
not alternative auth/execution paths. They are ASGI probes, not deployed ingress
measurements. Process-local budgets are explicitly documented by #842; do not
silently reinterpret them as a shared principal budget to satisfy #860.

`scripts/soak/run_soak.py:744` explicitly rejects exact-RC equivalence. The
executed CLI test at `tests/test_soak_promotion_gates.py:105` rejects missing,
null and preflight artifact evidence, even with synthetic four-hour duration.
It does not run for four hours. `deploy/docker-compose.prod.yml:11` says the
Compose artifact is a reference requiring digest pinning; its application
services build from source. No exact promotion artifact/configuration is
selected by this assignment. The profile's missing workloads and observability
limits are explicit at `docs/testing/soak/m3a-load-profile.md:165`.

| Issue acceptance criterion | Executed evidence / disposition |
| --- | --- |
| Representative RC concurrent users/Workspaces and request mix, fan-out, schedules, tools/models, Design/Canvas, workers | UNVERIFIED. Profile is a degraded-path preflight; listed workloads are missing or applicability unresolved. |
| At least two application replicas | UNVERIFIED for deployment. Two independent ASGI middleware/router instances were exercised, not two deployed RC replicas. |
| Sustained saturation, queue growth, lease reclaim, retry/backoff, memory/FD/process leaks, shutdown/restart | UNVERIFIED. No sustained production load window executed. |
| No duplicated physical schedule/task/Run/Attempt/Goal work | UNVERIFIED. Admission identity tests do not measure physical Attempt execution across recovery. |
| Rate/security/degraded enforcement cannot be bypassed by replica selection | UNVERIFIED for the selected deployment; independent same-principal allowances reproduced in production middleware. No global enforcement proof. |
| PostgreSQL usage/query latency/locks, application loop lag, worker/process/RSS/FD/queue/error telemetry with thresholds | UNVERIFIED. Local sampler regression passes, but no fresh full production time series; driver-loop lag is not application-loop lag. |
| Kill/restart during active work with drain/fencing/recovery | UNVERIFIED. No active-work deployment kill/restart executed. |
| Long exact-RC artifact/configuration soak; rerun after changes | UNVERIFIED. Current harness fails artifact equivalence by design. RC selection remains unresolved. |
| Earliest-invariant classification of load findings | UNVERIFIED for completeness. No new representative load findings collected; remote filing is prohibited. |
| Machine/human evidence tied to image/package/commit/config hashes | UNVERIFIED. This report binds source validation to HEAD, not an exact-RC production soak. |

## Disposition and handoff

**BLOCKED on #860 acceptance, not the reported CI repair.** The historical
schema failure is already resolved and the exact vulture ledger is clean.
A speculative code change or ledger amendment would not address actual failed
validation. No production implementation change was made in this round.

Exact-RC ambiguity was checked against the assignment and local deployment/
profile contract; record it as **UNRESOLVED**, without inventing the RC or
weakening the gate. Next owner must select the immutable promotion image and
normalized configuration, justify applicable workloads, and provide/run the
instrumented long production profile with active-work recovery and physical
Attempt evidence. Independent replica allowances/receipt visibility must be
resolved against that topology before promotion. A further retry of the old
schema/vulture failure alone cannot complete this issue.

Progress: checked 1 issue; acceptance-complete 0; skipped issues 0; command
failures 0. Local commit is a blocked handoff only, never integration approval.
