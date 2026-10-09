# #860 repair checkpoint — fda3235f

## Scope and disposition

**BLOCKED; no speculative repair.** Sole assigned issue #860, worktree
`/home/dev/Git/wt/auto-860`, branch `auto-860`, clean starting HEAD
`31939dcb25b9f734ad6a01a7d4d8c2bd24909818`. Supplied base
`e46ad6708fda20f76b8915679ef701f3ddb6b7e2` resolves locally. No merge conflict,
GitHub mutation, discarded work, production run or ledger/grant edit.
Only this checkpoint changes; no tests added, so no inventory delta.

Read repository instructions, documentation authority map, accepted ADRs
081426-1f7c (Attempt/runtime boundary), 081626-f383 (fencing), 082526-b36a
(renewal/reclaim), and 073126-c4e1 (immutable RC release provenance).
ADR-081 is Proposed, not accepted authority. The later reclaim ADR extends the
older fencing boundary; its earlier deferral is not a recovery waiver.
Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt` and existing authorities.

The supplied dispatch snapshot's issue acceptance, latest primary comments and
linked PR bodies do not select an immutable RC/configuration for this campaign.
No remote snapshot refresh was performed. Prior result was BLOCKED. There were
no driver `check-*.log` files in this job directory at entry; the explicitly
supplied historical failure was inspected instead.

## Executed validation (1,200-second timeouts)

Logs: `/home/dev/maistro/jobs/fda3235fe14f4dd6a1ab406ae2ba3307/worker-*.log`.

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1,326 reviewed identities / findings, zero unclassified or never-allowlist. No unbanked identity to amend.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3,170 files.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`: **37 passed, 6 skipped**. Historical job `98a11313167b41a98a420abfda80c292/check-3.log` failed with 24 versus 21 DDL statements. Current independent assertion already includes all three Gauntlet columns at `test_pg_learnings.py:175-177`; the failure does not reproduce. Skips are not live PostgreSQL evidence.
- `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q`: **100 passed**.
- `uv run python scripts/check-merge-markers.py`: PASS.
- `uv run python scripts/check-suite-inventory.py`: initial collection FAILED for server/turing/design with `OSError: [Errno 28] No space left on device` in pytest temporary capture files. `df -i /tmp` showed 1 free inode (100% used), despite 14 GiB free bytes. No files deleted. Repeated once with `TMPDIR=/home/dev/maistro/jobs/fda3235fe14f4dd6a1ab406ae2ba3307/tmp`: **PASS**, 17 suites, 29,499 unique identities, no duplicate evidence. Counts/gates unchanged.
- `uv run python -` imported the current driver, evaluated historical `evidence/m3a-round30-shakedown.json`, and asserted failures `sustain_duration` and `exact_rc_artifact`: **PASS**, 420.08 seconds versus 14,400 minimum. Also asserted current `preflight_artifact_check()['ok'] is False`. This evaluates historical evidence; it is not a new soak.

## Acceptance, checked individually

| #860 criterion | Executed evidence and remaining gap |
| --- | --- |
| Representative RC load profile | **UNVERIFIED complete.** `m3a-load-profile.md:153-172` identifies missing multiple users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas and Goal/background-worker traffic. Selected RC configuration must justify inclusions/exclusions. |
| At least two deployed application replicas | **UNVERIFIED for RC.** Tests exercise two real middleware instances, not two deployed RC replicas. |
| Sustained saturation, queue growth, reclaim, retries and leaks | **UNVERIFIED.** Historical duration rejected by current evaluator; no fresh sustained production workload. |
| No duplicate physical work; schedule/task/Run/Attempt admission and Goal reconciliation | **UNVERIFIED.** `run_soak.py:1075-1163` races schedule admission then terminalizes its probe Run, not physical Attempt execution; admission counters cannot prove sustained work fencing. |
| Concurrent rate/security/degraded behavior without replica-selection bypass | **UNVERIFIED as stated.** Executed `test_replica_selection_has_an_independent_production_allowance` at `tests/test_soak_promotion_gates.py:439` observes `[200, 200, 429]` independently on both instances for the same identity. `rate_limit.py:32-37` explicitly promises per-process, not cluster-wide, budgets. Do not silently reinterpret acceptance or introduce another authorization path. |
| Complete PostgreSQL/application/worker telemetry and thresholds | **UNVERIFIED complete.** Driver-loop lag is not application-loop lag; no current candidate observations of all required metrics. |
| Active-work replica kill/restart with drain/fencing/recovery | **UNVERIFIED.** Passing boot and evidence-gate regressions do not demonstrate production stale-effect rejection or recovery. |
| Long soak of exact promoted RC/configuration | **BLOCKED / UNVERIFIED.** `run_soak.py:730-741` always rejects host preflight as exact RC evidence; historical duration fails. No selected immutable RC/configuration supplied. |
| Findings filed/reclassified to earliest invariant | **UNVERIFIED completeness.** Existing findings retained; no new load campaign or GitHub mutations. |
| Hash-bound machine/human soak evidence | **UNVERIFIED for candidate.** Historical files preserved, not recertified for this HEAD; this report records local validation only. |

## Next action

Supply the immutable RC image/package/configuration identity and selected supported
deployment contract, then execute a representative production-topology campaign
of at least four hours with full telemetry and active-work fault injection.
Resolve the shared-versus-per-replica budget acceptance through the existing
security seam. Another green scanner run or longer host preflight cannot satisfy
these prerequisites. Local commit is a handoff, never integration approval.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "selected RC and production acceptance execution"}`.
Initial environmental inventory error was resolved with a private temporary directory.
