# Issue #860 — focused CI repair (38e30d12)

## Frozen scope

- Assigned issue: #860 only; branch `auto-860`.
- Starting HEAD verified: `f96cc67b63b9a7db0c6c7caeece1f9e67aa53adf`.
- Supplied develop base: `9a5eb7ba630cf8cb37ba7868f07fa410445bb674`.
- Initial worktree clean; no incoming edits to salvage.
- Process the supplied dispatch snapshot only; no GitHub mutations or ref refresh.
- Repair surface: actual findings from the exact vulture command, reviewed
  source identities and `quality/vulture-baseline.json` if needed; adjacent
  tests/inventory notes only if behavior changes; this validation record.
- Existing soak harness/evidence, repository instructions, ADRs and CI workflow
  are read-only context unless a demonstrated finding requires a scoped repair.
- Assumption: explicit CI-repair authorization permits only evidence-based
  vulture ledger reconciliation, not weakening promotion gates or manufacturing
  missing multi-hour production evidence.
- No `check-*.log` files were present in the supplied job directory at start.

## Results

- Exact requested vulture scan executed successfully (exit 0): 1,338 findings,
  1,338 reviewed identities, zero unclassified and zero never-allowlist findings.
  Output: `/tmp/860-38e30d12-vulture.log`. No unbanked identity exists to repair;
  changing the ledger would be unjustified. No ledger/source changes planned.
- Prior result `bce4cc9d.../result.json` read: BLOCKED, not an approval. Its
  acceptance claims will be checked against current source and focused tests.
- Dispatch issue body requires ten acceptance surfaces, including a long exact-RC
  run and replica-selection non-bypass; existing documentation explicitly calls
  the current runner a host-process preflight, not a promotion runner.

- `git diff --check 9a5eb7ba630cf8cb37ba7868f07fa410445bb674...HEAD`:
  exit 0; prior whitespace failure does not reproduce against the supplied base.
- `uv run ruff check .`: exit 0.
- `uv run ruff format --check .`: exit 0, 2,920 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py
  packages/maistro-server/tests/api/test_rate_limit.py -x -q`: exit 0,
  **74 passed**. This includes the real production middleware's independent
  replica allowances, incomplete topology rejection, fail-closed artifact CLI,
  receipt validation and a real Linux child-process resource sampler.
- Repeated the exact vulture scan with
  `RATCHET_BASE_REV=9a5eb7ba630cf8cb37ba7868f07fa410445bb674`: exit 0;
  resolver reports merge-base `94781cf6b708`, 1,338 reviewed identities matched.
  This is an explicit base-context check, not a claim about a future merge.

## Architectural reconciliation

Read repository instructions and ADR-081 (Proposed), ADR-085 (Accepted),
ADR-081226-a66b (Accepted), and ADR-081626-f383 (Accepted). The accepted lifecycle
keeps physical work under canonical Run/NodeRun/Attempt ownership. Fencing ADR
explicitly does not yet define expiry takeover: the issue's lease-reclaim request
cannot justify a competing scheduler or invented reclaim authority. ADR-085's
per-principal rate limiting does not prove cluster-wide enforcement. No accepted
ADR waives the issue's exact-artifact or physical-work evidence requirements.
No runtime, authorization, lifecycle or gate changes were made.

## Additional validation

- `uv run python scripts/check-suite-inventory.py`: exit 0, all 14 suites
  match; 26,020 unique identities, no copied-test duplicate evidence.
- `uv run python scripts/check-backlog-consistency.py`: exit 0, 168 items.
- `RATCHET_BASE_REV=9a5eb7ba630cf8cb37ba7868f07fa410445bb674 uv run python
  scripts/check-ratchet-provenance.py`: exit 0, 49 consumers covered.
- `uv run python scripts/check-shipped-surface-truth.py`: exit 0.
- Imported the current `scripts/soak/run_soak.py` evaluator and asserted that
  historical `evidence/m3a-round6-shakedown.json` returns exactly
  `['sustain_duration', 'exact_rc_artifact']`: exit 0. Recorded 90.43 seconds
  versus the 14,400-second minimum, historical HEAD `b31c5fdaa63b...`, and
  current preflight artifact check `ok=false`. This is rejection evidence,
  not a newly executed soak. Output: `/tmp/860-38e30d12-evidence.log`.
- One source-path lookup (`maistro_server/app.py`) was not found; skipped.
  Directory-scoped lookup located actual production wiring in
  `packages/maistro-server/src/maistro_server/main.py:57,593`, where the
  tested `RateLimitMiddleware` is imported and installed.
- Other command output is retained locally as `/tmp/860-38e30d12-*.log`.
  No services were started and no production soak was executed.

## Acceptance audit (all ten issue criteria)

| Criterion | Current evidence and verdict |
| --- | --- |
| Representative RC load profile | PARTIAL: `m3a-load-profile.md:46-103` defines mix and phases; `:152-166` explicitly lacks user/Workspace population, Graph/tool/Canvas and background-work coverage. Complete representative RC profile UNVERIFIED. |
| At least two application replicas | Production Compose claims two replicas (`deploy/docker-compose.prod.yml:3-4`); historical JSON has two process records, but current exact-RC execution UNVERIFIED. |
| Sustained saturation, growth, reclaim, retries and leaks | Historical JSON `:163-165,221-224` records 90.43 seconds against 14,400. Long-window observations UNVERIFIED. |
| No duplicated physical work; Goal reconciliation | Admission-only historical schedule probe cancels the queued Run (`evidence/m3a-round6-shakedown.json:11-15`). Receipt-oracle tests pass, but physical Attempt fencing and sustained Goal reconciliation UNVERIFIED. |
| Concurrency/security/degraded non-bypass | NOT MET for replica-selection allowance: `tests/test_soak_promotion_gates.py:439-488` passes the counterexample with real production middleware, both authenticated and unauthenticated. `rate_limit.py:25-30,72-76` intentionally uses process-local state. Local enforcement is not a shared budget. Full RC security/degraded behavior UNVERIFIED. |
| Required telemetry and pass/fail thresholds | PARTIAL: profile thresholds exist; real child-process sampler test passes. Application event-loop latency, worker census and long-window RC measurements remain UNVERIFIED (`m3a-load-profile.md:157-166`). |
| Kill/restart with physical-work drain/fencing/recovery | Historical JSON has process exit/rejoin, but no current live proof of in-flight Attempt recovery. UNVERIFIED; terminal Run counts are insufficient. |
| Long soak of exact RC artifact/config | NOT MET: current evaluator rejects historical evidence for duration and artifact; `run_soak.py:635-647` intentionally rejects host-uvicorn artifact equivalence. |
| Findings filed/reclassified before promotion | Local evidence pack contains classified findings; backlog consistency passes. External filing completeness UNVERIFIED. No GitHub mutation is authorized or performed. |
| Publish hash-bound machine/human evidence | Historical JSON and human pack exist, with historical hashes. Current RC image/config/hash-bound production evidence UNVERIFIED. |

## Handoff

**BLOCKED for #860 acceptance.** The requested exact-debt-ledger failure does not
reproduce; no source or ledger fix is warranted. Only this report changed. No
new tests were added, so no inventory delta note is required; the existing
inventory gate passes. Do not repeat short preflight runs as a substitute for a
promotion soak. Next work requires a selected immutable RC image/config, a
production-topology runner covering the omitted acceptance surfaces, resolution
of the replica-selection enforcement mismatch, and a fresh >=4-hour run with
physical-work recovery evidence. Preserve the current fail-closed gates.

Checkpoint: checked 1 assigned issue, done 1 bounded CI diagnosis, skipped 0
assigned items, errors 0 validation commands (one missing-path lookup recorded
above); issue completion remains blocked. Commit this report locally; no push,
PR, issue closure, policy change, or integration approval.

