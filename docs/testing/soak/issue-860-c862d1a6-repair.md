# Issue #860 — c862d1a6 repair checkpoint

## Frozen scope

Only issue #860 on `auto-860`, starting at
`6bd5bb8168cf0bf22b2ade91002126d1c931b496`, against supplied base
`3c761d14db944a727fa0744444bc67cfe36d49f7`. Initial worktree clean.
No PR processing, remote mutations, develop sync, or unrelated repairs.

Files in scope: this report; `scripts/soak/run_soak.py`,
`tests/test_soak_promotion_gates.py`, `docs/testing/soak/m3a-load-profile.md`,
`docs/testing/soak/m3a-soak-evidence.md`, existing prior report
`docs/testing/soak/issue-860-29f1948b-repair.md`; CI gate
`scripts/check-vulture-baseline.py`, `quality/vulture-baseline.json` only if
actual scan evidence requires its explicitly permitted repair. Read-only
architecture/ADR, workflow and adjacent production/test dependencies may be
inspected. No new tests planned absent an evidenced repair.

The supplied dispatch snapshot and prior result were read. The current job
has no `check-*.log` files in its initial directory listing. Prior reported
failure `/home/dev/maistro/jobs/98a11313167b41a98a420abfda80c292/check-3.log`
will be inspected directly. Assumption: this is a writer CI-repair round,
not a verifier-only assignment. The prior BLOCKED verdict is not proof;
validation and acceptance review follow below. No immutable RC identifier
was supplied in the lane assignment; do not invent a promotion artifact.

## Fresh deterministic results

- Required exact Vulture scan: PASS, 1323 findings / 1323 reviewed identities,
  zero unclassified / never-allowlist findings. Gate selected base
  `4aa68edc0b6b`. No ledger amendment is warranted.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3270 files already formatted.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q -rs`:
  **111 passed, 6 skipped**, 2.62 seconds. Skips require
  `MAISTRO_TEST_PG_DSN`; no live database validation is claimed.
- The historical check-3 failure (24 schema statements versus 21 expected)
  does not reproduce in the current schema test. No speculative assertion
  or production change is justified.

All validation commands used 1200-second timeouts. The passing limiter test
executes production middleware and reproduces independent allowances for the
same identity on two instances. The four-hour CLI gate tests use synthetic
evidence and explicitly reject host preflight; they do not run four hours of
traffic. Historical evidence is expressly provisional and not reused as proof
for this HEAD. No tests have been added or changed.

- `uv run python scripts/check-suite-inventory.py`: PASS, 17 suites,
  31128 unique identities, no duplicate evidence.
- `uv run python scripts/check-deployment-claims.py`: PASS. This checks
  component existence, not deployed runtime correctness.

## Architecture and acceptance review

Read repository instructions, documentation authority map, accepted ADR-085,
ADR-081626-f383 and ADR-082526-b36a, and proposed ADR-081. ADR-081 is not an
accepted override. Keep `Goal -> Graph -> Run -> NodeRun -> Attempt` and the
existing canonical authorization/store seams. The later accepted lease ADR
requires renewal/reclamation; the older ADR's deferred takeover boundary is
not a reason to waive recovery validation. ADR-085 specifies principal-based
rate identity but does not prove shared state. The documented process-local
implementation cannot establish #860's stronger replica-selection requirement;
that contract mismatch remains UNRESOLVED, not silently reinterpreted as pass.

| #860 acceptance criterion | Fresh evidence and disposition |
| --- | --- |
| Representative RC workload | **UNVERIFIED**. Profile read; `m3a-load-profile.md:152` records missing users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and Goal/background workloads. No selected-RC applicability contract supplied. |
| At least two deployed replicas | **UNVERIFIED**. Production Compose names two servers; passing boot-contract tests and two ASGI limiter instances do not deploy an RC. |
| Sustained saturation/queues/reclaim/retries/leaks | **UNVERIFIED**. Regression tests pass, including actual child-process resource growth detection; no sustained production traffic was executed. |
| No duplicated physical work | **UNVERIFIED**. `scripts/soak/run_soak.py:1044` explicitly cancels the admission probe without executing its Run. Admission identity tests do not prove physical Attempt or Goal reconciliation effects. |
| Rate/security/degraded non-bypass | **UNVERIFIED** at deployment grade, with contrary local evidence: `tests/test_soak_promotion_gates.py:439` observes `[200, 200, 429]` separately on both production limiter instances for the same authenticated or pre-auth identity. `main.py:648` installs the middleware; `api/rate_limit.py:93` constructs instance-local state. |
| Full telemetry with thresholds | **UNVERIFIED**. Profile thresholds exist, but `run_soak.py:1410` measures driver-loop lag rather than application-loop latency. No fresh RC telemetry series. |
| Kill/restart during active work, drain/fencing/recovery | **UNVERIFIED**. Passing cleanup/gate tests are not a deployed physical-work recovery experiment. |
| Long soak of unchanged exact RC | **UNVERIFIED / BLOCKED**. No immutable RC/configuration designation supplied. `run_soak.py:730` rejects exact-RC certification for its host topology. Synthetic four-hour CLI tests prove that rejection, not a four-hour soak. `deploy/docker-compose.prod.yml:11` is explicitly a reference artifact needing digest pinning. |
| File/reclassify load findings before promotion | Local findings recorded here; external disposition **UNVERIFIED**. GitHub mutations prohibited and not performed. |
| Machine/human evidence bound to image/package/commit/config | **UNVERIFIED**. Historical evidence is provisional and belongs to other heads. This report records source validation, not a new promotion evidence bundle. |

## Handoff

**BLOCKED**, not merge-ready. The assigned deterministic failures have no
currently reproducible repair: exact-debt ledger and reported schema regression
both pass. Only this report changes; no test inventory delta is required.
No source, runtime config, historical raw evidence, quality ledger or grant
has been changed. No sync conflict exists and no merge was attempted.

Next actionable inputs: designate the immutable promotion artifact and runtime
configuration, resolve the rate-budget contract mismatch, implement the missing
representative workloads and physical-effect/application telemetry oracles, then
execute the >=14400-second exact-artifact soak with active-work recovery. A
further replay of the old check-3 failure cannot supply that evidence. Docker
availability is not claimed as a blocker; no deployment was attempted without
the RC designation. The inherited broad branch diff is not certified by this
bounded validation round.

Progress: checked 1 issue; done 0 acceptance-complete issues; skipped 0 issues;
errors 0 validation commands; 6 database tests skipped. Local commit completes
this investigation only, not issue acceptance or integration approval.
