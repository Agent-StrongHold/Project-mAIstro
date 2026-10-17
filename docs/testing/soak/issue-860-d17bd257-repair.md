# Issue #860 — bounded repair d17bd257

## Frozen scope

- Assigned issue: #860 only; worktree `/home/dev/Git/wt/auto-860`.
- Starting HEAD: `7c5652aec7a4705990bbfef144301f1794480fd6`;
  supplied base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Worktree started clean; no incoming changes to salvage.
- Process the supplied vulture gate failure and independently validate the
  existing soak acceptance boundary. No GitHub mutations or adjacent issues.
- Planned edit surface: this report; `quality/vulture-baseline.json` only if
  the prescribed scan identifies reviewed retained identities. No speculative
  runtime repairs, grants, or new execution authority.
- Inputs: supplied dispatch snapshot and prior result. Current job directory
  contains no `check-*.log`; inspect the explicitly supplied previous log.

## Initial evidence / ambiguity

The previous result reports BLOCKED because no promoted immutable RC was
specified and the host harness is not production-topology certification.
That claim is not yet independently verified in this round. Assignment is
writer/repair, so the verifier-only no-edit instruction does not apply.

## Validation checkpoint

- Prescribed vulture command passed: 1,323 findings, 1,323 reviewed identities,
  zero unclassified/never-allowlist findings. No ledger amendment is warranted.
- Supplied `98a11313167b41a98a420abfda80c292/check-3.log` records a stale
  schema-fence assertion (24 DDL calls versus 21 expected), not vulture debt.
  Current test already independently lists the three Gauntlet columns.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py
  tests/test_soak_promotion_gates.py -x -q`: **102 passed, 6 skipped**.
  This re-executes the formerly failing assertion, host-RC rejection, and real
  production middleware replica-selection regression. Skips are not proof.
- An attempted prior-note path was not found; skipped. Supplied prior result
  JSON was readable. No ref fetch/merge or runtime repair was justified.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 3,270 files already formatted.
- Repeated targeted pytest with `-q -rs`: 102 passed, 6 skipped. All skips
  require `MAISTRO_TEST_PG_DSN`; no PostgreSQL integration claim is made.
- `uv run python scripts/check-suite-inventory.py`: passed, 17 suites,
  31,128 unique test identities, no duplicated evidence. No tests were added
  or edited in this round, so no inventory delta note is required.

## Architecture and acceptance review

Read repository instructions, documentation authority hierarchy, accepted
ADR-062 (including retirement of the old executor), ADR-082126-f69c,
ADR-082426-82c7 and ADR-082526-b36a. Scheduled work must admit canonical Runs;
occurrence admission alone does not prove physical execution uniqueness.
Recovery proof must observe canonical Attempt leases and fences, not infer
success from process rejoin. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`;
no scheduler, store, authorization path, or execution authority was added.

Reviewed `scripts/soak/run_soak.py`, its adjacent promotion tests, the
load profile/evidence pack, current schema-fence test and production
`maistro_server.api.rate_limit.RateLimitMiddleware`. Executed tests exercise
actual middleware instances through ASGI, but are not deployed replicas.
The production limiter explicitly promises per-process budgets; this does
not satisfy #860's stronger replica-selection criterion. That conflict
remains a release decision/implementation blocker, not a waiver or an excuse
to introduce an alternative authorization mechanism.

| #860 acceptance | Fresh evidence and disposition |
| --- | --- |
| Representative users/Workspaces/request mix/fan-out/schedules/tools/model/Design/Canvas/workers | UNVERIFIED. `m3a-load-profile.md` explicitly lists missing representative surfaces; the existing degraded single-key workload is insufficient. |
| At least two production application replicas | UNVERIFIED. Host preflight is not exact production Compose; no deployed RC run executed this round. |
| Sustained saturation, growth, reclaim, backoff and leak observations | UNVERIFIED. Sampler regression passes, but no sustained RC load or lease expiry/reclaim measurements were executed. |
| No duplicated physical work across replicas | UNVERIFIED. Admission-probe tests pass; canonical identity uniqueness alone cannot prove physical Attempt fencing or Goal reconciliation. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | UNVERIFIED as acceptance, with counterevidence: `test_replica_selection_has_an_independent_production_allowance` passes for both authenticated and anonymous identities, asserting `[200, 200, 429]` independently on each replica. |
| Required telemetry with explicit thresholds | UNVERIFIED. Process-group sampler tests pass; driver loop latency is not application loop latency, and no complete production threshold evidence exists from this round. |
| Kill/restart during active work proves drain/fencing/recovery | UNVERIFIED. Evaluator regressions pass, not a live active-Attempt restart/recovery test. |
| Long soak of exact promoted RC/config; rerun after changes | UNVERIFIED. `preflight_artifact_check` at `run_soak.py:730` always fails; three `test_four_hour_preflight_cannot_pass_cli` cases passed. No designated immutable promoted image/config supplied. |
| Load findings filed/reclassified before promotion | UNVERIFIED. Historical local findings are documented; their external disposition was not established by this round. No GitHub mutations permitted. |
| Machine/human evidence tied to image/package/commit/config hashes | UNVERIFIED for the exact RC. Historical preflight evidence is not fresh RC evidence. This report records starting code identity, not a soak signature. |

## Outcome and handoff

**BLOCKED for #860 acceptance.** The reported historical test failure does
not reproduce; the required debt gate is green, so neither speculative code
changes nor ledger churn are justified. This round changes only this report.
No full-tree pytest or long-running preflight was attempted: neither would
supply the missing immutable RC/topology, and a longer preflight cannot pass
its artifact gate. Passing local tests are not promotion approval.

Next: designate the exact immutable RC images/configuration and authorized
production-equivalent environment; resolve the replica-budget requirement;
then execute representative canonical workloads, physical-work recovery
observations and the >=4-hour hash-bound production soak with all required
telemetry. Any runtime/config repair invalidates earlier soak evidence.

Progress: checked 1 issue; done 0 acceptance-complete issues; skipped 0 issues;
errors 0 validation failures. Existing PostgreSQL integration checks skipped 6.
Local report commit is the checkpoint; no push or GitHub mutation.
