# #860 repair — job af4e4e25

## Frozen scope and initial state

- Sole issue: #860; assigned worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Verified clean starting HEAD: `3bf78044dcdf658331568a1118aab62208df6434`.
- Process only the requested exact-debt-ledger gate and existing #860 acceptance evidence/tests. Candidate edits: `quality/vulture-baseline.json` only for actual reviewed gate findings, and this handoff. No production changes or test additions planned absent reproduced evidence.
- Read-only acceptance inputs: repository instructions; execution/fencing/rate-limit ADRs; production rate-limit middleware; `scripts/soak/run_soak.py`; `tests/test_soak_promotion_gates.py`; load profile and historical evidence; adjacent PostgreSQL-learning and task-backpressure tests; vulture gate implementation and CI configuration.
- Job directory snapshot contains events.jsonl, manifest.json, prompt.txt, state.json; no driver `check-*.log` files. Driver checks cannot be verified here.
- Prior result db6e3522 reports BLOCKED, no executed driver checks, end HEAD matching this start. Its claims require revalidation.
- Ambiguity: no exact promotion RC image/configuration is designated. Proceed with focused gate/acceptance validation, not a guessed four-hour production soak. Never reinterpret host preflight as production evidence.
- Base-to-HEAD diff contains unrelated historical changes; not a sync-conflict assignment and clean worktree has no conflicts. Do not modify those files or merge an unsolicited ref.

## Validation

- Requested exact-debt-ledger command executed: `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` → exit 0, 1402 reviewed identities / 1402 findings, unclassified=0, never_allowlist=0. No unbanked identities; no justified ledger or runtime repair. Log: `/tmp/af4e4e25-vulture.log`.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py -x -q -rs` → **80 passed, 5 skipped** in 12.12 s. All skips require `MAISTRO_TEST_PG_DSN`; no live PostgreSQL result claimed. Log: `/tmp/af4e4e25-pytest.log`.
- `uv run ruff check .` → pass; `uv run ruff format --check .` → pass (2624 files).
- Executed existing production-middleware counterexample for both anonymous and authenticated identities: exhausting replica 1 yields `[200, 200, 429]`, then the same identity still gets `[200, 200, 429]` from replica 2. This confirms process-local enforcement, not the requested replica-selection non-bypass. The old shared-store wording is already corrected at this HEAD (`m3a-soak-evidence.md:171`); no cosmetic repeat repair is warranted.
- Executed existing CLI regressions rejecting otherwise-passing four-hour preflight evidence with missing/null/preflight artifact records, plus actual Linux uv-child memory/descriptor sampling and task-route backpressure tests. These are focused regressions, not an RC soak.
- Read AGENTS.md, CLAUDE.md and accepted ADRs 081426-1f7c (runtime mechanics), 081626-f383 (Attempt fences), 085 (principal limits), plus Proposed ADR-081 (deployment). Reconciliation: the fencing ADR explicitly does not define expiry takeover. Admission uniqueness or process restart is not physical-work recovery proof; this lane must not invent reclaim authority to satisfy the issue. Proposed ADR-081 is not an accepted override of #860.
- Executed `uv run python` importing the current `failed_promotion_checks` evaluator against the four historical JSON packs named in the initial evidence snapshot. Asserted all are rejected. Run 1 fails seven gates; repair-validation fails seven; round 5 fails rate limiting, duration and artifact; round 6 fails duration and artifact. Round 5 sustained 90.17 s, round 6 90.43 s. Missing top-level duration in the first two was printed as null, not inferred as zero or promoted to a pass.

## Acceptance disposition (all ten criteria)

| Criterion | Current executed evidence / disposition |
|---|---|
| Representative users/Workspaces and workload | **PARTIAL**: inspected `m3a-load-profile.md:46-68,146-160`; one API key and degraded provider traffic are not representative multi-user, Graph fan-out, successful tools/models, Canvas/Design or background-worker coverage. Complete RC profile **UNVERIFIED**. |
| Two application replicas | Historical host-process two-replica results only (`m3a-soak-evidence.md:163-180`). Exact supported RC topology **UNVERIFIED**; no new deployment run this round. |
| Sustained saturation, reclaim, retries, leaks and restart | **UNVERIFIED**. Evaluated historical packs are subminimum; round 6 `sustain_duration.ok=false`, 90.43 versus 14400 s (`evidence/m3a-round6-shakedown.json:221-224`). Live uv-child test proves sampler sensitivity, not sustained application behavior. |
| Exactly-once/fenced physical work and Goal reconciliation | **UNVERIFIED**. Admission oracle regressions pass; schedule probe only races admission and cancels its Run without execution (`m3a-load-profile.md:186-196`). No physical Attempt side-effect or Goal recovery proof. |
| Security/rate/degraded behavior non-bypass | **NOT MET** for replica-selection non-bypass: both production-middleware counterexample cases pass (`tests/test_soak_promotion_gates.py:436-486`). The real application installs that middleware (`packages/maistro-server/src/maistro_server/main.py:478`); its state is explicitly local (`api/rate_limit.py:25-30`). Concurrency security and degradation under exact RC load remain **UNVERIFIED**. |
| Required telemetry and explicit thresholds | **PARTIAL** profile/instrumentation only. Inspected profile's missing application-loop and detached-worker measurements; existing live child metrics regression passes. Full pool/query/lock/queue/error/leak evidence under RC load **UNVERIFIED**. Five PostgreSQL tests skipped, not passed. |
| Kill/restart during active work, drain/fencing/recovery | Historical process exit/rejoin is not physical-work recovery. **UNVERIFIED** for exact RC and in-flight Attempts; current focused tests do not prove this. |
| Long soak of exact RC; resoak after runtime/config change | **BLOCKED**. No designated exact RC image/config in assignment. Current host runner explicitly returns artifact failure (`scripts/soak/run_soak.py:635-646`). CLI tests confirm even four-hour preflight cannot pass. Do not spend four hours running an incapable signer. |
| Findings classified/filed before promotion | Local classifications inspected in `m3a-soak-evidence.md` (M3-A evidence validity, admission/boot availability). No new runtime defect discovered this round. External filing **UNVERIFIED** and prohibited in this lane. |
| Machine/human evidence with exact hashes | Historical JSON plus prose exists and was inspected/evaluated, but all four packs are rejected. Qualifying RC-artifact hash-tied evidence **UNVERIFIED**. This handoff is validation evidence only. |

## Outcome and next owner actions

**BLOCKED**, not merge-ready. The requested CI gate is already green at the assigned HEAD; no dead-code/ledger repair is supported by evidence. Do not manufacture a runtime change or bank extra identities. No tests were added or removed, so inventory delta is zero and existing inventory notes remain unchanged. Only this handoff is changed; historical JSON/logs, production behavior and gates are untouched.

Release/runtime owners must designate an immutable RC artifact and normalized production configuration, resolve the rate-limit acceptance/deployment mismatch without an alternate authorization path, complete the representative workload and physical-work/telemetry oracles, then execute at least 14400 s on the exact supported two-replica topology. Preserve the canonical Goal → Graph → Run → NodeRun → Attempt authority. Any code/runtime-config change requires another soak. Local finding classifications need authorized external disposition before promotion.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "#860 blocked on exact-RC soak and concurrency acceptance"}`. One assigned issue assessed; focused validation completed, acceptance unresolved. Commit this handoff locally; no push, PR, issue mutation or integration approval.
