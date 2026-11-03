# Issue #860 — d27f7605 validation checkpoint

## Frozen scope and initial evidence

- Process only issue #860 in `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Starting HEAD `c0a09922896efed0971cda6bbad4316fddc84581`; supplied develop
  base `b90df19a24a1ce65a2fc686cffa6960fc2a7d6ff`. Initially clean.
- Frozen inputs: supplied dispatch-context.json, prior result
  `5c90504a75724de587761157487accd6/result.json`, and reported
  `98a11313167b41a98a420abfda80c292/check-3.log`.
- Candidate edits: this report; `quality/vulture-baseline.json` only for real
  reviewed scanner debt; implicated production/test files only for reproduced
  defects. No remote enumeration, mutations, or release actions.
- Current job has no check logs. The supplied prior log fails the learnings DDL
  count (24 actual versus 21 expected), not the vulture gate.
- Prior BLOCKED result is not a develop-sync conflict. No merge is indicated.
- Read repository instructions and accepted ADRs 081426-1f7c, 081626-f383,
  082526-b36a and 073126-c4e1. Attempt remains physical execution identity;
  the renewal/reclaim ADR extends the original fencing boundary. Admission
  counts cannot establish physical-work uniqueness. No new execution authority.
- Ambiguity: no immutable promoted RC/configuration is selected by the lane.
  Do not reinterpret host preflight or unit tests as exact-RC soak evidence.

## Executed results

- `uv sync --locked --extra dev`: PASS, 256 resolved / 214 checked.
- Prescribed `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1,326 findings and
  1,326 reviewed identities, zero unclassified/never-allowlist findings.
  Log: `/tmp/860-d27f-vulture.log`. Gate reports merge-base `e46ad6708fda`;
  this is the gate's resolved base, not the dispatch's supplied develop tip.
  No ledger repair is justified by the actual scan.

- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py
  -x -q`: PASS, 37 passed / 6 PostgreSQL-dependent skips
  (`/tmp/860-d27f-schema.log`). The independent expected-DDL list already
  includes the three Gauntlet upgrade columns at lines 175–177. The supplied
  prior failure is not reproducible on this HEAD; no weakened assertion needed.
- `uv run pytest tests/test_soak_promotion_gates.py
  tests/test_prod_stack_boot_contract.py
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py
  packages/maistro-server/tests/api/test_rate_limit.py -x -q`: PASS, 100 passed
  (`/tmp/860-d27f-focused.log`). Includes real production limiter instances:
  each grants `[200, 200, 429]` independently to the same principal/IP.
  ASGI instances are not deployed RC replicas.
- `uv run ruff check .`: PASS (`/tmp/860-d27f-ruff.log`).
- `uv run ruff format --check .`: PASS, 3,195 files
  (`/tmp/860-d27f-format.log`).
- `uv run python scripts/check-merge-markers.py`: PASS.
- Read existing soak tests, profile and production rate middleware. The
  documented process-local allowance cannot certify cluster-wide non-bypass;
  the preflight artifact gate explicitly fails closed. Do not change these
  honest boundaries merely to satisfy the issue checklist.

- `uv run python scripts/check-suite-inventory.py --suite tests/`: PASS,
  5,116 expected/collected identities, no duplicates
  (`/tmp/860-d27f-inventory.log`). No test changes, so no inventory delta.
- `uv run python -` loaded the current soak module and evaluated preserved
  `m3a-round30-shakedown.json`: assertions PASS that `sustain_duration` and
  `exact_rc_artifact` fail. Observed historical duration 420.08 seconds;
  required duration 14,400 seconds. Also asserted the current preflight
  artifact check returns `ok=False`. This is a fresh negative evaluation,
  not a newly executed soak.

## Acceptance: all ten criteria checked

| Criterion | Executed evidence / remaining boundary |
| --- | --- |
| Representative RC load profile | **UNVERIFIED complete.** `m3a-load-profile.md:145–164` and `run_soak.py:1382–1395` omit concurrent Workspaces, Graph fan-out, successful model/tool, Design/Canvas and Goal worker traffic. Read directly this round. |
| Two deployed application replicas | **UNVERIFIED for RC.** Boot-contract and middleware tests pass, but do not deploy an immutable RC. |
| Sustained saturation, queues, reclaim, retries, leaks | **UNVERIFIED.** Current evaluator rejects historical duration; real-process sampler tests pass but do not prove long-window behavior. |
| No duplicate physical work; Goal reconciliation | **UNVERIFIED.** `run_soak.py:1044–1072` cancels the schedule probe Run without executing it. Admission uniqueness is not physical Attempt uniqueness. |
| Security/degraded/rate enforcement without replica-selection bypass | **UNVERIFIED as a complete criterion.** Executed `tests/test_soak_promotion_gates.py:439–493`: same credential/IP gets two independent allowances. `packages/maistro-server/src/maistro_server/api/rate_limit.py:32–37` explicitly documents process-local enforcement. No cluster-wide claim or alternative authorization path introduced. |
| Complete telemetry with thresholds | **UNVERIFIED.** Sampler tests pass; `run_soak.py:1420–1430` records driver loop lag, not application event-loop latency. Profile explicitly lists missing worker/pool/reclaim observations. |
| Active-work kill/restart, drain/fencing/recovery | **UNVERIFIED.** `run_soak.py:1436–1489` records process rejoin and HTTP counts without an active-Attempt physical-work oracle. No deployment restart run this round. |
| Long soak of exact RC/configuration | **BLOCKED / UNVERIFIED.** Fresh evaluation rejects duration and artifact; `run_soak.py:730–741` deliberately rejects host preflight. Dispatch specifies a branch HEAD, not an immutable promoted image/runtime configuration. |
| Findings reclassified to earliest invariant | **UNVERIFIED completeness.** Existing profile documents historical findings. No issue mutations permitted or performed; no claim that every load finding is resolved. |
| Machine/human evidence tied to exact artifact hashes | **UNVERIFIED for candidate.** `run_soak.py:1176–1212` hashes host preflight inputs rather than the selected production application image. Historical evidence is preserved unchanged. This report is validation-only evidence. |

## Handoff — BLOCKED

Only this report changed. No production code, tests, gates, quality ledgers,
permissions or historical evidence changed. Validation commands used 1,200-second
limits; PostgreSQL-dependent skips are not claimed as passes. No long soak,
remote mutations, background deployment or publication occurred.

The requested scanner/schema repair has no reproducible remaining defect on
this HEAD. The permitted ledger amendment is unnecessary because there are no
unbanked identities. Speculative changes would not address the actual issue.

To unblock acceptance, provide the immutable RC image/package identities and
runtime configuration intended for promotion, complete the representative
production-path workload and active-work oracle through canonical seams, then
execute the minimum four-hour soak with complete telemetry. Resolve the
process-local versus cluster-wide rate contract explicitly before claiming
replica-selection non-bypass. Repeating this same gate-only dispatch cannot
supply those prerequisites.

Progress: {checked: 1, done: 0, skipped: 0, errors: 0, next: exact-RC acceptance prerequisites}.
Local commit checkpoints validation only; issue #860 is not complete and this
is not integration approval.
