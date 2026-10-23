# Issue #860 — bounded CI repair (92fa5644)

## Frozen scope

- Worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Starting HEAD `c922d4ac2d3b3fd5807a0304da1d18a3ca79d809`; supplied develop base
  `ac7370141e8e61bd6f352bca35ed0b505104aadb`. Initial working tree clean.
- Only issue #860; no linked PR processing or GitHub mutations.
- Repair candidates: `packages/maistro-core/tests/persistence/test_pg_learnings.py`,
  `quality/vulture-baseline.json` (only evidenced retained identities), this report,
  and `docs/testing/inventory-notes/860-92fa5644-ci-repair.md` if tests change.
- Read-only investigation: corresponding learning persistence/schema code, relevant
  ADRs, soak runner and promotion tests, gate scripts/workflows and supplied job artifacts.

## Initial evidence / assumptions

The supplied previous check-3.log reports 24 schema statements versus 21 expected.
This is historical evidence, not a confirmed current failure. The supplied previous
result records unresolved production RC soak acceptance. This job directory has no
check-*.log files at start. Reproduce checks before deciding whether repair is needed.
No RC artifact/configuration has been supplied; local tests cannot substitute for it.

## Results

- Fresh persistence tests: `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` -> 37 passed, 6 skipped (1.43s).
  Historical failure does not reproduce: the independent expected DDL list already
  includes all three validation audit columns at lines 176–180. PostgreSQL skips
  are not live concurrency evidence.
- Exact mandated vulture command -> PASS: 1,322 findings / reviewed identities,
  zero unclassified or never-allowlist findings; selected base `321cbdb8fe9b`.
  No dead-code or ledger change is evidenced or justified.
- `uv run ruff check .` -> PASS.
- `uv run ruff format --check .` -> PASS, 3,301 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`
  -> 73 passed (2.11s). All validation commands used 1,200-second timeouts.
- `.github/workflows/quality.yml:1079` confirms the exact vulture arguments.
  No tests changed; no inventory delta required.

## Reachable behavior and architectural reconciliation

Read repository instructions, documentation authority hierarchy, the full
`m3a-load-profile.md`, and accepted ADRs `081426-1f7c` and `081626-f383`.
The canonical Goal -> Graph -> Run -> NodeRun -> Attempt authority is unchanged.
The fencing ADR intentionally does not define live-Attempt expiry takeover;
#860 cannot authorize a competing reclaim authority to manufacture acceptance.

Fresh test execution exercises production middleware/router through ASGI, not
production deployment replicas:

- `tests/test_soak_promotion_gates.py:439` observes `[200, 200, 429]` on each
  replica for the same identity. Production `api/rate_limit.py:32` explicitly
  documents per-process enforcement. Local enforcement does not prove resistance
  to increasing the aggregate allowance by replica selection.
- `tests/test_soak_promotion_gates.py:564` admits a real task through the production
  router using the canonical admission spine; receipt reads return local 200 and
  peer 404. This is not a durable cross-replica receipt proof.
- `scripts/soak/run_soak.py:744` returns `ok=False` for exact-RC equivalence:
  host-process preflight is not the promoted Compose image/configuration.
  Longer duration cannot repair this artifact mismatch.

## Acceptance matrix

| Criterion | Fresh evidence / status |
| --- | --- |
| Representative RC load profile | UNVERIFIED: reviewed profile admits missing concurrent users/Workspaces, Graph fan-out, successful model/tool calls, Design/Canvas and background/Goal workloads; no selected RC supplied to justify exclusions. |
| At least two deployed application replicas | UNVERIFIED: two ASGI instances are not deployed production replicas. |
| Sustained saturation, queue growth, expiry/reclaim, retries and leaks | UNVERIFIED: short deterministic tests only; PostgreSQL cases skipped. |
| No duplicate physical work, admission and Goal reconciliation | UNVERIFIED: admission/receipt safeguards are tested, not physical Attempts or sustained Goal reconciliation. |
| Replica-resistant security/degraded behavior | UNVERIFIED overall: fresh middleware tests demonstrate independent allowances; task-backpressure tests pass locally. |
| Required production telemetry and thresholds | UNVERIFIED: profile contains thresholds but no fresh production time series; driver-loop lag is not application-loop lag. |
| Active-work kill/restart, drain, fencing and recovery | UNVERIFIED: no physical worker kill/restart executed. |
| Long-running exact-RC soak | UNVERIFIED: immutable RC/configuration not supplied; existing runner explicitly fails equivalence. |
| Findings classified to earliest broken milestone | UNVERIFIED for completeness: no completed production run; findings recorded locally without GitHub mutation. |
| Machine/human evidence tied to exact artifact/config hashes | UNVERIFIED for promotion: this record identifies the tested commit, not an executed RC image/configuration. |

## Handoff

**BLOCKED** on production acceptance, not on the supplied historical CI failure.
Only this report changed. No source/test/ledger/grant changes were justified by
actual evidence. All existing work preserved; no merge conflict present.

Next: select the immutable RC and configuration, complete the representative
production workload and exact-artifact runner, reconcile replica-budget/receipt
and reclaim limitations, then execute the required long production soak. Repeating
this same passing ledger repair cannot supply that evidence.

Progress: checked 1 issue; done 0 acceptance sets; skipped 0 issues; errors 0
validation commands. Local documentation commit is a handoff, not integration
approval or an issue-closure action.
