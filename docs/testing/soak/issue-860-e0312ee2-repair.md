# Issue #860 — e0312ee2 repair checkpoint

## Frozen scope

- Only assigned issue #860 and its explicit exact-debt-ledger CI repair.
- Worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`, starting HEAD
  `841ae51c69deb8a0d2e1c8df9a18c21b198a940c`; initial worktree clean.
- Supplied base: `9522eb57d072e56211d2833671e1a5d91de8909c` (verify before use).
- Inspection scope: repository instructions, applicable execution/scheduling/
  security/deployment ADRs, existing production topology and rate limiter,
  existing soak runner/evidence and adjacent regression tests, exact gate.
- Edit scope: this handoff; production/ledger changes only if the mandated
  scan or focused validation demonstrates a repairable defect. No speculative
  debt banking or changes to historical raw evidence.
- Initial job-directory snapshot contains no `check-*.log` files. Driver
  results are unavailable, not green by assumption. Prior result was read;
  its BLOCKED verdict is not fresh validation.
- Ambiguity: brief requires ledger amendment without identifying a failing
  identity. Use the actual requested scan to determine whether amendment is
  warranted. The previous block describes acceptance gaps, not a sync conflict.

## First validation checkpoint

- Supplied base resolves to the exact commit above.
- Requested vulture command PASS: 1342 findings / 1342 reviewed identities,
  zero unclassified and zero never-allowlist findings. Its provenance baseline
  is `cfb6c3b64714`; candidate is starting HEAD. No unbanked identity exists
  to repair or retain, so no ledger amendment is justified.
- Production `RateLimitMiddleware` instantiates an `InMemoryRateLimiter` per
  middleware instance. Its documented N-times aggregate allowance contradicts
  replica-selection non-bypass; this is not a shared-store implementation.
- Production Compose declares two server services, PostgreSQL primary/replica,
  Redis and shared storage and requires an external model gateway. Existing
  host-process preflight does not execute this exact artifact.
- Accepted ADR-081626-f383 requires canonical Attempt leases and stale-writer
  rejection; admission identity alone cannot prove physical-work fencing.
  Accepted ADR-085 requires principal-keyed limits but does not establish a
  shared store. Neither waives #860 acceptance. Preserve canonical
  Goal → Graph → Run → NodeRun → Attempt; no alternate authority introduced.

## Executed validation

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 2857 files already formatted.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py -x -q -rs`:
  **80 passed, 5 skipped**. Live PostgreSQL tests require `MAISTRO_TEST_PG_DSN`;
  no live database proof is claimed. Passing tests exercise the production
  task backpressure router, production limiter, fail-closed CLI and live child
  process sampler, not a multi-replica production soak.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`:
  PASS as above; matches `.github/workflows/vulture-ratchet.yml:82-86`.
- `uv run python scripts/check-ratchet-provenance.py`: PASS, 47 quality JSON
  consumers checked, including delegated gates.
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- Inline `uv run python` imported the actual soak runner and evaluated unchanged
  `evidence/m3a-round6-shakedown.json`: asserted failed checks equal
  `['sustain_duration', 'exact_rc_artifact']`. PASS. Recorded duration is
  90.43 seconds versus 14400 minimum; current artifact check is false with
  topology `host-uvicorn-preflight`.

## Acceptance disposition

| #860 criterion | Executed evidence / remaining gap |
|---|---|
| Representative RC load profile | **UNVERIFIED**: `m3a-load-profile.md` has an explicit preflight mix and gap list, not representative users/Workspaces, fan-out, successful tools/models, Design/Canvas and background-worker traffic. |
| Two application replicas | **UNVERIFIED for RC**: inspected Compose declares two services; middleware tests use two in-process instances, not two running RC containers. |
| Sustained saturation, queue growth, reclaim, retry, leaks and shutdown | **UNVERIFIED**: executed evaluator rejects the 90.43-second shakedown. Historical wrapper-only memory/FD observations are invalid as application evidence. |
| No duplicate physical work / Goal reconciliation | **UNVERIFIED**: `run_soak.py:947-974` cancels the admitted schedule probe Run without execution. Canonical admission uniqueness does not establish physical Attempt fencing or sustained Goal reconciliation. |
| Rate limiting/security/degraded non-bypass | **NOT MET** for replica selection: executed `test_replica_selection_has_an_independent_production_allowance` returns `[200, 200, 429]` on each instance for the same authenticated/unauthenticated identity. Other security/degraded claims remain **UNVERIFIED under RC load**. |
| Complete telemetry and explicit thresholds | **UNVERIFIED**: profile has partial metrics/thresholds, not complete application-loop/worker/pool saturation/lease observations. Live child-sampling test passes but is not a long-window leak observation. |
| Active-work kill/restart/drain/fencing/recovery | **UNVERIFIED**: historical process exit/rejoin does not correlate physical effects across Attempt recovery. |
| Long-running exact RC soak | **NOT MET**: executed evaluator rejects duration and artifact. No immutable RC image/configuration is selected by this assignment; existing runner cannot certify Compose at any duration. |
| Findings filed/reclassified to earliest invariant | Local F1–F12 classifications inspected; external filing **UNVERIFIED**. GitHub mutations are prohibited in this lane. |
| Hash-bound machine/human RC evidence | Historical JSON/Markdown exists; **UNVERIFIED for exact RC**. No new soak or image/config-bound RC evidence produced. |

Accepted ADR-082426-82c7 governs occurrence-keyed Run admission, not physical
execution uniqueness. ADR-081 deployment guidance is Proposed, not an accepted
waiver. The prior incorrect shared-limiter-store statement is already corrected
in `m3a-soak-evidence.md:171`; no duplicate cosmetic repair is needed.

## Handoff — BLOCKED

Only this validation record changes. No source, ledger or historical raw evidence
was changed; tests added/removed: zero (no inventory note required). Green static
checks do not resolve the previous acceptance block. No merge conflict exists.

Next: select immutable RC images/config/provider topology, complete representative
production-path workloads and physical-effect/telemetry oracles, resolve the
replica-selection enforcement mismatch, then run that exact artifact for at least
four hours with active-work recovery observations. Code/runtime-config changes
require another soak. Do not rerun host preflight as a substitute or fabricate
ledger debt to satisfy the CI-repair wording.

Progress: checked 1, done 0, skipped 0, errors 0; one blocked issue, validation
handoff complete. Commit this record locally; no push or GitHub mutation.
