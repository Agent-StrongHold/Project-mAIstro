# Issue #860 repair checkpoint — 14b5e8e2

## Frozen scope

- Only issue #860, branch `auto-860`, starting HEAD
  `67f8efb43fb1a29d62f19cd641b6bb07a58fc4fa`, supplied base
  `ac7370141e8e61bd6f352bca35ed0b505104aadb`.
- Inputs: supplied dispatch-context.json, prior result f7f78b55 and failed
  check-3.log from job 98a11313; no GitHub re-enumeration or mutation.
- Planned changes: this evidence/handoff file; only if reproduced and reviewed,
  `quality/vulture-baseline.json` and the exact source identities implicated by
  the required vulture scan. No unrelated repair or authorization changes.
- Worktree initially clean; exact HEAD verified. No incoming salvage needed.
- Role assumption: writer (explicit assigned repair); verifier-only prohibition
  does not apply. No current-job check logs existed at initial inspection.

## Progress

Acceptance body inspected in supplied dispatch snapshot. Full production soak
acceptance is not inferred from previous attempts or unit tests.

- Required exact-argument vulture scan: exit 0, 1322 reviewed identities and
  1322 findings, zero unclassified. No ledger repair is warranted.
- Historical check-3.log inspected: schema-fence expected 21 versus 24 DDL
  statements. Current test already includes all three validation audit columns.
  Fresh scoped learnings test command exited 0 (details below).
- Prior result is BLOCKED on exact-RC designation and production evidence, not
  a develop merge conflict. No fetch/merge is warranted.
- Scope decision: no demonstrated source/test/ledger defect to repair. Finish
  focused acceptance validation and commit this blocked handoff, without
  manufacturing a scanner finding or weakening the exact-RC gate.

## Fresh validation

All commands used timeouts of 1200 seconds. Logs are in the supplied job directory
(`/home/dev/maistro/jobs/14b5e8e295e04a3cad1f84f73e63e354/worker-*.log`).

| Command | Outcome |
|---|---|
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS; 1322/1322 identities, zero unclassified |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 37 passed, 6 skipped; skipped PostgreSQL coverage is not claimed |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS; 3301 files formatted |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-core/tests/runs/test_execution_fencing.py packages/maistro-core/tests/graph/durable_runs/test_recovery_disposition.py -x -q` | 93 passed |
| `uv run python scripts/check-backlog-consistency.py` | PASS; 168 items |

No tests were added or changed; no inventory delta is required. Only this handoff
changed. No fresh load experiment, image deployment, or production soak was run.

## Architecture and production reachability

Read repository AGENTS.md, docs/README.md and accepted ADR-081426-1f7c,
ADR-081626-f383, ADR-082526-b36a. The latter defines optional TTL, fenced renewal
and reclamation beyond the earlier fence-only contract. Restart does not prove
worker death; canonical Attempt ownership and physical-effect observations are
required. No alternate execution/scheduling authority or policy change is made.

- `pg_learnings.py:215-216` encloses schema upgrades in a transaction with the
  advisory lock first. Current `test_pg_learnings.py:172-174` includes the three
  validation audit columns missing from the historical failed expectation.
- `maistro_server/main.py:648` installs the actual process-local middleware
  (`api/rate_limit.py:32`). The executed regression at
  `tests/test_soak_promotion_gates.py:439` gets `[200,200,429]` independently on
  both instances for the same identity. This is not proof of deployed ingress
  bypass, nor proof of a cluster-wide budget.
- `main.py:735,755` mounts the task router. `api/tasks.py:144` reads `queue.get`.
  The executed production-router probe at `tests/test_soak_promotion_gates.py:564`
  observes receipt 200 locally and 404 on the peer, using a shared canonical
  admission spine. These ASGI checks are not deployed replicas.
- `scripts/soak/run_soak.py:744-755` always rejects exact-RC equivalence for host
  preflight. Executed promotion regressions reject it even with a synthetic
  four-hour duration. This gate must not be bypassed.

## Acceptance assessment

| Issue acceptance criterion | Evidence and remaining requirement |
|---|---|
| Representative RC users/Workspaces/request mix/fan-out/workers | UNVERIFIED. Read `m3a-load-profile.md`; documented one-key preflight lacks Workspace population, Graph fan-out, successful tool/model, Design/Canvas and sustained Goal workloads. RC applicability needs designation. |
| At least two deployed application replicas | UNVERIFIED. Fresh checks use ASGI instances, not deployed production replicas. |
| Sustained saturation/queues/reclaim/backoff/leaks | UNVERIFIED. No sustained experiment or production resource series executed. |
| Schedule/task/Run/Attempt/Goal physical-work uniqueness | UNVERIFIED. Fencing/recovery tests pass; neither admission identity nor terminal state counts prove physical-effect uniqueness under load. |
| Replica-resistant rate/security/degraded behavior | UNVERIFIED overall. Actual middleware gives independent local allowances; task backpressure tests pass. No production ingress concurrency experiment. |
| Required telemetry and explicit thresholds | UNVERIFIED. Profile documents thresholds; driver-loop latency is not application-loop latency. No fresh production telemetry. |
| Active-work kill/restart and drain/fencing/recovery | UNVERIFIED. No process interruption executed; peer receipt visibility limitation reproduced. |
| Long soak of exact RC artifact/configuration | UNVERIFIED. Assignment does not designate immutable RC image/effective configuration; existing host runner explicitly fails this gate. |
| Findings classified to earliest broken invariant | UNVERIFIED for completeness. Backlog consistency passes, but no new load/classification audit. No GitHub mutations permitted or performed. |
| Machine/human evidence tied to image/package/commit/config hashes | UNVERIFIED for production acceptance. This records local source HEAD and validation only, not an RC evidence pack. |

## Disposition

BLOCKED on production acceptance. Both supplied deterministic repair triggers
are presently clean; changing tests, source or the ledger would not address an
observed failure. The prior block cannot be resolved by another unit-test run.
Next action: designate immutable RC images and effective configuration, complete
the workload applicability matrix, resolve replica-budget/receipt constraints,
and execute at least four hours with active-work interruption, production
telemetry and canonical physical-effect/fence observations. Publish hash-bound
machine/human evidence and classify actual failures before promotion.

Progress: checked 1 issue, done 0 acceptance-complete, skipped 0 issues, errors 0
validation commands. This local commit is a blocked handoff, not integration
approval. Do not redispatch the historical schema/vulture failure without fresh
failing evidence.
