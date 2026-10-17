# Issue #860 — repair checkpoint (3ae30d57)

## Frozen scope

- Only issue #860; branch `auto-860`, starting HEAD
  `13a7d596c61fe501317ae9fb82c4d88c95ed1308`, supplied base
  `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Initial worktree is clean; no incoming edits to salvage.
- Repair candidates: `packages/maistro-core/src/maistro/persistence/pg_learnings.py`,
  `packages/maistro-core/tests/persistence/test_pg_learnings.py`,
  `quality/vulture-baseline.json` (only measured, reviewed identities),
  `docs/testing/inventory-notes/860-3ae30d57-repair.md` if tests change,
  and this report. Other issue/PR work is out of scope.
- Evidence inspected: supplied dispatch-context.json issue body, prior result
  0a4d9505, and prior check-3.log from 98a11313. Current job directory has no
  check-*.log files at initial snapshot.
- The prior check reports 24 schema statements versus 21 expected. This is
  historical evidence, not proof of a current failure. Reproduce before repair.
- Assumption: this is a writer CI-repair round, not a verifier-only round.
  No RC artifact/config identity is supplied by the lane. Existing host-soak
  results must not be represented as promotion evidence.

## Validation

Fresh execution disproves the dispatched CI failure at this HEAD:
`uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q -rs`
passed (37 passed, 6 skipped for missing `MAISTRO_TEST_PG_DSN`). The schema test
already independently lists all 24 fenced DDL statements, including the three
Gauntlet validation columns. No repair to this test is warranted.

`uv sync --locked --extra dev` passed. The exact requested vulture scan passed:
1323 reviewed identities / 1323 findings, zero unclassified or never-allowlist.
The gate chose trusted base `4aa68edc0b6b`; no base override was used. No ledger
amendment is warranted. `uv run ruff check .` passed and
`uv run ruff format --check .` passed (3270 files). These are CI results, not
proof of issue acceptance. No tests or test counts changed.

Additional executed validation (1200-second command timeout):

| Command | Outcome |
| --- | --- |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q -rs` | 66 passed, 2.26 s |
| `uv run python scripts/check-ratchet-provenance.py` | PASS, 53 consumers; existing invalid-escape SyntaxWarnings |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS |

Vulture command, verbatim:
`uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`.
Companion gates match `.github/workflows/vulture-ratchet.yml:77-86`.
No live PostgreSQL tests or new production soak were executed; skipped tests
are not evidence of multi-replica database safety.

## Architecture and acceptance review

Read repository AGENTS.md and docs/README.md; read Accepted ADR-081226-a66b,
ADR-081626-f383, ADR-082426-82c7 and ADR-085. Preserve
Goal -> Graph -> Run -> NodeRun -> Attempt. The canonical Run store owns
occurrence claims and execution fencing. Admission uniqueness cannot prove
physical-work uniqueness. The lease ADR explicitly leaves expiry takeover of
an apparently live Attempt undefined: #860 is not permission to create a
competing reclaim authority. Existing per-principal authentication and rate
limiting must not be replaced with an alternate authorization path.

| Issue acceptance criterion | Fresh evidence / remaining gap |
| --- | --- |
| Representative RC load profile | **UNVERIFIED**. `m3a-load-profile.md` defines a preflight profile and explicitly lists remaining representative-profile gaps. Current driver uses one credential and health/task/receipt/metrics mix (`scripts/soak/run_soak.py:1373-1397`), not demonstrated concurrent Workspaces, Graph fan-out, successful tool/model calls or Canvas/background workloads. |
| At least two application replicas | **UNVERIFIED for RC**. Executed ASGI middleware tests use two instances, not two deployed RC replicas. |
| Sustained saturation, queue growth, lease reclaim, retry/backoff, resource leaks and shutdown | **UNVERIFIED**. The real uv-wrapper/child resource-sampler regression passed, but no sustained production load was run. |
| No duplicate physical schedule/task/Run/Attempt work and Goal reconciliation | **UNVERIFIED**. `scripts/soak/run_soak.py:1044-1069` explicitly cancels the schedule probe Run without executing it. HTTP admission regression tests do not prove physical effects or sustained Goal reconciliation. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **Not proven; shared allowance claim falsified**. Fresh `tests/test_soak_promotion_gates.py:439` test observes `[200,200,429]` on each production middleware instance with the same IP/credential. `packages/maistro-server/src/maistro_server/main.py:648` installs that middleware; `api/rate_limit.py:32-37` documents independent N-times aggregate allowance. This is documented local enforcement, not proof of the issue's non-bypass criterion. Full deployed security/degraded behavior remains **UNVERIFIED**. |
| Full telemetry with explicit thresholds | **UNVERIFIED**. Sampler regressions pass, but `scripts/soak/run_soak.py:1421` measures driver-loop lag rather than application event-loop latency; no complete RC database/worker/queue/error series collected. |
| Kill/restart during active work proves drain/fencing/recovery | **UNVERIFIED**. Boot cleanup tests pass. `scripts/soak/run_soak.py:1439-1490` observes process exit/rejoin and request counters, not a physical-effect/stale-Attempt reconciliation oracle. |
| Long unchanged exact-RC soak | **BLOCKED / UNVERIFIED**. `scripts/soak/run_soak.py:730-741` explicitly rejects host preflight as exact RC. The executed synthetic four-hour CLI cases fail closed as intended. No immutable RC/configuration is supplied or soaked. |
| Findings filed/reclassified before promotion | Local findings preserved here. External disposition **UNVERIFIED**; GitHub mutations prohibited. |
| Machine/human evidence bound to image/package/commit/config hashes | **UNVERIFIED for RC**. This is a fresh local validation report, not a hash-bound production soak evidence pack. Prior artifacts preserved, not relabeled as current. |

## Disposition

**BLOCKED for issue acceptance.** The prior schema failure is stale and the
requested vulture scan has no unbanked identities. No production, test, ledger
or grant edits are justified by these CI results. No inventory note is needed
because tests and counts are unchanged. Only this report changes.

Next: select the immutable RC/configuration, resolve the replica-selection
acceptance mismatch within the supported deployment contract, supply
representative workloads and physical-work/recovery oracles plus complete
telemetry, then run the long unchanged-artifact soak. Re-dispatching the same
passing schema/vulture checks cannot resolve these acceptance blockers.

Progress: checked 1 issue; done 0 acceptance-complete; skipped 0; errors 0
validation failures. Local commit is a handoff only, not integration approval.

