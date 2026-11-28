# Issue #860 — d9775828 repair checkpoint

## Frozen scope

Only issue #860, branch `auto-860`, starting HEAD
`479336c7bbe0d1f86b9afd27d330c8e60d7c92c8`, base
`ab8b3737fa64f8d840f421ef87ca506c509444ff`.
Initial worktree clean; no incoming edits to salvage.
No PR processing or GitHub mutations.

Read-only review: supplied dispatch-context.json and prior result/check-3.log;
AGENTS.md, docs/README.md, relevant execution/promotion ADRs;
`scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`,
`docs/testing/soak/m3a-load-profile.md`, production admission/rate-limit wiring,
`packages/maistro-core/src/maistro/persistence/pg_learnings.py` and adjacent tests,
CI workflow and vulture checker.
Permitted repair files: the persistence implementation/test above (only if the
reported failure reproduces), `quality/vulture-baseline.json` (only actual
reviewed scan findings), this report, and an inventory note if tests change.

## Initial evidence / assumptions

The supplied previous check-3.log failed the schema-fence test (24 statements
versus 21 expected). Its currency is unverified until rerun. The prior result
reports missing production soak evidence and per-replica allowances; these are
not accepted as proof. No check-*.log files were present in this job directory
at initial inspection. Treat this as a writer repair, not a verifier-only run.

## Executed results

- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  37 passed, 6 skipped. Historical schema failure does not reproduce. The current
  independent expected-DDL list includes the three validation audit columns.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`:
  passed; 1322 reviewed identities / 1322 findings, zero unclassified or forbidden
  findings. No ledger amendment is justified by this scan.

- `uv run pytest tests/test_soak_promotion_gates.py -x -q`: 72 passed,
  including both authenticated/unauthenticated independent-replica allowance
  cases. Each middleware instance accepts two requests and rejects the third;
  the second instance still accepts after the first exhausts its allowance.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 3301 files already formatted.

No source/test changes warranted by the reported CI failures.

## ADR reconciliation (fresh review)

Read docs/README.md and ADR-081, ADR-085, ADR-081626-f383 and
ADR-082526-b36a. ADR-081 is Proposed, not accepted deployment authority.
The previous handoff's statement that lease-expiry takeover is outside the
current contract is incomplete: accepted ADR-082526-b36a adds fenced renewal,
TTL-based reclamation and canonical executor heartbeats on top of
ADR-081626-f383. Reclaim must use that existing authority, not a new scheduler
or restart-implies-death rule. No claim is made here that reclamation has been
soak-proven. Goal -> Graph -> Run -> NodeRun -> Attempt remains canonical.
ADR-085's per-principal requirement and the issue's stronger replica-selection
criterion are not established by the process-local limiter tests.

## Acceptance evidence

| # | Criterion | Executed evidence / disposition |
|---|---|---|
| 1 | Representative RC load profile | UNVERIFIED: reviewed `m3a-load-profile.md`; its remaining-profile-gaps section excludes concurrent users/Workspaces, Graph fan-out, successful tool/model traffic and Design/Canvas. No selected immutable RC/configuration supplied or validated this round. |
| 2 | At least two production replicas | UNVERIFIED: `deploy/docker-compose.prod.yml:26,77` declares two replicas, but no production deployment was exercised this round. |
| 3 | Sustained saturation, growth, reclaim, retry and leak observations | UNVERIFIED: unit checks are not sustained production load. Reclaim must follow accepted ADR-082526-b36a. |
| 4 | No duplicate physical work | UNVERIFIED: `scripts/soak/run_soak.py:1067` cancels the schedule admission probe without execution. Admission deduplication is not physical-work uniqueness. |
| 5 | Replica-independent rate/security/degraded enforcement | Counterexample reproduced: `tests/test_soak_promotion_gates.py:439` passes for both identity classes while each replica independently permits `[200,200,429]`. Production registers this middleware at `packages/maistro-server/src/maistro_server/main.py:648`; it constructs an in-memory limiter at `api/rate_limit.py:94`. Full concurrent production security/degraded behavior remains UNVERIFIED. |
| 6 | Production telemetry with thresholds | UNVERIFIED: profile thresholds exist, but driver-loop lag is not application-loop latency; no fresh production telemetry collected. |
| 7 | Active-work kill/restart, drain, fencing and recovery | UNVERIFIED: no active-work interruption executed; process rejoin alone cannot establish this. |
| 8 | Long exact-RC soak | UNVERIFIED: `scripts/soak/run_soak.py:744` always rejects host preflight artifact equivalence. Executed four-hour-preflight gate tests confirm fail-closed behavior; no long production soak was run. |
| 9 | Findings filed/reclassified by milestone | UNVERIFIED: blockers recorded locally; no issue mutations permitted or performed. |
| 10 | Machine/human evidence bound to image/package/commit/config hashes | UNVERIFIED: this report is local validation evidence, not a production soak evidence pack. |

## Final validation and disposition

Additional required workflow-adjacent checks:
- `uv run python scripts/check-ratchet-provenance.py`: passed (53 consumers).
- `uv run python scripts/check-shipped-surface-truth.py`: passed.
- `git diff --check`: passed before final report update; rerun before commit.

**BLOCKED**, not merge-ready. Changed only this report. No tests added, so no
inventory delta is required. No ledger edits, gate weakening, runtime changes,
GitHub mutations or speculative repair. Six database-dependent schema tests
were skipped; their live behavior remains unverified. The broader issue cannot
be completed by repeating already-green deterministic checks or extending the
host preflight duration.

Next: select the immutable RC and complete its representative workload, resolve
replica-selection enforcement via the existing security path, instrument
physical-work/recovery and application telemetry, then execute the required long
production soak and bind its evidence to the artifact/configuration. Do not
interpret this local commit as integration approval.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0,
next: "production RC workload, enforcement and observability prerequisites"}`.

