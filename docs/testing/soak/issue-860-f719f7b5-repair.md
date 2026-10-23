# Issue #860 — job f719f7b5 validation handoff

## Frozen scope and initial state

Only issue #860 in `/home/dev/Git/wt/auto-860`, branch `auto-860`.
Starting HEAD: `50745813b8c7af0d142774ddbce042a9bf9b10ba`;
assigned base: `321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62`.
Worktree was clean. No GitHub mutations, ref changes or other issues processed.

Frozen candidate repair scope: the reported `pg_learnings.py` schema-fence test
and production implementation; `quality/vulture-baseline.json` only for actual
fresh scanner findings; this handoff. Soak runner/promotion tests, rate middleware,
backpressure tests, load profile and execution ADRs are validation evidence only.
No speculative repair or promotion-criteria relaxation.

The job directory contained no `check-*.log` files at entry. The supplied older
`98a11313167b41a98a420abfda80c292/check-3.log` reports 24 DDL statements versus
21 expected. Assumption: reproduce that failure before modifying either side.
The dispatch snapshot supplies no selected immutable RC artifact/configuration;
a branch head is not assumed to be the artifact #89 would promote.

## Fresh results

- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  **37 passed, 6 skipped**. Historical failure does not reproduce. The current
  independent DDL list includes the three validation-audit columns at lines
  173–177; production upgrades them under the advisory transaction lock at
  `packages/maistro-core/src/maistro/persistence/pg_learnings.py:215`.
  Skipped PostgreSQL tests are not live concurrency evidence.
- Exact requested vulture command:
  `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`:
  **PASS**, 1322 findings / 1322 reviewed identities, zero unclassified and
  zero never-allowlist. No retained unbanked or eliminated identities exist to
  amend; changing the ledger would be unjustified.

## Architecture reconciliation

Read accepted ADR-081226-a66b, ADR-081426-1f7c, ADR-081626-f383 and ADR-085.
Preserve Goal -> Graph -> Run -> NodeRun -> Attempt. Runtime execution identity
is Attempt ID; Run-store leases own fencing. ADR-081626-f383 explicitly does
not establish lease-expiry takeover. Do not invent a new reclaim authority to
make a soak pass. ADR-085 requires principal keying, but does not prove shared
replica budgets. The production middleware documents process-local allowances;
that cannot be relabeled as #860's stronger replica-selection guarantee.

## Additional executed validation

All validation used long command timeouts (600 or 1200 seconds).

| Command | Outcome |
| --- | --- |
| `uv sync --locked --extra dev` | PASS: 256 resolved, 214 checked |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q` | 99 passed |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS: 3301 files already formatted |

The vulture invocation matches `.github/workflows/vulture-ratchet.yml:82–85`.
No test was added, removed or modified; no inventory delta is required.

## Acceptance audit

| Issue criterion | Executed evidence / residual gap |
| --- | --- |
| Representative RC load profile | UNVERIFIED. `m3a-load-profile.md:169` documents missing multi-user/Workspace, Graph fan-out, successful tool/model, Design/Canvas and Goal/background workloads. RC applicability remains unresolved. |
| Two deployed application replicas | UNVERIFIED. The executed middleware regressions use two ASGI instances, not deployed RC replicas. |
| Sustained saturation, queue growth, reclaim, retries and leaks | UNVERIFIED. Short source tests cannot establish sustained behavior; no production load was executed. |
| No duplicate physical work | UNVERIFIED. Admission checks do not prove physical Attempt execution uniqueness or Goal reconciliation under load. |
| Replica-selection-resistant rate/security/degraded behavior | NOT SATISFIED at the production middleware seam: `tests/test_soak_promotion_gates.py:439` passed for both identity types, observing `[200, 200, 429]` independently on each replica. `main.py:648` installs this middleware; `api/rate_limit.py:93` constructs a local limiter. Deployed security/degraded behavior otherwise UNVERIFIED. |
| Full telemetry and thresholds | UNVERIFIED. No fresh production PostgreSQL/application-loop/worker/RSS/FD/queue/error telemetry; driver-loop timing cannot stand in for application-loop latency. |
| Active-work restart, drain, fencing and recovery | UNVERIFIED. No deployed active-work restart was performed. |
| Long soak of exact RC artifact/configuration | UNVERIFIED. `scripts/soak/run_soak.py:744` explicitly rejects artifact equivalence. Executed CLI tests at `tests/test_soak_promotion_gates.py:106` reject missing, null and preflight artifact evidence even with synthetic four-hour duration; they are not four-hour load evidence. |
| Findings classified to earliest broken invariant | UNVERIFIED for completeness. Independent rate budgets are an enforcement prerequisite, not a throughput optimization. No GitHub filing is permitted. |
| Machine/human evidence tied to exact artifact/config hashes | UNVERIFIED for production soak. This note identifies source validation only, not promoted-image provenance. |

## Disposition

**BLOCKED.** The historical schema failure and presumed unbanked vulture debt
are absent at the assigned HEAD. Only this handoff changed; production code,
tests, ledgers and grants remain untouched. No conflict required a develop merge.
The previous blocked status cannot be resolved by inventing an RC identity or
repeating a preflight emulator that deliberately fails artifact equivalence.

Next: designate the immutable promotion artifact and normalized configuration,
settle the representative workload and replica-independent enforcement contract
through existing seams, then execute the long supported-topology soak with
physical-work observations and complete telemetry. Preserve current fail-closed
promotion checks. This local commit is not integration approval.

Progress: checked 1 issue; done 0 acceptance-complete; skipped 0 issues;
validation errors 0; next: blocked RC execution above.
