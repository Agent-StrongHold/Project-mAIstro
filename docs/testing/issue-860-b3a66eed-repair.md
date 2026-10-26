# Issue #860 repair checkpoint — b3a66eed

## Frozen scope

One item: issue #860 on `auto-860`, starting at
`2a93aa168b3522600c6c10563022b6f68b613846`; supplied comparison base
`2154f845347c9541016288c760f8da3f5cd2e064` resolves. Worktree started clean.
No GitHub mutations or ref changes are planned.

Read scope: supplied dispatch snapshot and prior failure/result; repository
instructions; execution, fencing, rate-limit and measurement ADRs;
`scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`,
`docs/testing/soak/m3a-load-profile.md`, relevant server backpressure tests,
vulture checker and CI invocation. Conditional edit scope: genuinely dead
identities reported by the requested scanner, reviewed vulture ledger entries,
and this report. No speculative runtime or scheduler changes.

Ambiguity: dispatch requests CI repair but supplies an earlier BLOCKED soak
result. Treat the scanner failure and production acceptance as separate claims;
passing CI will not establish deployed soak acceptance. No current-job
`check-*.log` files were present in the initial directory snapshot.

Initial checkpoint: assigned refs resolved; no incoming uncommitted work needs
salvage.

## Reproduced results

- Requested vulture command passed: 1323 findings / 1323 reviewed identities,
  zero unclassified and never-allowlist findings. No unbanked identity exists
  to repair or amend in this run; changing the ledger would be unjustified.
- Supplied historical `check-3.log` is not a vulture failure. It reports
  `test_pg_learnings.py:186` expecting 21 schema statements and receiving 24.
  Reproduction against this head is next.
- Read accepted ADR-081626-f383 (canonical durable lease owner), ADR-085
  (principal-keyed limits), and ADR-083026-a91e (absent metrics are not zero).
  No contract permits interpreting bounded admission/fencing checks as a
  sustained physical-work uniqueness proof.
- The profile explicitly calls this a host-process preflight, not the promoted
  Compose artifact. Its remaining-gaps section excludes representative users,
  successful tools/models, fan-out and Goal reconciliation. Those are acceptance
  gaps, not reasons to weaken the promotion gate.

## Focused validation (executed this round)

All validation commands used 600/1200-second timeouts.

| Command | Result |
| --- | --- |
| `uv sync --locked --extra dev` | PASS; 256 resolved, 214 checked |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS; 1323/1323; matches `.github/workflows/quality.yml:1078` |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS; 3277 files |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-core/tests/runs/test_execution_fencing.py packages/maistro-core/tests/graph/durable_runs/test_recovery_disposition.py -x -q` | PASS; 130 passed, 6 skipped in 2.91 s |
| `uv run python scripts/check-deployment-claims.py` | PASS; static component-existence check, not deployment acceptance |
| `uv run python scripts/check-execution-lifecycles.py` | PASS; 19 classified / 19 discovered |
| `git diff --check` | PASS |

The old schema failure does not reproduce. The current test independently lists
all three additional audit columns at `test_pg_learnings.py:175–177` and verifies
the complete ordered DDL body inside the advisory-lock transaction. No test or
production change is justified by that historical failure.

One exploratory read used a nonexistent `maistro_server/middleware/rate_limit.py`
path (not found; skipped). The test's actual import identifies
`maistro_server/api/rate_limit.py`; that source was read successfully. It creates
`InMemoryRateLimiter` at line 93. Production `main.py:648` installs this middleware.
The executed regression at `tests/test_soak_promotion_gates.py:439` demonstrates
`[200, 200, 429]` independently on both instances with the same identity, for both
authenticated and unauthenticated requests. This is a real production middleware
seam, but ASGI instances are not deployed RC replicas.

Read accepted renewal/recovery ADR-082526-b36a and ADR-082826-08f0 as well: they
extend the original lease contract with liveness-based reclaim and canonical
reconciliation. Stale-write fencing does not establish unique physical work.
No alternate execution, Goal, authorization or event authority was introduced.
The documented process-local limiter contract does not waive #860's stronger
replica-selection criterion.

## Acceptance disposition

| #860 criterion | Evidence / disposition |
| --- | --- |
| Representative RC workload | UNVERIFIED. Profile exists but explicitly lacks multi-user/Workspace, fan-out, successful model/tool, Design/Canvas and Goal/background coverage; no selected RC applicability justification supplied. |
| At least two deployed replicas | UNVERIFIED. Read production Compose's two declared server services; executed tests use ASGI instances, not deployed images. |
| Sustained saturation, growth, reclaim, retries, leaks and shutdown | UNVERIFIED. Bounded tests completed in seconds; no sustained production series generated. |
| No duplicate schedule/task/Run/Attempt physical work; Goal reconciliation | UNVERIFIED under load. Fencing/recovery and admission regressions pass; physical-work uniqueness and Goal reconciliation were not exercised in a deployed soak. |
| Rate/security/degradation cannot be bypassed by replica selection | NOT SATISFIED at the tested middleware seam: each instance supplies a fresh allowance. Full deployed security/degraded behavior remains UNVERIFIED. |
| All required telemetry and pass/fail thresholds | UNVERIFIED. Profile defines thresholds, but no fresh complete PostgreSQL, application-loop, worker, RSS/fd, queue and error/timeout production series exists in this round. Driver-loop latency is not application-loop latency. |
| Active-work replica kill/restart with drain/fencing/recovery | UNVERIFIED under deployed load. Bounded recovery tests are not this experiment. |
| Long exact-RC/config soak, repeated after changes | UNVERIFIED. `run_soak.py:744` explicitly returns `exact_rc_artifact.ok=false`; executed CLI regressions at `test_soak_promotion_gates.py:103` reject even synthetic four-hour preflight evidence. |
| Load findings classified before promotion | UNVERIFIED for completeness: no representative sustained experiment was run. This report records the confirmed limiter gap without remote mutations. |
| Human/machine evidence bound to image/package/commit/config hashes | UNVERIFIED. This source-head validation report is not an exact-RC soak evidence pack. |

## Handoff

**BLOCKED** on production acceptance, not the supplied historical CI failure.
Only this report changed. No new tests, so no inventory delta is required;
no ledger/grant edits, no gate weakening, no remote mutations.

Next requires designation of the immutable RC image/configuration and applicable
workload, resolution of the cluster-budget prerequisite at existing canonical
identity/limiter seams, and a fresh exact-RC soak (profile minimum four hours)
with active-work failure/recovery and physical-work observations. Neither another
identical ledger repair nor a longer host preflight can supply those facts.
Do not redispatch this same CI-repair claim without a new failing command or new
RC/workload inputs. The previous BLOCKED outcome remains unresolved.

Progress: checked 1 issue; acceptance-complete 0; skipped 0 issues;
validation failures 0. Local report commit is a checkpoint, not integration
approval. Next: the production-soak prerequisites above.
