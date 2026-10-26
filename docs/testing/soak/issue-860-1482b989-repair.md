# Issue #860 — isolated CI-repair handoff (1482b989)

## Frozen scope

- Assigned issue: #860 only; branch `auto-860`.
- Starting HEAD: `15d587736be088e121c848eadb87454e40ed4844` (verified).
- Supplied develop base: `159fbafe96e65ab14526173a85d360211b3040c2`.
- Initial worktree clean; no incoming changes to salvage.
- Inputs: supplied dispatch-context.json and prior result artifact, repository
  instructions, applicable ADRs, existing soak runner/profile/tests and CI gates.
- Repair file snapshot: this handoff and `quality/vulture-baseline.json` only,
  conditional on the exact requested scanner producing reviewed retained debt.
  No scheduler, authorization, production behavior or gate changes are planned.
- No `check-*.log` files exist in the supplied job-directory listing. Run fresh
  validation rather than relying on earlier claims.

## Assumptions and progress

The explicit CI-repair instruction permits ledger amendments, but does not
permit inventing a release artifact or treating a short historical shakedown as
a long-running RC soak. Production acceptance must remain blocked wherever
current executed evidence is absent. No GitHub mutations will be performed.

Exact requested vulture scan completed successfully (exit 0): 1338 reviewed
identities, 1338 findings, zero unclassified and zero never-allowlist findings.
It selected base `cd5618223cbd` and candidate `15d587736be0`. There is no
unbanked identity to repair; the conditional ledger edit is skipped. Changing
production code or the ledger without a finding would violate this repair brief.

The supplied prior result is BLOCKED, not acceptance proof. The current profile
explicitly identifies its runner as a host-process emulator and records missing
representative workloads.

Fresh validation exit codes: root ruff check 0, root ruff format --check 0,
focused soak-gate/server-rate-limit/server-backpressure pytest 0. The supplied
base resolves; `git diff --check <supplied-base>...HEAD` passes, so the prior EOF
finding does not reproduce. One inspection referenced a nonexistent
`.github/workflows/quality-ratchets.yml` (not found; skipped); actual workflow
references are in `quality.yml`, `ci.yml`, and `vulture-ratchet.yml`.

Architecture review: accepted ADR-085 requires per-principal rate limiting;
accepted ADR-081626-f383 locates execution authority and fencing in the
canonical Attempt/Run store. Proposed ADR-081 cannot waive issue acceptance.
Production middleware still constructs an independent InMemoryRateLimiter per
instance. No competing execution or authorization authority is introduced.
The canonical `Goal -> Graph -> Run -> NodeRun -> Attempt` model is unchanged.

## Executed validation

All commands ran in the assigned worktree, with 1200-second validation timeouts:

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  — PASS; 1338 exact reviewed identities. Arguments match
  `.github/workflows/vulture-ratchet.yml:82-85`.
- `uv run ruff check .` — PASS.
- `uv run ruff format --check .` — PASS; 2943 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_rate_limit.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`
  — PASS; 75 tests in 8.25 seconds. Includes actual production middleware
  counterexamples (both credential classes), fail-closed artifact CLI checks,
  real child-process resource sampling, and the wired task backpressure route.
  These are focused tests, not a deployed production soak.
- `uv run python scripts/check-ratchet-provenance.py` — PASS.
- `uv run python scripts/check-shipped-surface-truth.py` — PASS.
- `uv run python scripts/check-suite-inventory.py` — PASS; 15 suites,
  26365 unique identities, no duplicate evidence.
- `uv run python scripts/check-backlog-consistency.py` — PASS; 168 items.
- `git diff --check 159fbafe96e65ab14526173a85d360211b3040c2...HEAD`
  — PASS before this documentation-only commit.
- Imported the current `scripts/soak/run_soak.py` via `uv run python` and
  evaluated retained `evidence/m3a-round6-shakedown.json`:
  `failed_promotion_checks == ['sustain_duration', 'exact_rc_artifact']`;
  `sustain_seconds == 90.43`, required minimum `14400`.
  `preflight_artifact_check()` returns `ok: false` and
  `topology: host-uvicorn-preflight`.
  The initial diagnostic looked for a top-level/identity git hash and printed
  None; direct file inspection establishes the actual nested
  `hashes.git_head` is `b31c5fdaa63b40506335bbb288889e87bdb9ba0c`, not this HEAD.

Command output is retained locally under `/tmp/issue-860-1482-*.log`; this
committed summary preserves the outcomes. No tests added or modified, so no
inventory-delta note is needed. No ledger/grant edits were warranted.

## Acceptance, checked individually

| #860 criterion | Current evidence and disposition |
| --- | --- |
| Representative RC load profile | UNVERIFIED: profile lines 152-160 explicitly omit multi-user/Workspace, Graph fan-out, successful tool/model, Canvas and Goal workloads; this round does not supply them. |
| At least two production application replicas | UNVERIFIED: existing harness emulates two host processes, not the selected production artifact (profile lines 19-24). |
| Sustained saturation, queue, leases, retries, leaks, restart | UNVERIFIED: retained 90.43-second run fails the duration gate; no long run executed. |
| Exactly-once/fenced physical work and Goal reconciliation | UNVERIFIED: admission probes do not execute the raced schedule Run; profile lines 197-200 explicitly withhold physical-work and Goal claims. |
| Replica-selection-safe rate limiting, security and degraded behavior | NOT MET for non-bypass: passing tests at `tests/test_soak_promotion_gates.py:437-489` observe `[200, 200, 429]` on each independent replica for the same identity. Local limiter and task-backpressure tests pass; full concurrent production behavior is UNVERIFIED. |
| Complete thresholded production telemetry | UNVERIFIED: process-group sampling regression passes but driver loop lag is not application loop lag; worker, pool and long-window observations remain absent. |
| Active-work kill/restart, drain, fencing, recovery | UNVERIFIED: evaluator checks tested; no new production active-work recovery run. |
| Long-running exact RC artifact/configuration | NOT MET: current evaluator rejects retained evidence for both duration and artifact identity; host runner cannot certify Compose. |
| Classify findings to earliest broken invariant | Existing backlog consistency passes; completeness/earliest-invariant classification is UNVERIFIED. No GitHub mutations authorized or performed. |
| Machine/human evidence with exact hashes | Historical files exist, but current RC-bound evidence is UNVERIFIED: retained hash is an older commit and no exact production image/configuration was exercised. |

## Handoff

Verdict: **BLOCKED**, not integration approval. The supplied CI failure did not
reproduce, so no evidence-backed source or ledger repair exists for this round.
No new RC soak is claimed. The known process-local rate policy must be reconciled
with #860's non-bypass requirement without creating a second authorization path.
A selected immutable production RC/config, representative workload and complete
telemetry/fencing probes are prerequisites to a fresh >=4-hour production soak.

Changed file: this handoff only. Progress: `{checked: 1, done: 0, skipped: 0,
errors: 0, next: "resolve production acceptance blockers; select and soak exact RC"}`.
The one assigned issue has been explicitly finalized as blocked; no next issue
was started.
