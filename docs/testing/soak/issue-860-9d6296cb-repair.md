# Issue #860 — repair checkpoint (job 9d6296cb)

## Frozen scope

- Issue #860 only; worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Starting HEAD `7f39ba6bc0fa56e19084a01a4cd8fe3b7c8dba73`;
  supplied base `31d891a561dffd6db1312ea4a85c4835c8048440`.
- Starting tree clean; no incoming edits to salvage.
- Review scope: `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`,
  `tests/test_prod_stack_boot_contract.py`, production task/rate middleware,
  PostgreSQL learnings and adjacent tests, `docs/testing/soak/m3a-load-profile.md`,
  historical round6 evidence, relevant ADRs and quality gate implementation.
- Conditional repair scope: reviewed vulture identities in the explicitly permitted
  `quality/vulture-baseline.json`; genuine dead code only if demonstrated by scan.
  This handoff records findings if no safe in-scope implementation repair exists.
- No GitHub mutations, runtime authority replacement or gate relaxation.

## Initial evidence and assumptions

The supplied dispatch snapshot contains the ten acceptance criteria and prior PR
history. No `check-*.log` files exist in this job directory at initial inspection.
The supplied prior result reports BLOCKED; that is context, not fresh proof.
The reported `launch/preflight: string indices must be integers, not 'str'` has
no supplied traceback. Treat it as unresolved driver provenance unless reproduced
in the checked-in runner; do not guess a code change.

## Fresh CI-repair evidence

The requested exact vulture command exited 0: 1,339 findings match 1,339
reviewed identities, with zero unclassified/unreachable findings and no stale
or unbanked identities. The gate selected merge base `69dd90fad2ae`.
Log: job-directory `check-vulture.log`. No ledger amendment is justified by this
scan; the CI-repair failure is not reproduced at the assigned head.

## Focused validation checkpoint

- `uv run ruff check .`: exit 0.
- `uv run ruff format --check .`: exit 0.
- `git diff --check 31d891a561dffd6db1312ea4a85c4835c8048440`: exit 0;
  prior trailing-blank-line failures are not reproduced.
- `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  92 passed, 6 skipped (PostgreSQL-dependent coverage remains unexecuted).
  Production middleware tests reproduce independent allowances on both replicas;
  they do not prove a shared budget or a running deployment.
- The dispatch JSON has no occurrence of the reported preflight exception and
  supplies no traceback. Source attribution remains UNRESOLVED; no speculative
  parser repair was made.

## Architecture reconciliation

Read repository instructions, `docs/README.md`, ADR-081 (Proposed, not an accepted
promotion waiver), accepted ADR-081226-a66b and ADR-081626-f383. Preserve the
Goal → Graph → Run → NodeRun → Attempt model and Run-store fencing authority.
The accepted lease ADR explicitly does not define automatic lease-expiry takeover;
#860 cannot authorize a competing reclaim scheduler. Admission deduplication is
not proof of physical-work uniqueness. Rate middleware explicitly documents
process-local budgets; the issue's non-bypass acceptance is not waived by that
implementation limitation.

## Additional executed checks

- `uv run python scripts/check-backlog-consistency.py`: exit 0.
- `uv run python scripts/check-test-duplicates.py`: exit 0.
- `uv run python scripts/soak/run_soak.py --help`: exit 0; CLI import/argument
  parsing works, but this does not exercise deployment launch.
- Imported the current runner and evaluated
  `docs/testing/soak/evidence/m3a-round6-shakedown.json` with
  `failed_promotion_checks`: returned `sustain_duration` and `exact_rc_artifact`.
  Assertions that both checks fail passed. Observed 90.43 s versus 14,400 s.
  Script/output preserved in the job's tool transcript / `check-historical-evidence.log`.

All validation logs are in
`/home/dev/maistro/jobs/9d6296cbf3d94569b306064701dc69e7/check-*.log`.
No new tests or suite-count changes; no inventory delta required. No runtime,
configuration, ledger or grant edits. Only this handoff is changed this round.

## Acceptance audit (in issue order)

| Criterion | Fresh evidence and disposition |
| --- | --- |
| Representative users/Workspaces and workload mix | PARTIAL definition only. `m3a-load-profile.md:152-165` explicitly lacks user populations, Graph fan-out, successful model/tool calls, Canvas and background-worker coverage. Representative production behavior UNVERIFIED. |
| At least two production application replicas | `deploy/docker-compose.prod.yml:26-82` declares two. Boot contract tests pass, but no running exact-RC deployment was exercised this round. UNVERIFIED. |
| Sustained saturation, queue/lease/retry/leak/shutdown observations | Current evaluator rejects historical 90.43 s against 14,400 s. No new long run; UNVERIFIED. |
| No duplicate physical work across schedule/task/Run/Attempt/Goal operations | Admission-probe tests pass, but `m3a-load-profile.md:197-200` describes a cancelled queued schedule-probe Run, not physical work or sustained Goal reconciliation. UNVERIFIED. |
| Security/degraded/rate behavior cannot be bypassed by replica selection | NOT MET for a shared allowance: passing production middleware tests at `tests/test_soak_promotion_gates.py:439-488` observe `[200,200,429]` on each replica for the same authenticated/unauthenticated identity. `main.py:593` installs this middleware in production; `api/rate_limit.py:25-30,72-77` documents/constructs process-local state. Existing admission backpressure test passes, but it does not close the non-bypass gap. |
| Required metrics and explicit thresholds | PARTIAL: sampler and missing-measurement tests pass. `m3a-load-profile.md:159-165` distinguishes driver loop lag from app lag and leaves worker counts/saturation/leaks unverified. No production telemetry collected. |
| Kill/restart during active work proves drain/fencing/recovery | Process rejoin/terminal counts are insufficient for physical fencing. No production fault injection performed. UNVERIFIED. |
| Long soak of exact RC, rerun after code/config changes | NOT MET. `run_soak.py:635-647` explicitly rejects its host-uvicorn topology. Current evaluator rejects archived evidence. No exact promoted image/config identity supplied for a new run. |
| Load findings filed/reclassified to earliest broken invariant | Existing local backlog entries are present and consistency gate passes. Complete milestone disposition UNVERIFIED; no GitHub mutations permitted/performed. |
| Machine/human evidence bound to exact hashes | Historical JSON/human evidence exists, but no qualifying current-RC evidence. UNVERIFIED. |

## Final disposition / next owner

**BLOCKED**, not a promotion approval. The requested CI vulture failure and
whitespace failures were not reproduced; no speculative repairs are warranted.
The preflight exception remains **UNRESOLVED**: CLI help and focused tests pass,
but neither is evidence that the failed external launch path is repaired. Supply
its actual traceback and input payload before attributing it to repository code.

Next: select the exact RC image/config and supported workload, implement/use a
production-topology driver without replacing canonical execution authority,
resolve the shared-budget acceptance mismatch through its owning path, and run
at least four hours with real workload/fencing/telemetry evidence. Merely
extending the host preflight duration cannot satisfy acceptance. Existing
PostgreSQL integration skips must also be rerun against a configured database;
unit doubles do not prove concurrent PostgreSQL startup.

Checkpoint: checked 1 assigned issue; done 0 acceptance completions; skipped 0
issues; 0 validation command failures; 1 unattributed prior launch error remains.
This local commit preserves the current evidence and leaves all prior work intact.
