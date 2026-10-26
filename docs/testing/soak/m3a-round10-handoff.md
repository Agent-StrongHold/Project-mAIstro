# #860 repair checkpoint (round 10)

## Frozen scope

Assigned issue: #860 only; worktree `/home/dev/Git/wt/auto-860`, branch
`auto-860`, starting HEAD `078fec6fa69059c8fb3358220f6e06242a90e6ce`,
base `4e7ef1ab1ceb41edb175baa06557ab18f4657162`.

Review snapshot: existing `scripts/soak/run_soak.py`,
`tests/test_soak_promotion_gates.py`, `docs/testing/soak/` evidence and handoffs,
`packages/maistro-server/src/maistro_server/api/rate_limit.py`, adjacent changed
API/persistence tests, and applicable architecture/deployment ADRs. Candidate
edits are limited to demonstrated #860 defects, corresponding tests/inventory
notes, and this handoff. The CI-repair exception permits
`quality/vulture-baseline.json` only if the required check finds actual debt.
No other issues or refs will be processed.

## Initial recorded results

- HEAD resolves exactly to the assignment; `git status --short` is empty.
- No `check-*.log` files are present in the assigned job directory at inspection.
  Driver validation is therefore unavailable, not assumed passing.
- Required vulture command completed successfully: 1402 findings, 1402 reviewed
  identities, zero unclassified/never-allowlist findings. No ledger edit needed.
- Role ambiguity resolved as writer because this is an assigned repair and
  explicitly requires a local commit. No GitHub mutations will be performed.

## Architecture and blocker review

- Read repository `AGENTS.md`/`CLAUDE.md` and accepted ADR-081426-1f7c,
  ADR-081626-f383, ADR-082426-82c7 and ADR-085. Attempt identity/fencing and
  occurrence admission remain owned by the canonical execution spine. Unique
  admission does not prove unique physical work. ADR-081 is Proposed, not an
  accepted waiver of the supported reference topology or issue acceptance.
- Read the supplied prior result: BLOCKED, with no driver checks. The prior H3
  shared-store wording is already retracted in the current evidence pack; no
  duplicate cosmetic repair is justified.
- Inspected production `rate_limit.py`: each middleware instance constructs an
  `InMemoryRateLimiter` and explicitly documents N-times aggregate allowance.
  Replica-selection non-bypass is not proven by six independent burst probes.
- Inspected `deploy/docker-compose.prod.yml`: two application services use a
  local build, not a supplied immutable promotion image. No designated exact RC
  configuration is supplied. Assumption: do not invent a release candidate or
  run a four-hour emulator that explicitly cannot sign promotion evidence.
- Existing profile explicitly lacks concurrent users/Workspaces, Graph fan-out,
  successful tool/model calls, Design/Canvas and Goal workers. Existing evidence
  is historical preflight, not the missing long-running exact-artifact soak.

## Fresh validation

- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q`
  — **102 passed, 5 skipped in 9.14s**. PostgreSQL-dependent skips are not
  credited as live concurrency proof. Production middleware fixtures reproduce
  `[200, 200, 429]` independently on each replica for the same authenticated or
  unauthenticated identity. The real uv-child sampler test observes memory and
  descriptor growth; synthetic admission probes do not prove physical effects.
- `uv run ruff check .` — PASS.
- `uv run ruff format --check .` — PASS, 2624 files.
- `uv run python scripts/check-suite-inventory.py --suite tests/` — PASS,
  4198 collected tests match inventory. No tests added; inventory delta is zero.
- Commands used 1200/1800-second validation timeouts. No live Compose load or new
  soak has been run. Test results cannot replace the missing acceptance evidence.

- `uv run python -` imported the actual driver, evaluated preserved round-6
  JSON, and asserted failures exactly `sustain_duration` and `exact_rc_artifact`:
  PASS. Observed duration is 90.43 seconds versus 14400. The current artifact
  gate is false, topology `host-uvicorn-preflight`. No historical data changed.
- Production reachability confirmed: `maistro_server/main.py:478` installs the
  inspected `RateLimitMiddleware`; independent allowances are not merely an
  unused library behavior.
- `git diff --check` — PASS before final report completion.

## Acceptance disposition

| Criterion | Evidence / remaining gap |
| --- | --- |
| Representative release-candidate profile | PARTIAL: inspected profile defines mix and thresholds, but explicitly lacks users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and Goal workloads. RC applicability UNVERIFIED. |
| At least two application replicas | UNVERIFIED for the exact production artifact. Compose defines two; executed middleware instances and historical host processes are not a production Compose soak. |
| Sustained saturation, growth, reclaim, retries and leak observations | UNVERIFIED. Fresh evaluation rejects the preserved 90.43-second run. No sustained RC run executed. |
| No duplicate physical work / Goal reconciliation | UNVERIFIED. Admission-oracle regression tests pass, but occurrence admission uniqueness is not physical Attempt/effect fencing. Historical schedule probe cancels its queued Run. |
| Rate-limit/security/degraded concurrency non-bypass | NOT MET for a cluster-wide allowance: executed production-middleware tests demonstrate independent allowances after replica selection. Local security/backpressure tests pass; RC degraded behavior UNVERIFIED. |
| Required metrics and explicit pass/fail thresholds | PARTIAL: sampler regressions pass, including a live uv child. Application-loop latency, detached/container workers and sustained pool/queue/lock/leak thresholds remain UNVERIFIED. |
| Kill/restart during active work and fencing/recovery | UNVERIFIED. Historical process-exit/rejoin and unit tests do not prove in-flight physical Attempt drain, fencing or recovery. |
| Long-running exact-RC artifact/configuration soak | BLOCKED: no designated immutable promotion RC/configuration supplied; driver deliberately rejects host preflight even at four hours. Fresh CLI regression tests verify rejection. |
| Findings filed/reclassified to earliest invariant | PARTIAL: existing evidence records local classifications F1–F12. External filing UNVERIFIED; prohibited in this lane. No new defect invented. |
| Hash-tied machine/human evidence | PARTIAL: historical JSON and reports preserved; fresh qualifying exact-RC image/config/commit evidence UNVERIFIED. |

## Handoff and residual risks

**BLOCKED**, not integration approval. Only
`docs/testing/soak/m3a-round10-handoff.md` changes. No production, runtime config,
test or ledger changes are justified by this CI-repair check; existing work is
preserved. No new tests means no inventory-note addition is required.

The unresolved block requires the release owner to designate the immutable RC
artifact/configuration, resolve aggregate rate-limit acceptance with the owning
security/deployment lane, complete production-path workloads and physical-effect
oracles, then execute and publish a new >=4-hour soak. A longer run of the
current emulator cannot resolve it. Missing measurements remain absent, not zero
or inferred passes. No GitHub mutations or background commands were performed.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: designated RC,
production-path evidence and sustained soak}`. CI-repair validation is complete;
#860 acceptance is not. This handoff is committed locally as the writer checkpoint.
