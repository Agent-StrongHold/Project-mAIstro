# Issue #860 — bounded repair bcca9833

## Frozen scope

- Issue #860 only; worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Starting HEAD `8f2a1d972cd208f9ee14583aa9a3c0a2c4b8f0b1`; supplied base
  `435dc1937e0407ab4de198ffcced49860bb14ad2`; both resolve locally.
- Initial worktree clean; no uncommitted salvage needed.
- Review snapshot: supplied dispatch context and prior result; `AGENTS.md`,
  `docs/README.md`, relevant execution/deployment ADRs; existing soak harness,
  load profile, promotion tests, and Vulture checker/ledger/workflow.
- Edit scope: this record and `quality/vulture-baseline.json` only if the
  mandated scan identifies reviewed retained identities. Any actual source
  repair outside that snapshot requires a handoff, not guessed edits.
- No GitHub mutations, new execution authority, gate weakening, or RC designation.

## Initial evidence and ambiguity

The current job directory contains no `check-*.log` files. The prior result
claims BLOCKED, with no exact-RC soak; those claims are not fresh validation.
The inherited diff is large and includes unrelated historical removals; this
round does not certify or rewrite those changes. The explicit assignment is a
Vulture CI repair plus fresh acceptance assessment, not an authorization to
invent the release artifact/configuration.

## Fresh checkpoint

- `uv sync --locked --extra dev`: passed (214 packages checked).
- Mandated `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: passed; 1323 findings /
  1323 reviewed identities, zero unclassified or forbidden. Checker selected
  base `4aa68edc0b6b`, not the dispatch base. No evidence justifies a ledger edit.
- Historical `98a11313167b41a98a420abfda80c292/check-3.log` was read: schema
  fence test expected 21 DDL statements but observed 24.
- Fresh `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py
  tests/test_soak_promotion_gates.py
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q -rs`:
  **103 passed, 6 skipped in 2.98s**. The historical failure does not reproduce.
  Six live-PostgreSQL cases skipped for missing `MAISTRO_TEST_PG_DSN`.
- The executed replica-selection test uses production rate middleware in two
  ASGI apps: each accepts two requests for the same identity before returning
  429. This confirms local enforcement, not a cluster-wide budget; both
  authenticated and unauthenticated variants ran. It is not a deployed soak.

## Remaining validation

All commands executed in the assigned worktree with 1200–1800 second timeouts:

| Command | Outcome |
| --- | --- |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3270 files |
| `uv run python scripts/check-suite-inventory.py` | PASS, 17 suites / 31128 unique identities / zero duplicates |
| `uv run python scripts/check-deployment-claims.py` | PASS, component existence only; not deployed-runtime proof |

Vulture arguments match `.github/workflows/quality.yml:1078–1081`.
The current schema-fence test independently enumerates all 24 DDL operations
(`packages/maistro-core/tests/persistence/test_pg_learnings.py:162–194`), and
production acquires its lock inside the transaction (`pg_learnings.py:215–216`).
No source, test, inventory, grant or ledger changes were warranted or made.
This report is the only changed file; tool outputs are in the job session trace.

## Architectural reconciliation

Read accepted ADR-081226-69ee, ADR-081626-f383, ADR-082526-b36a and ADR-085.
Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`; admission deduplication
is not physical-work fencing. A restart cannot authorize reclaim of another
live holder. Principal-keyed rate limits do not establish shared replica state:
production explicitly documents process-local budgets. That narrower contract
cannot silently satisfy #860's stronger replica-selection acceptance criterion.
No competing scheduler, authority, authorization path or speculative distributed
limiter was introduced.

## Acceptance assessment

| #860 criterion | Fresh evidence / disposition |
| --- | --- |
| Representative RC load profile | **UNVERIFIED**. `m3a-load-profile.md:151–170` explicitly lacks concurrent users/Workspaces, Graph fan-out, successful tool/model calls and Design/Canvas/background workloads. Applicability to a designated RC is unresolved. |
| At least two application replicas | **UNVERIFIED at runtime**. `deploy/docker-compose.prod.yml:26–78` declares two servers; this round did not deploy a designated RC. |
| Sustained saturation, queue/reclaim/retry, memory/descriptor/process leak observation | **UNVERIFIED**. The 2.98-second regression run is not sustained-load evidence; no new telemetry series was generated. |
| Schedule/task/Run/Attempt/Goal physical-work uniqueness | **UNVERIFIED**. `m3a-load-profile.md:193–203` describes a single admission race whose Run is cancelled before execution. No sustained physical-work witness. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **NOT PROVEN; allowance multiplication reproduced** by both variants of `tests/test_soak_promotion_gates.py:439–489`. `api/rate_limit.py:93` instantiates a local limiter, installed in production at `main.py:648`. This is a production-middleware test, not a full deployed security experiment. |
| Complete telemetry and explicit thresholds | **UNVERIFIED for RC**. Existing documented thresholds and sampler tests are not observed application-loop, pool, worker, PostgreSQL, queue and leak telemetry for the promoted configuration. |
| Kill/restart during active work; drain/fencing/recovery | **UNVERIFIED**. Gate regressions executed, but no active-work replica fault injection ran. |
| Long exact-RC/configuration soak, repeated after changes | **UNVERIFIED / BLOCKED**. No immutable promotion artifact/configuration designated in the assignment. `scripts/soak/run_soak.py:730–741` explicitly rejects host-process preflight as exact-RC evidence; executed gate tests retain that boundary. |
| Findings filed/reclassified before promotion | Local disposition recorded here. External filing/reclassification **UNVERIFIED**; GitHub mutations prohibited. |
| Machine/human evidence tied to exact artifact/config hashes | **UNVERIFIED for RC**. This source-bound validation record is not a promotion soak bundle; historical bundles were not recertified. |

## Final disposition and handoff

**BLOCKED**, not merge-ready. The requested CI failure is not reproducible;
there are no unbanked Vulture identities to amend. Do not dispatch another
identical ledger repair expecting it to establish release acceptance. The next
work requires an owner-designated immutable RC/configuration, representative
production workloads and physical-work/recovery witnesses, then the long soak
with complete telemetry. Reconcile the observed per-replica allowance with the
non-bypass requirement through the existing enforcement path before promotion.
The inherited large diff (including unrelated removals) remains outside this
bounded CI validation and requires separate integration review.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "designate RC and resolve production-soak prerequisites"}`.
Local commit of this report is a checkpoint, not issue completion or integration
approval.
