# Issue #860 repair — job 6abab665

## Frozen scope

- Issue #860 only; assigned worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Starting HEAD verified: `dc98746f9418cb757b9a6be5b953e87fa8238cc8`; initial worktree clean.
- Inputs: supplied dispatch-context.json, prior result 3ae30d57, and cited prior check-3.log. No GitHub mutations or list refreshes.
- Candidate edits: this report and `quality/vulture-baseline.json` only if the exact scanner produces reviewed retained identities. Production/test changes require concrete evidence and a recorded scope clarification first.
- Current job directory contained no check-*.log at initial snapshot. Prior BLOCKED result is not accepted as fresh validation.
- Ambiguity: no exact RC artifact/configuration or deployment authorization is identified in the lane brief. Do not invent an RC or claim host preflight as promotion evidence.

## Progress

Fresh exact vulture gate passed: 1323 findings / 1323 reviewed identities; zero unclassified or never-allowlist. No ledger edit is justified. The cited prior check-3.log is a schema-test failure (24 DDL statements versus 21 expected), not a vulture failure. Fresh `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` passed: 37 passed, 6 skipped. Fresh `uv run pytest tests/test_soak_promotion_gates.py -x -q` passed: 65 passed. The historical failure does not reproduce; do not make cosmetic repairs.

## Validation results

All commands used a 1200-second timeout. Commands executed in this worktree:

| Command | Outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1323 reviewed identities / findings; trusted base selected by gate `4aa68edc0b6b` |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 37 passed, 6 skipped; live PostgreSQL coverage not established |
| `uv run pytest tests/test_soak_promotion_gates.py -x -q` | 65 passed |
| `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | 1 passed |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3270 files |
| `uv run python scripts/check-ratchet-provenance.py` | PASS, 53 consumers; existing invalid-escape SyntaxWarnings |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS |

The vulture/provenance/shipped-surface commands match `.github/workflows/vulture-ratchet.yml:77-86`. No flags weakened gates and no ledger/grant changed. The schema regression at `packages/maistro-core/tests/persistence/test_pg_learnings.py:162-193` already includes the three Gauntlet columns missing from the historical log.

## Architecture reconciliation

Read AGENTS.md, docs/README.md, the soak profile, production middleware wiring and driver probes, adjacent tests, and Accepted ADRs 081226-a66b, 081626-f383, 082426-82c7, 085 and 082526-b36a. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`; canonical stores own occurrence admission and execution fencing.

Correction to the prior report's architecture explanation: ADR-082526-b36a supplies the later TTL/renewal/reclaim contract left open in ADR-081626-f383. Reclaim must be tested through that canonical mechanism, not characterized as wholly undefined or replaced with a second authority. The outstanding #860 gap is observed production soak evidence, not absence of a reclaim ADR.

## Acceptance review

No new deployed soak was executed. Unit/ASGI tests and historical artifacts do not prove an unchanged exact RC. All ten issue criteria remain unverified at promotion grade:

| Criterion | Executed evidence / outstanding gap |
| --- | --- |
| Representative RC profile | **UNVERIFIED**. Profile exists but explicitly lists missing concurrent Workspaces, Graph fan-out, successful tool/model and Canvas/background workloads. Driver uses one credential and a health/task/receipt/metrics mix (`scripts/soak/run_soak.py:1373-1397`). |
| At least two application replicas | **UNVERIFIED for RC**. Executed middleware tests instantiate two ASGI applications, not two deployed RC replicas. |
| Sustained saturation/reclaim/retry/leak observations | **UNVERIFIED**. No sustained production traffic run; passing sampler regressions do not supply this observation window. |
| No duplicate physical work; Goal reconciliation | **UNVERIFIED**. `scripts/soak/run_soak.py:1044-1069` cancels the schedule admission probe without executing its Run. Admission uniqueness is not physical-effect uniqueness or sustained Goal reconciliation. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **UNVERIFIED overall; shared-budget interpretation falsified**. Fresh passing `tests/test_soak_promotion_gates.py:439` observes `[200,200,429]` independently on both production middleware instances for the same identity. Production installs it at `packages/maistro-server/src/maistro_server/main.py:648`; `api/rate_limit.py:32-37` explicitly documents N-times aggregate allowance. Local 429 enforcement is not proof of replica-selection non-bypass. |
| Complete telemetry and explicit thresholds | **UNVERIFIED**. `scripts/soak/run_soak.py:1409-1421` measures driver-loop lag, not application event-loop latency. No complete RC pool/query/lock/worker/queue/error series collected. |
| Active-work kill/restart, graceful drain/fencing/recovery | **UNVERIFIED**. Driver process exit/rejoin and HTTP counters (`scripts/soak/run_soak.py:1428-1487`) lack a physical-effect/stale-worker reconciliation oracle. |
| Long unchanged exact-RC soak | **BLOCKED / UNVERIFIED**. No immutable RC/configuration supplied by this lane. `scripts/soak/run_soak.py:730-741` deliberately rejects host preflight as exact RC; passing fail-closed regressions cannot substitute for a four-hour production soak. |
| Findings filed/reclassified before promotion | Local findings preserved here; external disposition **UNVERIFIED**, GitHub mutations prohibited. |
| Hash-bound machine/human RC evidence | **UNVERIFIED**. This is local validation evidence, not a production artifact/configuration-bound soak pack. Old artifacts remain untouched and are not relabeled as current. |

## Disposition and handoff

**BLOCKED for issue acceptance.** Only this report changes. No test addition/change, so no inventory delta note is needed. No schema or ledger repair is supported by fresh results. Do not redispatch the historical schema failure as a current defect.

Next: release owner must identify the immutable RC and supported configuration; resolve the local-rate-limit versus replica-selection acceptance contract; supply representative production workloads, physical-work/recovery oracles and application telemetry; execute the long unchanged-artifact soak and retain hash-bound evidence. This requires more than rerunning passing deterministic gates.

Progress: checked 1 issue; done 0 acceptance-complete; skipped 0; errors 0 validation failures. Local report commit is a handoff only, not integration approval.

