# Issue #860: a37ec9aa validation handoff

## Scope and disposition

**BLOCKED — no reproducible CI repair; production acceptance incomplete.**
One frozen item: #860 in `auto-860`, starting at
`4c7816981580500d293aa66b12c314c03d4e7233`, against resolved supplied base
`321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62`. Starting worktree was clean.
This report is the only change. No source, tests, inventory counts, ledger,
grant, gate or runtime configuration changed. No GitHub mutations or ref refresh.

Read repository instructions, supplied dispatch issue/recent comments/PR bodies,
prior eb06b9bb result and its report, and the cited historical failure log.
No `check-*.log` existed in the current job directory at initial inspection.
Prior claims were not accepted as verification; the checks below were rerun.

## Fresh validation

All commands used a 1200-second timeout and exited 0. Logs are retained under
`/home/dev/maistro/jobs/a37ec9aa84494a5eb2f7e40701a3dfc1/`.

| Command | Executed result | Log |
| --- | --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | 1322 findings / 1322 reviewed identities; zero unclassified or never-allowlist findings | `worker-vulture.log` |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 37 passed, 6 skipped | `worker-schema.log` |
| `uv run ruff check .` | PASS | `worker-ruff.log` |
| `uv run ruff format --check .` | PASS, 3301 files | `worker-format.log` |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q` | 99 passed | `worker-soak-tests.log` |
| `uv run python scripts/check-ratchet-provenance.py` | PASS, 53 quality JSON consumers have explicit provenance | `worker-provenance.log` |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS | `worker-shipped-surface.log` |

The supplied `98a11313167b41a98a420abfda80c292/check-3.log` fails a schema
expectation (24 statements versus 21), not vulture. The current test at
`packages/maistro-core/tests/persistence/test_pg_learnings.py:175` already lists
the three Gauntlet columns missing from that historical expectation. Its fresh
suite passes. No ledger amendment or test weakening is justified by these results.
Database-dependent skips are not production acceptance evidence.

## Reachable behavior and architectural boundaries

Read accepted ADR-081226-a66b, ADR-081426-1f7c, ADR-081626-f383,
ADR-082526-b36a and ADR-085. Preserve Goal -> Graph -> Run -> NodeRun ->
Attempt. The later b36a contract authorizes fenced renewal/reclaim, extending
f383; `packages/maistro-core/src/maistro/container.py:1260` calls the canonical
reclaim seam. No new execution, scheduling, persistence or authorization owner
is warranted here. Reclaim is supported, but was not exercised under load.

`packages/maistro-server/src/maistro_server/main.py:648` registers the production
rate middleware. Its constructor at `api/rate_limit.py:93` creates an in-memory
limiter. The executed regression at `tests/test_soak_promotion_gates.py:439`
observes `[200, 200, 429]` independently on each middleware instance for the same
identity, both authenticated and unauthenticated. This proves local allowances,
not the supported deployment's full ingress posture or a shared principal budget.
The production-router test at line 569 also observes a peer-local receipt 404.
ASGI instances with a shared admission spine are not deployed production replicas.

`scripts/soak/run_soak.py:744` always marks the host-process preflight as not the
exact RC artifact. Executed CLI regressions reject missing/null/preflight artifact
records even with simulated four-hour evidence. Keep this fail-closed gate intact.

## All ten acceptance criteria

| Criterion | Disposition and evidence boundary |
| --- | --- |
| Representative RC profile | UNVERIFIED: `docs/testing/soak/m3a-load-profile.md:165` lists missing users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and Goal/background work. Applicability must be bound to the selected RC. |
| At least two deployed application replicas | UNVERIFIED: this round ran ASGI regressions, not the production topology. |
| Sustained saturation, growth, reclaim, retries and leaks | UNVERIFIED: short tests cannot substitute for sustained observations. |
| No duplicated physical work across replicas | UNVERIFIED: admission identities and receipt visibility do not prove physical Attempt or Goal work uniqueness. |
| Replica-selection-resistant rate/security/degraded behavior | UNVERIFIED for deployment; independent allowances reproduced at the production middleware seam, so local 429s cannot establish the stronger criterion. |
| Required telemetry with thresholds | UNVERIFIED: no fresh production series for PostgreSQL contention, application-loop lag, worker counts, RSS/FD, queue depth and error/timeout rates. |
| Active-work kill/restart, drain/fencing/recovery | UNVERIFIED: no real production work was killed/recovered this round. |
| Long soak of exact RC artifact/configuration | UNVERIFIED: no immutable promotion target supplied; existing runner is explicitly preflight-only. |
| Findings classified to earliest broken invariant | UNVERIFIED for completeness; rate/receipt prerequisites documented locally, no remote filing performed. |
| Hash-bound machine/human production evidence | UNVERIFIED: these source-bound validation logs and this report are not an exact-image/configuration soak bundle. |

## Next required input

Provide the immutable RC image/package and normalized deployment configuration,
with the representative workload's applicability decisions. Resolve or explicitly
reconcile the observed replica-local enforcement/receipt prerequisites through
existing production seams, then run the long production soak with physical-work
correlation, recovery and all required telemetry. Another host preflight or ledger
edit cannot establish that evidence. Do not re-dispatch the historical schema
failure or a clean exact-debt scan as an actionable repair without new findings.

Checkpoint: checked 1 issue; acceptance-complete 0; skipped 0; validation errors 0.
Writer handoff only; no integration approval.
