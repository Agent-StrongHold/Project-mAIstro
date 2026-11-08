# Issue #860 bounded repair — e2286645

## Frozen scope

- Only issue #860, branch `auto-860`, starting HEAD
  `7a70eeafca8eb687698c9ecb6f17bdbbf254e9d5`; supplied develop base
  `1c55afe5189619e1cbac7e1eaf20725d4d5b6621`.
- Work items, in order: (1) reproduce/repair the supplied learnings schema-fence
  test failure; (2) run the exact vulture gate and review actual findings only;
  (3) validate existing soak acceptance evidence and record unresolved criteria.
- Candidate edit files: `packages/maistro-core/tests/persistence/test_pg_learnings.py`,
  `docs/testing/inventory-notes/issue-860-schema-fence-refresh.md`,
  `quality/vulture-baseline.json` (only if the instructed scan establishes debt),
  and this report. Production/schema and soak code, adjacent tests, ADRs, and CI
  definitions are inspection/validation inputs, not a mandate to widen repairs.
- Initial worktree clean; no salvage needed. No GitHub mutations or integration.

## Initial evidence and assumptions

- Job directory has no `check-*.log`; inspected the explicitly supplied prior
  `98a11313167b41a98a420abfda80c292/check-3.log` instead. It reports 24 schema
  statements versus the test's expected 21. This is historical evidence and
  will be reproduced before editing.
- Prior result `c9cda998b4534842a93635b5351969d8/result.json` reports BLOCKED,
  with no complete exact-RC soak. It is not accepted as current verification.
- Ambiguity: dispatch requests both CI repair and complete production soak.
  Proceed with bounded evidence-driven CI repairs; report missing production
  acceptance honestly rather than inventing an RC artifact or deployment.

## Results

### Item 1 — supplied schema-fence failure: already repaired, no edit

- `uv sync --locked --extra dev`: passed (256 resolved, 214 checked).
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  **37 passed, 6 skipped** in 1.36s. PostgreSQL-only cases were skipped;
  this is not live database concurrency proof.
- The current independent expected-DDL list already includes
  `validated_evaluator_version`, `validation_run_ids`, and
  `validation_content_hash`, matching the additive production upgrades inside
  the transaction/advisory lock. The historical 24-versus-21 failure is not
  reproducible. Do not weaken or duplicate the test; no inventory delta.
- ADR-087 retains additive migration ownership; no production schema or
  execution authority changed. Current branch differs substantially from the
  supplied develop tip; that two-tip diff alone is not evidence of a merge
  conflict, and no sync conflict was reported. No merge performed.

### Item 2 — exact vulture gate

Completed: `uv run python scripts/check-vulture-baseline.py packages/*/src
--min-confidence 60 --exclude '*/third_party/*'` exited 0: **1326 findings,
1326 reviewed identities, 0 unclassified, 0 never_allowlist**, trusted merge
base `e46ad6708fda`. Arguments match `.github/workflows/vulture-ratchet.yml`.
No missing identities were found; changing the ledger would be unsupported.

### Item 3 — acceptance and remaining validation

Inspected accepted ADR-081626-f383 (Attempt fencing),
ADR-082426-82c7 (occurrence admission is not physical-work proof), and
ADR-083026-a91e (missing measurement is not zero). The load profile explicitly
identifies the current runner as host-process preflight, not production Compose,
and lists representative-workload and telemetry gaps. Preserve the canonical
Goal → Graph → Run → NodeRun → Attempt model; do not substitute a second runner
or authority to manufacture passing promotion evidence.

Executed validation:

- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 3195 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py
  tests/test_prod_stack_boot_contract.py
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  **74 passed** in 2.21s. This includes real production limiter instances,
  negative HTTP-probe cases, real subprocess resource sampling, CLI rejection
  of preflight evidence, and task backpressure mapping. ASGI tests and host
  subprocess sampling do not establish deployed-replica correctness.
- Imported `scripts/soak/run_soak.py` and executed `failed_promotion_checks`
  against `docs/testing/soak/evidence/m3a-round30-shakedown.json`, asserting both
  duration and artifact rejection: passed; rejected checks are exactly
  `sustain_duration` and `exact_rc_artifact`. This is evaluation of historical
  evidence, not a fresh soak. It records **420.08 s**, versus **14400 s** minimum,
  and an older code hash `c4f45b309fd622f2e8a4b315dad35e721d81aad3`.
- `test_replica_selection_has_an_independent_production_allowance` passed for
  authenticated and unauthenticated callers: the same identity exhausts one
  instance (`200, 200, 429`) then receives another allowance on the second
  (`200, 200, 429`). Thus local overload enforcement is demonstrated, not the
  issue's replica-selection non-bypass requirement. ADR-085's principal-keyed
  policy is not permission to silently waive that requirement.

- `uv run pytest packages/maistro-core/tests/persistence -x -q`: **604 passed,
  290 skipped, 27 warnings** in 4.09s. Skips are not claimed as database proof;
  warnings concern Python 3.12's deprecated SQLite datetime adapter.
- `uv run python scripts/check-ratchet-provenance.py`: passed, 52 quality JSON
  consumers have explicit provenance; delegated gates passed. Existing syntax
  and local HTTP CORS warnings did not fail the gate.
- `uv run python scripts/check-shipped-surface-truth.py`: passed.
- `git diff --check`: passed.
- Wiring inspection: `packages/maistro-server/src/maistro_server/main.py:648`
  installs the tested production `RateLimitMiddleware`. An additional searched
  `maistro_server/app.py` path was not found; skipped, not a product defect.

Only this report changed. No code, tests, thresholds, or ledgers changed. No new
or removed tests means no inventory delta or inventory-note addition is warranted.
Full-monorepo pytest was not run; validation stayed within the affected persistence,
server-backpressure, and soak/boot-contract surfaces.

## Acceptance audit (all ten issue criteria)

| Criterion | Current evidence and disposition |
| --- | --- |
| Representative RC profile | **UNVERIFIED complete.** `m3a-load-profile.md:152` explicitly excludes concurrent users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and Goal/background-worker workloads from the current preflight. A documented partial profile is not representative execution evidence. |
| At least two deployed application replicas | **UNVERIFIED at exact RC.** `deploy/docker-compose.prod.yml:26` and `:79` define two replicas, but the current runner reports host uvicorn preflight (`run_soak.py:730`), not those promoted images/configuration. No fresh deployed soak executed here. |
| Sustained saturation/reclaim/retry/leak observations | **UNVERIFIED.** Executed historical evaluator rejects the supplied 420.08-second sample against the 14400-second minimum. Process sampler regression passes but does not establish long-window pool, queue, lease, or leak behavior. |
| Physical-work uniqueness, admission, Goal reconciliation | **UNVERIFIED complete.** Negative admission-probe tests pass; `run_soak.py:1044` explicitly cancels the schedule probe's queued Run without executing it. One admitted Run is not proof of nonduplicated physical Attempts or Goal reconciliation. |
| Security/degraded behavior and replica-selection resistance | **Not proven; narrower independent-allowance claim reproduced.** Both production-middleware identity cases in `test_soak_promotion_gates.py:439` pass with a second allowance on replica 2 after replica 1 is exhausted. Six-path overload rejection does not demonstrate a shared budget. Full deployed security/degraded behavior remains **UNVERIFIED**. |
| Complete telemetry with thresholds | **UNVERIFIED.** Historical evidence has PG/resource samples and thresholds, but `run_soak.py:1410` measures driver loop lag, not application event-loop lag. The profile acknowledges worker/pool/reclaim and long-window gaps. |
| Kill/restart during active work, drain/fencing/recovery | **UNVERIFIED.** Historical process drain/rejoin booleans do not correlate killed physical Attempts with durable lease/fence recovery. No active-work kill/restart was executed in this repair. |
| Long exact-RC soak; rerun after changes | **UNVERIFIED / blocked.** Executed evaluator rejects `m3a-round30-shakedown.json:222` (artifact) and `:280` (duration). Its code hash at `:70` is not this repair's starting head. No exact promoted image/configuration was supplied for a replacement run. |
| Load findings filed/reclassified at earliest invariant | **UNVERIFIED complete.** `m3a-soak-evidence.md` records and classifies historical findings; this does not prove all external filing/reclassification is complete. No GitHub mutation was performed. |
| Machine/human evidence tied to exact hashes | **Partial historical evidence only; exact-RC publication UNVERIFIED.** Re-evaluated JSON and the human evidence pack exist, but their own artifact check rejects promotion equivalence. No new soak evidence or publication is claimed. |

## Handoff

**BLOCKED for issue acceptance, not a reproduced CI failure.** Both dispatched CI
repair targets already pass at the supplied head. Making speculative source or
ledger changes would not address actual evidence. This commit records fresh
validation, not implementation completion or integration approval.

Next: supply the immutable RC images and complete runtime configuration intended
for #89; complete a production-path representative profile, reconcile the
replica-selection requirement with the supported rate-limit deployment, and run
that exact topology for at least the profile's four-hour minimum with active-work
fencing/recovery and full telemetry. Do not repeat short host-process soaks as a
substitute. No merge, push, PR, issue action, or background service started.

Progress: `{checked: 3, done: 2, skipped: 1, errors: 0, next: exact-RC acceptance}`.
The skipped work is new production soak execution, not silently passed acceptance.
Local diagnostic logs: `/tmp/860-e228-{schema,vulture,ruff,format,focused,persistence,
provenance,surfaces}.log`; historical evaluation:
`/tmp/860-e228-historical-evaluation.json`. Outcomes above remain in this committed
report even if temporary logs expire.
