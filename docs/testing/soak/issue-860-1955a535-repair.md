# Issue #860 repair checkpoint — 1955a535

## Frozen scope

- Issue: #860 only; branch `auto-860` in `/home/dev/Git/wt/auto-860`.
- Starting HEAD: `99f350655d2b85fccaf57703d4305b1b0836db72` (resolved; clean).
- Develop base supplied: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Evidence: supplied dispatch-context.json, prior result 34533434, prior
  check-3.log from 98a11313; current job has no check-*.log files.
- File scope: existing scripts/soak, tests/test_soak_promotion_gates.py,
  associated soak docs/inventory notes, and quality/vulture-baseline.json
  only if the prescribed scan proves a required retained-identity repair.
- Inspect repository instructions, accepted execution/deployment ADRs,
  adjacent tests and actual gate output before changing implementation.

## Initial result and assumptions

Prior result is evidence, not verification: it reports exact-RC acceptance
unproven and independent replica rate allowances. This is a writer repair
round, not permission to choose a release artifact or create a new authority.
No RC artifact/configuration is specified in the assignment. Verify locally
what is executable; explicitly retain missing deployment acceptance as
UNVERIFIED. Do not repeat remote enumeration or mutate GitHub.

## Reproduced gate results

- Prescribed Vulture command: PASS, 1323 reviewed identities / 1323 findings,
  zero unclassified and zero never-allowlist. No ledger amendment is justified.
- Prior check-3.log is a real historical 24-versus-21 schema assertion failure.
  Fresh `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py
  -x -q -rs`: **37 passed, 6 skipped** (missing MAISTRO_TEST_PG_DSN).
  The reported failure does not reproduce at this HEAD.
- These checks used 1200-second timeouts; logs are in
  `/tmp/issue-860-1955-{vulture,persistence}.log`.

Read AGENTS.md, docs/README.md and accepted ADR-085, ADR-081626-f383,
ADR-082526-b36a. The later lease ADR requires renewal/reclaim, so the older
ADR's deferred takeover boundary cannot waive recovery acceptance. Preserve
Goal -> Graph -> Run -> NodeRun -> Attempt and the canonical lease authority.
ADR-085 requires principal-keyed limits; it does not prove that replica-local
budgets satisfy #860's stronger replica-selection criterion.

## Focused validation

All commands below ran with a 1200-second timeout:

| Command | Result |
| --- | --- |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3270 files |
| `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q -rs` | 74 passed |
| `uv run python scripts/check-suite-inventory.py` | PASS, 17 suites; 31128 unique identities; no duplicate evidence |
| `uv run python scripts/check-deployment-claims.py` | PASS; checks existence, not deployed behavior |
| `git diff --check` | PASS |

Logs: `/tmp/issue-860-1955-{ruff,format,soak-tests,inventory,deployment}.log`.
Combined targeted pytest result: **111 passed, 6 skipped**. No test was added
or changed, so no inventory delta is required. CI invocation locations were
checked in `.github/workflows/{quality,vulture-ratchet,ci}.yml`.

The schema test already lists the three Gauntlet validation columns independently
at `packages/maistro-core/tests/persistence/test_pg_learnings.py:177`; changing
its assertion to fix the historical log would not be an evidence-based repair.

Also read ADR-081: its canonical status is **Proposed**, not Accepted. Its
reference from Compose is not a waiver of the issue's deployment requirements.
No accepted ADR is changed or overridden by this round.

## Acceptance matrix — independently inspected at the assigned HEAD

| #860 criterion | Executed evidence and disposition |
| --- | --- |
| Representative RC workload | **UNVERIFIED**. `m3a-load-profile.md:152` acknowledges missing users/Workspaces, Graph fan-out, successful tool/model, Design/Canvas and Goal/background traffic. Driver mix at `scripts/soak/run_soak.py:1381` is health/task/receipt/metrics with one credential. No selected-RC applicability justification was supplied. |
| At least two deployed application replicas | **UNVERIFIED**. Compose declares two replicas; boot-contract tests pass. This round did not deploy the designated RC, and two ASGI middleware instances are not deployment proof. |
| Sustained saturation, growth, reclaim, retry/backoff and leaks | **UNVERIFIED**. Executed sampler tests observe real child RSS/descriptor growth and do not hide incomplete samples. They are not sustained production saturation/reclamation evidence. |
| No duplicate physical work for schedule/task/Run/Attempt/Goal paths | **UNVERIFIED**. Admission-probe tests reject absent/conflicting identities, but `run_soak.py:1044` explicitly cancels a schedule probe Run that is never executed. It cannot establish physical-effect uniqueness or sustained Goal reconciliation. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **UNVERIFIED at deployment grade; contrary local evidence reproduced**. `tests/test_soak_promotion_gates.py:439` observes `[200, 200, 429]` independently on both instances for the same principal/client, including after the first is exhausted. Production installs that middleware at `packages/maistro-server/src/maistro_server/main.py:648`; it constructs an `InMemoryRateLimiter` at `api/rate_limit.py:93`. The local-budget versus cluster non-bypass mismatch remains UNRESOLVED; no new authorization path was introduced. |
| Complete telemetry and explicit thresholds | **UNVERIFIED**. Profile thresholds exist, but `run_soak.py:1410` measures the driver's loop, not the application loop. No fresh production pool/query/worker/queue/error series or complete application telemetry oracle was executed. |
| Kill/restart during active work; drain/fencing/recovery | **UNVERIFIED**. Boot cleanup and fail-closed evaluator tests pass, but no active physical-work production recovery experiment ran. |
| Long unchanged exact-RC soak | **UNVERIFIED / BLOCKED**. No designated immutable promotion artifact/configuration is supplied. `deploy/docker-compose.prod.yml:11` calls itself a reference requiring digest pinning. Executed four-hour CLI tests use synthetic evidence and confirm host preflight cannot certify an RC (`run_soak.py:730`); they do not run four hours of traffic. |
| Findings filed/reclassified to earliest broken invariant | Local disposition recorded: schema failure is non-reproducing, no unbanked Vulture debt, runtime rate-budget mismatch and release-evidence gaps remain open. External filing/reclassification is **UNVERIFIED**; no GitHub mutation was performed. |
| Machine/human soak evidence tied to exact image/package/commit/config hashes | **UNVERIFIED**. `m3a-soak-evidence.md:3` explicitly labels historical evidence provisional. This validation report does not claim to be a hash-bound RC soak bundle. |

## Final handoff

**BLOCKED** on release acceptance, not on the historical CI log. The only file
changed this round is this report. No production/test/ledger edit is justified
by the reproduced gate results. Existing branch history and artifacts are
preserved; the broad inherited diff is not certified by this focused review.
No merge/sync conflict was present, so no fetch/merge was needed.

Next required inputs/work: designate the immutable RC and supported runtime
configuration, resolve the replica-budget acceptance mismatch, complete the
representative workload and physical-effect/recovery/application-telemetry
oracles, then run the unchanged production artifact for at least 14400 seconds.
Docker availability is not asserted as a blocker; missing RC designation and
insufficient oracles cannot be repaired by repeating a short host preflight.

Progress: checked 1 issue; done 0 acceptance-complete issues; skipped 0 issues;
errors 0 fresh validation commands. Six DB-dependent tests remain skipped. This
report is committed locally as the writer handoff; it is not integration or
promotion approval.
