# Issue #860 — repair checkpoint (job 0218599e)

## Frozen scope

Only issue #860; branch `auto-860`; starting HEAD
`dfb4ce9b3852b31381b86da6bd1188f71d9f1e3a`; supplied develop base
`435dc1937e0407ab4de198ffcced49860bb14ad2`. Starting worktree clean.
No PR processing or GitHub mutations. No driver `check-*.log` files were
present in the supplied job directory at initial inspection.

Read-only scope: frozen dispatch issue/PR evidence, repository instructions,
relevant ADRs, `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`,
production rate middleware and task admission paths, adjacent package tests,
vulture gate/workflow and prior explicitly supplied failed-check evidence.
Write scope: this report; `quality/vulture-baseline.json` only if the exact
requested scan demonstrates reviewed retained unbanked identities. Any actual
code defect needing a larger repair will be reported rather than guessed.

Assumption: this is a writer CI-repair lane, not a verifier-only lane. Existing
BLOCKED claims are not acceptance evidence; fresh validation is required.
The hundreds of inherited handoffs and unrelated historical branch changes
are not additional assigned items.

## Progress

- Exact prescribed vulture scan freshly passed: 1323 findings / 1323 reviewed
  identities; zero unclassified or forbidden findings. Gate-selected base
  `4aa68edc0b6b`; log `/tmp/860-0218599e-vulture.log`. No ledger change justified.
- Supplied historical `check-3.log` concerns the learnings schema-fence test:
  24 DDL statements versus 21 expected, not a vulture failure. Fresh tests pass;
  current expectation independently includes the three validation audit columns.
- Frozen issue #860 has ten acceptance criteria. Parent #89 requires the identical
  tested RC; captured PR #1672 is only a draft claim-stake. Neither body designates
  the immutable RC artifact/configuration. Do not invent one from local HEAD.

## Fresh executed validation

All validation commands used 1200-second timeouts.

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS (above); matches both CI workflows.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`: **103 passed, 6 skipped**, 2.64 s; `/tmp/860-0218599e-tests.log`. Skipped PostgreSQL tests are not live database evidence.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3270 files.
- `uv run python scripts/check-deployment-claims.py`: PASS.
- `uv run python scripts/check-execution-lifecycles.py`: PASS, 19 classified lifecycles.

## Architecture and acceptance assessment

Read ADR-081 (Proposed), ADR-085, ADR-081426-1f7c and ADR-082526-b36a
(Accepted). Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`. Physical
execution identity is Attempt, not Run; recovery must use canonical lease and
heartbeat fencing. No new execution or authorization authority is introduced.
ADR-085 requires principal-keyed limits but does not mandate a shared replica
store. This does not waive #860's replica-selection non-bypass criterion.

Production installs `RateLimitMiddleware` at `maistro_server/main.py:648`;
`api/rate_limit.py:95` creates an in-memory limiter per instance. The freshly
executed test `tests/test_soak_promotion_gates.py:439` observes `[200,200,429]`
on each replica for the same identity, for authenticated and pre-auth cases.
Thus shared-budget semantics are falsified; per-process enforcement is not
proof of the broader deployed security requirement. Changing that contract
without a designated RC/profile is not a speculative CI repair.

| #860 acceptance criterion | Evidence / remaining gap |
| --- | --- |
| Representative RC profile | **UNVERIFIED**. `m3a-load-profile.md:152` explicitly lists missing users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas and Goal/background workloads. Applicability needs the RC configuration. |
| At least two production replicas | **UNVERIFIED**. Two real middleware instances exercised in ASGI tests, not two deployed promoted images. |
| Sustained pool/queue/reclaim/retry/resource/shutdown observations | **UNVERIFIED**. Sampler regression includes a real uv child; no long-running RC workload executed. |
| No duplicate physical work across replicas | **UNVERIFIED**. Admission probe tests pass, but unique Run receipts do not prove unique physical Attempt effects. |
| Replica-selection non-bypass for rate/security/degraded behavior | Shared aggregate allowance **falsified** by executed middleware test above; complete RC security criterion **UNVERIFIED**. Task admission backpressure test passes against the canonical in-memory Run spine and production router (`api/tasks.py:117`). |
| Complete metrics with thresholds | **UNVERIFIED at RC grade**. Profile thresholds exist, but application-loop lag, sustained pool pressure and lease reclaim observations remain missing. Driver-loop lag is not application-loop lag. |
| Active-work kill/restart with drain/fencing/recovery | **UNVERIFIED**. Boot cleanup tests pass, not proof of physical-work recovery. |
| Long-running exact RC/configuration | **UNVERIFIED / BLOCKED**. No designated immutable RC established. `scripts/soak/run_soak.py:730` explicitly rejects host preflight as exact RC evidence; CLI fail-closed tests freshly pass. |
| Findings filed/reclassified before promotion | **UNVERIFIED externally**. Findings recorded locally only; no GitHub mutations permitted or performed. |
| Machine/human evidence bound to exact artifact/configuration hashes | **UNVERIFIED for RC**. This checkpoint and inherited preflight artifacts are not a production soak pack for this HEAD. |

## Handoff

**BLOCKED**, not a develop-sync conflict. No reproducible CI/schema failure
requires a code or ledger amendment. Only this report changes; no tests added
or removed, so inventory delta is zero and no inventory note is needed.
All inherited work is preserved; the large inherited branch diff is not certified.

Required next input: immutable RC image/package/configuration designation and
representative workload scope, plus resolution of aggregate rate-limit semantics.
Then run the production-topology long soak with physical Attempt-effect
correlation, complete telemetry and active-work recovery. Repeating this passing
CI-only repair does not supply those missing release inputs.

Progress: checked 1 issue; done 0 acceptance-complete issues; skipped 0 issues;
errors 0 fresh validation commands. CI-repair check complete, release acceptance
blocked. Local commit records the checkpoint only, never integration approval.
