# Issue #860 repair validation

## Frozen scope

- Issue: #860 only; assigned worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Starting HEAD: `6d4d69cade1a11c894006304ea2415fa6c2a340f`; supplied develop base: `321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62`.
- Initial worktree clean; no incoming changes to salvage.
- Repair targets: recorded schema-fence failure in `packages/maistro-core/tests/persistence/test_pg_learnings.py`; reviewed identities from the mandated exact vulture scan in `quality/vulture-baseline.json` if required; associated inventory note and this validation report.
- Read-only acceptance inspection: `scripts/soak/`, `tests/test_soak_promotion_gates.py`, related deployment/evidence documents, relevant production code and ADRs. No other issue or PR is being processed.

## Initial evidence and assumptions

- Current job directory contains no `check-*.log`; supplied previous `check-3.log` shows the schema-fence test expected 21 DDL statements but production executed 24.
- Prior result explicitly reported BLOCKED for exact-RC evidence; this is a claim to recheck, not acceptance proof.
- Assumption: this is a focused writer/CI repair, not authorization to fabricate an RC artifact or change runtime authority to make the soak pass.
- Rechecked `pg_learnings.py` and adjacent tests: the three Gauntlet audit columns are already present in the independent ordered DDL expectation. The supplied failure is stale at this HEAD; no further schema-test repair is warranted.
- Executed `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`: **37 passed, 6 skipped** (PostgreSQL-dependent cases not configured).
- Executed `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: **PASS**, 1322 reviewed identities / 1322 findings, zero unclassified or never-allowlist findings. No ledger amendment warranted; no identities were eliminated or added.
- Executed `uv run ruff check .`: **PASS**.
- Executed `uv run ruff format --check .`: **PASS**, 3301 files already formatted.
- Executed `uv run pytest tests/test_soak_promotion_gates.py -x -q`: **72 passed**. These tests exercise production rate middleware and task-router seams, plus evidence-oracle/sampler behavior; they do not deploy an exact RC or run a sustained soak.
- Read the current load profile and evidence pack: both explicitly withhold promotion proof. The profile lists missing concurrent users/Workspaces, fan-out, successful model/tool calls, Design/Canvas and Goal/background workloads. It describes only driver-loop lag, not application-loop lag. No runtime/test edits are justified by the supplied failures.
- Executed `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`: **1 passed**, exercising the production route's retryable 429 on canonical concurrency refusal.
- Executed `uv run python scripts/check-suite-inventory.py`: **PASS**, all 17 suites match, 31,323 unique identities, zero duplicate evidence. No tests added or modified, so no inventory delta is needed.
- Executed `uv run python scripts/check-backlog-consistency.py`: **PASS**, 168 items.
- Executed `git diff --check`: **PASS**.

## Architecture reconciliation

Read repository instructions, the documentation authority hierarchy, ADR-081,
ADR-081626-f383 and ADR-082826-b601. ADR-081 is **Proposed**, not an accepted
multi-replica guarantee. The accepted lease contract assigns execution authority
to canonical Attempt leases and does not itself define expiry takeover. The
accepted consumer uses canonical lifecycle transitions as claims and executes
through the existing Run/NodeRun/Attempt spine. No new scheduler, Goal store,
event authority, authorization path, reclaim semantics or execution authority
is introduced to satisfy the stronger issue wording.

## Acceptance audit

| Issue criterion | Executed evidence and remaining gap |
| --- | --- |
| Representative RC workload profile | **UNVERIFIED**. Current profile explicitly lists absent multi-user/Workspace, Graph fan-out, successful model/tool, Design/Canvas and Goal/background traffic. Documented preflight traffic is not a complete RC profile. |
| At least two deployed application replicas | **UNVERIFIED** for the exact RC. Fresh tests use ASGI apps; no deployed pair was exercised in this round. Historical shakedowns are not fresh proof. |
| Sustained saturation, growth, reclaim, retries, leaks and restart | **UNVERIFIED**. No sustained production run executed. Sampler regressions passing do not prove long-window behavior. |
| No duplicate physical work across replicas | **UNVERIFIED**. Admission tests validate observed identity accounting, not physical Attempt effects. The profile's schedule probe admits then cancels its Run; it does not execute/reclaim that work. |
| Replica-selection-resistant limiting/security/degraded behavior | **NOT PROVEN**. Freshly passed `tests/test_soak_promotion_gates.py:439` reproduces `[200, 200, 429]` independently on each replica for the same identity, authenticated and unauthenticated. `api/rate_limit.py:32` documents the process-local scope; construction at line 94 instantiates independent state. No production concurrency/security soak was run. |
| Complete telemetry and explicit thresholds | **UNVERIFIED**. Driver-loop lag is not application-loop lag; application workers, pool saturation and reclaim observations remain missing. Local sampler tests are not complete production telemetry. |
| Active-work kill/restart, graceful drain, fencing and recovery | **UNVERIFIED**. No active-work fault injection executed. Fresh `tests/test_soak_promotion_gates.py:564` passes by observing owner 200 / peer 404 through the production task router; `api/tasks.py:144` reads the local queue. Process rejoin alone cannot establish physical recovery. |
| Long exact-RC artifact/config soak | **UNVERIFIED / BLOCKED**. `scripts/soak/run_soak.py:744` explicitly returns `ok=False` for host preflight artifact equivalence. Fresh CLI regression tests reject even four-hour evidence without exact-RC proof. No selected immutable RC image/config or new four-hour run is established here. |
| Findings classified to earliest broken invariant | **UNVERIFIED** for completeness. Existing evidence pack classifies findings, but no new production load or exhaustive classification was executed. No external filing is permitted in this lane. |
| Machine/human evidence tied to exact artifact hashes | **UNVERIFIED** for promotion. This report identifies the source HEAD and fresh local commands only; it is not image/config-bound soak evidence. Historical packs remain unchanged. |

## Disposition and handoff

**BLOCKED**. Only `docs/testing/issue-860-repair-validation.md` changes in this
round. The supplied schema failure is already repaired, and the exact ledger
matches the scan. No speculative source/test/ledger changes, gate weakening,
GitHub mutation or develop merge were warranted. The worktree arrived clean and
had no sync conflict.

Next required work is a selected, immutable RC artifact/configuration and a
representative production workload with complete application telemetry and
physical-effect accounting. Resolve the per-replica allowance/receipt-recovery
contract gaps through the canonical owners, then execute the >=4-hour exact-RC
soak with active-work failure. Any runtime/config change requires a new run.
Running the host preflight longer cannot unblock promotion.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "exact-RC prerequisites and production soak"}`.
The single assigned issue was checked; its full acceptance remains incomplete.
This report is committed locally as the checkpoint; no integration approval is
claimed.
