# Issue #860 repair — ae8c852a

## Frozen scope

- Only issue #860, branch `auto-860`, starting head
  `aa285e20fbde892e5bca5703dedd507bda6f7166`, base
  `ac7370141e8e61bd6f352bca35ed0b505104aadb` (both verified).
- Worktree initially clean; no incoming edits to salvage.
- Repair candidates: `packages/maistro-core/tests/persistence/test_pg_learnings.py`
  and its production module `packages/maistro-core/src/maistro/persistence/pg_learnings.py`;
  `quality/vulture-baseline.json` only if the explicitly requested exact scan
  demonstrates retained unbanked identities. Inventory note if test coverage changes.
- Acceptance inspection: `scripts/soak/run_soak.py`,
  `tests/test_soak_promotion_gates.py`, `docs/testing/soak/m3a-load-profile.md`,
  `docs/testing/soak/m3a-soak-evidence.md`, and relevant ADRs/CI instructions.
- No other issues/PRs are being processed; supplied dispatch snapshot is authoritative
  for the issue's ten acceptance criteria. No GitHub mutation or ref refresh.

## Initial evidence and assumptions

- Supplied prior `98a113.../check-3.log` reports expected 21 versus actual 24 DDL
  statements in the schema-fence test. Reproduction pending; no speculative fix.
- Supplied `072123.../result.json` reports BLOCKED on production-soak acceptance.
  Those claims will not be treated as fresh validation.
- Current job directory had no `check-*.log` files at initial inspection.
- Ambiguity: this dispatch requests both CI repair and resolving prior acceptance
  blockers. Proceed with evidence-based local repair, and explicitly leave any
  unexecuted production acceptance UNVERIFIED rather than invent RC identity or
  change execution/security authority.

## Validation and disposition

- Exact requested vulture gate passed: 1322 reviewed identities / 1322 findings,
  zero unclassified. No ledger amendment is warranted by actual evidence.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`
  passed: 37 passed, 6 PostgreSQL-dependent tests skipped. The reported 21/24
  schema mismatch is already repaired at the assigned head: the test explicitly
  covers all three validation audit columns at lines 174–176. No source repair
  is warranted for this stale failure.
- The current profile explicitly describes missing representative workloads and
  a host-process preflight, not the promoted Compose artifact. No RC designation
  is supplied. Acceptance validation continues with existing production-seam
  tests; these cannot substitute for a long production soak.
- `uv run pytest tests/test_soak_promotion_gates.py
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  73 passed. The existing replica-selection test executes production middleware
  with the same identity on two instances and observes independent `[200, 200,
  429]` allowances. The receipt test executes the production task router and
  observes a successful local read followed by a peer 404. These are ASGI seam
  probes, not a deployed soak. Backpressure mapping remains covered.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 3301 files already formatted.
- `uv run python scripts/check-suite-inventory.py`: passed, all 17 suites,
  31323 unique identities, no duplicate evidence. No tests changed or added;
  no inventory delta or inventory-note amendment is warranted.
- `git diff --check`: passed. Validation commands used 1200-second timeouts.
  Raw command output is in `/tmp/860-ae8c852a-{vulture,pg-learnings,soak-gates,inventory}.log`
  for this environment; the outcomes above are the durable record.

## Architecture and production reachability

Read repository instructions, documentation authority map, accepted ADR-085,
ADR-081626-f383, ADR-082826-b601 and ADR-073126-c4e1; also read ADR-081, whose
front matter is **Proposed**, not accepted authority. No execution, event,
scheduler, Goal-store or authorization path changed.

The accepted consumer ADR retains the canonical Run transition as its claim
and executes through NodeRun/Attempt. The fencing ADR makes the canonical Run
store the lease authority; its original boundary does not itself define expiry
takeover. Therefore one successful admission cannot be promoted into proof of
physical-work uniqueness or reclaim. No alternative execution mechanism was
introduced to make a probe pass.

`packages/maistro-server/src/maistro_server/api/rate_limit.py:93` constructs an
`InMemoryRateLimiter` per middleware instance. Its module contract explicitly
states N-times aggregate allowance with N replicas. ADR-085 requires principal
identity; it does not justify claiming a shared allowance from this code. The
issue's replica-selection requirement remains unproven, not waived by a comment.
`api/tasks.py:144` reads the local queue, as exercised by the receipt probe.
`scripts/soak/run_soak.py:744` always rejects exact-artifact equivalence for its
host-process runner; existing CLI tests verify failure for missing/null/preflight
artifact evidence even with a synthetic four-hour duration.

## Acceptance audit (issue body in frozen dispatch)

| Criterion | Fresh evidence / disposition |
| --- | --- |
| Representative RC load profile | UNVERIFIED: existing profile documents one API key and missing users/Workspaces, fan-out, successful model/tool calls, Design/Canvas and Goal/background workloads. No selected-RC coverage justification supplied. |
| Two application replicas in supported production profile | UNVERIFIED: two-instance ASGI tests executed, no production topology executed in this round. |
| Sustained saturation, growth, reclaim, retry/backoff, leaks and restart | UNVERIFIED: short deterministic tests provide no sustained production series. |
| No duplicate physical work across schedule/task/Run/Attempt/Goal operations | UNVERIFIED: no physical-work production accounting or Goal reconciliation soak executed. |
| Replica-resistant rate/security/degraded behavior | NOT PROVEN: executed tests reproduce independent per-replica allowances for authenticated and unauthenticated identities; deployed security/degraded acceptance remains UNVERIFIED. |
| PostgreSQL/application-loop/process/RSS/FD/queue/error telemetry and thresholds | UNVERIFIED: profile thresholds exist, but no fresh production telemetry; driver loop latency is not application loop latency. |
| Active-work replica kill/restart with drain/fencing/recovery | UNVERIFIED: no active-work production restart executed. |
| Long-running exact-RC artifact/configuration soak | UNVERIFIED: immutable RC/configuration not designated; current runner explicitly fails artifact equivalence. Profile minimum is four hours. |
| Findings filed/reclassified to earliest broken invariant | UNVERIFIED for completion: historical findings exist, but no completed representative production run audited here; no GitHub mutations performed. |
| Human/machine evidence bound to exact image/package/commit/config hashes | UNVERIFIED: this source-head validation handoff is not an exact-RC soak evidence pack. |

## Handoff

**BLOCKED**, not MERGE-READY. This round found no currently failing CI gate to
repair. Only this checkpoint changed; changing a passing schema test or banking
already-reviewed identities would be cosmetic, not evidence-based repair.

The previous production-acceptance block remains unresolved. Next action needs
an explicitly selected immutable RC and production configuration, representative
workloads and application telemetry through the existing canonical runtime, and
an at-least-four-hour production soak with active-work restart and physical-work
accounting. Resolve the replica-allowance contract without inventing another
authorization path. Any runtime/code change requires a new soak. Repeating this
same stale schema/vulture repair dispatch cannot supply that evidence.

Progress: checked 1 issue; done 0 acceptance-complete; skipped 0; errors 0 in
executed validation commands. Local commit is a blocked handoff only, not
integration or release approval.
