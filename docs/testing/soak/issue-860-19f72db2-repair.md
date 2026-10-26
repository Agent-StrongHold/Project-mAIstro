# Issue #860 — bounded CI repair (19f72db2)

## Frozen scope

- Issue #860 only; worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Starting HEAD: `25c5c51c1c8cb16e59e14adbd951cbe95a1e974f`.
- Supplied base: `ab8b3737fa64f8d840f421ef87ca506c509444ff`.
- Clean starting tree; no incoming edits to salvage.
- Inputs: supplied dispatch snapshot, prior result 105a0787, reported check-3 log
  from job 98a11313, repository instructions and relevant ADRs.
- Review surfaces: existing soak runner/profile/evidence and adjacent tests,
  vulture checker and any identities it actually reports. Only this report and
  evidence-backed repairs within those surfaces may change.
- No current-job check logs were present at initial inspection. Assumption:
  reproduce the specified vulture command rather than infer a scanner failure.
- No remote mutations, alternative execution authority, or promotion claims.

## Progress

- Requested vulture scan passed: 1,322 reviewed identities, zero unclassified,
  zero never-allowlist findings. No ledger amendment is warranted.
- Supplied historical check-3 failure is the learning-schema test's 24 versus
  21 statement mismatch, not a scanner finding. Fresh execution passed:
  37 passed, 6 skipped. No speculative schema changes warranted.
- Ruff lint and format checks passed (3,301 files formatted).
- Soak promotion gates plus task backpressure tests: 73 passed.
- Suite inventory: 17 suites, 31,327 unique test identities, no duplicates;
  all counts match. No tests added or changed, hence no inventory delta.
- Read repository instructions, accepted ADR-081426-1f7c and
  ADR-081626-f383, current profile, runner gates, adjacent tests, and production
  rate-limit middleware. Canonical Attempt identity and Run-store fencing remain
  authoritative; admission uniqueness is not physical execution uniqueness.
  No competing scheduler, store, authorization, or reclaim path was introduced.
- Executed current `failed_promotion_checks` on the frozen historical
  `evidence/m3a-round30-shakedown.json`: rejected `sustain_duration` and
  `exact_rc_artifact` (420.08 seconds versus 14,400 minimum). Also asserted
  `preflight_artifact_check()['ok'] is False`. This is re-evaluation, not a new
  live soak. Both assertions passed.

## Executed validation commands

All commands below exited zero; none constitutes an exact-RC soak:

```text
uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'
uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q
uv run ruff check .
uv run ruff format --check .
uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q
uv run python scripts/check-suite-inventory.py
```

The additional `uv run python` inline evaluator imported the runner using
`importlib.util`, loaded round30 JSON, asserted the two failed checks listed
above, and asserted the preflight artifact check is false.

## Acceptance review

| # | Criterion | Current evidence / disposition |
|---|---|---|
| 1 | Representative RC workload | UNVERIFIED. Profile's remaining-gaps section explicitly omits multiple users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas and Goal workers. The assignment does not designate an immutable RC deployment/configuration. |
| 2 | Two production application replicas | UNVERIFIED. Runner's artifact check at `scripts/soak/run_soak.py:744` identifies host-process preflight, not production Compose. Middleware tests do not prove a deployed topology. |
| 3 | Sustained load, saturation, retries and leaks | UNVERIFIED. Executed evaluator rejects historical 420.08-second sample against 14,400 minimum. No new sustained run performed. |
| 4 | Physical-work uniqueness | UNVERIFIED. Schedule probe cancels its queued Run without execution (`scripts/soak/run_soak.py:1070`). Admission gates passing cannot prove Attempt or Goal physical-work uniqueness. |
| 5 | Replica-independent security/degradation | UNVERIFIED as a whole; independent budgets reproduced for authenticated and unauthenticated identities by `tests/test_soak_promotion_gates.py:439`. Each production middleware instance returns 200,200,429 for the same identity. Middleware is actually installed in `packages/maistro-server/src/maistro_server/main.py:648`. Its documented process-local policy (`api/rate_limit.py:32`) needs reconciliation with this criterion, not an invented authorization path. |
| 6 | Complete production metrics and thresholds | UNVERIFIED. Sampler regressions passed, but profile measures driver loop lag, not application loop lag; no complete exact-RC series produced. |
| 7 | Kill/restart during physical work | UNVERIFIED. No production Attempt kill/restart executed. Process health/rejoin alone cannot prove fencing or loss-free recovery. |
| 8 | Long soak of exact RC/configuration | UNVERIFIED. Current evaluator rejects both sampled duration and artifact identity. A longer host-process run cannot satisfy the artifact check. |
| 9 | Findings filed/reclassified before promotion | UNVERIFIED. Historical reports are not fresh confirmation of external disposition. GitHub mutations prohibited and none performed. |
| 10 | Machine/human evidence bound to promoted hashes | UNVERIFIED. Historical evidence exists but does not establish a newly designated immutable promoted image/configuration. |

ADR reconciliation: `Goal -> Graph -> Run -> NodeRun -> Attempt` remains the
only execution model. ADR-081626-f383 leaves lease-expiry takeover undefined;
this round does not invent reclaim authority to make a soak pass.

## Handoff

**BLOCKED**, not merge-ready. Only this report changed; no production, test,
ledger, grant or gate edits are justified by the reproduced checks. The supplied
historical failure no longer reproduces. Missing promotion prerequisites are
not a vulture defect and must not trigger speculative ledger edits.

Next: designate immutable RC images, configuration and deployment scope;
complete the representative workload and application observability, reconcile
replica-budget semantics, then execute the >=4-hour exact-RC soak with active
Attempt recovery/fencing evidence. Publish hashes and findings disposition.
Another identical CI-repair dispatch cannot substitute for those prerequisites.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "designated RC and production soak"}`.
Local report commit required; no remote actions or integration approval.

