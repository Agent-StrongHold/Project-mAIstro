# Issue #860 — c976773f repair checkpoint

## Frozen scope

- Assigned issue: #860 only; branch `auto-860`.
- Verified starting HEAD: `a788a17161e350b11640474fb5eae1a930a02b06`.
- Supplied base: `ab8b3737fa64f8d840f421ef87ca506c509444ff`.
- Initial worktree clean; no salvage needed.
- Inspect supplied dispatch snapshot, prior result and failed check; repository instructions,
  relevant ADRs, existing soak runner/profile/tests and production rate enforcement.
- Run requested exact vulture gate and focused validation. Edit ledger/source only if
  fresh evidence identifies an actionable issue; otherwise commit this evidence handoff.
- No GitHub mutations, new authority paths, or unrelated repairs.

## Initial observations

The current job directory contains no `check-*.log` files in its initial listing.
The supplied prior result reports BLOCKED, not production acceptance. Treat those
claims as unverified until checked below. This is a writer repair assignment;
verifier-only no-edit instructions do not apply.

## Fresh validation

- Requested exact vulture command: PASS, 1,322 reviewed identities / 1,322
  findings, zero unclassified and zero never-allowlist findings. No evidence
  justifies ledger changes.
- Supplied historical `check-3.log` fails the learnings schema fence test
  (24 actual statements versus 21 expected), not vulture. Review the explicitly
  implicated core source/test as part of this issue, not unrelated packages.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py
  tests/test_soak_promotion_gates.py -x -q`: PASS, 109 passed / 6 skipped.
  The historical failure is not reproduced on the assigned head.

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3,301 files already formatted.
- Historical schema expectation already includes the three audit columns at
  `packages/maistro-core/tests/persistence/test_pg_learnings.py:171–175`.
  Production `ensure_schema` takes the advisory lock inside its transaction at
  `packages/maistro-core/src/maistro/persistence/pg_learnings.py:215–216`.
- One exploratory lookup of `maistro_server/middleware` returned path not found;
  skipped that path. The existing test imports `maistro_server.api.rate_limit`.

## Architecture reconciliation

Read repository instructions, `docs/README.md`, ADR-062, ADR-081,
ADR-081226-a66b and ADR-081626-f383. ADR-081 is Proposed, not an accepted
acceptance waiver. Accepted lifecycle/fencing contracts retain the canonical
Goal → Graph → Run → NodeRun → Attempt model. Admission uniqueness is not
physical-work uniqueness, and fencing alone does not define lease-expiry
reclaim authority. No alternative execution or authorization path was added.

## Acceptance review

All ten criteria were compared to the supplied issue body and current runner,
profile and focused tests. Local tests are not a production-soak substitute.

| # | Criterion | Evidence and disposition |
|---|---|---|
| 1 | Representative RC profile | UNVERIFIED: `m3a-load-profile.md` explicitly lacks multiple users/Workspaces, fan-out, successful tool/model calls, Canvas and sustained Goal reconciliation. |
| 2 | Two production application replicas | UNVERIFIED: `scripts/soak/run_soak.py:744` identifies host-uvicorn preflight, not promoted production Compose. |
| 3 | Sustained saturation/reclaim/leak observation | UNVERIFIED: no new long-window production run executed; passing unit probes cannot demonstrate it. |
| 4 | No duplicate physical work | UNVERIFIED: `scripts/soak/run_soak.py:1067` cancels the schedule admission probe Run without executing it. |
| 5 | Replica-independent security/rate/degraded behavior | UNVERIFIED with counterevidence: executed `tests/test_soak_promotion_gates.py:439` reproduces independent allowances for both anonymous and authenticated identities using production middleware. `packages/maistro-server/src/maistro_server/api/rate_limit.py:32–37` explicitly documents N × limit; its constructor creates an in-memory limiter per instance. |
| 6 | Production telemetry and thresholds | UNVERIFIED: profile distinguishes driver loop lag from application lag and process-group sampling from complete worker/container telemetry. |
| 7 | Restart during active work proves drain/fencing/recovery | UNVERIFIED: no new production fault injection performed; replica rejoin and terminal row counts are insufficient. |
| 8 | Long exact-RC soak | UNVERIFIED: executed CLI tests at `tests/test_soak_promotion_gates.py:105` reject missing/null/preflight artifact records even at four-hour duration. |
| 9 | Load findings classified before promotion | UNVERIFIED: no completed production soak to disposition; blockers are recorded here, without GitHub mutation. |
| 10 | Machine/human evidence bound to artifact/config hashes | UNVERIFIED: this handoff is local validation, not a hash-bound production evidence pack. |

## Disposition

The supplied CI failure is already repaired on this head. The exact vulture
scan identifies no unbanked or eliminated identities requiring amendment.
No speculative scanner fix or cosmetic source change is justified.

Outcome remains **BLOCKED** on production acceptance. Next work requires a
selected immutable RC/configuration, representative production-path workloads,
production telemetry and active-work recovery probes. Do not run the host
preflight for four hours and relabel it promotion evidence.

Only this handoff changed. No test additions or inventory delta. Six tests
skipped; DB-backed coverage is not certified by this run. No source, ledger,
grant, existing artifact or remote state changed.

Progress: checked 1; acceptance-complete 0; skipped issues 0; validation failures
0; next: production evidence prerequisites. This handoff is the sole file staged
for the required local commit; no integration approval is claimed.
