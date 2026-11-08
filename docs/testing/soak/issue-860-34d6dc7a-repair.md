# Issue #860 repair checkpoint (job 34d6dc7a)

## Frozen scope

Only issue #860, branch `auto-860`, starting HEAD
`ea4928774d5249abfda6eff96445f0fbf4f7c6e8`; supplied base
`3c761d14db944a727fa0744444bc67cfe36d49f7`.
Worktree initially clean. No GitHub mutations or unrelated work planned.

Files under review: `scripts/soak/run_soak.py`,
`tests/test_soak_promotion_gates.py`,
`packages/maistro-core/src/maistro/persistence/pg_learnings.py`,
`packages/maistro-core/tests/persistence/test_pg_learnings.py`, and
`quality/vulture-baseline.json` (only if the assigned exact scanner proves drift).
This report is the planned documentation change; an inventory note is required
if tests change. Adjacent architecture and instructions are read-only context.

## Initial evidence and ambiguity

The current job directory contains no `check-*.log` files. The supplied prior
`98a11313167b41a98a420abfda80c292/check-3.log` reports 24 schema statements versus
21 expected. The prior result claims this no longer reproduces; independently
retest rather than editing based on stale evidence. No exact release-candidate
image/configuration has yet been identified; do not substitute host processes
for deployed RC evidence. An initial overly broad instruction-file search listed
sibling paths; no sibling files were read or changed. Exploration is now confined
to the frozen scope and directly relevant architecture.

## Fresh validation checkpoint

- Exact requested Vulture scan: PASS, 1323 reviewed identities / 1323 findings,
  zero unclassified or forbidden. Automatic ratchet base `4aa68edc0b6b`.
  No evidence supports a ledger amendment.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  37 passed, 6 skipped in 1.70s. The historical failure does not reproduce:
  the expected ordered schema statements already include the three audit columns.
- Both commands used a 1200-second timeout. Production acceptance remains pending;
  these checks are not deployed-RC validation.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3270 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py -x -q -rs`: 65 passed in
  1.24s, including real production-middleware independent-allowance probes for
  authenticated and unauthenticated clients and fail-closed artifact gates.
- `uv run python scripts/check-deployment-claims.py`: PASS (component existence,
  not proof of deployed concurrency).
- `uv run python scripts/check-suite-inventory.py`: PASS, 17 suites / 31128
  unique identities, no duplicate evidence. No tests changed, so no inventory
  delta is required. Additional commands also used 1200-second timeouts.

## Architecture and reachable behavior

Repository instructions and accepted ADR-081226-69ee, ADR-081626-f383,
ADR-082526-b36a and ADR-085 were read. The later lease ADR requires renewal and
expiry-based reclamation, not restart-implies-death. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`; admission
uniqueness is not physical-work uniqueness, and a process restart does not prove
fenced recovery. Per-principal keying does not establish a shared replica budget.
No alternate execution, event, store or authorization authority is introduced.

- `packages/maistro-core/src/maistro/persistence/pg_learnings.py:215` encloses
  the advisory lock and schema upgrades in a transaction; the independent ordered
  expectation at `packages/maistro-core/tests/persistence/test_pg_learnings.py:162`
  already includes the missing validation-audit columns from the historical log.
- `packages/maistro-server/src/maistro_server/main.py:648` installs the real
  middleware. `api/rate_limit.py:93` creates an instance-local limiter.
  `tests/test_soak_promotion_gates.py:439` exercises it and observes
  `[200, 200, 429]` separately on both replicas with the same identity. This
  falsifies shared-budget enforcement at that seam; it is not a deployed exploit.
- `scripts/soak/run_soak.py:730` returns `exact_rc_artifact.ok=false` for its
  host-process topology. No duration extension makes that topology the RC.
- `docs/testing/soak/m3a-load-profile.md:151` identifies missing representative
  workloads and telemetry; its schedule probe cancels the queued Run without
  executing physical work (lines 193–203). Historical bundles are not recertified.

## Acceptance disposition

| Issue criterion | Fresh evidence / disposition |
| --- | --- |
| Representative RC profile | UNVERIFIED: preflight lacks multiple users/Workspaces, Graph fan-out, successful tool/model work, Design/Canvas and background reconciliation applicability. |
| At least two deployed application replicas | UNVERIFIED for RC: middleware instances are not deployed immutable images. |
| Sustained saturation, growth, reclaim, retry, leaks and shutdown observation | UNVERIFIED: short regression tests are not a sustained load series. |
| No duplicate physical work across schedule/task/Run/Attempt/Goal operations | UNVERIFIED: no physical-work witness executed. |
| Rate/security/degraded non-bypass by replica selection | Independent allowances reproduced by executed production-middleware tests; broader deployed security/degraded behavior UNVERIFIED. |
| Complete PG/loop/worker/RSS/descriptor/queue/error telemetry and thresholds | UNVERIFIED for RC: no new complete telemetry series; driver loop lag is not application loop lag. |
| Kill/restart during active work with drain/fencing/recovery | UNVERIFIED: no active-work fault injection or recovery witness. |
| Long soak of exact promoted RC/configuration | BLOCKED / UNVERIFIED: no immutable RC/config designated by assignment; host runner fails exact-artifact certification by construction. |
| Findings filed/reclassified before promotion | Local disposition recorded; external filing/reclassification UNVERIFIED (GitHub mutations prohibited). Rate-budget discrepancy is correctness, not throughput optimization. |
| Machine/human evidence bound to image/package/commit/config hashes | UNVERIFIED for RC: this source-bound validation report is not an RC evidence bundle. |

## Handoff

BLOCKED on production-soak prerequisites, not the reported schema or vulture
failures. Only this report changes. No speculative runtime/test/ledger edits,
no sync conflict, no fetch/merge, no GitHub mutations. Existing work preserved.
The supplied base is not claimed as the automatic ratchet comparison base.

Next: release owner designates immutable RC and runtime configuration; reconcile
the replica-budget acceptance with the existing enforcement path; complete the
representative production workload, telemetry and physical-work witnesses; run
the long exact-RC soak and publish hash-bound evidence. Do not repeat this repair
for the same historical log without new failure evidence. This report is not
integration or promotion approval.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "designate exact RC and complete production-soak prerequisites"}`.

