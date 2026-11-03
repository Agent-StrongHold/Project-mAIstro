# Issue #860 — cf269d5f repair checkpoint

## Frozen scope

Only issue #860, starting at `fff6cd7feb9f8a1ab96078e573f1bc70ef759d5e`
(base `ab8b3737fa64f8d840f421ef87ca506c509444ff`), in `auto-860`.
No GitHub mutations or develop sync requested by an actual conflict.
Initial worktree is clean. Current job has no `check-*.log` files.

Process the supplied schema-fence failure, then the exact vulture gate,
then focused soak acceptance checks. Candidate edit surfaces are
`packages/maistro-core/tests/persistence/test_pg_learnings.py`,
`packages/maistro-core/src/maistro/persistence/pg_learnings.py`,
`quality/vulture-baseline.json` (only if the executed scan requires it),
a corresponding inventory note, and this report. Existing soak runner/tests,
repository instructions, ADRs and deployment/profile docs are read-only evidence.

The prior check-3.log reports 24 schema statements versus 21 expected.
This is historical evidence, not a current failure until reproduced.
Prior BLOCKED result reports no exact-RC/physical-work soak evidence; verify
that distinction rather than relabeling host probes as production proof.

Ambiguity: dispatch includes writer and verifier instructions. The lane explicitly
assigns repair and requires a local commit; proceed as writer with focused
validation. No RC artifact/configuration is supplied in the lane brief.

## Results

- Historical check-3 failure does not reproduce: `uv run pytest
  packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  **37 passed, 6 skipped**. Lines 173–178 already include the three Gauntlet
  validation columns missing from the historical failure. No test fix needed.
- Exact requested vulture command passed: `uv run python
  scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'`: **1322 reviewed identities / 1322 findings,
  zero unclassified, zero never_allowlist**. No ledger amendment justified.
- Read repository AGENTS.md and accepted ADR-081626-f383 (canonical Attempt
  leases), ADR-083026-a91e (absent measurements), ADR-085 (per-principal limits).
  Preserve canonical execution authority; admission deduplication and absent
  measurements cannot be relabeled physical-work or production-soak proof.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 3301 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py -x -q`: **72 passed**,
  including both authenticated/unauthenticated replica-selection counterexamples
  using production `RateLimitMiddleware` and fail-closed promotion checks.
- `uv run python scripts/check-test-duplicates.py`: passed, 1597 unique files,
  no duplicate groups.
- `git diff --check`: passed.

## Acceptance assessment

These are local checks, not a live production soak. No supplied immutable RC
image/configuration was selected, no new deployment was started, and no new
production results were manufactured. The load profile itself describes the
remaining gaps; running the host preflight longer cannot repair its artifact
mismatch (`scripts/soak/run_soak.py:744`).

| # | Criterion | Current evidence / disposition |
|---|---|---|
| 1 | Representative RC profile | UNVERIFIED. `docs/testing/soak/m3a-load-profile.md` defines preflight traffic but explicitly lacks concurrent Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and Goal-worker coverage. Requires selected RC scope. |
| 2 | At least two production replicas | UNVERIFIED. Host processes/ASGI limiter instances are not the exact Compose deployment. |
| 3 | Sustained saturation/leak/reclaim load | UNVERIFIED. Unit tests validate evidence gates, not observed sustained behavior. |
| 4 | No duplicate physical work | UNVERIFIED. `scripts/soak/run_soak.py:1067` cancels the admission-probe Run; its physical work never executes. |
| 5 | Replica-independent security/rate/degraded enforcement | UNVERIFIED, with counterevidence: `tests/test_soak_promotion_gates.py:439` passes against production middleware, observing `[200, 200, 429]` independently on each replica for the same identity. Local enforcement is not a shared allowance. |
| 6 | Production telemetry and thresholds | UNVERIFIED. Profile distinguishes driver-loop lag from application-loop lag; local checks cannot establish production measurements. |
| 7 | Kill/restart during active work; fencing/recovery | UNVERIFIED. Admission identity and process rejoin alone do not demonstrate physical-work recovery. |
| 8 | Long exact-RC soak | UNVERIFIED. `preflight_artifact_check` always fails exact-RC identity; profile requires at least four hours on the actual promoted artifact/config. |
| 9 | Findings filed/reclassified before promotion | UNVERIFIED. Existing historical findings are not independently proven disposed by these local checks. No GitHub mutation permitted. |
| 10 | Machine/human evidence bound to production hashes | UNVERIFIED. This report is validation evidence only, not an exact-image/config soak pack. |

## Handoff

Verdict: **BLOCKED** on production acceptance, not on the supplied historical
schema failure or vulture debt. Only this report changed; no source/tests,
quality ledger, authorization, scheduler or execution authority changed. No new
tests were added, so no inventory delta is needed. Six database-dependent tests
were skipped; no live PostgreSQL concurrency result is claimed.

Next action requires the selected immutable RC artifact/configuration and a
production-path workload/observer that covers physical Attempts and application
telemetry, plus disposition of replica-local rate allowance semantics. Do not
replay the already-passing schema/vulture repair as a substitute for that work.
The current host-only runner cannot supply promotion proof even with a longer
run. Reconcile those prerequisites before another soak attempt.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0,
next: "resolve exact-RC and production workload prerequisites"}`.
The assigned issue remains unresolved; this commit is a validation handoff only.
