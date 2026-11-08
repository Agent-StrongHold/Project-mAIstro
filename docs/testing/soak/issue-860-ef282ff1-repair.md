# Issue #860 — bounded CI repair ef282ff1

## Frozen scope

- Assigned issue: #860 only; branch `auto-860`.
- Starting HEAD: `2b61f4bc8a177960645d65912d1d1b199af7fa9f` (verified); working tree clean.
- Supplied base: `b78637f52be33c53d49aca1aa5738e3ab820aad3`.
- Process the supplied schema-fence failure and required exact Vulture scan,
  then validate existing soak promotion/rate evidence. No GitHub mutations.
- Candidate edits are limited to `packages/maistro-core/tests/persistence/test_pg_learnings.py`,
  its inventory note, this report, and `quality/vulture-baseline.json` only if
  the required scan identifies reviewed retained debt. Production schema code
  is read for comparison; no competing execution or authorization path.
- Current job directory contains no `check-*.log`; supplied prior `check-3.log`
  reports 24 executed schema statements versus 21 expected. Prior result is
  BLOCKED, not promotion evidence.

## Ambiguity and assumption

This is a writer CI-repair round, not a verifier-only run. The supplied prior
failure may already be repaired at the assigned HEAD; reproduce before editing.
The broad historical branch/base diff is not a request to process unrelated
issues or reverse existing work. Exact production RC identity/configuration is
not supplied; do not manufacture promotion evidence from local unit tests.

## Results

- Reproduced the supplied schema-test command: **37 passed, 6 skipped**.
  The 24-statement assertion already includes all three Gauntlet audit columns
  at `test_pg_learnings.py:175-177`; the historical failure is not current.
- Required exact Vulture scan: **PASS**, 1332 reviewed identities and findings,
  zero unclassified/forbidden. No ledger amendment is justified.
- No production/test change is supported by either reported CI failure.
  Continue only with focused acceptance checks and report unresolved criteria.
- Focused soak/boot/gitleaks/task-backpressure/rate-limit tests: **104 passed**.
- `uv run ruff check .`: PASS; `uv run ruff format --check .`: PASS
  (3105 files); `uv run python scripts/check-suite-inventory.py`: PASS
  (17 suites, 28182 unique test identities, no duplicate evidence).

## Architecture and acceptance evidence

Read accepted ADR-081226-69ee (canonical execution), ADR-081626-f383 (Attempt
fences), ADR-082526-b36a (renewal/reclamation), ADR-082826-08f0 (recovery
through the canonical lifecycle), and ADR-085 (principal-keyed rate limits).
Later recovery ADRs supersede the older fencing ADR's historical omission of
lease-expiry takeover. Restart alone cannot authorize recovery of a live lease.
No scheduler, Goal store, event authority, or authorization path is changed.

Executed `tests/test_soak_promotion_gates.py:439-488` uses the real middleware
with the same credential/IP on two instances: each independently yields
`[200, 200, 429]`. This falsifies a shared per-principal allowance, but does not
mean all rate/security controls are absent. Production explicitly documents
process-local N-times-limit semantics (`api/rate_limit.py:25-30`) and constructs
one limiter per instance at line 72. Aggregate semantics need reconciliation
with #860's non-bypass requirement, not an ad-hoc second authorization path.

The CLI regression tests at `test_soak_promotion_gates.py:96-121` prove that
otherwise-passing four-hour fixtures cannot pass without exact-artifact proof.
The actual host driver unconditionally reports that limitation at
`scripts/soak/run_soak.py:730-741`. Unit fixtures are not live soak evidence.

## Executed commands

All validation used `uv run` in the assigned worktree with 600–1200 second
command timeouts. No live production stack or sustained load was launched.

- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`
  — 37 passed, 6 skipped (not live PostgreSQL evidence).
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  — PASS; matches `.github/workflows/quality.yml:1013-1016`.
- `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py tests/test_gitleaksignore_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q`
  — 104 passed.
- `uv run ruff check .` and `uv run ruff format --check .` — PASS.
- `uv run python scripts/check-suite-inventory.py` — PASS.
- `uv run python scripts/check-backlog-consistency.py` — PASS, 168 items.
- `uv run python -` imported the current soak evaluator and evaluated preserved
  `evidence/m3a-round6-shakedown.json`: asserted failed gates contain
  `sustain_duration` and `exact_rc_artifact`; observed 90.43 seconds versus
  14400 required, and `preflight_artifact_check()['ok'] is False` — PASS.
- `git diff --check` — PASS.

## Acceptance disposition

| Criterion | Executed evidence / remaining gap |
| --- | --- |
| Representative RC load profile | UNVERIFIED. Profile at `m3a-load-profile.md:153-172` lacks concurrent users/Workspaces, fan-out, successful tool/model calls and Design/Canvas/background-worker coverage. Immutable RC/configuration not designated in dispatch. |
| Two production application replicas | UNVERIFIED live. `deploy/docker-compose.prod.yml:26-76` defines two replicas; the executed ASGI tests do not deploy them. |
| Sustained saturation, queue growth, reclaim, backoff and leaks | UNVERIFIED. Evaluated historical evidence lasts only 90.43 seconds; no sustained production load ran. |
| Fenced/exactly-once physical work and Goal reconciliation | UNVERIFIED. `m3a-load-profile.md:195-204` describes a single occurrence admission followed by cancellation without physical execution. Unit admission success is insufficient. |
| Rate/security/degraded non-bypass by replica selection | NOT MET for a shared principal allowance: executed production middleware tests observe independent allowances. Broader sustained security/degraded behavior remains UNVERIFIED. |
| Full telemetry and explicit pass/fail thresholds | UNVERIFIED. Profile acknowledges driver rather than application loop latency and incomplete pool/reclaim/leak coverage; unit sampler tests are not production telemetry. |
| Active-work kill/restart, drain, fencing and recovery | UNVERIFIED. No live active-Attempt interruption experiment ran. Boot tests do not establish this. |
| Long-running exact RC artifact/configuration | NOT MET by evaluated evidence: duration and artifact gates both fail. Longer host-preflight execution cannot satisfy artifact identity. |
| Findings filed/reclassified before promotion | UNVERIFIED. Backlog consistency passing does not prove filing completeness. No GitHub mutations performed. |
| Hash-bound machine/human production soak evidence | UNVERIFIED. Preserved historical artifacts are not exact-RC acceptance evidence; this report is only a validation handoff. |

## Handoff

**BLOCKED** on production acceptance, not on the supplied stale CI failure.
Only this report changed. No tests added or modified, so no inventory-delta note
is needed. No ledger/grant amendment, policy weakening, speculative code edit,
or unrelated develop sync was performed. Existing branch work is preserved.

Next: designate the immutable RC and representative workload/configuration,
reconcile aggregate rate-budget semantics, and run a production-topology soak
with physical-work/recovery oracles and complete telemetry for at least four
hours. Redispatching the same historical schema failure is not actionable.

Progress: {checked: 1, done: 0, skipped: 0, errors: 0, next: production RC
acceptance prerequisites}. CI validation handoff completed; issue acceptance
remains unresolved. Local commit is required; no integration approval implied.

