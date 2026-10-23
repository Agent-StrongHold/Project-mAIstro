# Issue #860 — aea2b671 validation checkpoint

## Frozen scope

- Sole item: #860, branch `auto-860`, starting head
  `1a2b34a195c17b4f1572f0c0b8046b16789a202e`, supplied base
  `321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62`.
- Worktree clean at entry; no incoming edits to salvage.
- Inspect supplied dispatch evidence, referenced prior failure, repository instructions,
  applicable ADRs, existing soak harness/tests and reachable production paths.
- Edit scope: this validation report; `quality/vulture-baseline.json` only if
  fresh exact CI scan identifies reviewed retained debt. No speculative fixes.
- Current job directory contains no `check-*.log`; referenced historical failure
  must be distinguished from a fresh result.
- Prior result says BLOCKED; treated as a claim to revalidate, not acceptance evidence.

## Progress

Fresh exact CI vulture command passed: 1322 findings / 1322 reviewed identities,
zero unclassified, zero never-allowlist. No ledger amendment is warranted.
Fresh `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`
passed: 37 passed, 6 skipped. The referenced historical check-3 failure expected
21 DDL statements; the current test explicitly includes all three validation-audit
columns (24 statements). No regression repair is warranted for that old failure.

## Fresh validation results

All commands ran in the assigned worktree with 1200-second timeouts:

| Command | Result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1322 reviewed identities / findings; no unbanked identities |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 37 passed, 6 skipped |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q` | 99 passed |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS: 3301 files already formatted |
| `uv run python scripts/check-ratchet-provenance.py` | PASS: 53 consumers covered; nonfatal invalid-escape SyntaxWarnings |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS |

The vulture/provenance/surface commands match `.github/workflows/vulture-ratchet.yml`.
The six schema-suite skips are not live PostgreSQL evidence. No deployment or
long-running soak was performed. Passing local regression tests do not establish
production acceptance.

## Architecture and reachable behavior

Read repository instructions, documentation authority hierarchy, the supplied
issue body, referenced prior result/failure, load profile, adjacent schema and
soak tests, production routes/middleware, and production Compose wiring.
Read accepted ADR-081426-1f7c, ADR-081626-f383 and ADR-082526-b36a:
physical execution is Attempt-scoped; the canonical store owns fencing; renewal
and reclamation extend the earlier lease boundary. Admission deduplication is
not physical-work uniqueness. Preserve Goal -> Graph -> Run -> NodeRun -> Attempt.
ADR-081 is **Proposed**, not authority to waive acceptance or choose a new topology.
No alternative scheduler, execution authority, store, event or auth path added.

- `scripts/soak/run_soak.py:744` always returns a failed exact-RC artifact check.
  The executed CLI regression rejects missing, null and preflight artifact
  evidence even with a synthetic four-hour duration. This proves fail-closed
  behavior, not a four-hour run.
- `packages/maistro-server/src/maistro_server/main.py:648` installs the production
  rate middleware; `api/rate_limit.py:93` constructs its process-local limiter.
  The executed test at `tests/test_soak_promotion_gates.py:439` gets
  `[200, 200, 429]` on each of two instances for the same identity, both with
  and without credentials. Exhausting one replica does not exhaust its peer.
  These ASGI probes do not measure deployed ingress enforcement.
- Production task routes are mounted at `main.py:735` and `main.py:755`.
  `api/tasks.py:145` reads the queue; the executed production-router test at
  `tests/test_soak_promotion_gates.py:569` observes the admitted task as 200 on
  the admitting instance and 404 on its peer. No load-balancer affinity or
  shared durable receipt guarantee is established by that test.

## Acceptance disposition

The ten criteria below are from the issue body captured in dispatch-context.json.

| Criterion | Executed evidence / remaining limit |
| --- | --- |
| Representative RC profile | UNVERIFIED. `m3a-load-profile.md:165` identifies absent multi-user/Workspace traffic, Graph fan-out, successful tools/models, Design/Canvas and background reconciliation. RC applicability remains unresolved. |
| At least two deployed replicas | UNVERIFIED. Compose declares two instances; the executed ASGI tests are not deployment evidence. |
| Sustained saturation, queue growth, reclaim, retries and leaks | UNVERIFIED. No sustained production observation window executed. |
| No duplicate physical schedule/task/Run/Attempt/Goal work | UNVERIFIED. Admission and receipt regression tests do not observe physical execution across recovery. |
| Replica-selection-resistant rate/security/degraded enforcement | UNVERIFIED for deployment. Independent local allowances reproduced through production middleware; no shared principal budget proven. |
| Full production telemetry with thresholds | UNVERIFIED. No fresh PostgreSQL/app-loop/worker/RSS/FD/queue/error time series; driver-loop lag cannot substitute for app-loop lag. |
| Kill/restart during active work, drain/fencing/recovery | UNVERIFIED. No production replica kill/restart executed. |
| Long exact-RC soak | UNVERIFIED. Current harness fails exact-RC equivalence by design; no selected immutable RC artifact/configuration supplied in the assignment. |
| Earliest-invariant classification of load findings | UNVERIFIED for completeness. No new representative load window; no remote filing authorized. |
| Hash-bound machine/human production evidence | UNVERIFIED. This source-bound validation report is not an image/package/config-bound production soak bundle. |

## Disposition and handoff

**BLOCKED for acceptance; reported CI repair is already passing.** No speculative
production change, ledger edit, grant, or weakened gate is justified. Only this
report changed. No tests added/changed, so no inventory delta or inventory note
is required.

Exact-RC ambiguity checked against the supplied assignment and local
profile/Compose: `deploy/docker-compose.prod.yml:11` explicitly describes a
reference that requires digest pinning and builds server images from source.
Assumption: do not silently select the promotion artifact/configuration or
relabel preflight as production evidence. RC selection remains UNRESOLVED.

Next owner action: identify the immutable RC and normalized deployment config,
confirm applicable workloads, resolve canonical receipt/policy prerequisites,
and execute an instrumented long production soak plus active-work recovery.
Do not redispatch the old schema/vulture failure as an unresolved CI defect.

Progress: checked 1 issue; acceptance-complete 0; skipped issues 0; fresh command
failures 0. This is a committed blocked handoff, not integration approval.
