# Issue #860 CI repair handoff

## Frozen scope

- Assigned issue: #860 only; writer in `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Verified starting HEAD: `43c8df6699c3ae4e729875d65a25aec33c05f440`.
- Verified supplied develop base: `91996e19223db61bab49ce2e8a8d5b8f6eb2728e`.
- Initial worktree clean; no incoming changes to salvage.
- Job directory contains no `check-*.log` files. Driver checks therefore cannot be assumed.
- Snapshot: explicit vulture exact-debt-ledger repair; the three previously reported soak Markdown whitespace findings; existing soak runner/profile/evidence/tests and relevant architecture read-only for acceptance review. This handoff records results. No other issues or remote mutations.
- Ambiguity: the task requests CI repair while the issue requires a long exact-RC production soak. Proceed with evidence-backed gate repair only; do not claim a replacement soak or promotion approval.

## Progress

- Initial refs and worktree checked.
- Required exact vulture scan passed: 1,342 findings / 1,342 reviewed identities, zero unclassified or never-allowlist findings, comparison base `91996e19223d`. No ledger amendment or source deletion is evidence-backed.
- Prior result read; existing load profile explicitly identifies host-process preflight limitations and representative-workload gaps.
- Reproduced all three reported trailing-blank-line defects via `git diff --check 91996e19223db61bab49ce2e8a8d5b8f6eb2728e`. Removed only those terminal blank lines, retaining historical report content.
- `uv sync --locked --extra dev`: PASS. `uv run ruff check .`: PASS. `uv run ruff format --check .`: PASS (2,889 files).
- Focused soak/production-stack/learning-store/task-backpressure tests: 88 passed, 5 skipped. Replica-selection regressions execute real production middleware and confirm independent allowances; application installs it at `packages/maistro-server/src/maistro_server/main.py:593`.
- Historical shakedown JSON independently read: 90.43 seconds, duration check false, code identity `b31c5fdaa63b40506335bbb288889e87bdb9ba0c`, no exact-RC artifact check. It cannot certify the assigned HEAD. The current evaluator still rejects it; final evaluation recorded below.
- Post-repair `git diff --check 91996e19223db61bab49ce2e8a8d5b8f6eb2728e`: PASS. `uv run python scripts/check-backlog-consistency.py`: PASS (168 items).
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q -rs`: 27 passed, 5 skipped explicitly for missing `MAISTRO_TEST_PG_DSN`; no database-integration claim made.
- `DOCKER_HOST=unix:///var/run/docker.sock docker info --format '{{.ServerVersion}}'`: PASS, 29.7.2. Docker availability is not the remaining blocker; no exact RC identity/configuration was supplied and the existing runner is not an exact-artifact runner.

## Architecture reconciliation

Read repository instructions and accepted ADR-085, ADR-081626-f383,
ADR-082526-b36a and ADR-082426-82c7, plus Proposed ADR-081. Keep
Goal -> Graph -> Run -> NodeRun -> Attempt as the sole execution spine.
Occurrence uniqueness proves admission, not physical side-effect uniqueness.
The later lease ADR defines renewal/reclaim beyond the original fencing ADR;
reclaim must be exercised rather than presumed absent or silently replaced.
ADR-085 principal keys do not establish shared replica counters, nor waive #860's
replica-selection requirement. No new execution, authorization or scheduler
path is introduced.

## Final validation and acceptance

All commands below were executed locally with 1,200-second timeouts for the
validation batches; historical pass claims were not substituted for execution.

- `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`: **88 passed, 5 skipped** as detailed above.
- `uv run python scripts/check-ratchet-provenance.py`: PASS, 49 quality consumers and delegated gates checked; existing syntax/CORS warnings only.
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: PASS, 12,800 collected identities.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-server/tests`: PASS, 502 collected identities.
- Inline `uv run python` imported the actual soak evaluator and loaded `evidence/m3a-round6-shakedown.json`: asserted failed checks are exactly `sustain_duration` and `exact_rc_artifact`, and that the current runner's artifact check is false. The historical JSON was not changed.

| #860 acceptance criterion | Executed/reviewed evidence and result |
| --- | --- |
| Representative release-candidate profile | PARTIAL: `m3a-load-profile.md:152-165` explicitly leaves users/Workspaces, Graph fan-out, successful model/tool calls, Design/Canvas and background reconciliation unverified. Complete representative profile **UNVERIFIED**. |
| At least two supported application replicas | PARTIAL: production Compose defines two servers (`deploy/docker-compose.prod.yml:26-78`); historical preflight describes two host processes. Exact supported topology execution **UNVERIFIED**. |
| Sustained load observing saturation/reclaim/retries/leaks | NOT MET: evaluator executes against 90.43-second evidence versus 14,400 required (`evidence/m3a-round6-shakedown.json:163-165,221-225`). Long-window observations **UNVERIFIED**. |
| No duplicate physical schedule/task/Run/Attempt/Goal work | **UNVERIFIED**: schedule probe cleanup cancels the admitted Run without execution (`evidence/m3a-round6-shakedown.json:12-16`); admission uniqueness is not a physical-work oracle. |
| Rate/security/degraded behavior non-bypass across replicas | NOT MET: executed production middleware tests (`tests/test_soak_promotion_gates.py:439-489`) give the same identity fresh allowance on replica 2. Other production security/degraded claims under a qualifying soak **UNVERIFIED**. |
| Required telemetry with pass/fail thresholds | PARTIAL: profile thresholds and sampler tests exist, but application-loop latency, worker completeness, saturation and qualifying RC measurements **UNVERIFIED** (`m3a-load-profile.md:152-165`). |
| Kill/restart with drain/fenced recovery | PARTIAL: historical JSON reports SIGTERM/rejoin; physical Attempt recovery under sustained active work **UNVERIFIED**. Evaluator tests are not a new failure-injection soak. |
| Long soak of exact promoted RC, rerun after changes | NOT MET: `scripts/soak/run_soak.py:635-647` always returns false for this host runner; evaluator rejects existing evidence. No selected immutable RC/configuration or new qualifying soak supplied. |
| Findings filed/reclassified before promotion | Locally VERIFIED: `BACKLOG.md:267-279` tracks engine-116 and explicitly blocks #860 promotion; human evidence classifies findings, including replica boot at M3-A (`m3a-soak-evidence.md:74-89`). Backlog consistency check passes. No GitHub mutation performed. |
| Machine/human evidence tied to exact hashes | PARTIAL: historical JSON/human packs exist, but the JSON is tied to `b31c5fdaa63b40506335bbb288889e87bdb9ba0c`, not this candidate or an exact RC image/configuration. Qualifying evidence **UNVERIFIED**. |

## Disposition

**BLOCKED for #860 acceptance.** The explicit CI-ledger failure did not reproduce;
there are no unbanked identities to review or amend. The three reproduced
whitespace failures are repaired. Changed files are this handoff and only the
trailing blank lines of `issue-860-13ec34d7-repair.md`,
`issue-860-62822668-repair.md`, and `m3a-round16-handoff.md` in this directory.
No source, runtime configuration, tests, gates, ledger, grants or historical
measurement data changed; no inventory delta is required because no tests changed.

The previous validation-budget block cannot be resolved by another passing scan
or short host preflight. Next: designate the immutable RC/configuration, resolve
the replica-budget contract, implement representative production workloads and
physical-work/telemetry oracles, then execute and publish >=4 hours on that exact
topology. Any code/runtime-config change requires a new soak. PostgreSQL
integration tests also remain unexecuted in this round (missing test DSN), not
silently counted as passes. This local commit is a blocked writer handoff, never
integration approval.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "#860 exact-RC prerequisites and qualifying soak"}`. Gate repair assessment complete; issue acceptance remains open.
