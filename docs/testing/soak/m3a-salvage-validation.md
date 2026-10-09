# #860 recovery and admission-oracle repair

## Frozen scope and preservation

- Assigned issue #860 only, worktree `/home/dev/Git/wt/auto-860`, branch
  `auto-860`, verified initial HEAD `a8b9c129a967aa96417e1f2a36eed2a87c276b1d`.
  Supplied develop base `fa2deb0a45155641f1c5c396d452ab47855bd028` resolves.
- At entry the index was clean; only the inherited #860 soak scripts, tests,
  evidence and notes were untracked. The previous 261-file staged recovery
  problem is no longer present. No merge, ref deletion or destructive recovery
  was needed. Backed up tracked diff and all untracked files in
  `/home/dev/Git/wt/incoming-860.patch` and `incoming-860-untracked.tgz`.
  The initial archive command missed the NUL list delimiter and failed;
  corrected with `git ls-files -z` before editing. No work was discarded.
- Frozen edit scope: preserve those inherited #860 paths, repair only observed
  soak-oracle defects, add corresponding tests/inventory note and this report.
  The explicit CI-repair ledger exception was considered but not needed.
- Job `2b196a9d0c294ac39ae11d81855577fb` contained no `check-*.log` files.
  Prior result and historical reports were read as context, not fresh checks.
  New validation logs are `worker-*.log` in that job directory.

## Actual repair

Before editing, executing `phase_exactly_once_tasks` with an HTTPX transport
returning twelve 409s produced `ok=true`, `cause=ok`, `distinct_run_ids=[]`.
The supposed successful admission observation was empty. This is F11, an
M3-A evidence-validity defect, not proof of runtime duplication.

H1 now requires at least two submissions, valid non-empty Run identities on
all 200/202 receipts, exactly one distinct observed identity, and only
200/202/409 statuses. Replay (200) IDs now participate in the comparison.
Twelve HTTP-probe regression cases exercise the actual probe and propagate its
verdict into the CLI's evaluator. Inventory delta: `tests/: +12` in
`m3a-860-observed-admission.md`. Profile and human evidence explain the stronger
oracle; historical raw evidence is preserved byte-for-byte.

Read repository instructions and accepted ADR-081426-1f7c (Attempt runtime
identity), ADR-081626-f383 (canonical lease authority), ADR-082426-82c7
(occurrence uniqueness on Run), and ADR-085 (principal rate limits). No new
scheduler, Goal store, execution/event authority, or authorization path was
introduced. Admission uniqueness does not prove physical work uniqueness;
principal identity does not make process-local limits cluster-wide. Neither
boundary is waived to satisfy the issue.

## Fresh validation

All commands used `uv run` and 1800-second tool timeouts.

| Command | Result |
| --- | --- |
| `python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1402 findings / 1402 reviewed identities, zero unclassified and never-allowlist; no ledger edit justified |
| `pytest tests/test_soak_promotion_gates.py packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q` | Before repair: 84 passed, 5 skipped; after repair: 96 passed, 5 skipped. PostgreSQL cases skipped without a configured database; not credited as live proof |
| `ruff check .` | PASS |
| `ruff format --check .` | Initial failure on two newly edited Python files; formatted only those files; final PASS: 2624 files |
| `python scripts/check-suite-inventory.py --suite tests/ --suite packages/maistro-core/tests --suite packages/maistro-server/tests` | PASS: root 4192, core 11531, server 427; all three match recorded inventory |

Additional final checks: `uv run pytest packages/maistro-server/tests -x -q`
PASS (427 passed, 21 existing deprecation warnings, 80.15 seconds);
`uv run python scripts/check-deployment-claims.py` PASS (names resolve, not a
behavioral topology test); `uv run python scripts/check-doc-links.py` PASS
(1386 Markdown files, zero broken relative links). Final lint also PASSed.
After staging the recovered paths, `git diff --cached --check` and
`uv run python scripts/check-merge-markers.py` PASSed. SHA-256 comparison
against the incoming archive verified all 20 historical evidence files are
byte-identical. The checkpoint includes 36 files: recovered script/config,
server regression, root gate tests, seven inventory notes, historical evidence,
and five profile/evidence/handoff documents (see the commit's file list).

No deployment or new soak was executed. In particular, a passing ASGI test
is not evidence of two deployed application replicas. Historical logs are
not current validation logs.

## Acceptance disposition

| # | Criterion | Executed evidence / remaining gap |
| --- | --- | --- |
| 1 | Representative RC profile | PARTIAL: profile inspected; single-key provider-less mix lacks user/Workspace population, Graph fan-out, successful tool/model, Design/Canvas and Goal/background traffic. RC applicability UNVERIFIED. |
| 2 | Two production replicas | UNVERIFIED: Compose defines two services, but no exact-image deployment executed. Two ASGI middleware instances only prove the tested seam. |
| 3 | Sustained saturation/reclaim/retry/leak observation | UNVERIFIED: preserved round-6 JSON records 90.43 seconds, not the required 14400. No long-window observation added. |
| 4 | Exactly-once/fenced physical work and Goal reconciliation | UNVERIFIED: new H1 tests prevent empty admission evidence from passing, but do not execute physical Attempts. Historical schedule probe cancels its queued Run. |
| 5 | Rate-limit/security/degraded non-bypass | NOT MET for a cluster-wide allowance: executed production-middleware tests demonstrate `[200,200,429]` independently for the same identity on each replica, authenticated and unauthenticated. Full RC security/degraded behavior UNVERIFIED. |
| 6 | Complete metrics with thresholds | UNVERIFIED: driver-loop lag is not application-loop latency. Additionally `sample_once` reads the `uv run` wrapper PID, not its uvicorn child; inherited RSS/FD observations cannot establish application leak freedom. Worker counts and sustained pool/lease pressure remain unproven. |
| 7 | Kill/restart active-work drain/fencing/recovery | UNVERIFIED: no RC restart executed; historical wrapper exit/rejoin is not physical Attempt/effect correlation. |
| 8 | >=4-hour exact RC artifact/configuration soak | BLOCKED: no designated immutable RC image/configuration supplied, no exact Compose runner or qualifying evidence. Executed tests reject missing/null/preflight artifact records even for a synthetic four-hour duration. Any code/runtime-config change still requires a new soak. |
| 9 | Findings filed/reclassified before promotion | PARTIAL: F11 locally classified as M3-A evidence validity. Historical classifications retained. External filing UNVERIFIED and forbidden in this lane; no GitHub mutations. |
| 10 | Human/machine evidence tied to artifact hashes | PARTIAL: historical JSON/log/human packs preserved, not re-signed. Exact current RC image/config/package soak evidence UNVERIFIED. |

## Handoff

**BLOCKED for #860**, not integration approval. Recovery and the focused H1
repair are checkpointed locally; issue acceptance is not done.
The inherited runtime fixes (`pg_learnings.py`, `api/tasks.py`) and nginx change
were not changed this round. Their recovered tests/notes are included so the
existing branch repairs do not lose their validation context.

Next: designate the immutable promotion artifact/configuration, reconcile
cluster-wide rate-limit requirements with the owning security/deployment lane,
complete production-path workload and physical-effect/metric oracles, and run
and publish a new >=4-hour exact-artifact soak. Do not spend another four hours
on the host-process preflight and call it promotion evidence.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: exact-RC prerequisites and sustained soak}`.
The item is checkpointed, not completed. No push, PR, merge, comment or closure.
