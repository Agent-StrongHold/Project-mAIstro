# Issue #860 repair checkpoint — 12bfc6a2

## Frozen scope

- Assigned issue: #860 only; branch `auto-860`.
- Starting HEAD: `ce2f51629dd33f43ade506a804356f6f5416a2df` (verified); clean worktree.
- Supplied base: `9a4b0c5cc0fc9a5b64589382c4b6b26cd0a183e4`.
- Process existing soak harness/profile/evidence and adjacent promotion tests;
  reported suite-inventory mismatch; exact vulture gate and any identities it
  actually reports. No other issues or linked PRs will be processed.
- Potential write surfaces: this checkpoint, existing soak harness/tests,
  `docs/testing/inventory-notes/860-12bfc6a2.md`, and
  `quality/vulture-baseline.json` only if the authorized scan demonstrates debt.
- Read-only supporting surfaces: repository instructions, relevant ADRs,
  deployment/rate-limit wiring, inventory/gate implementation and CI arguments.

## Initial evidence / assumptions

The job directory has no `check-*.log` files at inspection. The dispatch snapshot
contains the ten issue acceptance criteria; prior claims are not fresh validation.
This is a writer repair, not verifier-only work. No exact promoted RC artifact or
runtime configuration has been assigned; do not invent one or call a local unit
test a multi-replica production soak. No GitHub mutations are permitted.

## Progress

- Exact vulture command passed: 1322 reviewed identities, 1322 findings,
  zero unclassified/never-allowlist findings. No ledger amendment warranted.
- `uv run python scripts/check-suite-inventory.py --suite tests` failed:
  expected 5353, collected 5354. Investigate provenance before recording a delta.
- Existing profile explicitly labels its runner a preflight emulator and leaves
  representative workloads/physical fencing/long-window observations unproven.
  Prior result read; its blocked outcome is not treated as fresh evidence.
- `uv run ruff check .`: passed. `uv run ruff format --check .`: passed
  (3306 files). Focused soak + production boot contracts: 92 passed.
- Inventory provenance: UNRESOLVED after bounded inspection of the supplied
  base diff, latest test merge, overlapping-wheel note and strict-booleans note.
  The latter correctly records its 12 parametrized additions. Do not bank an
  unexplained +1 or delete a test to silence the alarm. No tests added here.

## ADR reconciliation

Read ADR-085, ADR-081226-a66b, ADR-081626-f383 and ADR-082526-547c.
Rate limits remain per principal, through the canonical resolver; adding a new
limiter/authorization path is not an appropriate soak repair. The existing
process-local enforcement is not evidence for replica-independent allowance.
Canonical Attempt fencing rejects stale writers, but ADR-081626-f383 explicitly
leaves lease-expiry takeover outside its current contract. Do not invent reclaim
semantics or infer physical-work deduplication from Run admission counts.
ADR-081 is Proposed, not an accepted topology waiver. The selected production
configuration and representative workload still need explicit RC ownership.

## Executed validation

All commands ran in the assigned worktree with 1200-second timeouts.

| Command | Outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS; 1322/1322, no new debt |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS; 3306 files |
| `uv run python scripts/check-suite-inventory.py --suite tests` | FAIL; 5353 expected, 5354 collected |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q` | PASS; 92 tests |
| `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | PASS; 1 test |
| `uv run python` importing `scripts/soak/run_soak.py`, loading round-30 JSON and calling `failed_promotion_checks` | Returned `['sustain_duration', 'exact_rc_artifact']`; duration 420.08 seconds; host-uvicorn-preflight |

Command logs are `/tmp/860-12bfc6a2-{vulture,ruff,format,inventory,soak-tests,server-tests}.log`.
No new tests, inventory deltas, baseline edits, runtime changes, or gate changes.
The only changed file is this handoff. No new live soak was run: the existing
runner cannot attest the promoted artifact even after four hours, and selecting
an arbitrary new configuration would not establish the issue's exact-RC claim.

## Acceptance evidence (all ten criteria)

1. **Representative workload: UNVERIFIED.** Profile exists, but
   `m3a-load-profile.md:167-183` explicitly excludes concurrent users/Workspaces,
   fan-out, successful tool/model calls, Canvas and Goal reconciliation.
2. **Two application replicas: UNVERIFIED for the RC.**
   `deploy/docker-compose.prod.yml:26-77` declares two application services;
   passing boot-contract tests establish wiring, not a fresh deployed run.
3. **Sustained saturation/reclaim/leak observations: UNVERIFIED.** Executed
   evaluator rejects the 420.08-second round-30 evidence against the 14400-second
   minimum; profile gaps remain. No lease-takeover semantics invented.
4. **Exactly-once/fenced physical work: UNVERIFIED.** Passing admission/evidence
   tests and one-occurrence race design do not prove physical Attempt execution
   or sustained Goal reconciliation (`m3a-load-profile.md:215-217`).
5. **Replica-independent rate/security/degraded behavior: NOT MET.** Executed
   `test_replica_selection_has_an_independent_production_allowance` (both auth
   variants, `tests/test_soak_promotion_gates.py:481-526`) observes each middleware
   accepting two requests independently, then returning 429. Production installs
   this middleware at `packages/maistro-server/src/maistro_server/main.py:648`;
   per-instance limiter construction is in `api/rate_limit.py:92-100`.
   Backpressure regression passes; it does not satisfy the broader criterion.
6. **Metrics and thresholds: UNVERIFIED at promotion grade.** Profile defines
   thresholds and tests validate sampler/probe behavior; application event-loop
   latency, saturation and long-window leak evidence are still absent. Driver
   loop latency is not application loop latency.
7. **Active-work restart/drain/fenced recovery: UNVERIFIED.** Passing evaluator
   tests are not a live kill/restart during physical work on the RC.
8. **Long-running exact RC: NOT MET.** Direct evaluator execution rejects both
   duration and artifact identity in `evidence/m3a-round30-shakedown.json`.
9. **Findings filed/reclassified: UNVERIFIED.** Local findings recorded here;
   no remote filing or issue mutation performed or claimed.
10. **Machine/human evidence with promoted hashes: UNVERIFIED.** Existing JSON
    and profile are inspectable historical preflight evidence, not evidence for
    this head or a supplied immutable promoted image/configuration.

## Handoff / stop condition

Verdict: **BLOCKED**. This is not a completed implementation or promotion signoff.
The authorized CI-repair scan found nothing requiring a ledger edit. The inventory
mismatch remains unresolved; do not mask it with a guessed delta. Required next
inputs/work are an owner-selected immutable RC image/configuration and supported
workload matrix, production-path instrumentation/runner, resolution or explicit
architectural reconciliation of replica-selectable budgets, and a fresh ≥4-hour
soak covering physical work and recovery. A subsequent code/configuration change
requires another soak. Re-running this same preflight cannot close those gaps.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 1, next: RC prerequisites and inventory provenance}`.

## Follow-up validation — job 0a8dafd2

Starting HEAD `9e55b3bb9cb74fe040860aaf90162adb96b6680e` was clean.
No driver `check-*.log` files were supplied. The following were executed again,
not inferred from the preceding report (600-second validation timeouts):

- Exact vulture command above: **PASS**, 1322 reviewed identities / findings,
  zero unclassified and never-allowlist findings. No ledger change justified.
- Ruff check and format check: **PASS**, 3306 files already formatted.
- Inventory `--suite tests`: **FAIL**, expected 5353, collected 5354.
- Soak promotion + production boot + server backpressure tests: **93 passed**.
- Server rate-limit + backpressure tests: **27 passed** (the backpressure test
  overlaps the preceding invocation; these are not 120 distinct tests).
- `uv run python scripts/check-deployment-claims.py`: **PASS**, component/backend
  names resolve; this does not establish deployed behavior.
- Round-30 evidence re-evaluated with the current `failed_promotion_checks`:
  **rejected** for `sustain_duration` and `exact_rc_artifact`, at 420.08 seconds.

### Inventory provenance refinement

The supplied develop ref is **not an ancestor** of this branch:
`git merge-base 9a4b0c5cc0fc9a5b64589382c4b6b26cd0a183e4 HEAD` returns
`2f56be40ad241262b0384ab0b97834ebd37fe4d7`. A triple-dot diff is therefore
not a comparison against the supplied develop tree. Do not treat it as one.
The triple-dot root-test diff contains only the soak, boot and gitleaks files;
their fresh collections are respectively **84, 8 and 8**. The supplied base
boot file contains seven unparametrized tests, and the changed inventory notes
sum to **+93** for `tests/`. These counts do not identify the unexplained extra
node or prove a clean collection of either base. The direct two-tree diff also
includes CI-test changes absent from the triple-dot diff. Provenance remains
**UNRESOLVED**; no guessed +1 note, baseline edit or test removal was made.

All ten acceptance dispositions above remain unchanged. The production-middleware
replica-selection tests executed again and still demonstrate independent budgets.
Accepted ADR-081626-f383 does not authorize inventing lease-expiry takeover to
satisfy the issue. No exact RC identity/configuration was supplied and no new
promotion soak was run. This follow-up changes only this handoff, not production
behavior, tests, gates or evidence artifacts. Logs and the frozen work notes are
in `/home/dev/maistro/jobs/0a8dafd2e98e44e9a4610b144a5a524c/worker-*`.

Disposition: **BLOCKED**, not a vulture repair or integration approval.
Next: resolve inventory provenance, obtain the selected immutable RC and workload
matrix, address replica-selectable rate budgets and production-path coverage,
then execute the required sustained soak. Repeating a clean vulture scan or a
short preflight cannot resolve these prerequisites.

