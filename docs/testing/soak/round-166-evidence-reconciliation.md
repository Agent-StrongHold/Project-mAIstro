# Issue #860 — evidence reconciliation (job 7ce45d12613341e0976ebf11a3103b44)

Scope frozen to issue #860 at `788b1e6b98072a0802968ec39949f25b36456d94`.
The assigned job directory had no `check-*.log` files. Prior validation's
statement that **every** pack used host uvicorn is incorrect: round 7/8 packs
record a locally built `deploy/docker-compose.prod.yml` stack with two server
containers; `evidence/m3a-round8-prodstack-extended.json` records a 1,200 s
window and two container image IDs. That is **not** a promotion run: its own
checks mark `sustain_duration.ok=false` (1,200 < 14,400 s) and
`exact_rc_artifact.ok=false` (no owner-designated RC), at git head
`20c975f3b617ac5caa8ac97a04c510ee21bbfdce`, not this branch's head.
Round 7 records shorter 360 s observation windows and has no promotion checks.
The host-process driver in `scripts/soak/run_soak.py` still fails its exact-RC
check without an override; a longer run of that driver cannot sign the RC.

The load profile previously said the current task route read only process-local
receipts. This is stale: `api/tasks.py` now calls `queue.get_shared(task_id,
user_id=owner)`, with shared Run-backed peer lookup exercised by
`packages/maistro-core/tests/tasks/test_cross_replica_receipt_reads.py`.
Updated the profile to distinguish current production wiring from historical
soak observations. This correction does **not** retroactively validate the
historical HTTP receipt coverage or provide a production latency measurement.

Executed at the starting head (documentation correction only afterward):

- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` — 181 passed, 6 skipped (PostgreSQL-dependent tests), 1 deprecation warning.
- `uv run pytest packages/maistro-core/tests/tasks/test_cross_replica_receipt_reads.py -x -q` — 18 passed.
- `uv run ruff check .` and `uv run ruff format --check .` — passed.
- `uv run python scripts/check-suite-inventory.py` — passed, 21 suites / 35,468 unique identities. No test additions; no inventory delta is required.
- Independent JSON scan of `docs/testing/soak/evidence/*.json` selecting packs with `sustain_duration` or `exact_rc_artifact` checks: 15 gate-bearing packs, **0** duration passes, **0** exact-RC passes, maximum recorded `observed_s` 1,200. The earlier 16-pack count used a different selection; do not treat either count as an RC-run denominator without a defined selection.
- `git diff --numstat f8a2df966a1d0db82be5fc08a571ed4750902c88..788b1e6b98072a0802968ec39949f25b36456d94 -- quality/ scripts/check-*.py` — no edits; no gate/ledger changes needed.

Acceptance disposition (not a waiver): representative users/Workspaces and
Graph/tool/Canvas/Goal workload, promotion-grade pool/worker/event-loop/lease
telemetry, sustained physical Attempt fencing and active-work drain/recovery
remain unproven (`m3a-load-profile.md`, Remaining representative-profile gaps).
The six-path rate probe proves per-replica 429s, not non-bypass of a shared
principal budget: `api/rate_limit.py` explicitly stores process-local state;
`test_replica_selection_has_an_independent_production_allowance` passes when
selection grants a second allowance. ADR-085 requires per-principal limits but
is silent on cluster aggregation; owner ruling is outstanding. F3/F2 filing /
reclassification is not established by the existing evidence; no GitHub
mutations were made. Before promotion: designate the immutable RC, settle the
rate-limit scope, cover the missing workload/invariants, run >= 4 h on its
production configuration with hash-bound machine/human evidence, and file or
reclassify findings to their earliest broken invariant. No production soak was
executed in this validation round.
