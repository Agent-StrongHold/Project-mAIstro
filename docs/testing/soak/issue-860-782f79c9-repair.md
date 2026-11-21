# Issue #860 repair — job 782f79c9

## Frozen scope

Only issue #860, branch `auto-860`, starting head
`a91f0c4e45db22157326537c4c6f32be525229e0`, base
`ac69535ef165ded3ca82cd3428728569de3251fa`. Initial worktree clean.
No PR processing, GitHub mutations, or develop synchronization requested by
observed conflict state (none).

Files in scope for potential repair: `quality/vulture-baseline.json` (explicit
CI-repair exception), `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`,
the associated inventory note if tests change, and this report. Surrounding
production code, ADRs, existing evidence, and supplied prior job logs are read-only
inspection inputs. Expand implementation scope only with recorded actual evidence.

Current job directory contains no driver `check-*.log` files. Supplied prior
`check-3.log` and result artifact will be inspected. Ambiguity: this is a writer
repair assignment, so the verifier-only prohibition on edits does not apply.

## Progress

- Snapshot frozen; head verified; no uncommitted work to salvage.
- Acceptance criteria extracted from supplied dispatch snapshot; no remote refresh.
- Exact requested Vulture scan passed: 1323 reviewed identities / 1323 findings,
  zero unclassified or never-allowlist. No ledger amendment is justified.
- `uv run ruff check .` passed; `uv run ruff format --check .` passed (3277 files).
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q`
  passed: 118 passed, 6 skipped, 2.64 seconds (1200-second command timeout).
- Prior check-3.log showed a 24-versus-21 DDL expectation mismatch. The current
  focused suite does not reproduce it. Skipped database tests are not soak proof.
- Existing runner/profile explicitly distinguish host preflight from an exact-RC
  soak. Inspection and executed tests confirm the blockers below; no speculative
  source edits.

## Architecture reconciliation

Read repository `AGENTS.md`, `docs/README.md`, ADR-082826-b601 (Accepted),
ADR-085 (Accepted), and ADR-081 (Proposed, not overriding authority).
Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`: canonical consumption uses
lifecycle transition-as-claim and the existing execution service, not another
scheduler. Admission uniqueness cannot establish physical Attempt fencing.
ADR-085 requires principal-keyed rate limits; it does not establish shared replica
budgets. The existing process-local implementation is not proof of #860's stronger
replica-selection criterion. No architectural or acceptance waiver is applied.

The supplied historical failure is already covered by the current independent
24-statement expectation at
`packages/maistro-core/tests/persistence/test_pg_learnings.py:161`, including
validation audit columns. Production `ensure_schema` acquires the transaction
advisory lock before DDL at
`packages/maistro-core/src/maistro/persistence/pg_learnings.py:215`.

## Acceptance matrix (fresh inspection, not historical pass claims)

| Criterion | Evidence / disposition |
| --- | --- |
| Representative RC load profile | **UNVERIFIED**: `docs/testing/soak/m3a-load-profile.md:171` explicitly lists missing concurrent users/Workspaces, fan-out, successful tool/model calls, Design/Canvas and reconciliation. |
| Two production replicas | **UNVERIFIED**: focused ASGI/boot-contract tests passed, but no deployed exact-RC replicas were exercised in this round. |
| Sustained saturation, queues, reclaim, retries, leaks | **UNVERIFIED**: focused tests are not sustained production observations; no long-window run performed. |
| Schedule/task/Run/Attempt physical deduplication and Goal reconciliation | **UNVERIFIED**: profile's occurrence race admits then cancels its Run without physical execution; admission counts do not prove this criterion. |
| Concurrent security/degraded behavior, replica-selection non-bypass | **UNVERIFIED** at deployment scale, with contrary component evidence: executed `tests/test_soak_promotion_gates.py:439` observes independent 200/200/429 allowances for the same identity on both production middleware instances. Production registers that middleware at `packages/maistro-server/src/maistro_server/main.py:648`; process-local state is constructed at `api/rate_limit.py:94`. |
| Complete telemetry and pass/fail thresholds | **UNVERIFIED**: profile documents only partial coverage; driver-loop latency is not application-loop latency, and saturation/reclaim and long-window leak measurements remain missing. |
| Kill/restart during active work, drain/fencing/recovery | **UNVERIFIED**: no production active-work recovery executed. Exit/rejoin alone is insufficient. |
| Long-running exact-RC soak | **UNVERIFIED**: `scripts/soak/run_soak.py:744` deliberately returns `ok: false` for its host topology, wired into evidence at line 1579. Promotion tests passed without weakening this gate. No immutable RC image/configuration was designated by the assignment. |
| Findings filed/reclassified to earliest invariant | **UNVERIFIED**: no new live-load experiment or remote filing performed; GitHub mutation prohibited. Existing gaps recorded here, not declared resolved. |
| Hash-bound machine/human production evidence | **UNVERIFIED**: this report binds source checks to starting HEAD, not an exact-image production soak. |

## Handoff

**BLOCKED**, not merge-ready. The requested CI failure is not reproducible, the
Vulture ledger exactly matches the scan, and there is no merge conflict. Only
this report changes. No tests added/changed, so no inventory delta is warranted.
All existing work preserved; no GitHub mutations, gate weakening, or ledger edits.

Next action is production-soak ownership: designate the immutable RC image and
configuration, complete representative workloads and telemetry, settle the
replica-selection allowance requirement, then execute the >=4-hour exact-RC soak
with physical-work fencing and active-work recovery. Repeating this same CI-only
repair cannot satisfy these missing criteria. Do not relaunch it as a ledger repair
without a new failing scan.

Progress: checked 1 issue, done 0 acceptance-complete issues, skipped 0,
validation errors 0. `uv run python scripts/check-doc-links.py` passed (2700
Markdown files, zero broken relative links); `git diff --check` passed. Local
report commit is a handoff only, not integration approval.
