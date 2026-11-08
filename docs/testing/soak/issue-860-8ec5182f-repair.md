# Issue #860 — bounded CI repair (8ec5182f)

## Frozen scope

- Issue: #860 only; branch `auto-860` in `/home/dev/Git/wt/auto-860`.
- Starting HEAD: `640bbe6cdb5972f6cae4d47f16603803cdc9221b` (verified).
- Supplied base: `3c761d14db944a727fa0744444bc67cfe36d49f7` (resolved by diff).
- Initial working tree: clean; no salvage needed.
- Input snapshot: supplied dispatch-context.json, prior result bec55d36,
  prior check-3.log 98a11313. No GitHub queries or mutations.
- Repair candidates: `quality/vulture-baseline.json` only if the exact scan
  demonstrates retained unbanked identities; source fixes only for identities
  actually reported. No speculative dead-code changes or gate weakening.
- Acceptance review: existing `scripts/soak/run_soak.py`,
  `scripts/soak/nginx-soak.conf`, `tests/test_soak_promotion_gates.py`,
  `docs/testing/soak/m3a-load-profile.md`,
  `docs/testing/soak/m3a-soak-evidence.md`, and applicable ADRs.
- Validation: exact requested vulture scan, repository ruff checks, existing
  focused soak tests and relevant CI checks. No new tests planned.

## Initial observations

No `check-*.log` files were present in this job directory. The supplied prior
failure and result exist and will be inspected, not treated as current proof.
The branch contains substantial historical evidence and repair notes; those
are preserved and are not evidence that this HEAD passed a production RC soak.

## Results

- `uv sync --locked --extra dev`: passed.
- Exact requested vulture scan: passed, 1323 findings / 1323 reviewed
  identities, zero unclassified or forbidden identities. No ledger amendment
  is warranted; there is no reproduced scanner defect to repair.
- Supplied old failure was `test_pg_learnings.py` expecting 21 DDL statements
  but observing 24. Fresh targeted core backlog/persistence and server
  backpressure tests: **63 passed, 6 skipped**. That failure does not reproduce.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed (3277 files).
- Exploratory ADR numeric glob lookup returned absent 119/120/121 names;
  not found, skipped. Applicable named ADR paths were resolved instead.

- Existing soak/production-boot/gitleaks contract tests: **81 passed**.
  Includes real `RateLimitMiddleware` instances (both identity classes), the
  real Linux child-process resource sampler, and fail-closed CLI gate tests.
  Mocked admission/HTTP tests are oracle tests, not production-load proof.
- `check-suite-inventory.py --suite packages/maistro-core/tests`: passed,
  16263 collected identities; server equivalent: passed, 566 identities.
- `check-doc-links.py`: passed, 2680 markdown files, zero broken links.
- `git diff --check`: passed.
- Executed current `failed_promotion_checks()` against round-100 and round-44
  JSON: both fail `sustain_duration` and `exact_rc_artifact`. Observed windows
  are 420.04 and 420.05 seconds respectively, not the required 14400 seconds.
  Round-100 records clean `ed0fe24a07a008f2ca9e2d092d8140370ab10aad`;
  round-44 records dirty `b4cfb94db2e4a1b94773674f4ce850ab1db80ea9`.
  Reading/re-evaluating historical evidence is not a new soak.

No production source, test, or ledger change is justified by these results.
No tests were added; no inventory delta is required.

## Architecture reconciliation

Read repository instructions, documentation authority map, accepted
ADR-081226-a66b (one Run/NodeRun/Attempt lifecycle) and ADR-081626-f383
(canonical durable lease/fencing ownership). ADR-081 deployment topology is
**Proposed**, not an accepted waiver of the issue's supported-topology claims.
The accepted lease ADR explicitly excludes implicit lease-expiry takeover;
this issue cannot justify inventing a new recovery authority or scheduler.
No authority paths were changed. The admission probe's cancellation of its
queued Run through `PgRunStore` is not physical-work fencing proof.

## Acceptance assessment at this HEAD

| Criterion | Executed evidence and remaining gap |
| --- | --- |
| Representative profile | Reviewed profile and driver. A preflight mix exists, but the profile explicitly omits multi-user/Workspace traffic, Graph fan-out, successful model/tool calls and Canvas/Goal worker workloads. Representative exact-RC profile **UNVERIFIED**. |
| At least two replicas | Round-100 JSON describes two host application replicas, and its gate evaluation was rerun. No new production topology was exercised this round; exact-RC replica exercise **UNVERIFIED**. |
| Sustained saturation/reclaim/leaks | Both evaluated packs fail duration. Long-window saturation, lease reclaim and leak behavior **UNVERIFIED**; no repeat smoke run can close this. |
| Exactly-once/fenced physical work | Current schedule probe cancels its admitted Run without executing it (`run_soak.py:1043-1075`). Admission is narrower than physical work. Goal reconciliation and physical Attempt deduplication **UNVERIFIED**. |
| Rate/security/degraded concurrency | Executed production-middleware tests demonstrate the same identity gets `[200,200,429]` independently on each replica (`test_soak_promotion_gates.py:439-491`). Cluster-wide non-bypass criterion is **not met** by process-local limits; exact-RC security/degraded load behavior **UNVERIFIED**. |
| Required metrics and thresholds | Reviewed sampler/gates and executed Linux child-resource test. Driver loop lag is not application loop lag (`run_soak.py:1410-1423`); physical worker counts and complete pass/fail thresholds at RC duration **UNVERIFIED**. |
| Kill/restart recovery | Historical round-100 records SIGTERM exit/rejoin, but no correlated physical Attempt recovery proof. No live restart performed this round; drain/fencing/no-loss acceptance **UNVERIFIED**. |
| Long-running exact RC | Executed `preflight_artifact_check()` returns `ok=False`; fail-closed CLI regressions pass. This host runner cannot satisfy the exact-Compose requirement, regardless of duration (`run_soak.py:730-741`). **UNVERIFIED / BLOCKED**. |
| Findings filed/reclassified | F1-F12 are documented locally with invariant mapping in the evidence pack. No external issue filing performed or independently proven; external filing **UNVERIFIED** (GitHub mutations prohibited). |
| Machine/human hash-tied evidence | Inspected historical JSON identities and human profile/evidence; round-100 carries commit/config/Postgres identity, not both promoted application image digests. Exact-RC hash-tied soak publication **UNVERIFIED**. |

## Handoff

**BLOCKED**, not promotion-ready. Checked: 1 assigned issue; done: 1 bounded
CI reproduction/acceptance review; skipped: 0 issues; errors: 0 validation
failures reproduced. Only this report changes in this round. Commit locally;
no GitHub mutation, gate weakening, RC designation, or soak certification.

Next: release owners must designate the exact RC images/configuration and
provide a representative production-topology run, including the missing
physical-work recovery and metrics oracles. Resolve the rate-limit
replica-selection acceptance mismatch without silently weakening #860, then
run and publish the >=4-hour exact-artifact soak. The old DDL failure and
vulture ledger are not current blockers; do not repeatedly repair passing gates.
