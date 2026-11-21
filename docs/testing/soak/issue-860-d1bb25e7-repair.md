# Issue #860 repair checkpoint — d1bb25e7

## Frozen scope

- Issue #860 only; branch `auto-860`, starting HEAD
  `adcf3b1768085340637327c7a8823fb0d0e483fa`, supplied base
  `3c761d14db944a727fa0744444bc67cfe36d49f7` (both resolved locally).
- Starting worktree clean; no salvage needed.
- Inspect existing `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`,
  `docs/testing/soak/m3a-load-profile.md`, `docs/testing/soak/m3a-soak-evidence.md`,
  supplied prior result/logs, applicable ADRs, and vulture gate implementation.
- Potential edit scope: reviewed identities in `quality/vulture-baseline.json`
  only if the required scan demonstrates a mismatch; directly implicated soak
  code/tests only if fresh evidence demonstrates a defect; this checkpoint.
- No GitHub mutations, integration, grants, or unrelated repairs.

## Initial evidence / ambiguity

The current job directory has no driver `check-*.log` files. The supplied prior
failure and prior result will be inspected; their claims are not fresh validation.
The assignment is a writer/CI-repair round, not a verifier-only round. Full issue
acceptance includes an exact-RC long soak; passing static gates cannot establish it.

## Fresh checkpoint

- Required exact vulture scan passed: 1323 reviewed identities / 1323 findings,
  zero unclassified or never-allowlist findings. No ledger amendment is justified.
  Its default trusted base resolved to `4aa68edc0b6b`; supplied-base validation
  remains to be checked separately.
- Supplied `98a11313/check-3.log` reported 24 schema statements versus 21 expected.
  Fresh `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py
  -x -q`: **37 passed, 6 skipped** (1.50 s). This historical failure does not
  reproduce; skips do not prove live PostgreSQL behavior.
- Current profile explicitly calls the runner a host-process preflight, not an
  exact Compose RC soak. Existing tests exercise fail-closed artifact checks and
  independent production limiter allowances; execution pending below.
- Prior result reports BLOCKED, not a develop-sync conflict. No merge is warranted.

Logs: `/tmp/860-d1bb-vulture.log`, `/tmp/860-d1bb-learnings.log`.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed (3270 files already formatted).
- `uv run pytest tests/test_soak_promotion_gates.py
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  **66 passed** in 2.44 s, including real middleware allowance tests for both
  authenticated and unauthenticated identities and live child-process sampling.
- `uv run python scripts/check-ratchet-provenance.py`: passed (default base).
- `uv run python scripts/check-shipped-surface-truth.py`: passed.

Logs for these checks: `/tmp/860-d1bb-{ruff,format,soak-tests,provenance,surface}.log`.
No new tests or test-count changes; an inventory-delta note is not needed.

## Architecture and acceptance reconciliation

Read Accepted ADR-081226-a66b (one Run/NodeRun/Attempt lifecycle),
ADR-081626-f383 (canonical-store lease identity and stale-write fencing),
ADR-082426-82c7 (occurrence claims on the Run, not a second claim authority), and
ADR-085 (per-principal rate limits independent of token quota). ADR-081 is
**Proposed**, not an accepted deployment waiver. No competing lifecycle,
scheduler, event, Goal, or authorization authority is introduced here.
Admission uniqueness cannot establish physical-work uniqueness: the runner's
`_terminalize_probe_run` cancels the queued schedule probe without execution
(`scripts/soak/run_soak.py:1044`). The current production limiter explicitly
owns process-local state (`packages/maistro-server/src/maistro_server/api/rate_limit.py:32`)
and the existing real-middleware test reproduces a second allowance by replica
selection (`tests/test_soak_promotion_gates.py:439`). These are unresolved
acceptance gaps, not permission to silently waive #860's requirements.

## Final validation and acceptance accounting

- Repeated the exact vulture command with
  `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7`: passed,
  again 1323/1323 identities. The gate intentionally resolves the merge base
  (`scripts/ratchet_provenance.py:317`), so both invocations report
  `4aa68edc0b6b`. Log: `/tmp/860-d1bb-vulture-supplied-base.log`.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py
  -q -rs`: 37 passed, 6 skipped (1.56 s). All six skips require
  `MAISTRO_TEST_PG_DSN` pointing to a migrated database; no live-database proof
  is claimed. Log: `/tmp/860-d1bb-learnings-skips.log`.
- `git diff --check`: passed.

| #860 acceptance criterion | Fresh evidence and disposition |
| --- | --- |
| Representative release-candidate profile | **UNVERIFIED**. Profile exists, but `main_async` uses one credential and readiness/liveness/task/receipt/metrics traffic (`scripts/soak/run_soak.py:1383`), not concurrent Workspaces, graph fan-out, successful model/tool calls, Design/Canvas and background-worker coverage. |
| At least two supported application replicas | **UNVERIFIED** at exact RC. Focused tests use ASGI middleware instances; the runner boots host processes, not promoted Compose images. |
| Sustained pool/queue/reclaim/retry/leak/shutdown observations | **UNVERIFIED**. No new sustained RC run executed. The live child-process regression verifies sampler sensitivity only. |
| No duplicate physical work across schedule/task/Run/Attempt/Goal paths | **UNVERIFIED**. Admission tests pass; schedule probe explicitly cancels without execution (`run_soak.py:1044`). |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **NOT PROVEN**. Freshly passing production-middleware regression at `tests/test_soak_promotion_gates.py:439` demonstrates independent allowances on both replicas for the same identity (both auth classes). Six-path local 429 checks cannot prove a shared budget. |
| Complete telemetry with pass/fail thresholds | **UNVERIFIED**. Process sampler tested; `run_soak.py:1421` measures driver-loop lag, not application-loop latency. Complete production worker, DB contention, queue and timeout series were not collected. |
| Kill/restart during active work proves drain/fencing/recovery | **UNVERIFIED**. Boot cleanup tests pass, but process exit/rejoin (`run_soak.py:1439`) is not a physical Attempt/effect reconciliation oracle. |
| Long unchanged exact-RC soak | **UNVERIFIED / BLOCKED**. `preflight_artifact_check` always returns false (`run_soak.py:730`); four-hour synthetic preflight CLI cases exit 1 in the freshly executed tests. No exact promoted artifact/configuration was selected or soaked in this round. |
| Load findings reclassified to earliest broken invariant | Local evidence-validity and replica-rate-limit gaps recorded here and in the existing evidence pack. External disposition **UNVERIFIED**; GitHub mutations prohibited. |
| Machine/human evidence tied to exact image/package/commit/config | **UNVERIFIED** for current RC. Existing historical evidence was not altered or relabelled; this report records fresh focused validation only, not a new soak. |

## Handoff

**BLOCKED for issue acceptance.** No currently failing CI debt or schema regression
was found to repair. No production, test, inventory or ledger changes are justified
by these checks. The only changed file this round is this validation/handoff record;
it must be committed locally. The earlier BLOCKED result is confirmed rather than
resolved: acceptance requires an exact-RC production runner/workload, physical
execution/effect recovery oracles, resolution of the replica-local rate-budget
mismatch, complete telemetry, then a new >=4-hour unchanged-artifact soak. Starting
a longer host preflight would still fail the explicit artifact gate and cannot
repair these gaps. No promotion or integration approval is given.

Progress: checked 1 assigned issue, done 0 (acceptance incomplete), skipped 0,
errors 0 validation command failures. Next: resolve the documented production
acceptance blockers; do not repeat clean-ledger repair rounds as soak evidence.

