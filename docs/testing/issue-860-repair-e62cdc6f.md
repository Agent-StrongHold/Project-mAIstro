# Issue #860 repair — e62cdc6f

## Frozen scope

- Issue #860 only; branch `auto-860`, clean starting HEAD
  `fb3541a905fa6963906d6389881dfa9d1d13ba3d`.
- Supplied base resolves: `30a8ff9d7307deb5595a634e0d359810538e313f`.
- Evidence snapshot: supplied dispatch-context.json and prior result
  e228664563f540aa88f3c50170255507/result.json; reported failure
  98a11313167b41a98a420abfda80c292/check-3.log. Current job has no check logs.
- Repair candidates frozen to persistence/pg_learnings.py, its adjacent
  test_pg_learnings.py, quality/vulture-baseline.json only if the instructed
  scan demonstrates retained debt, and this report / matching inventory note.
- Acceptance inspection: existing scripts/soak/run_soak.py,
  tests/test_soak_promotion_gates.py, docs/testing/soak/m3a-load-profile.md,
  m3a-soak-evidence.md and evidence/m3a-round30-shakedown.json; relevant
  repository instructions, ADRs and gate scripts/workflows.

## Initial evidence / assumptions

The supplied historical failure reports 24 schema statements against 21
expected statements. Reproduce before changing anything. The previous result
is BLOCKED on exact-RC evidence, not a develop merge conflict. Do not merge or
fetch unrelated changes. No exact RC artifact/configuration is supplied by the
dispatch; historical shakedowns are not assumed to satisfy promotion.

No scheduler, execution authority, authorization path or production topology
will be invented to turn a preflight into an RC soak.

## CI repair results (freshly executed)

- `uv sync --locked --extra dev`: passed; 256 resolved, 214 checked.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  **37 passed, 6 skipped**. The historical 24-vs-21 failure is not reproducible:
  the independent expected-DDL list already includes all three Gauntlet columns.
  No schema/test edit justified; skips are not live PostgreSQL proof.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'`: passed, **1326 reviewed identities / 1326 findings,
  zero unclassified, zero never_allowlist**, trusted base `e46ad6708fda`.
  No unbanked debt; ledger amendment would not repair any observed failure.

Both dispatched CI repair targets are already passing. Continue only with the
frozen acceptance inspection and validation; do not search for unrelated repairs.

## Architecture / acceptance inspection

Read repository AGENTS.md and documentation authority map plus accepted ADR-087
(schema expansion), ADR-081626-f383 (Attempt lease fencing), ADR-082426-82c7
(occurrence claim), ADR-083026-a91e (unmeasured metrics), and ADR-085 (principal
rate limiting). Admission uniqueness does not establish physical-work uniqueness;
process exit does not establish lease recovery. ADR-085 does not justify waiving
the issue's replica-selection requirement. No competing authority or policy
change is proposed.

The frozen load profile explicitly calls the runner a host-process preflight,
excludes representative user/Workspace, Graph, tool/model, Design/Canvas and
Goal worker traffic, and identifies missing production-loop and recovery proof.
`run_soak.py:730` always rejects exact-RC artifact equivalence. The existing
production-middleware regression at `test_soak_promotion_gates.py:439` checks
independent per-replica allowances, not a shared budget. Validate these checks
now; no additional short emulator soak could close those gaps.

## Additional executed validation

- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed (3195 files).
- `uv run pytest packages/maistro-core/tests/persistence -x -q`:
  **604 passed, 290 skipped**, 27 SQLite datetime-adapter deprecation warnings.
- `uv run pytest tests/test_soak_promotion_gates.py
  tests/test_prod_stack_boot_contract.py
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  **74 passed**. Includes actual production limiter instances, negative admission
  probes, real subprocess sampling, preflight CLI rejection and task backpressure.
- Imported the current soak module and called `failed_promotion_checks` against
  `docs/testing/soak/evidence/m3a-round30-shakedown.json`, asserting its rejected
  checks are exactly `sustain_duration` and `exact_rc_artifact`: passed.
  Printed observed **420.08 seconds** against minimum **14400**, and artifact
  rejection reason `not the exact production Compose image and configuration`.
  This re-evaluates historical evidence; it is not a fresh deployed soak.
- `uv run python scripts/check-ratchet-provenance.py`: passed (52 consumers plus
  delegated gates); existing syntax/local-HTTP CORS warnings did not fail it.
- `uv run python scripts/check-shipped-surface-truth.py`: passed.
- `git diff --check`: passed.
- Reachability inspection: production `maistro_server/main.py:648` installs the
  tested RateLimitMiddleware; its module at `api/rate_limit.py:32-34` explicitly
  documents process-local state and N-times aggregate budget. The passing
  two-replica test observes `[200, 200, 429]` separately on each instance for the
  same identity, both authenticated and unauthenticated. This is positive
  evidence of independent allowances, not deployment-wide non-bypass proof.

## All acceptance criteria

| Criterion | Executed evidence / disposition |
| --- | --- |
| Representative RC load profile | **UNVERIFIED complete**: inspected profile explicitly lacks multi-user/Workspace, Graph fan-out, successful model/tool, Design/Canvas and Goal-worker traffic (`m3a-load-profile.md:152`). |
| At least two deployed replicas | **UNVERIFIED for RC**: ASGI two-instance tests passed; these are not deployed images. Existing runner identifies itself as host preflight. |
| Sustained saturation, reclaim, retry and leaks | **UNVERIFIED**: historical evaluator rejects 420.08 s versus 14400 s; passing subprocess sampler tests cannot establish long-window production behavior. |
| Exactly-once/fenced physical work and Goal reconciliation | **UNVERIFIED**: admission negative tests pass, but the schedule probe cancels its queued Run without physical execution. No production Attempt/Goal soak executed. |
| Rate limiting, security/degraded behavior, replica-selection resistance | **UNVERIFIED as a whole; independent allowances reproduced** by both production-middleware identity tests. Six-path rejection probes do not prove a shared allowance; no waiver inferred from ADR-085. |
| Complete telemetry and thresholds | **UNVERIFIED**: sampler tests pass; profile admits missing application-loop, detached-worker, saturation/reclaim and long-window observations. Driver loop timing is not application-loop timing. |
| Active-work kill/restart, drain/fencing/recovery | **UNVERIFIED**: boot/cleanup gate tests pass but no physical in-flight Attempt recovery drill was executed. |
| Long exact-RC soak, rerun after changes | **UNVERIFIED / BLOCKED**: executed evaluator rejects both duration and artifact; current CLI preflight rejection tests pass. Dispatch supplies no selected immutable promotion image/configuration. |
| Findings filed/reclassified at earliest invariant | **UNVERIFIED complete**: human evidence classifies historical findings and explicitly records some external filings not performed. No GitHub mutation authorized or performed. |
| Published machine/human evidence with exact artifact/config hashes | **Partial historical evidence only; exact-RC publication UNVERIFIED**: both formats inspected, but machine artifact/duration checks reject promotion equivalence. |

## Handoff

**BLOCKED for #860 acceptance; no reproducible CI repair remains in the two
assigned targets.** This report is the only changed file. No source, tests,
thresholds, ledger, grants or prior evidence changed. No inventory note is needed:
there are no added/removed tests. No external mutation, merge, service startup or
background command was performed. PostgreSQL-skipped tests are not claimed as
live concurrency proof. Full-tree pytest intentionally not run.

Next prerequisite: select and supply immutable RC images and complete runtime
configuration for #89, finish its representative production-path workload and
telemetry, reconcile replica-selection protection, then execute at least the
four-hour profile with correlated physical Attempt fencing/recovery. Repeating
these already-green CI checks or a short host-process soak cannot resolve that
blocker. Do not schedule another identical repair without new failure evidence
or those production-soak prerequisites.

Progress: `{checked: 3, done: 2, skipped: 1, errors: 0, next: exact-RC acceptance}`.
The skipped item is executing a new production soak, not acceptance validation.
Commit this report locally as required; it records a blocked handoff, not merge
or integration approval.
