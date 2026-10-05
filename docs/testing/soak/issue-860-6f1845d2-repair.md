# Issue #860 — repair round 6f1845d2

## Scope and disposition

**BLOCKED: no exact-RC production soak established.** Passing CI is not soak
acceptance or integration approval.

Assigned branch/worktree: `auto-860`, `/home/dev/Git/wt/auto-860`.
Starting head: `af0b84e5262ab571a3a73dd436fe206e550f65d2`.
Supplied base: `b672b799aba6d3db9edc3e1be18b1a3335dd3bc0`.
The initial tree was clean; no sync conflict or uncommitted salvage was present.
Only #860 was processed using the supplied local dispatch snapshot and prior
result. No GitHub mutations, service changes, or additional issue work occurred.
No driver `check-*.log` files were supplied in this job directory.

The explicitly requested vulture repair does not reproduce: both fresh scans
match all 1,338 reviewed identities. No ledger or grant amendment is warranted.
The actual failing command was the supplied-base `git diff --check`, reporting
`docs/testing/soak/issue-860-4de4d819-repair.md:109: new blank line at EOF`.
Removed only that blank line, preserving every statement in the prior report.
The initial candidate edit list omitted this prior artifact; this narrow scope
deviation is recorded explicitly. No production code, gate, or historical
machine-readable evidence changed. No tests were added, so no inventory delta
is required.

## Architecture review

Read `AGENTS.md`, the documentation authority map, ADR-081 (Proposed), and
accepted ADR-085, ADR-081626-f383, ADR-082126-f69c. Preserve
`Goal -> Graph -> Run -> NodeRun -> Attempt`: recurrence admits canonical Runs,
and canonical Attempt leases own fencing authority. Admission deduplication is
not proof of nonduplicated physical execution. ADR-085's per-principal identity
rule does not waive #860's replica-selection requirement. The shipped middleware
is explicitly process-local and is installed in `maistro_server/main.py:593`.
No alternate scheduler, authorization path, or execution authority was introduced.

## Fresh validation

Commands ran in the assigned worktree with 1,200-second timeouts. Raw logs:
`/home/dev/maistro/jobs/6f1845d2215742ba932e61bb6480486e/worker-*.log`.

| Command | Observed result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS twice; 1,338 findings / reviewed identities; zero unclassified and never-allowlist findings |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS; 2,943 files formatted |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q` | 60 passed |
| `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | 1 passed |
| `uv run python scripts/check-ratchet-provenance.py` | PASS |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS |
| `uv run python scripts/check-backlog-consistency.py` | PASS; 168 items |
| `git diff --check b672b799aba6d3db9edc3e1be18b1a3335dd3bc0...HEAD` before repair | FAIL, exit 2; prior-report EOF blank line above |
| `git diff --check b672b799aba6d3db9edc3e1be18b1a3335dd3bc0` after repair | PASS |
| `uv run python` importing current evaluator against retained round-6 JSON | PASS: asserts rejection for `sustain_duration` and `exact_rc_artifact`; see `worker-retained-evidence.log` |

The second vulture scan and provenance gate explicitly used
`RATCHET_BASE_REV=b672b799aba6d3db9edc3e1be18b1a3335dd3bc0`.
`git merge-base` independently resolved that ref and HEAD to
`cd5618223cbdd9ac55d40695987e09fd8b4ef184`, matching the gate baseline.
The tests validate production middleware, harness failure handling, resource
sampling, and configuration contracts; they do not boot the production stack.

## Acceptance ledger

| Criterion | Executed evidence / remaining gap | Status |
| --- | --- | --- |
| Representative users/Workspaces, request mix, Graph/node fan-out, schedules, queue, tool/model, Canvas and background workers | Source review of `m3a-load-profile.md:152-165` identifies omitted workload classes; no representative promotion workload executed | UNVERIFIED |
| At least two production application replicas | Compose declares two at `deploy/docker-compose.prod.yml:26-78`; passing configuration tests do not exercise them under load | UNVERIFIED |
| Sustained saturation, queue growth, lease reclaim, retry, memory/fd/process leaks and restart | Current evaluator rejects retained 90.43-second sustain against 14,400 seconds; no new sustained series | UNVERIFIED |
| Schedule/task/Run/Attempt admission and Goal reconciliation without duplicate physical work | Receipt-probe tests pass; profile lines 197-200 explain the schedule probe cancels its Run without execution; no physical-work assertion under production load | UNVERIFIED |
| Rate/security/degraded behavior cannot be bypassed by replica selection | Both parameterizations of `tests/test_soak_promotion_gates.py:437-488` passed, showing the same identity gets `[200,200,429]` independently on both real middleware instances | NOT MET for non-bypass |
| PostgreSQL, application-loop, worker/process, RSS/fd, queue and error telemetry with thresholds | Sampler tests pass, but profile lines 156-165 distinguish driver-loop/process-group measurements from required application/worker observations | UNVERIFIED |
| Kill/restart during active work proves drain/fencing/recovery | No production active-work restart executed; historical exit/rejoin and terminal counts do not prove physical fencing | UNVERIFIED |
| Long-running exact-RC artifact/configuration soak | Fresh evaluator rejects retained evidence; `scripts/soak/run_soak.py:635-646` deliberately rejects host-uvicorn preflight even for long durations | NOT MET |
| Findings filed/reclassified to earliest broken milestone invariant | Backlog consistency passes; completeness of load findings cannot be established without representative execution; no GitHub mutation authorized | UNVERIFIED |
| Machine/human soak evidence tied to exact image/package/commit/config hashes | Retained JSON names `b31c5fdaa63b40506335bbb288889e87bdb9ba0c`, not assigned HEAD; no new image/config-bound production evidence | UNVERIFIED |

## Handoff

The whitespace repair and this report are the only changed files. The unresolved
work requires a selected immutable RC image/configuration, a production Compose
runner with representative workloads and application telemetry, resolution of
the replica-selection limitation at the canonical security seam, then at least
the profile's four-hour soak with active-work recovery assertions. Extending the
current host-process preflight cannot satisfy the artifact gate. Repeating the
passing vulture scan cannot resolve these acceptance blockers.

Progress: checked 1 issue; done 0 acceptance-complete issues; skipped 0 issues;
1 initial validation failure repaired. Next: exact-RC soak work, not ledger churn.
