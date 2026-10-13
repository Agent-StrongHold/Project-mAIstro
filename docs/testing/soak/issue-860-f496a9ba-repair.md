# Issue #860 — f496a9ba CI repair

## Frozen scope

- Assigned issue: #860 only; branch `auto-860`.
- Starting HEAD: `49e26eb21fe875f717d4e337da88e729ef397db1`.
- Supplied base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Worktree initially clean. No salvage required.
- Inputs: supplied dispatch-context.json, prior result artifact, prior failed
  check-3.log, repository instructions, relevant execution ADRs and soak tests.
- Repair target: reproduce exact vulture command; review only identities it
  reports and amend `quality/vulture-baseline.json` under the explicit CI-repair
  exception. No speculative runtime changes or alternate execution authority.
- Additional file scope: this report; inventory notes only if tests change.
- Current job directory has no check-*.log files. Prior artifact is evidence,
  not a successful validation result for this head.

## Assumptions / unresolved acceptance

The assignment is a bounded CI repair, not authorization to substitute a local
preflight for a production RC soak. Prior result reports missing exact-RC and
multi-replica correctness evidence; each acceptance item remains unverified
until independently checked. No GitHub mutation or external finding filing.

## Progress

- `uv sync --locked --extra dev`: passed.
- Exact assigned vulture command passed: 1323 reviewed identities / 1323
  findings; zero unclassified / forbidden identities, using supplied base
  `3c761d14db94`. No retained unbanked identity exists to amend. A cosmetic
  ledger change would not address actual evidence and is not warranted.
- Inspected prior check-3.log: failure was the learning-schema fence test
  expecting 21 DDL statements and seeing 24, not a vulture failure.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py
  -x -q`: **38 passed, 6 skipped**. The old schema-fence failure does not
  reproduce; its independent expected DDL list already includes all 24
  statements. Skips are not evidence of live database behavior.
- `uv run pytest tests/test_soak_promotion_gates.py
  tests/test_prod_stack_boot_contract.py tests/test_gitleaksignore_contract.py
  -x -q`: **81 passed**. Includes actual production rate-limit middleware
  demonstrating independent per-replica allowances, Linux child-process
  sampling, and fail-closed exact-artifact CLI tests. Mocked admission and
  HTTP fixtures are oracle validation, not a production soak.

## Architecture reconciliation

Read AGENTS.md, docs/README.md and accepted ADR-081226-a66b (one execution
lifecycle) and ADR-081626-f383 (canonical durable lease/fencing ownership).
The lease contract explicitly does not authorize implicit expiry takeover.
Preserve Goal -> Graph -> Run -> NodeRun -> Attempt; this issue cannot justify
an alternate scheduler, reclaim authority or event/Goal store.

The load profile itself distinguishes the host-process preflight from the
exact production artifact and lists workload and physical-work proof gaps.
Existing passing tests cannot waive those requirements. No source/test/ledger
change is supported by the reproduced CI results; no inventory delta needed.

## Final validation

- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 3277 files.
- `uv run python scripts/check-doc-links.py`: passed, 2681 markdown files,
  zero broken relative links.
- `git diff --check`: passed.
- Executed current `preflight_artifact_check()`: `ok=False`, topology
  `host-uvicorn-preflight`. Inspected its call in the production driver at
  `scripts/soak/run_soak.py:1552`; no CLI duration can make this an RC run.
- Executed current `failed_promotion_checks()` on the frozen round-100 and
  round-44 evidence JSON: both fail `sustain_duration` and `exact_rc_artifact`.
  Durations are 420.04 and 420.05 seconds, respectively, not 14400 seconds.
  Round-100 records clean `ed0fe24a07a008f2ca9e2d092d8140370ab10aad`;
  round-44 records dirty `b4cfb94db2e4a1b94773674f4ce850ab1db80ea9`.
  Both record SIGTERM/rejoin but no physical Attempt recovery oracle. Reading
  and re-evaluating historical packs is not a new live soak.

## Acceptance evidence / limits

| #860 criterion | Assessment from executed checks and reachable code |
| --- | --- |
| Representative profile | **UNVERIFIED**. `m3a-load-profile.md` explicitly omits multi-user/Workspace load, Graph fan-out, successful model/tool calls, Canvas and Goal workers; driver mix at `run_soak.py:1381` does not supply them. |
| Two production application replicas | **UNVERIFIED this round**. Historical packs describe two host replicas; no exact-RC production topology was exercised here. |
| Sustained load exposing saturation/reclaim/leaks | **UNVERIFIED**. Both executed historical gate evaluations reject duration; 420 seconds is not the required four-hour observation window. |
| No duplicate physical work / Goal reconciliation | **UNVERIFIED**. `run_soak.py:1043` cancels its admitted schedule Run without executing it; deduplicated admission is not physical Attempt fencing or Goal reconciliation. |
| Effective concurrency rate/security/degraded behavior without replica-selection bypass | **NOT MET for aggregate rate allowance**. Executed `test_soak_promotion_gates.py:439` uses actual production middleware: the same identity receives `[200,200,429]` independently on each replica. Local 429 tests cannot establish cluster-wide non-bypass. Security/degraded behavior under exact-RC load **UNVERIFIED**. |
| Complete metrics with pass/fail thresholds | **UNVERIFIED**. Linux child-process sampler regression passes, but `run_soak.py:1410` samples driver-loop lag, not application-loop lag. Complete worker/pool/leak metrics at RC duration not observed. |
| Kill/restart with physical-work drain/fencing/recovery | **UNVERIFIED**. Historical process exit/rejoin is not correlated physical Attempt loss/duplication evidence; no live restart was run here. |
| Long-running exact RC artifact/configuration | **BLOCKED / UNVERIFIED**. Executed artifact check returns false; three missing/null/preflight CLI regressions pass by rejecting synthetic four-hour evidence. Promoted image/config identity and production-topology soak are still prerequisites. |
| Findings filed/reclassified | Local F1-F12 evidence/invariant mapping reviewed in `m3a-soak-evidence.md`; external filing **UNVERIFIED**. No GitHub mutation performed. |
| Machine/human evidence tied to artifact hashes | Historical JSON/human evidence exists and was inspected. Evaluated JSON carries commit/config/Postgres identity, not both promoted application image digests; exact-RC publication **UNVERIFIED**. |

## Handoff

**BLOCKED**, not promotion-ready. Checked: 1 issue; done: 1 bounded CI
reproduction/acceptance review; skipped: 0 issues; errors: 0 reproduced CI
failures. The only changed file this round is this report, committed locally.
No ledger/grant, production source, test, inventory or gate changes.

The old DDL failure and vulture ledger are not current blockers. Do not
redispatch this same CI-repair brief without a new failing check or new RC
inputs. Next: release owners must designate exact RC image/config hashes;
resolve the replica-budget acceptance mismatch and missing workload/metrics/
physical-work oracles within canonical authority, then execute and publish
at least four hours on the exact supported production topology. A longer
host-process preflight cannot close the issue.
