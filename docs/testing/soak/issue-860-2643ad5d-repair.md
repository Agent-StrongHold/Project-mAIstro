# Issue #860 repair — 2643ad5d

## Frozen scope

- Only issue #860; assigned worktree `/home/dev/Git/wt/auto-860`.
- Starting HEAD `81d4f698db4fc71541b65e04fc9c63efcb0f27fc`; assigned base `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Clean starting tree; no incoming changes to salvage.
- Process the supplied vulture CI failure, existing soak runner/tests, relevant ADRs,
  and this report. Amend `quality/vulture-baseline.json` only if fresh findings
  warrant the explicit lane exception. No other issues or PRs are being processed.
- Current job has no `check-*.log` files. Inspect the explicitly supplied prior
  failure and run fresh validation rather than accepting prior success claims.
- Ambiguity: this is a writer repair, not verifier-only mode, per lane assignment.
  Exact promoted RC identity/configuration is not supplied; local tests cannot
  substitute for an unchanged deployed RC soak.

## Progress

Fresh exact vulture scan passes: 1323 findings / 1323 reviewed identities,
zero unclassified or never-allowlist findings. No ledger edit is warranted.
The supplied historical check-3 failure is a schema-test DDL count mismatch,
not a vulture finding. Fresh combined targeted tests pass: 103 passed, 6 skipped
(learning persistence, soak promotion gates, task concurrency backpressure).
No test or production edit is justified by that stale failure. Acceptance
review and remaining validation follow below.

## Architecture and reconciliation

Read repository instructions, documentation authority map, the supplied issue
body and captured PR bodies/latest issue comments, load profile, adjacent tests,
and accepted ADRs 081226-a66b, 081626-f383, 082426-82c7 and 082526-b36a.
The later lease ADR defines renewal/reclaim beyond the earlier fencing ADR's
initial boundary. Neither occurrence admission nor process restart proves
physical-effect uniqueness. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`;
no competing execution, recovery, authorization or event authority was added.

The historical schema failure expected 21 statements. The current independent
expected list includes the three Gauntlet audit columns at
`packages/maistro-core/tests/persistence/test_pg_learnings.py:175-179`;
production executes the upgrade loop inside its advisory-lock transaction at
`packages/maistro-core/src/maistro/persistence/pg_learnings.py:215-226`.
Fresh execution confirms the test passes, not that live concurrent PostgreSQL
boot has been re-proven (six database-dependent tests skipped).

## Executed validation

Commands ran in the assigned worktree with 600/1200-second validation timeouts.

| Command | Result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS; 1323/1323, zero unclassified/never-allowlist; matches workflow arguments |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | 103 passed, 6 skipped in 2.47 s |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS; 3270 files |
| `uv run python scripts/check-ratchet-provenance.py` | PASS; 53 consumers; existing invalid-escape SyntaxWarnings |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS |

Vulture selected trusted base `4aa68edc0b6b` under repository policy; no override
was used to force the dispatch base. Raw test and vulture output is in
`/tmp/860-2643-tests.log` and `/tmp/860-2643-vulture.log` (ephemeral local logs).
No ledger/grant, production code or test changes. No suite-count delta, so no
inventory note is necessary. Existing evidence was preserved unchanged.

## Acceptance disposition

All ten criteria remain **UNVERIFIED at promotion grade**. No deployed soak ran
in this repair. Prior result claims are not being adopted as fresh evidence.

| Acceptance criterion | Fresh evidence / outstanding requirement |
| --- | --- |
| Representative release-candidate load profile | **UNVERIFIED**. Reviewed `m3a-load-profile.md` and runner mix at `scripts/soak/run_soak.py:1373-1395`: one credential and health/task/receipt/metrics traffic, not representative concurrent users/Workspaces, Graph fan-out, successful tool/model, Canvas and background reconciliation traffic. RC applicability is not designated. |
| At least two deployed application replicas | **UNVERIFIED**. Executed tests exercise two ASGI applications using real production middleware, not two deployed immutable RC replicas. |
| Sustained saturation, queue growth, reclaim, retry and leak observations | **UNVERIFIED**. Deterministic sampler/accounting tests pass; no sustained observation window executed. |
| Physical-work uniqueness, admission and Goal reconciliation | **UNVERIFIED**. Runner `scripts/soak/run_soak.py:1044-1069` cancels a queued schedule probe Run without executing it. Admission uniqueness alone cannot prove physical effects, stale-Attempt fencing or sustained Goal reconciliation. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **UNVERIFIED overall; shared-budget interpretation falsified locally**. Executed `tests/test_soak_promotion_gates.py:439` for both anonymous/authenticated identities: each real middleware instance independently returns `[200,200,429]` for the same identity. Production installs it at `packages/maistro-server/src/maistro_server/main.py:648`; `api/rate_limit.py:32-37` explicitly documents N-times aggregate allowance. Resolve this contract rather than treating six 429 probes as a shared budget. |
| Complete telemetry and explicit thresholds | **UNVERIFIED**. `scripts/soak/run_soak.py:1409-1421` measures driver-loop lag, not application-loop lag. No current RC pool/query/lock/queue/worker/RSS/fd/error series was collected. |
| Active-work kill/restart, drain/fencing/recovery | **UNVERIFIED**. Reviewed `scripts/soak/run_soak.py:1428-1487`: exit/rejoin and HTTP deltas lack a physical-effect/stale-worker recovery oracle. No active-work restart executed here. |
| Long soak of unchanged exact RC artifact/configuration | **BLOCKED / UNVERIFIED**. No designated immutable promotion RC/configuration supplied. `scripts/soak/run_soak.py:730-741` always rejects the host-process topology. Passing tests prove fail-closed promotion checks, not a four-hour deployed soak. |
| Load findings filed/reclassified before promotion | **UNVERIFIED** externally. Existing gaps recorded locally; no new load finding claimed. No GitHub mutation permitted or attempted. |
| Machine/human evidence bound to exact artifact/configuration hashes | **UNVERIFIED**. This report identifies the checked commit and executed validation, not a hash-bound RC deployment soak. Historical evidence has not been relabeled. |

## Handoff

**BLOCKED** for issue acceptance; no reproducible CI defect remains in the
supplied failure. Only this report changes. Further identical gate-only retries
cannot establish release acceptance. Required next input/work: designate the
immutable RC and supported configuration, resolve the replica-local allowance
contract, add representative production-path workloads and physical-work/recovery
oracles plus application telemetry, then execute the unchanged long RC soak.
Do not substitute another host-preflight run or weaken the artifact gate.

Progress: checked 1 issue, done 0 acceptance-complete, skipped 0 issues, errors 0
validation failures. Report will be committed locally as a blocked handoff, not
integration approval.
