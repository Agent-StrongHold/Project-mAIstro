# Issue #860 — dd1bb6b8 repair checkpoint

## Frozen scope

- Issue: #860 only; writer/CI-repair lane, branch `auto-860`.
- Verified starting HEAD: `2d5888bfcfa046cd9ad14b28bb5bee5982445f6f`.
- Assigned develop base: `30677b185400538df2aab0432c63c02d673f3d0e`.
- Initial worktree clean; no incoming edits to salvage.
- Evidence snapshot: `/home/dev/maistro/jobs/dd1bb6b893dd4967b8f783162370ba22/dispatch-context.json`.
- Fixed inspection scope: issue body/comments and linked PR evidence in that snapshot;
  repository instructions and execution ADRs; `scripts/soak/`,
  `tests/test_soak_promotion_gates.py`, `tests/test_soak_samplers.py`,
  `docs/testing/soak/`, production rate-limit middleware and adjacent tests;
  vulture gate, its CI configuration and ledger, and identities it actually reports.
- Planned writes: this report, plus only evidenced vulture repairs and required
  test/inventory notes if tests change. No unrelated runtime redesign.
- No `check-*.log` files were present in the supplied job-directory listing.
- Prior result was BLOCKED, not a develop-sync conflict. No merge is warranted.

## Assumption and progress

This is the explicitly authorized vulture CI-repair round. Ledger changes are
allowed only for reviewed scanner findings; no guessed debt will be banked.
Promotion acceptance must independently remain blocked unless production evidence
proves every criterion.

First executed results:
- Exact requested vulture command passed: 1,338 findings / 1,338 reviewed identities,
  zero unclassified, zero never-allowlist. There is no evidenced ledger repair.
  Its automatic provenance base is `94781cf6b708`, not the assigned develop base;
  explicit-base verification also passed (see final validation below).
- Assigned develop base resolves; `git diff --check <assigned-base>...HEAD` passed.
  The previously reported EOF whitespace failures do not reproduce.
- Prior report filename guessed from job ID was not found; skipped. The supplied
  prior result JSON was read successfully instead. ADR-111/113 glob matches were
  not found; skipped. Resolve relevant ADR filenames from the documentation index.
- Snapshot issue body and all 24 comments plus linked PR bodies/reviews were read.
  They supply no current passing RC soak evidence.
- `uv run ruff check .` passed; `uv run ruff format --check .` passed (2,920 files).
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_rate_limit.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`
  passed: 75 tests, including both authenticated/unauthenticated replica-selection
  counterexamples, production-middleware probes and real `uv` child sampling.
- `uv run python scripts/check-backlog-consistency.py` passed: 168 items.
- `tests/test_soak_samplers.py` was a scope assumption, not a resolved file;
  sampler tests are in `tests/test_soak_promotion_gates.py` and were executed.

## Architecture reconciliation

Read ADR-032 (Accepted), ADR-081 (Proposed), ADR-085 (Accepted),
ADR-081226-a66b (Accepted) and ADR-081626-f383 (Accepted). ADR-081 is not an accepted waiver of #860's
production-topology requirement. Attempt leases/fencing belong to the canonical
Run store, not the soak driver. No scheduler, store, execution authority, event
owner or authorization path was introduced. Rate limiting uses the existing
canonical principal resolver, but `RateLimitMiddleware` explicitly allocates an
`InMemoryRateLimiter` per instance; `main.py:593` wires it into the shipping app.
Passing local enforcement is not proof of a cluster-wide allowance. No accepted
ADR read here waives the issue's replica-selection criterion.

## Final executed validation

- `RATCHET_BASE_REV=30677b185400538df2aab0432c63c02d673f3d0e uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  passed, again 1,338 reviewed identities / findings. The reported trusted base
  `94781cf6b708` is correct: `git merge-base HEAD <assigned-base>` independently
  returned `94781cf6b708a385f33a9aafcbe9f83a481b6858`. No ledger changes needed.
- `uv run python scripts/check-ratchet-provenance.py` passed, 49 quality JSON
  consumers have explicit provenance. Existing SyntaxWarning did not fail it.
- `uv run python scripts/check-suite-inventory.py` passed: 14 suites, 26,020
  unique test identities, zero copied-file duplicate evidence. No tests added
  or changed in this round, so no inventory-delta note is required.
- `uv run pytest packages/maistro-server/tests -x -q` passed: 495 passed,
  8 skipped, 22 existing Starlette deprecation warnings. Skips are not evidence.
- Executed an inline `uv run python` import of the current soak evaluator on
  `evidence/m3a-round6-shakedown.json`: asserted failures exactly
  `sustain_duration` and `exact_rc_artifact`, 90.43 < 14,400 seconds, and the
  current driver's artifact check is false. Recorded head is
  `b31c5fdaa63b40506335bbb288889e87bdb9ba0c`, not this lane's assigned head.
  Historical functional booleans are not revalidated physical-work evidence.

## Acceptance matrix (all ten issue criteria)

| Criterion | Current evidence and disposition |
|---|---|
| Representative profile | PARTIAL: profile exists, but `m3a-load-profile.md:152-166` explicitly omits concurrent users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas and Goal/background work. Representative RC workload UNVERIFIED. |
| At least two production replicas | UNVERIFIED: `run_soak.py:635-647` labels its boot path host-uvicorn preflight, not exact production Compose; no RC replicas were deployed this round. |
| Sustained saturation/reclaim/retry/leak observations | UNVERIFIED: current evaluator rejects historical 90.43-second run against 14,400-second floor. Local sampler regression tests passed but do not observe sustained production behavior. |
| No duplicated physical work across replicas | UNVERIFIED: historical schedule probe creates one Run then cancels it (`m3a-round6-shakedown.json:12-15`); admission uniqueness does not prove physical Attempt fencing or Goal reconciliation. |
| Security/degraded behavior and replica-selection non-bypass | NOT MET: executed authenticated and unauthenticated production-middleware counterexamples (`test_soak_promotion_gates.py:439-488`) receive `[200, 200, 429]` independently on each replica for the same identity. Local security tests are not a sustained RC proof. |
| Complete telemetry and explicit thresholds | PARTIAL: process-group sampler regression passes, but production application-loop lag, worker coverage and long-window pool/lock/leak/error measurements remain UNVERIFIED (`m3a-load-profile.md:158-166`). |
| Active-work replica kill/restart recovery | UNVERIFIED: historical process exit/rejoin lacks correlated in-flight physical-work/fence/recovery evidence. No current RC fault injection executed. |
| Long soak of exact RC configuration | NOT MET: current evaluator rejects both duration and artifact; even a longer host-process run cannot satisfy `exact_rc_artifact`. |
| Findings filed/reclassified to earliest invariant | PARTIAL: existing human evidence records findings and backlog consistency passes. Completeness of filing/reclassification remains UNVERIFIED; no GitHub mutation permitted or performed. |
| Published machine/human evidence bound to exact hashes | PARTIAL: historical JSON and Markdown exist, but their head is not the assigned head and lacks promoted application-image/config identity. Current RC evidence UNVERIFIED. |

## Disposition and handoff

**BLOCKED**, not promotion-ready. Changed file this round: this report only.
There is no reproduced vulture or whitespace failure to repair; cosmetic source
changes or invented ledger amendments would not address acceptance. Existing
runtime/tests/evidence are preserved. No gates weakened, no new authority added,
no services disturbed, no GitHub writes performed.

Required next work: select the immutable RC image/configuration and representative
workload; resolve the replica-wide rate-budget requirement through the existing
security owner (not a second auth path); instrument physical Attempt fencing,
reconciliation and application telemetry; execute and publish an exact-artifact
soak of at least four hours with active-work kill/restart and complete hashes.
Do not send another vulture-only retry expecting it to establish these facts.

Checkpoint summary: checked 1 assigned issue; done 0 acceptance completions;
skipped 0 assigned issues; errors 0 validation failures. Missing guessed paths
above were explicitly skipped, not treated as passing evidence. Local commit
contains this bounded validation/handoff, not an implementation-completion claim.

