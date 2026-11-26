# Issue #1151 isolated repair checkpoint

## Frozen scope

- Issue #1151 only; branch `auto-1151`, starting HEAD `6fcc0297f7c2d7830a19c155ab9f2fcad8715cd1`, supplied develop base `f72d4fc921135dfe7df727c226fa6a29903c59af`.
- Evidence: supplied job `cae1b0d0dd6a40c5a2fb2f33ea8a438b/dispatch-context.json`, prior result `d13acb1b4a2f49d380b9e892e095603f/result.json`, existing #1151 repair notes.
- File scope: reconciliation in `packages/maistro-core/src/maistro/container.py`, `graph/durable_runs/canonical_store.py`, `runs/execution.py`; adjacent core reconciliation tests and their inventory note; this report; `quality/vulture-baseline.json` only if the explicitly requested exact-debt scan proves amendment necessary.
- Read-only architecture/ADR, workflow and validation scripts inspection is in scope. No GitHub operations or new issue/PR enumeration.

## Initial evidence

- `pwd; git status --short; git rev-parse HEAD`: correct assigned worktree, clean, exact expected head.
- Job directory contains no `check-*.log` files. Writer validation must be executed locally.
- Prior result reports BLOCKED: total inspected work is not bounded by repair quota; parked/terminal policy remains pending an accepted decision. These are claims to verify, not assumed proof.
- Assumption: this is a writer repair round, including the explicit Vulture exact-debt-ledger check. The supplied starting commit already preserves the previous worker's work; no uncommitted salvage exists.

## Evidence checkpoint

- Read the complete captured primary issue body. It explicitly permits four reachable parked-conflict characterization rows and isolation control, but blocks a new disposition; total-work policy remains with #1098. Existing measurement must not be repeated as a substitute for those decisions.
- `uv sync --locked --extra dev`: passed.
- Requested exact Vulture command: passed, 1322 reviewed identities / 1322 findings, no unclassified findings. No ledger amendment is justified.
- Scoped next item: inspect existing parked-conflict tests for actual walker/decision reachability; strengthen only this explicitly permitted proof if deficient. This falls within the frozen adjacent core reconciliation test scope.

## Architecture/test inspection

Read accepted ADR-b36a, ADR-08f0 and ADR-6e2a completely. The existing parked matrix explicitly constructs the terminal continuation by changing its status; it does not execute a walker to reach those four disagreements. Canonical recovery refuses parked COMPLETED/FAILED conflicts (`_reconcile_terminal_graph` requires RUNNING); HITL terminal repair only accepts CANCELLED/TIMED_OUT with matching store-authored settlement evidence. No general override is authorized.

Inspecting ordinary pause/answer/resume boundaries next to determine a defensible production-reachable proof. If all four conflicts cannot be reached without synthetic status edits, report that limitation rather than relabeling constructed inputs as crash proof.

## Repair checkpoint

- Replaced the parked test's manually completed NodeRun and hand-authored pause metadata with `run_durable_graph` executing a node that calls `pause_until`. The actual canonical fold writes a completed physical Attempt and a WAITING/PAUSED logical NodeRun; both stores are independently read before terminal mismatch injection.
- Assert accepted physical outcome and lease identity; PAUSED cases additionally exercise public resume refusal before node resolution and verify raw continuation immutability.
- The terminal continuation mismatch remains injected, explicitly documented. No proof of natural reachability of all four conflicts or new parked disposition is claimed. No production policy was changed.
- Corrected the older running-reconciliation inventory note's unsupported claim that chat tests close universal Graph result-preservation acceptance. Inventory counts are unchanged (15 matrix/isolation nodes).
- Initial memory-only focused run: 5 passed; targeted Ruff lint and format checks passed.
- Full dual-store matrix with live `auto-1151-pg`: **15 passed, no skips**; collected node IDs saved in `check-parked-collection.log`.
- Re-executed focused acceptance battery with PostgreSQL enabled: **203 passed, 4 existing strict xfails, no skips** (`check-acceptance.log`). Xfails were not edited and are not acceptance evidence.
- Hive canonical cadence/delegation: **21 passed** (`check-hive.log`).

Logs are in the supplied current job directory. PostgreSQL credentials were read from the assigned container into subprocess environment only, never printed or written to the tree.

## Final validation checkpoint

- Negative control (`check-parked-negative-control.log`): in-process mutation of the production fold treats a physical pause as logical COMPLETED. The revised memory WAITING/COMPLETED test fails at the walker-produced parked-status assertion (actual COMPLETED). The original function was restored; no source mutation was made. This detects the production behavior the old hand-built fixture bypassed.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 3312 files.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: passed, 16572 collected nodes, unchanged inventory.
- `uv run python scripts/check-test-duplicates.py`: passed, no duplicate groups.
- `git diff --check`: passed.
- Source inspection reconfirms the terminal-replay `while reconciled < limit` loop bounds repairs, not reads, and traverses nested NodeRun/Attempt history for unchanged RUNNING candidates. No new bound/cursor policy is introduced.
- Inherited branch differences versus supplied develop include unrelated sandbox/UI/ADR changes. They are preserved, outside this round's four-file diff and not approved by this validation.

- Re-executed existing inspection matrix with PostgreSQL: **96 passed, no skips** (`check-inspection.log`). This is verification of the known limitation, not its repair. At 10 unchanged pages / 3 nodes / 4 Attempts, the first tick reads 11 candidate Runs, 122 list-returned NodeRuns and 121 list-returned Attempts for one repair. Each repeated/fresh-Container tick reads 10 / 120 / 120 for zero repairs. Point reads and internal SQL work are separate; no total-work ceiling is proven.
- Final exact requested Vulture gate: passed, 1322/1322 (`check-vulture.log`); Radon: passed, 137/137 (`check-radon.log`). No ledger/grant amendment is warranted.
- `runs/execution.py:522` still invokes `_terminalize_if_open` once for provider success; `_terminalize` delegates one store transition. No inline terminal-write retry was added or claimed.

## Acceptance ledger

All test logs below are this round's executed results, not inherited assertions.

| Retained criterion | Evidence and disposition |
| --- | --- |
| Bounded/indexed RUNNING candidate enumeration and re-derivation | PG backlog and SQLite index-plan tests in `check-acceptance.log` pass. Existing inspection matrix passes. Candidate pagination is demonstrated; total inspected-work bound remains **UNVERIFIED**. |
| Terminal required NodeRuns settle without new Attempt | Real-PG completion windows through public Container tick pass, with immutable physical history/no-dispatch checks (`check-acceptance.log`). |
| Lost frontier/resume_at=None does not strand | PG lost-frontier and active-Attempt guard tests pass; existing quiet-period protection is retained (`check-acceptance.log`). |
| Canonical/terminal continuation disagreement, including WAITING/PAUSED | Canonical terminal projection repairs pass. Revised matrix proves genuine walker-authored pending decisions survive recovery and public HITL resume refuses. General parked COMPLETED/FAILED repair is **UNSATISFIED / DESIGN_BLOCKED**; natural reachability of all four conflicting pairs remains **UNVERIFIED**. |
| QUEUED continuation / RUNNING checkpoint-1 | Existing PG expired-claim and live-claim refusal cases pass (`check-acceptance.log`). No immediate claim-free transition is claimed. |
| Successful-runtime persistence failure preserves result/retry policy/recoverability | Chat post-dispatch-recording-failure and store-conformance cases pass. Universal Graph output preservation and retry policy remain **UNVERIFIED**, not inferred from chat. |
| Chat lease/fence/reclaim and non-swallowed terminal-write failure | Targeted chat recovery, execution fencing, recording-failure and conformance tests pass with PostgreSQL enabled (`check-acceptance.log`). No unleased ownership inference added. |
| Replica idempotence/fencing | PG independent-pool convergence/fencing tests pass; revised parked matrix reaches fixed point and inspection peer-first cases preserve physical history (`check-acceptance.log`, `check-inspection.log`). |
| PostgreSQL crash/forced-interleaving proofs for each window | Existing real-PG spine crash and chat cases pass. Complete crash coverage remains **UNVERIFIED**; injected projection mismatch and independent pools are not OS process-death proof. |
| Sweep bounded/indexed, not all historical Runs | Terminal historical exclusion/keyset traversal pass. Actual nested reads grow independently of repair quota; total-work bound remains unresolved under #1098. No unapproved cursor/fairness change. |
| #804 consumes canonical truth, no Workspace-private repair | Existing Hive canonical cadence/delegation tests: 21 pass (`check-hive.log`). Complete #804 acceptance remains **UNVERIFIED**. No product-private authority introduced. |

## Handoff

Changed files (only this round):

1. `packages/maistro-core/tests/graph/durable_runs/test_parked_terminal_continuation_disposition.py`
2. `docs/testing/inventory-notes/1151-parked-terminal-continuation-disposition.md`
3. `docs/testing/inventory-notes/1151-running-reconciliation.md`
4. `docs/testing/1151-repair-20261018-current.md`

No production source, ledger, grant, lifecycle policy or unrelated inherited file changed. No GitHub mutations, merge, push or destructive Git operations. No conflict existed to resolve. Full monorepo pytest was not run; validation was scoped to the relevant core/Hive paths. Exact commands and collection IDs are recorded in current job logs.

Scoped proof repair is complete for local commit; parent remains **BLOCKED**, not integration-ready. The prior architectural/policy holds cannot safely be removed by this worker. Next: accepted parked-disposition mapping/proof, #1098 bound/cursor decision, and missing Graph durability/downstream acceptance. Do not treat test strengthening or passing quality gates as release authorization.

Checkpoint: checked 1 assigned issue; done 1 scoped test/evidence repair; skipped 0 issues; errors 0 unexpected validation failures (negative-control failure intentional).
