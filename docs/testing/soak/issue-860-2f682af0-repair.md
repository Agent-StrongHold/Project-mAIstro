# Issue #860 — bounded CI repair (2f682af0)

## Frozen scope

- Only issue #860, branch `auto-860`, starting HEAD
  `fd2466ab80ec1e21cb8f8271795c64491ba9f8b4`, supplied base
  `435dc1937e0407ab4de198ffcced49860bb14ad2`.
- Initial worktree clean; no incoming uncommitted work to salvage.
- Process the supplied vulture CI failure and current soak acceptance evidence.
  Candidate edit files: this report and `quality/vulture-baseline.json` only if
  the required fresh scanner identifies reviewed retained debt. No speculative
  production changes, unrelated repairs, GitHub mutations, or ledger grants.
- Read-only inspection: supplied dispatch/prior artifacts, repository instructions,
  relevant ADRs, soak runner/profile/tests, production limiter, vulture gate and CI.
- Current job directory contains no `check-*.log`; supplied prior check-3 log exists.
- Assumption: this is a writer repair, not the read-only verifier role. An exact
  RC cannot be inferred from branch HEAD; inspect supplied evidence for designation.

## Progress

Starting refs verified. Fresh requested vulture scan PASS: 1323 findings,
1323 reviewed identities, zero unclassified/forbidden; selected trusted base
`4aa68edc0b6b`. No ledger amendment warranted.

The supplied check-3 log is a historical schema-fence assertion failure
(24 DDL statements versus 21 expected), not a vulture failure. Fresh command:

`uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`

Result: **103 passed, 6 skipped in 2.63s**. Historical failure does not reproduce.
Production middleware tests demonstrate separate allowances on each replica for
both authenticated and unauthenticated identities. These tests are not deployed
RC or sustained-load evidence. No test additions; inventory delta zero.

Additional executed commands (all PASS):

- `uv run ruff check .`
- `uv run ruff format --check .` — 3270 files already formatted.
- `uv run python scripts/check-deployment-claims.py`
- `uv run python scripts/check-execution-lifecycles.py` — 19 classified/discovered.

CI argument forms checked in `.github/workflows/ci.yml`, `quality.yml`, and
`vulture-ratchet.yml`. No gate weakening or ledger amendment. Six skipped tests
are not successful PostgreSQL integration evidence.

## Architecture and acceptance

Read repository instructions, documentation authority map, ADR-081 (Proposed),
ADR-085 (Accepted), ADR-081426-1f7c (Accepted), and ADR-082526-b36a (Accepted).
Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`; physical execution identity
is Attempt. Admission uniqueness is not physical-work uniqueness. Lease renewal
and reclamation remain canonical lifecycle responsibilities. ADR-085 principal
keying does not establish a shared replica budget. No competing authority added.

| Issue acceptance criterion | Fresh evidence / remaining gap |
| --- | --- |
| Representative RC load profile | **UNVERIFIED**. `m3a-load-profile.md:152` explicitly lists absent concurrent users/Workspaces, fan-out, successful tool/model, Design/Canvas and Goal/background reconciliation traffic. Applicability to a designated RC is not established. |
| At least two application replicas | **UNVERIFIED for deployed RC**. Tests exercise two production middleware instances, not two immutable promoted images. |
| Sustained saturation, queue growth, reclaim, retries, leaks and shutdown | **UNVERIFIED**. No long-running production soak executed this round; targeted tests cannot substitute. |
| No duplicate physical work | **UNVERIFIED**. Admission/receipt tests do not observe Attempt-side physical effects under replica contention. |
| Rate/security/degraded behavior non-bypass | **Aggregate allowance claim falsified**: executed `tests/test_soak_promotion_gates.py:439` observes `[200, 200, 429]` independently on both middleware instances for the same authenticated/unauthenticated identity. `packages/maistro-server/src/maistro_server/api/rate_limit.py:93` constructs the local limiter. Backpressure tests pass; broader concurrent security acceptance **UNVERIFIED**. |
| Required metrics and explicit thresholds | **UNVERIFIED at RC grade**. Profile has thresholds, but required application event-loop, pool/worker/reclaim and long-window observations are incomplete. Driver-loop lag is not application-loop lag. |
| Active-work replica restart, drain/fencing/recovery | **UNVERIFIED**. No production restart executed; boot-cleanup tests are not physical-work recovery evidence. |
| Long-running exact RC/configuration, repeated after changes | **UNVERIFIED / BLOCKED**. No immutable promotion artifact/configuration established. `scripts/soak/run_soak.py:730` explicitly rejects host preflight as exact-RC evidence; executed CLI/gate tests enforce that rejection. |
| Findings filed/reclassified before promotion | **UNVERIFIED externally**. Findings retained locally here; GitHub mutation prohibited and not performed. |
| Machine/human evidence tied to image/package/commit/config hashes | **UNVERIFIED for RC**. This report documents fresh validation, not a hash-tied production soak. |

## Handoff

**BLOCKED**; no actual current scanner or test failure justifies a code/ledger
repair. Only this report changes. Tests unchanged, so no inventory note needed.
The large inherited branch diff is preserved, not certified by this bounded pass.

Next input required: designated immutable RC and configuration, representative
workload applicability, and resolution of cross-replica rate-budget semantics.
Then execute the production-topology long soak with physical Attempt-effect
correlation, complete metrics, and active-work restart. Repeating the same
preflight/tests cannot satisfy these missing acceptance criteria.

Progress: checked 1 issue, done 0 acceptance-complete issues, skipped 0 issues,
errors 0 fresh validation commands. Local commit is a checkpoint, not approval.
