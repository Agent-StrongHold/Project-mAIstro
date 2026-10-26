# Issue #860 — repair job 8ac1be3b

## Frozen scope

- Only issue #860, branch `auto-860`, assigned worktree `/home/dev/Git/wt/auto-860`.
- Starting HEAD `3eca70985598666ee377168f4ae27ed0bcf15736`; supplied base `2154f845347c9541016288c760f8da3f5cd2e064` resolves.
- Initial tree clean; no salvage patch needed.
- Repair candidates frozen: `packages/maistro-core/tests/persistence/test_pg_learnings.py`, corresponding `packages/maistro-core/src/maistro/persistence/pg_learnings.py`, `quality/vulture-baseline.json` only if actual scanner findings require authorized repair, this report, and an inventory note if tests change.
- Read-only acceptance inspection: supplied dispatch snapshot and prior result/log; `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`, existing load profile/evidence and applicable ADRs/quality instructions. No GitHub refresh or mutation.

## Initial evidence and assumptions

The current job directory contains no `check-*.log` files. The supplied prior
`98a11313167b41a98a420abfda80c292/check-3.log` reports an expected-DDL length
mismatch (21 expected, 24 actual). This is historical evidence, not assumed to
remain reproducible. The supplied prior result is BLOCKED on release-candidate
soak acceptance. This is a CI-repair assignment, not permission to invent
release identity or production evidence. Validate the exact scanner before
considering ledger changes. Broad acceptance gaps will be recorded rather than
replacing canonical execution or weakening promotion checks.

## Fresh results

- `uv sync --locked --extra dev`: PASS.
- Exact requested vulture command: PASS, 1323 reviewed identities and 1323
  findings, zero unclassified/never-allowlisted. No ledger amendment justified.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  PASS, 37 passed / 6 skipped. Historical failure does not reproduce. The current
  independent expected-DDL list includes the three Gauntlet audit columns, and
  production executes all 24 upgrades inside the advisory-locked transaction.
  No speculative test or production edit is justified.
- Read all ten acceptance criteria from the frozen issue body. Full RC soak
  remains a separate requirement; skipped PostgreSQL tests are not live proof.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3277 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q`:
  PASS, 80 passed. This includes authenticated/unauthenticated tests showing
  independent `[200, 200, 429]` allowances on both real middleware instances;
  these are ASGI tests, not a deployed two-replica soak.

## Architecture reconciliation

Read accepted ADR-081226-a66b (canonical lifecycle), ADR-081626-f383 (execution
leases/fencing), and ADR-085 (principal rate limits). The first two retain
Run/NodeRun/Attempt authority and explicitly do not define automatic lease-expiry
takeover. The issue's reclaim requirement does not authorize a competing recovery
scheduler or implicit takeover. ADR-085 requires principal rate limiting; passing
per-replica rejection probes cannot establish the issue's aggregate non-bypass
claim. No authority or execution-model changes made.

## Additional executed validation

All validation commands used a 1200-second timeout.

- `uv run pytest packages/maistro-server/tests/api/test_rate_limit.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  PASS, 27 passed.
- `uv run python scripts/check-backlog-consistency.py`: PASS, 168 items.
- `uv run python scripts/check-adr-index.py`: PASS.
- `uv run python` loading `scripts/soak/run_soak.py` with `runpy.run_path`:
  asserted `preflight_artifact_check()['ok'] is False`; loaded historical
  `docs/testing/soak/evidence/m3a-round6-shakedown.json` and asserted its failed
  promotion checks include `sustain_duration` and `exact_rc_artifact`. PASS;
  printed exactly those two failures. This validates rejection, not acceptance.
- `.github/workflows/vulture-ratchet.yml:82` confirms the requested scanner
  arguments match CI. No unbanked or eliminated identities to amend.

## Acceptance audit

| Issue criterion | Fresh evidence / disposition |
| --- | --- |
| Representative RC load profile | `m3a-load-profile.md:162` lists missing multiple users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and Goal workers. Complete representative profile UNVERIFIED. |
| At least two deployed application replicas | Tests exercise two middleware instances, not deployed RC replicas. UNVERIFIED. |
| Sustained saturation, queues, reclaim, retries, leaks, shutdown | No new soak; historical short run freshly rejected. Long-window behavior UNVERIFIED. |
| No duplicate physical work across schedule/task/Run/Attempt/Goal paths | `run_soak.py:1067` cancels admission probes without executing physical work. Gate tests are not physical-effect evidence. UNVERIFIED. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | `main.py:648` installs the production middleware; `api/rate_limit.py:93` constructs a process-local limiter. Passing `test_soak_promotion_gates.py:439` reproduces independent allowances for the same identity on both instances. Aggregate non-bypass NOT MET; deployed security/degraded behavior UNVERIFIED. |
| Required telemetry and explicit thresholds | Profile has partial thresholds; driver loop lag is not application loop lag, and receipt reads are process-local. Complete RC telemetry UNVERIFIED. |
| Kill/restart during active work with drain/fencing/recovery | No live active-work restart performed; rejoin and terminal counts do not prove physical recovery. UNVERIFIED. |
| Long soak of exact RC artifact/configuration | `run_soak.py:744` rejects host-process topology by construction; freshly executed gate confirms this. Exact immutable RC/config soak UNVERIFIED. |
| Findings classified to earliest invariant | Local backlog consistency PASS; complete load-derived classification UNVERIFIED. No GitHub mutations. |
| Machine/human evidence bound to image/package/commit/config hashes | This report is local validation, not newly generated production soak evidence. UNVERIFIED. |

## Final disposition and handoff

**BLOCKED**. Checked 1 assigned issue; acceptance-complete 0; skipped issues 0;
failed validation commands 0; blocked issues 1. The alleged CI failure is already
fixed and the exact-debt ledger passes. Repeating CI-repair dispatch cannot supply
the missing production acceptance. No code, tests, ledger or inventory edits are
warranted by current evidence; this report is the sole changed file.

Next required work is a selected immutable RC image/configuration and complete
representative workload, resolution of aggregate rate-policy acceptance versus
existing process-local enforcement, canonical physical-effect/fencing/recovery
observations, and a >=4-hour exact-RC soak with hash-bound evidence. Do not run
the host-process emulator longer and relabel it production proof. Do not introduce
implicit lease takeover contrary to the accepted fencing ADR. No new tests were
added, so no inventory delta is required. All inherited work is preserved.
