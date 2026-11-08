# Issue #860 — bounded repair 340157aa

## Frozen scope

- Issue #860 only; branch `auto-860`, starting HEAD
  `353c4fd209d14373cb57edc8bbafaae7c4c7a65e`, supplied base
  `ac69535ef165ded3ca82cd3428728569de3251fa`.
- Review existing `scripts/soak/`, adjacent soak tests, relevant runtime/ADR
  contracts, and the explicit vulture per-identity gate. Only amend
  `quality/vulture-baseline.json` if the requested scan provides evidence.
- This report is the planned documentation change. No new tests planned unless
  an actual repair requires them. No remote mutations or promotion actions.
- Starting tree clean. Assigned job directory contains no `check-*.log` files.
  Prior result is evidence to recheck, not proof.
- Ambiguity: writer and verifier instructions coexist; explicit repair assignment
  and commit requirement select writer mode.

## Results

- Requested Vulture scan executed (1200-second timeout): exit 0, 1323
  reviewed identities / 1323 findings, zero unclassified or never-allowlist.
  No ledger amendment or dead-code deletion is justified by this scan.
- Historical `98a11313/check-3.log` reports 24 versus 21 learning-schema DDL
  statements, not a Vulture failure. It does not reproduce (results below).
- Reviewed the current profile, driver artifact gate and adjacent middleware
  regression. The driver deliberately cannot certify the exact RC artifact;
  representative production workloads remain missing. No production acceptance
  claim is made.
- Optional README paths under `scripts/soak/` and `docs/testing/soak/` were not
  found; skipped. The actual profile is `m3a-load-profile.md`.
- `uv run ruff check .`: exit 0.
- `uv run ruff format --check .`: exit 0; 3277 files already formatted.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py
  tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q`:
  exit 0; **118 passed, 6 skipped**, 2.71 seconds. Skips are not live-DB proof.
- `uv run python scripts/check-doc-links.py`: exit 0, no broken relative links.
  Validation battery timeout: 1200 seconds.
- Current schema test independently enumerates the three additional audit
  columns at `test_pg_learnings.py:175`; production takes its transaction-scoped
  advisory lock before DDL at `pg_learnings.py:215`. No repair is needed for the
  historical statement-count failure.

## Architecture reconciliation

Read `AGENTS.md`, the documentation authority map, ADR-062 (including the retired
execution entrypoint), ADR-082826-b601, and ADR-085. Preserve
`Goal -> Graph -> Run -> NodeRun -> Attempt`: admission uniqueness is not proof
of physical-work uniqueness. No alternative execution or authorization path was
introduced. ADR-085 specifies principal-keyed limits, not a proof of shared
cluster allowances; the issue's replica-selection criterion is not waived by
current process-local behavior.

## Acceptance review

No live production soak was run. Tests of the preflight harness do not establish
production acceptance, regardless of their passing result.

| Issue criterion | Current evidence / disposition |
| --- | --- |
| Representative RC profile | **UNVERIFIED**. Profile explicitly lacks concurrent users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas and reconciliation workloads (`m3a-load-profile.md:171`). |
| Two production replicas | **UNVERIFIED**. Executed ASGI/boot-contract tests are not deployed RC replicas. |
| Sustained saturation, growth, reclaim, retries and leaks | **UNVERIFIED**. No sustained production time series; profile records those gaps. |
| Physical-work deduplication and Goal reconciliation | **UNVERIFIED**. Schedule probe cancels its queued Run without physical execution; admission receipts cannot prove Attempt fencing. |
| Security/degraded behavior and replica-selection non-bypass | **UNVERIFIED**, with contrary evidence for a shared allowance. Executed `tests/test_soak_promotion_gates.py:439` confirms the same identity receives 200/200/429 independently on both production middleware instances. `rate_limit.py:33` documents N-times aggregate allowance. |
| Complete telemetry and explicit thresholds | **UNVERIFIED**. Partial profile thresholds exist; driver-loop lag is not application-loop lag, and required production saturation/reclaim observations are absent. |
| Active-work kill/restart, drain/fencing/recovery | **UNVERIFIED**. Harness tests do not prove production physical-work recovery. |
| Long-running exact RC artifact/configuration | **UNVERIFIED**. `scripts/soak/run_soak.py:744` unconditionally rejects its host-process topology. Promotion regression tests pass, preserving this rejection. No designated immutable RC image/configuration was supplied. |
| Findings filed/reclassified | **UNVERIFIED**. No new live-load findings or remote filing; GitHub mutations prohibited. |
| Human/machine evidence tied to exact hashes | **UNVERIFIED**. Source validation is not a production soak evidence bundle. |

## Handoff

**BLOCKED** on production acceptance, not the Vulture gate or historical schema
failure. Only this report changes. No code, ledger, tests or inventory changed;
there is no inventory delta. Existing branch content is preserved.

Next owner action: designate immutable RC image/configuration, complete the
production workload and telemetry, resolve replica-selection semantics, and run
the >=4-hour production soak with active-work recovery and physical fencing
observations. Another identical CI-repair dispatch cannot supply that evidence.

Progress: checked 1 issue, done 0, skipped 0, validation errors 0; next is the
production prerequisite handoff. Local report commit is not integration approval.
