# Issue #860 — repair checkpoint (job 22633b3e)

## Frozen scope

Only issue #860, branch `auto-860`, starting HEAD
`8c8b0d869aea55ce598b607e3398dee6d97574c3`, supplied base
`321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62`. No GitHub mutations or
other issues/PRs will be processed. Worktree was clean at entry.

Candidate repair files: `packages/maistro-core/src/maistro/persistence/pg_learnings.py`,
`packages/maistro-core/tests/persistence/test_pg_learnings.py`,
`scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`,
`quality/vulture-baseline.json` (only if fresh scanner evidence requires it),
`docs/testing/inventory-notes/m3a-860-promotion-gates.md`, and this note.
Adjacent rate-limit/task code, tests, load-profile documentation, and accepted
execution ADRs are read-only evidence. No speculative gate/ledger repair.

## Initial evidence and ambiguity

The supplied job directory has no `check-*.log` files. The explicitly supplied
older `98a11313.../check-3.log` reports 24 schema statements versus 21 expected.
This is historical evidence, not a claim about current HEAD; rerun before editing.
The supplied previous result reports unresolved exact-RC evidence and
replica-local rate budgets. Assumption: CI-repair authority does not authorize
inventing an RC identity or a competing execution/security authority.

## Fresh checkpoint

- Exact requested vulture command: PASS, 1322 findings / 1322 reviewed
  identities, zero unclassified, zero never-allowlist. No ledger amendment
  justified; no genuinely dead unbanked identity was reported.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  37 passed, 6 skipped. The supplied historical schema failure does not reproduce.
  Skips are not PostgreSQL integration proof.
- Read accepted runtime contract ADR-081426-1f7c and fencing ADR-081626-f383:
  canonical Attempt identity and Run-store fence authority remain unchanged.
  Fencing explicitly does not establish lease-expiry takeover by itself.
- Current profile calls its runner a host-process preflight, explicitly not an
  exact promoted Compose artifact. Four hours of this emulator cannot satisfy
  exact-RC acceptance. No production/security changes are justified solely by
  the stale CI failure.

## Remaining executed validation

All commands ran in the assigned worktree with a 1200-second timeout; outcomes
were captured in this session's tool output, not inferred from prior reports.

| Command | Result |
| --- | --- |
| `uv sync --locked --extra dev` | PASS, 256 resolved / 214 checked |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q` | 99 passed |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3301 files already formatted |

Vulture arguments match `.github/workflows/vulture-ratchet.yml:82–85`.
The schema test now independently names the three validation-audit columns at
`packages/maistro-core/tests/persistence/test_pg_learnings.py:173–177` and checks
all 24 statements inside the transaction/advisory-lock fence. Production takes
the lock before upgrades at `packages/maistro-core/src/maistro/persistence/pg_learnings.py:215`.
No tests were added/removed or edited, so no inventory delta is needed.

## Reachable behavior and ADR reconciliation

The production app installs `RateLimitMiddleware` at
`packages/maistro-server/src/maistro_server/main.py:648`. Its constructor at
`packages/maistro-server/src/maistro_server/api/rate_limit.py:93` creates a
per-instance in-memory limiter. The executed regression at
`tests/test_soak_promotion_gates.py:439` observes `[200, 200, 429]` from **each**
instance for the same identity, both authenticated and unauthenticated. This
is a meaningful production-middleware counterexample, not a deployed soak.
ADR-085 requires principal keying; that does not establish shared replica budgets.
Do not relabel the documented process-local contract as satisfying #860's
stronger replica-selection requirement. Any coordinated enforcement repair must
use the existing security seam, not a second authentication path.

`preflight_artifact_check()` at `scripts/soak/run_soak.py:744` correctly returns
`ok: false`. The executed CLI regression at `tests/test_soak_promotion_gates.py:106`
checks that otherwise-passing four-hour synthetic evidence still exits 1 with
missing, null or preflight artifact evidence. This guards against false approval;
it is not actual four-hour load evidence.

Also read accepted ADR-081226-a66b and ADR-073126-c4e1: preserve
Goal -> Graph -> Run -> NodeRun -> Attempt and the existing release provenance
path. No new authority, scheduler or release artifact was introduced. A branch
head alone cannot be substituted for the exact artifact #89 would promote.

## Acceptance audit (all ten criteria)

| Criterion | Executed evidence / remaining gap |
| --- | --- |
| Representative RC workload | UNVERIFIED: `m3a-load-profile.md` documents a preflight mix and missing multi-user/Workspace, Graph fan-out, successful tool/model, Design/Canvas and Goal/background workloads. RC applicability is unresolved. |
| At least two deployed application replicas | UNVERIFIED: the executed ASGI tests use two middleware instances, not two deployed RC replicas. |
| Sustained saturation, queue growth, lease reclaim, retries, resource leaks | UNVERIFIED: bounded unit/ASGI checks cannot establish sustained behavior. |
| No duplicate physical work across schedule/task/Run/Attempt/Goal operations | UNVERIFIED: admission evidence is not physical execution evidence. No production-load execution was performed. |
| Replica-independent rate/security/degraded behavior | NOT SATISFIED at the middleware seam: the executed same-identity regression demonstrates independent budgets. Other deployed security/degraded behavior remains UNVERIFIED. |
| Complete PostgreSQL/application-loop/process/RSS/FD/queue/error telemetry with thresholds | UNVERIFIED: no fresh production telemetry collected; driver-loop latency is not application-loop latency. |
| Active-work replica kill/restart, drain/fencing/recovery | UNVERIFIED: no deployed active-work restart performed. |
| Long exact-RC/config soak, repeated after runtime changes | UNVERIFIED: no selected immutable promotion artifact/configuration supplied; preflight artifact gate deliberately fails. |
| Load findings classified to earliest broken invariant | UNVERIFIED for completeness. Independent rate allowances are a prerequisite security/enforcement concern, not throughput optimization. No GitHub filing is permitted in this lane. |
| Human/machine evidence bound to image/package/commit/config hashes | UNVERIFIED for production soak. This note identifies source validation only. |

## Disposition and required next action

**BLOCKED.** No current vulture or schema failure exists to repair, and no
merge conflict was present. Only this handoff note changed; no ledger, grants,
production code, tests or gates changed. Repeating the same CI repair cannot
supply the missing acceptance evidence.

Next: designate the immutable RC artifact and normalized production configuration,
resolve representative-profile applicability and replica-independent enforcement
through existing owners/seams, then execute the long supported-topology soak
with physical-work observations and complete telemetry. Preserve fail-closed
promotion checks. Do not treat this local handoff commit as integration approval.

Progress: checked 1 issue; done 0 acceptance-complete; skipped 0 issues;
validation errors 0; next is the blocked RC execution above.
