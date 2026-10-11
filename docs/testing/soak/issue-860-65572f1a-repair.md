# Issue #860 — repair checkpoint (65572f1a)

## Frozen scope

- Worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Starting head `9a1f195cd7cae796c9bc59bf75440f9fb6fa9005`;
  supplied develop base `435dc1937e0407ab4de198ffcced49860bb14ad2`.
- Only issue #860; dispatch snapshot supplied with this job. No GitHub mutations.
- Candidate edits: this evidence note and, only for observed retained/dead
  identities in the requested scan, `quality/vulture-baseline.json` and the
  directly implicated source/tests (with an inventory note for test additions).
- Existing worktree was clean. No salvage required.
- Current job directory has no `check-*.log` files. Prior result reports BLOCKED;
  this is not treated as fresh validation.

## Assumption and stopping boundary

This is a bounded CI-repair round, not authority to designate an RC or change
production rate-limiting architecture. Execute the exact requested vulture
scan first. Validate the existing soak guards and production-adjacent tests.
Do not label preflight or historical artifacts as an exact-RC soak.

## Results

- Exact requested vulture scan: PASS, 1323 findings / 1323 reviewed identities,
  zero unclassified. Gate chose trusted base `4aa68edc0b6b`. There are no
  observed unbanked identities to amend; no ledger change is justified.
- Read historical `98a11313/check-3.log`: schema-fence test expected 21 DDL
  statements but saw 24. Fresh execution does not reproduce the failure:
  `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py
  -x -q -rs`: 37 passed, 6 skipped (no `MAISTRO_TEST_PG_DSN`).
- `uv run pytest tests/test_soak_promotion_gates.py
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py
  -x -q -rs`: 66 passed, including real middleware allowance and child-process
  sampling tests. Not a deployed soak.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3270 files.
- `uv run python scripts/check-deployment-claims.py`: PASS.
- `uv run python scripts/check-execution-lifecycles.py`: PASS, 19 classified /
  19 discovered lifecycles. Gate names checked against workflows.
- `git diff --check`: PASS.
- Executed an import/replay of `failed_promotion_checks` against
  `evidence/m3a-round43-shakedown.json`: asserted rejection on
  `sustain_duration` and `exact_rc_artifact`; recorded duration 420.09 seconds
  versus required 14400. Asserted current `preflight_artifact_check().ok` is
  false. This checks rejection, not the historical measurements' validity.

## Architecture reconciliation

Read repository instructions, documentation authority hierarchy, ADR-081
(Proposed), ADR-085, ADR-081426-1f7c, ADR-081626-f383 and ADR-082526-b36a
(Accepted). Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`; physical
execution identity is the Attempt, not an admission receipt.

Correction to the prior handoff's incomplete lease framing: the original
lease ADR deferred takeover, but accepted ADR-082526-b36a subsequently defines
TTL renewal and expired-Attempt reclamation through the canonical store and
execution service. Therefore missing soak coverage is not evidence of a
missing reclamation contract, nor permission to introduce a second authority.
ADR-085's principal-keyed requirement does not waive the issue's stronger
replica-selection criterion. Production middleware explicitly documents local
scope and creates `InMemoryRateLimiter` at `api/rate_limit.py:94`; it is wired
at `maistro_server/main.py:648`.

## Acceptance matrix

| Criterion | Fresh evidence / disposition |
| --- | --- |
| Representative RC profile | UNVERIFIED. Read `m3a-load-profile.md`: one API key; missing user/Workspace population, Graph fan-out, successful tools/models, Canvas and sustained Goal/background traffic. These gaps require an RC applicability decision. |
| Two application replicas | UNVERIFIED for deployed RC. Passing tests instantiate two real middleware instances, not two promoted images. |
| Sustained saturation, queue growth, reclaim, retries and leaks | UNVERIFIED. Historical JSON fails the current four-hour gate; no long-running production window executed here. |
| No duplicate physical work | UNVERIFIED. Admission identity/probe tests pass but cannot establish physical Attempt effects or reconciliation under sustained load. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | Aggregate per-identity allowance claim falsified by executed `tests/test_soak_promotion_gates.py:439`: both authenticated and unauthenticated identities receive `[200, 200, 429]` on each replica independently. Other production-load security properties UNVERIFIED. |
| Required metrics and explicit thresholds | UNVERIFIED at promotion grade. Child-process sampler tests pass; profile still lacks application-loop, worker/pool saturation and long-window evidence. |
| Active-work replica restart/drain/fencing/recovery | UNVERIFIED. No deployed replica killed/restarted this round. Terminal Run counts alone cannot prove physical-work recovery. |
| Long-running exact RC/config | BLOCKED / UNVERIFIED. Assignment supplies no designated immutable RC/config; current runner explicitly rejects host preflight as exact RC at `scripts/soak/run_soak.py:730`, verified by CLI regression tests. |
| Findings filed/reclassified before promotion | UNVERIFIED externally. Local findings recorded; GitHub mutation is prohibited. |
| Published machine/human evidence tied to exact hashes | UNVERIFIED for RC. Historical JSON is rejected; this report is validation evidence, not promotion evidence. |

## Handoff

Only this report changed. No source, tests, gates, grants or ledger edits were
justified by the executed CI checks. No tests added/modified; inventory delta
is zero and no new inventory note is required. Six live PostgreSQL tests
remain skipped; passing unit/probe tests do not satisfy the soak acceptance.

Verdict: BLOCKED. Next: designate immutable RC and runtime configuration,
resolve the aggregate rate-allowance acceptance mismatch, and provide an
exact-topology workload with physical Attempt correlation and application
metrics before running/publishing the sustained window. Do not redispatch a
vulture-ledger repair without a new failing scan: this scan is already clean.
No integration approval, remote mutations or issue closure.

Progress: checked 1 issue; done 0 acceptance-complete issues; skipped 0 issues;
errors 0 validation commands. Local report commit is the checkpoint.
