# Issue #860 — 9fd4332e CI-repair checkpoint

## Frozen scope and initial evidence

Only issue #860 on `auto-860`, starting head
`2cae58c7d97d6d42a369c6202438520de5ac7a66`, supplied develop base
`ac69535ef165ded3ca82cd3428728569de3251fa`. Initial tree clean.
No fetch, merge, GitHub mutation, or unrelated repair is planned.

Inputs: this job's frozen dispatch context, prior b11a00ff result, and cited
98a11313 `check-3.log`. Current job had no driver `check-*.log` files.
Review scope: soak driver/profile, promotion-gate tests, learning-schema fence,
production rate-limit middleware, related ADRs, and CI Vulture configuration.
Conditional edit scope: identities actually reported by Vulture and its ledger;
this checkpoint. Tests/inventory notes only if a demonstrated repair needs them.

Assumption: writer CI-repair round, not promotion approval. Existing branch/base
changes are preserved; the supplied prior BLOCKED result is not proof of a
current scanner failure. Historical soak reports cannot certify this HEAD.

## Recorded results

- Prescribed `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: exit 0; 1323 reviewed
  identities / 1323 findings, no unclassified or never-allowlist findings.
  Log: job directory `vulture-initial.log`; timeout 600 seconds.
  No evidence supports a source or ledger amendment.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py
  tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q`:
  **118 passed, 6 skipped** in 2.47 seconds (`focused.log`).
  The cited 24-versus-21 schema failure does not reproduce. The current test
  independently enumerates the three Gauntlet audit columns inside the fence
  (`test_pg_learnings.py:175`); production takes the advisory lock inside the
  transaction before upgrades (`pg_learnings.py:215`). Skips are not live-PG proof.
- `uv run ruff check .`: passed (`ruff.log`).
- `uv run ruff format --check .`: 3277 files already formatted (`format.log`).
  These checks used a 1200-second timeout.
- `uv run python scripts/check-doc-links.py`: passed (`doc-links.log`,
  1200-second timeout). `git diff --check`: passed.
- The scanner arguments match `.github/workflows/vulture-ratchet.yml:82` and
  `.github/workflows/quality.yml:1078`.

## Architecture and acceptance

Read repository instructions, documentation authority map, accepted ADR-062
(including its retired execution entrypoint), ADR-082826-b601 and ADR-085.
Keep `Goal -> Graph -> Run -> NodeRun -> Attempt`; admission receipts are not
physical execution evidence. No alternate scheduler, authorization or event
path was introduced. ADR-085 requires principal-keyed limits; it does not make
process-local buckets a shared cluster allowance. The issue's stronger
replica-selection requirement remains unresolved, not waived.

Each criterion below is assessed from the frozen issue body. No live production
soak was run in this round; the focused tests cannot substitute for one.

| Acceptance criterion | Fresh evidence and disposition |
| --- | --- |
| Representative RC workload | **UNVERIFIED**. `m3a-load-profile.md:171` identifies absent users/Workspaces, Graph fan-out, successful models/tools, Design/Canvas and reconciliation traffic. |
| Two supported production replicas | **UNVERIFIED**. Executed boot-contract and ASGI tests, not deployed RC replicas. |
| Sustained saturation, queue growth, reclaim, retries, leaks and restart | **UNVERIFIED**. Sampler tests passed; no production time series or sustained workload executed. |
| No duplicate physical work; Goal reconciliation | **UNVERIFIED**. Profile phase 4 cancels its admitted probe Run without executing it; admission uniqueness cannot certify physical Attempt fencing. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **UNVERIFIED**, with contrary shared-budget evidence: executed `test_soak_promotion_gates.py:439` gives the same identity 200/200/429 independently on both production middleware instances. `rate_limit.py:32` explicitly documents N-times aggregate allowance. |
| Complete production telemetry and explicit thresholds | **UNVERIFIED**. Profile has partial thresholds, but driver-loop lag is not application-loop lag; worker, saturation and reclaim observations remain missing. |
| Kill/restart during active work, drain/fencing/recovery | **UNVERIFIED**. Boot cleanup tests do not prove physical-work recovery or deduplication. |
| Long-running exact-RC artifact/configuration soak | **UNVERIFIED**. `run_soak.py:744` rejects its host-process topology unconditionally; executed promotion tests preserve that failure even at four hours. No designated immutable RC image/configuration was supplied. |
| Findings filed/reclassified before promotion | **UNVERIFIED**. No new live-load findings or remote filing performed; GitHub mutations prohibited. |
| Human/machine soak evidence tied to exact hashes | **UNVERIFIED**. These source-validation logs are not exact-RC production soak evidence. |

## Handoff

**BLOCKED** on production acceptance, not on the prescribed Vulture check.
No actual unbanked identity or reproduced schema failure supports a code or
ledger repair. Only this report changes; no tests added, so no inventory delta.
Existing branch changes and historical evidence remain untouched.

Next: designate the immutable RC image/configuration, complete representative
production workload/telemetry, resolve the replica-selection contract, then run
the >=4-hour exact-RC soak with active-work recovery and physical-work fencing
observations. Do not rerun this CI-repair loop as a substitute for that work.

Progress: checked 1 issue, done 0, skipped 0, validation errors 0; next is the
production-soak prerequisite handoff. Local commit is not integration approval.
