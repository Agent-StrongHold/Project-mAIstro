# Issue #860 — bounded repair 869a7ba7

## Frozen scope

- Issue: #860 only; branch `auto-860`.
- Starting head: `7fa8b9cee2c61d27567dcf1bd9ae4d3f619f81b6` (verified); clean worktree.
- Supplied base: `ab8b3737fa64f8d840f421ef87ca506c509444ff`.
- Process only the supplied dispatch snapshot; no remote enumeration or mutations.
- Files for review: repository instructions, relevant execution/deployment ADRs,
  `scripts/soak/run_soak.py`, its profile/docs, `tests/test_soak_promotion_gates.py`,
  `scripts/check-vulture-baseline.py`, `quality/vulture-baseline.json`, and the
  supplied prior result and failed check log.
- Allowed edits: this handoff and evidence-driven vulture repairs if reproduced.
  No speculative production changes or fabricated RC evidence.

## Initial observations

The current job directory has no `check-*.log` files. The supplied prior result
reports BLOCKED, not a merge conflict. Assumption: rerun the explicitly assigned
vulture gate and validate the reported acceptance blockers locally; do not merge
unrelated develop changes. All ten issue acceptance criteria remain unverified
until independently checked below.

## Reproduced gate results

- Exact requested vulture command passed: 1,322 findings / 1,322 reviewed
  identities, zero unclassified and zero never-allowlist findings. No ledger
  amendment is justified by this scan.
- The supplied historical `check-3.log` is a learnings-schema test failure
  (`24` observed DDL statements versus `21` expected), not a vulture failure.
  Add only `packages/maistro-core/tests/persistence/test_pg_learnings.py` and
  `packages/maistro-core/src/maistro/persistence/pg_learnings.py` to the bounded
  review to reproduce this explicitly supplied failure; do not widen the lane.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py
  tests/test_soak_promotion_gates.py -x -q`: **109 passed, 6 skipped**. The
  historical failure is already repaired: the ordered expectation includes the
  three Gauntlet audit columns (lines 171–175); no test weakening is needed.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed (3,301 files).
- Existing real-middleware tests reproduce independent replica allowances for
  both anonymous and authenticated clients; the exact-RC rejection tests pass.
  These are meaningful local tests, not production-soak acceptance evidence.

## Architecture and acceptance disposition

Read repository instructions, documentation authority hierarchy, ADR-062,
ADR-081, ADR-081226-a66b and ADR-081626-f383. ADR-081 is **Proposed**, not an
accepted waiver. Accepted lifecycle/fencing contracts retain canonical
Goal → Graph → Run → NodeRun → Attempt authority; admission-row uniqueness
cannot substitute for physical Attempt fencing. The fencing ADR explicitly
does not itself define lease-expiry takeover. No alternate scheduler, store,
authorization path or reclaim authority is introduced here.

| # | Issue criterion | Current evidence / disposition |
|---|---|---|
| 1 | Representative RC profile | UNVERIFIED: `m3a-load-profile.md` documents one-key preflight and explicitly missing multi-Workspace, fan-out, successful model/tool and Canvas workloads. |
| 2 | At least two production replicas | UNVERIFIED: `preflight_artifact_check` at `scripts/soak/run_soak.py:744` identifies host uvicorn topology, not exact production Compose. |
| 3 | Sustained saturation/reclaim/leak observation | UNVERIFIED: no new long-window run performed; short local tests cannot establish this. |
| 4 | No duplicate physical work | UNVERIFIED: `scripts/soak/run_soak.py:1067` cancels an unexecuted admission-probe Run; row uniqueness is narrower than physical execution uniqueness. |
| 5 | Replica-independent security/rate/degraded behavior | UNVERIFIED with counterevidence: `tests/test_soak_promotion_gates.py:439` passes by reproducing separate allowances on two real production middleware instances, authenticated and anonymous. Production `rate_limit.py:32` explicitly documents N × limit. This is not a new shared-limiter implementation assignment. |
| 6 | Production telemetry and thresholds | UNVERIFIED: profile acknowledges driver loop lag is not application loop lag and process-group sampling is not container/worker telemetry. |
| 7 | Kill/restart during physical work with recovery | UNVERIFIED: no new active-work production fault injection; rejoin/terminal-row counts alone do not establish recovery. |
| 8 | Exact-RC long soak | UNVERIFIED: executed `test_four_hour_preflight_cannot_pass_cli` rejects missing, null and host-process artifact evidence; no promoted image/config was exercised. |
| 9 | Findings classified before promotion | UNVERIFIED: no complete production soak to disposition. This local handoff records blockers; no GitHub mutation performed. |
| 10 | Machine/human evidence bound to artifact/config | UNVERIFIED: this validation note is not a hash-bound production soak evidence pack. |

## Handoff

Outcome: **BLOCKED** on production-soak acceptance, not the supplied historical
CI failure. The exact vulture scan gives no unbanked identities to review or amend.
Do not rerun a four-hour host preflight expecting it to become exact-RC evidence.
Next work requires a selected immutable RC/config and production-path workload
and telemetry/fault-injection support, while respecting the canonical authority.

Only this handoff changed. No source or tests changed, so no test inventory delta
is needed. Six tests skipped; local passing tests do not certify database-backed
or production behavior. No existing work discarded; no remote mutation.

Progress: checked 1 issue; done 0 acceptance-complete issues; skipped 0 issues;
validation errors 0; next: resolve the production evidence prerequisites above.
