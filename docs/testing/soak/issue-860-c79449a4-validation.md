# Issue #860 — repair disposition, job c79449a4

## Frozen scope

Only issue #860, branch/worktree `auto-860`, starting HEAD
`3ef326b229c1fd51f4ebd8eccf0c5f27dd8d0a0f`, supplied develop base
`321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62`. Starting tree clean; no conflict
or incoming edits to salvage. No GitHub mutations or ref changes performed.
This report is the only changed file. No tests added or changed, so no suite
inventory delta. No production, ledger, grant, or gate edits are justified.

**BLOCKED for acceptance, not for the requested CI repair.** The exact vulture
scan passes without amendments. The supplied historical failure at
`98a11313167b41a98a420abfda80c292/check-3.log` expected 21 schema statements
instead of 24; the current test explicitly covers all three validation-audit
columns and passes. The current job directory contained no `check-*.log` files.
Prior verification claims were not treated as executed evidence for this round.

Read repository instructions, the supplied issue body, prior result and failure,
load profile, adjacent tests, production task/rate middleware and Compose wiring,
and accepted ADR-081426-1f7c, ADR-081626-f383, ADR-082526-b36a. The latter adds
renewal/reclamation to the earlier fencing boundary, not another execution
authority. Preserve Goal -> Graph -> Run -> NodeRun -> Attempt. Admission
uniqueness does not establish physical-work uniqueness.

## Fresh validation

Executed in this worktree with 1200-second timeouts; all checks passed:

| Command | Result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | 1322 reviewed identities / 1322 findings; unclassified and never-allowlist both 0 |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 37 passed, 6 skipped |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q` | 99 passed |
| `uv run ruff check .` | Passed |
| `uv run ruff format --check .` | 3301 files already formatted |
| `uv run python scripts/check-ratchet-provenance.py` | 53 quality consumers covered; nonfatal SyntaxWarnings |
| `uv run python scripts/check-shipped-surface-truth.py` | Matrix complete |

The six skips are not live PostgreSQL proof. No production soak was run.

## Acceptance evidence and limits

The production application installs `RateLimitMiddleware` at
`packages/maistro-server/src/maistro_server/main.py:648`; its constructor creates
an `InMemoryRateLimiter` at `api/rate_limit.py:93`. Fresh execution of
`tests/test_soak_promotion_gates.py:439` reproduced independent `[200,200,429]`
allowances for one identity on two instances (authenticated and unauthenticated).
The production-router probe at line 569 reproduced an admitted receipt's peer
404, consistent with `api/tasks.py:145` reading its queue. These are ASGI probes,
not two deployed replicas or proof about the complete deployed ingress policy.

| Acceptance criterion | Disposition |
| --- | --- |
| Representative RC profile | UNVERIFIED: `m3a-load-profile.md:165` identifies missing users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas and reconciliation workloads. Applicability to the selected RC remains unresolved. |
| At least two deployed replicas | UNVERIFIED: Compose declares two; local ASGI instances are not deployment evidence. |
| Sustained saturation, queue growth, reclaim, retry/backoff and resource leaks | UNVERIFIED: regression tests do not supply a sustained production observation window. |
| No duplicate physical schedule/task/Run/Attempt/Goal work | UNVERIFIED: admission/receipt tests do not measure physical work across failure/recovery. |
| Replica-selection-resistant rate/security/degraded enforcement | UNVERIFIED for deployment: independent local allowances reproduced, not a shared principal budget. |
| PostgreSQL/app-loop/worker/RSS/FD/queue/error telemetry and thresholds | UNVERIFIED: no fresh production time series; driver-loop latency is not app-loop latency. |
| Kill/restart during active work with drain/fencing/recovery | UNVERIFIED: no production replica kill/restart performed. |
| Long exact-RC soak | UNVERIFIED: `scripts/soak/run_soak.py:744` deliberately rejects equivalence for its host-process runner; passing tests preserve that gate. |
| Complete earliest-invariant classification of load findings | UNVERIFIED: existing findings are documented, but no new representative production window establishes completeness. No remote filing authorized. |
| Hash-bound machine/human production evidence | UNVERIFIED: these source-bound checks are not an RC image/config-bound soak bundle. |

## Handoff / unresolved input

The supplied assignment does not select the immutable RC artifact and normalized
runtime configuration that #89 would promote. `deploy/docker-compose.prod.yml:11`
explicitly calls itself a reference requiring pinned digests and builds application
images from source. Assumption: do not silently choose a promotion target or call
preflight evidence production evidence. A longer preflight cannot repair this.

Next: obtain the RC selection and workload applicability, resolve receipt and
policy prerequisites through canonical owners, instrument physical execution and
production telemetry, then run the required long soak plus recovery exercise.
Repeated dispatch of the already-passing vulture/schema repair cannot close these
acceptance gaps. No speculative production repair or ledger amendment made.

Progress: checked 1 issue; acceptance-complete 0; skipped issues 0; validation
failures 0. This committed report is a blocked handoff, not integration approval.
