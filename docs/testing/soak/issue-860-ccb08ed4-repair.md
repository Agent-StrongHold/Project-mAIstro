# Issue #860 — ccb08ed4 repair checkpoint

## Frozen scope

- Only issue #860; worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Starting head `56cda08f6f764a014972e8d0c99f74f0a05cfdf1`; supplied base
  `435dc1937e0407ab4de198ffcced49860bb14ad2`. Starting worktree clean.
- Inputs: supplied dispatch-context.json, previous result 65572f1a, and reported
  failed check `/home/dev/maistro/jobs/98a11313167b41a98a420abfda80c292/check-3.log`.
- Inspection/validation surfaces: repository instructions, relevant execution and
  deployment ADRs, `scripts/soak/`, `tests/test_soak_promotion_gates.py`,
  production middleware and adjacent tests, existing soak load profile/evidence,
  `scripts/check-vulture-baseline.py`, `quality/vulture-baseline.json`, CI gates.
- Planned write surface: this report; ledger only if the requested exact scan
  demonstrates reviewed retained identities requiring amendment. No speculative
  production changes, gate weakening, or unrelated issue work.

## Initial results / assumptions

No check-*.log files were present in the supplied job directory at startup.
The prior result reports BLOCKED, not a merge conflict. Its claims will be
rechecked, not treated as fresh validation. An exact RC artifact/configuration
has not been identified in the dispatch; local preflight cannot substitute for
release-owner-selected RC evidence. No remote mutations are permitted.

## Executed validation (checkpoint)

- Requested exact vulture scan: PASS, 1323 findings / reviewed identities,
  zero unclassified; gate selected trusted base `4aa68edc0b6b`. No ledger
  amendment is justified by this scan.
- Read the supplied historical check-3.log: expected 21 schema DDL statements
  versus 24 observed. Fresh targeted execution does not reproduce it:
  `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py
  tests/test_soak_promotion_gates.py
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py
  -x -q -rs` -> 103 passed, 6 skipped (MAISTRO_TEST_PG_DSN unset).
- Logs: `/tmp/860-ccb08ed4-vulture.log`, `/tmp/860-ccb08ed4-pytest.log`.

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3270 files.
- `uv run python scripts/check-deployment-claims.py`: PASS.
- `uv run python scripts/check-execution-lifecycles.py`: PASS, 19 classified /
  discovered lifecycles. Gate commands checked against CI workflows.
- Gate log: `/tmp/860-ccb08ed4-gates.log`.

## Architecture and acceptance review

Read repository instructions, `docs/README.md`, ADR-081 (Proposed), ADR-085,
ADR-081426-1f7c and ADR-082526-b36a (Accepted). Preserve
`Goal -> Graph -> Run -> NodeRun -> Attempt`: physical execution identity is
Attempt, not admission receipt. Lease renewal/reclamation already has a canonical
contract; missing soak observations do not justify a second recovery authority.
Principal-keyed rate limiting in ADR-085 does not prove a shared replica budget.
No ADR or acceptance requirement was rewritten to make the existing probes pass.

| Issue acceptance criterion | Fresh evidence / disposition |
| --- | --- |
| Representative RC load profile | UNVERIFIED. `m3a-load-profile.md` explicitly lacks concurrent users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas and sustained Goal/background activity; no selected RC applicability decision supplied. |
| Two application replicas | UNVERIFIED for deployed RC. Tests use real middleware instances, not two promoted images. |
| Sustained saturation, queue/reclaim, retry, memory/descriptor/process leak observations | UNVERIFIED. No long-running production window executed this round. |
| No duplicate physical work across replicas | UNVERIFIED. Admission receipts are not physical Attempt effects; passing probe tests cannot establish this criterion. |
| Rate/security/degraded enforcement cannot be bypassed by replica selection | Aggregate-budget claim falsified: executed `tests/test_soak_promotion_gates.py:439` gives the same authenticated or unauthenticated identity `[200, 200, 429]` independently on each middleware instance. `api/rate_limit.py:94` constructs the process-local limiter. Other load security properties UNVERIFIED. |
| Complete required metrics with explicit thresholds | UNVERIFIED at RC grade. Process sampler tests pass, but driver-loop latency is not application-loop latency; profile names missing worker/pool and long-window observations. |
| Active-work kill/restart, graceful drain/fencing/recovery | UNVERIFIED. No deployed RC replica restarted here; terminal Run counts cannot prove physical effects. |
| Long-running exact RC artifact/configuration | UNVERIFIED / BLOCKED. No designated immutable RC/configuration supplied. `scripts/soak/run_soak.py:730` always rejects its host-process preflight as exact RC; executed CLI regression tests preserve that rejection. |
| Findings filed/reclassified before promotion | UNVERIFIED externally. Local blockers recorded here; GitHub mutations prohibited. |
| Published machine/human evidence tied to exact image/package/commit/config hashes | UNVERIFIED for RC. This report records validation only, not a promotion soak. |

## Handoff

BLOCKED, not an integration approval. Exact vulture and the historical failed
schema-fence test both pass now; neither justifies speculative source/ledger
changes. Only this report changes. No tests added/modified: inventory delta zero,
so no new inventory note. Six live PostgreSQL tests were skipped, not passed.

Next required input is a designated immutable RC/configuration and approved
representative workload, plus resolution of the aggregate rate-limit acceptance
mismatch. A production-topology run must correlate physical Attempt effects and
capture the missing metrics before the four-hour window can sign promotion.
Do not repeat this ledger-repair lane without a fresh failing scan or new RC
inputs. Existing work is preserved; no remote mutations or issue closure.

Progress: checked 1 issue, done 0 acceptance-complete issues, skipped 0 issues,
errors 0 executed validation commands. Commit of this report is the checkpoint.
