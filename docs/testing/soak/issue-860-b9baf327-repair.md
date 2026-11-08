# Issue #860 — bounded CI repair b9baf327

## Frozen scope

Only issue #860, branch `auto-860`, starting head
`1a6cb3d22b8a6dbdcd511ff75695249f3654f5d6`, supplied develop base
`ab8b3737fa64f8d840f421ef87ca506c509444ff`.
Worktree was clean. No salvage was necessary.

Inspect the supplied dispatch snapshot, reported check-3 failure, repository
instructions/ADRs, soak implementation and adjacent tests. Candidate repair
surfaces are `quality/vulture-baseline.json` (only observed reviewed identities),
`scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`, an inventory note
if tests change, and this handoff. No other issue/PR will be processed.

Ambiguity: assignment is a writer CI-repair, while generic prompt also describes
a read-only verifier. Proceed as writer per explicit lane and commit requirement.
The current job directory had no check-*.log files at initial inspection. The
prior BLOCKED result is evidence to revalidate, not proof of current behavior.

## Progress

Initial head and clean status verified. Acceptance includes actual sustained
production multi-replica execution, not just preflight/unit-test success.
The supplied prior check-3 log is a failing schema-fence assertion (24 actual
DDL statements versus 21 expected), not a vulture finding. Include read-only
validation of `packages/maistro-core/tests/persistence/test_pg_learnings.py`;
no repair is justified unless that failure reproduces.

The required exact vulture command passed: 1,322 reviewed identities matched
1,322 findings, zero unclassified and zero never-allowlist findings. No ledger
amendment is warranted. `docs/testing/soak/README.md` was not found; skipped in
favor of the explicit profile/evidence paths in the driver's module docstring.

Fresh validation:

- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py -x -q`
  — **109 passed, 6 skipped**, 2.61 s. The schema-fence test now explicitly
  includes the three Gauntlet audit columns (lines 176–180); the reported
  24-versus-21 failure does not reproduce. Skips are not production proof.
- `uv run ruff check .` — passed.
- `uv run ruff format --check .` — passed, 3,301 files already formatted.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  — passed against supplied base `ab8b3737fa64`.

Architecture reconciliation: accepted ADR-081426-1f7c assigns physical identity
to Attempt and keeps domain semantics outside ExecutionRuntime. Accepted
ADR-081626-f383 requires canonical-store lease/fencing authority and explicitly
does not yet define expiry takeover. ADR-085 requires per-principal rate limits;
it does not establish shared replica state. An admission race, a queued Run
cancellation, or local middleware enforcement cannot substitute for the issue's
physical-work/recovery and replica-selection acceptance. No alternative scheduler,
store, authorization path, or authority was introduced.

- `uv run python scripts/check-suite-inventory.py` — passed: all 17 suites,
  31,327 unique identities, zero duplicate evidence. No tests were added or
  changed, so no inventory delta note is necessary.
- `git diff --check` — passed before final handoff update.

## Acceptance disposition

These are current scope judgments, not adoption of earlier verification claims.
The freshly executed tests prove narrow preflight properties only.

| # | Criterion | Evidence / status |
|---|---|---|
| 1 | Representative RC profile | **UNVERIFIED**: profile defines traffic and thresholds but explicitly lacks multi-user/Workspace, Graph fan-out, successful model/tool, Design/Canvas and Goal/background workloads (`m3a-load-profile.md`, Remaining representative-profile gaps). |
| 2 | At least two production application replicas | **UNVERIFIED**: `run_soak.py:744–755` identifies the runner as host-uvicorn preflight, not promoted Compose. ASGI middleware instances in tests are not deployed replicas. |
| 3 | Sustained saturation/reclaim/leak/restart load | **UNVERIFIED**: no sustained load was run this round; short deterministic tests cannot prove the required four-hour observations. |
| 4 | No duplicate physical work across replicas | **UNVERIFIED**: `run_soak.py:1067–1092` cancels the schedule probe Run without executing it. Canonical admission uniqueness is narrower than physical-work fencing. |
| 5 | Replica-independent rate/security/degraded enforcement | **UNVERIFIED, counterevidence reproduced**: both parametrizations of `test_replica_selection_has_an_independent_production_allowance` passed. The same identity receives `[200,200,429]` independently on each real middleware instance (`tests/test_soak_promotion_gates.py:439–492`); middleware creates `InMemoryRateLimiter` per instance (`rate_limit.py:95`). |
| 6 | Production telemetry with explicit thresholds | **UNVERIFIED**: real wrapper/child sampler regression passed, but no production query/pool/app-loop/worker telemetry was captured. Driver loop latency and driver SELECT 1 are not application telemetry. |
| 7 | Active-work kill/restart drain/fencing/recovery | **UNVERIFIED**: exit/rejoin and queued probe cancellation do not show physical Attempt recovery; no active-work production fault injection was executed. |
| 8 | Long-running exact RC artifact/config soak | **UNVERIFIED**: all three CLI rejection cases passed for otherwise-passing four-hour evidence with missing/null/preflight artifact records. This establishes fail-closed rejection, not a successful RC soak. |
| 9 | Findings classified to earliest broken invariant | **UNVERIFIED**: historical evidence pack contains local findings, but this round cannot establish complete disposition of production-load findings without the required run. No GitHub mutations performed. |
| 10 | Published hash-bound machine/human production evidence | **UNVERIFIED**: this handoff is validation evidence at the stated starting head, not new production soak evidence. Historical packs do not validate the current exact RC. |

## Handoff / stop condition

**BLOCKED** on production acceptance, not on a reproduced vulture/schema-test
failure. The only changed file in this round is this handoff. No ledger,
runtime, tests, configuration, or gates were modified. Inventing a scanner
repair or rerunning the known non-promoting emulator cannot resolve this gap.

Next prerequisite: select the immutable RC image/configuration and complete its
representative production workload/telemetry harness using canonical execution
authority; resolve and re-prove the replica-selection enforcement gap and
physical Attempt recovery before the >=4-hour production soak. Any runtime or
configuration repair then requires a fresh exact-artifact soak. Earlier
provisional findings must retain their scope; none is promoted by this commit.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "production RC prerequisites and soak"}`.
The assigned issue remains unfinished; this commit preserves the checked
failure disposition and acceptance blockers for handoff only.
