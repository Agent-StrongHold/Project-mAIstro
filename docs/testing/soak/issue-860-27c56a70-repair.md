# Issue #860 — repair checkpoint (27c56a70)

## Frozen scope

Only issue #860, branch `auto-860`, starting HEAD
`9d2961036ad1deed8d4422e092899a0dfeef17e0`, supplied base
`2f56be40ad241262b0384ab0b97834ebd37fe4d7`.
The starting worktree was clean. No GitHub mutations or ref changes.

Review targets: supplied dispatch-context.json and prior result/check-3.log;
repository instructions, applicable ADRs; `scripts/soak/run_soak.py`,
`tests/test_soak_promotion_gates.py`, production rate limiting and adjacent tests;
`quality/vulture-baseline.json` only if the prescribed scanner demonstrates debt.
Edit targets: this checkpoint and evidence-backed fixes in those targets, with
inventory notes for any added tests. No unrelated debt cleanup.

No check-*.log files were present in the supplied current job directory.
The prior result is a claim to recheck, not acceptance evidence.
Assumption: the explicit writer/repair assignment applies, not the verifier-only
instruction. A passing CI gate is not proof of a production soak.

## Progress

- Prescribed vulture scan passed: 1322 findings / 1322 reviewed identities,
  zero unclassified and zero never-allowlist findings. No ledger edit justified.
- Supplied historical check-3.log is a schema-fence test failure (24 DDL
  statements versus 21 expected), not a vulture failure. Reproduction pending.
  Its persistence source/test are included as direct reported-failure targets.
  Fresh reproduction: `uv run pytest
  packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` passed
  (37 passed, 6 skipped). The historical failure does not reproduce.
- Dispatch acceptance has ten production-soak criteria; local unit/CI success
  alone cannot satisfy them.
- `uv run pytest tests/test_soak_promotion_gates.py -x -q`: 72 passed.
  This includes the production-middleware counterexample: the same identity
  exhausts replica 1 but replica 2 still accepts two requests, for authenticated
  and pre-auth identities. This is not a live production deployment test.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed (3301 files already formatted).
- Reviewed ADR-081 (Proposed), ADR-085, ADR-081626-f383 and ADR-082526-b36a
  (Accepted). Reclaim is governed by the later TTL/renewal contract; the older
  fencing ADR's no-takeover boundary must not be mistaken for the current
  contract. Preserve Goal -> Graph -> Run -> NodeRun -> Attempt and the existing
  execution/authorization authorities. No runtime change is justified merely
  to make a preflight claim promotion success.
- `uv run python scripts/check-ratchet-provenance.py`: passed (53 consumers).
- `uv run python scripts/check-shipped-surface-truth.py`: passed.
- `git diff --check`: passed; rerun before commit.

## Acceptance review

| # | Criterion | Evidence / disposition |
|---|---|---|
| 1 | Representative release-candidate profile | UNVERIFIED: reviewed `m3a-load-profile.md`; its remaining-gaps section excludes concurrent user/Workspace populations, Graph fan-out, successful tool/model traffic and Design/Canvas. No selected immutable RC/configuration was validated. |
| 2 | At least two production application replicas | UNVERIFIED: executed ASGI limiter-instance tests, not a production deployment. |
| 3 | Sustained saturation, queues, reclaim, retries and leak observations | UNVERIFIED: no sustained production load run; passing deterministic tests cannot establish these observations. |
| 4 | No duplicate physical work | UNVERIFIED: `scripts/soak/run_soak.py:1067` cancels the schedule probe Run without executing it. Its admission race cannot establish physical Attempt uniqueness or Goal reconciliation. |
| 5 | Replica-independent rate/security/degraded enforcement | Counterexample reproduced by both parametrizations of `tests/test_soak_promotion_gates.py:439`: after replica 1 exhausts its allowance, replica 2 accepts more requests from the same identity. Production registers the middleware at `packages/maistro-server/src/maistro_server/main.py:648`; `api/rate_limit.py:94` constructs its process-local limiter. Full production concurrent security/degraded behavior remains UNVERIFIED. |
| 6 | Production telemetry and explicit thresholds | UNVERIFIED: profile thresholds exist, but driver-loop lag is not application-loop latency, and no new production telemetry was collected. |
| 7 | Kill/restart during active work with drain/fencing/recovery | UNVERIFIED: no active-work interruption executed. Exit/rejoin alone is insufficient. |
| 8 | Long soak of exact RC artifact/configuration | UNVERIFIED: `scripts/soak/run_soak.py:744` always rejects host preflight artifact equivalence. Executed four-hour-preflight tests confirm fail-closed behavior, not a four-hour soak. |
| 9 | Findings filed/reclassified before promotion | UNVERIFIED: local blockers documented; no GitHub mutations permitted or performed. |
| 10 | Published machine/human evidence bound to exact hashes | UNVERIFIED: this checkpoint is local validation evidence, not an exact-image/config production evidence pack. |

## Disposition and handoff

**BLOCKED.** The historical CI failure does not reproduce and the required
vulture scan has no unbanked identities. The current schema test independently
includes the three validation audit columns missing from the historical failed
expectation (`test_pg_learnings.py:174-176`). No source, test, ledger or grant
edits are warranted by those failures. Only this checkpoint changed; no test
addition means no inventory delta is required. Six database tests were skipped;
their live behavior is not claimed verified.

The remaining issue requires a selected immutable RC/configuration, a complete
representative workload and production runner, replica-independent enforcement
through the existing security path, physical-work/recovery observations, and a
long exact-artifact soak with hash-bound evidence. Do not resolve it by extending
the host preflight duration, relabeling local limiter semantics as cluster-wide,
or weakening gates. No speculative implementation of those prerequisites was
attempted in this CI-repair round. No integration approval is implied.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0,
next: "production RC/workload and enforcement prerequisites; then exact-RC soak"}`.

