# Issue #860 — fresh validation, job 3105294a

## Scope and disposition

**BLOCKED: production acceptance remains unverified.** Checked only issue #860
in assigned worktree `auto-860`, starting at verified clean HEAD
`7cf3e2f0fff1c7501cef56dd009cfcfc45fe128e`, against assigned base
`321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62`. No merge conflict existed.
Read the supplied dispatch snapshot, prior result and cited prior failure.
There were no driver `check-*.log` files in this job directory at inspection.

The cited historical `check-3.log` expected 21 schema statements instead of 24.
Current `packages/maistro-core/tests/persistence/test_pg_learnings.py:173`
already includes the three validation-audit columns. Fresh execution passes;
no further test weakening or production change is warranted.
The exact requested vulture scan also passes: no unbanked identities to repair.
No ledger edits, test additions, inventory delta, or runtime changes were made.
This validation report is the only repository change this round.

Read accepted ADR-081426-1f7c, ADR-081626-f383 and ADR-082526-b36a. The latter
extends the former lease boundary with heartbeat/reclamation; it does not
permit another execution authority. Preserve Goal -> Graph -> Run -> NodeRun
-> Attempt. Admission uniqueness is not proof of physical-work uniqueness.

## Executed validation

All commands below exited 0, with a 1200-second command timeout. Logs live in
`/home/dev/maistro/jobs/3105294aa7b441c6802c02cc8fe7a30f/`.

| Command | Result / log |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | 1322 reviewed / 1322 observed; unclassified 0; never-allowlist 0; `worker-vulture.log` |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 37 passed, 6 skipped; `worker-schema.log` |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q` | 99 passed; `worker-soak-tests.log` |
| `uv run ruff check .` | passed; `worker-ruff.log` |
| `uv run ruff format --check .` | 3301 files formatted; `worker-format.log` |
| `uv run python scripts/check-ratchet-provenance.py` | 53 quality consumers covered; `worker-provenance.log` (nonfatal SyntaxWarnings) |
| `uv run python scripts/check-shipped-surface-truth.py` | matrix complete; `worker-surface.log` |

The six skipped schema tests are not live PostgreSQL evidence. No full-tree
pytest run or production soak was performed. Passing local checks is not
integration approval.

## Acceptance against reachable behavior

`maistro_server/main.py:648` installs the real rate middleware, which constructs
an in-memory limiter at `api/rate_limit.py:93`. Executed tests at
`tests/test_soak_promotion_gates.py:439` reproduce independent `[200, 200, 429]`
allowances on two instances for one identity, authenticated and unauthenticated.
The production-router test at line 569 observes a receipt on its originating
queue and a 404 on its peer. These are meaningful ASGI probes, not deployed
replicas; they do not establish whether the deployed ingress policy is safe.

`scripts/soak/run_soak.py:744` always rejects exact-RC equivalence for the
host-process runner; executed tests preserve the rejection. The reference
Compose file (`deploy/docker-compose.prod.yml:11`) asks operators to pin image
digests and builds application images from source. Neither that file nor this
assignment selects the immutable artifact/configuration #89 would promote.
Assumption: do not invent that selection or relabel preflight as production.

| Issue criterion | Evidence and remaining boundary |
| --- | --- |
| Representative RC load profile | UNVERIFIED. `m3a-load-profile.md:165` lists absent multi-user/Workspace, Graph fan-out, successful tool/model, Design/Canvas and Goal/background workloads. RC applicability is unresolved. |
| At least two deployed application replicas | UNVERIFIED. Compose declares two; executed ASGI tests are not deployment evidence. |
| Sustained saturation, queue growth, reclaim, retry/backoff, memory/FD/process leaks | UNVERIFIED. Short regression runs do not observe a sustained production window. |
| No duplicated physical schedule/task/Run/Attempt/Goal work | UNVERIFIED. Receipt/admission checks cannot establish physical-work uniqueness. |
| Replica-selection-resistant rate/security/degraded behavior | UNVERIFIED for deployment. Independent local allowances freshly reproduced, not a shared principal budget. |
| Required PostgreSQL/application/worker/resource/queue/error telemetry and thresholds | UNVERIFIED. No fresh production time series; driver-loop latency is not application-loop latency. |
| Active-work replica kill/restart, drain/fencing/recovery | UNVERIFIED. No production replica killed or recovered this round. |
| Long soak of exact promoted artifact/config | UNVERIFIED. Exact RC selection absent; preflight gate deliberately rejects equivalence even at long duration. |
| Findings classified to earliest broken invariant | UNVERIFIED for completeness. Existing local allowance/receipt prerequisites remain; no GitHub mutations authorized or performed. |
| Machine/human evidence bound to image/package/commit/config hashes | UNVERIFIED for production. Source-bound regression logs are not a hash-bound RC soak bundle. |

## Handoff

Checked 1 issue; acceptance-complete 0; skipped issues 0; validation failures 0.
Next required input: immutable RC artifact and normalized deployment config,
representative workload applicability, and production-path instrumentation and
recovery proof. Resolve policy/receipt prerequisites through existing canonical
owners; then execute the required long soak. Repeating a clean scanner cannot
resolve those prerequisites. Do not weaken promotion gates or issue closure
criteria to turn this blocked handoff into approval.
