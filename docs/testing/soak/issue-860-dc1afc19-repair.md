# Issue #860 — dc1afc19 repair checkpoint

## Frozen scope

- One issue: #860; branch `auto-860`; starting head `9a243fc61fbd60ede3bf330f8e575bbe3e790211` (verified clean).
- Supplied comparison base `f72d4fc921135dfe7df727c226fa6a29903c59af` resolves locally. No merge conflict is present; no develop sync is assumed necessary.
- Inputs: supplied dispatch-context.json, prior 8d50e6eb result, repository instructions, relevant execution/soak ADRs, `docs/testing/soak/m3a-load-profile.md`, round30 evidence, `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`, production rate limiter and adjacent server tests, inventory checker/notes, vulture checker/ledger, CI gate invocation.
- Potential writes limited to this report and evidence-backed corrections to those issue/gate files. No unrelated inherited branch diff is being repaired.
- Job directory listing contained no `check-*.log` files; driver verification cannot be assumed.
- Prior BLOCKED result is input evidence, not fresh validation. No uncommitted work needed salvage.

## Progress

- Vulture gate freshly PASS: 1322 reviewed identities / 1322 findings, zero unclassified and zero never-allowlist. No ledger amendment is justified; the requested CI failure is not reproducible at this head.
- Read the ten acceptance criteria from the supplied issue snapshot. Full representative workload, exact RC/config and long-running physical-work observations are required, not only passing CI.
- One exploratory JSON print failed (`AttributeError`: top-level `issue` is an integer); corrected by reading `sources[0].data.body`. No remote lookup or scope expansion.
- Prior report and current profile agree the host-process harness cannot certify the production artifact. No incapable short soak will be repeated.
- `uv run ruff check .`: PASS. `uv run ruff format --check .`: PASS (3306 files).
- `uv run pytest tests/test_soak_promotion_gates.py -x -q`: PASS (84 tests, 1.48 s). Includes production middleware tests reproducing independent replica allowances and real router receipt reads returning peer-local 404s; not live deployment proof.
- `uv run pytest packages/maistro-server/tests -x -q`: PASS (566 passed, 8 skipped, 22 HTTP-status deprecation warnings, 32.63 s). Skips are not acceptance evidence.
- Accepted ADR-081626-f383 assigns fencing to canonical Attempt/Run storage and explicitly does not define expiry takeover. Accepted ADR-082426-82c7 claims occurrences on canonical Runs, not a separate scheduler/claims store. Reconciliation: admission uniqueness is not physical-work fencing; do not invent reclaim authority for this soak.
- Accepted ADR-085 requires principal-keyed request limits, separate from token quotas. It does not waive #860's replica-selection criterion. ADR-081 is Proposed, not an accepted override.
- Validation output retained in `/tmp/860-dc1afc19-{vulture,ruff,format,soak-tests,server-tests}.log` (local ephemeral logs).
- `uv run python scripts/check-suite-inventory.py`: PASS, all 17 suites, 31,489 unique identities, root `tests/` 5354. The supplied 5353/5354 mismatch is not reproducible. Log: `/tmp/860-dc1afc19-inventory.log`.
- Imported current `scripts/soak/run_soak.py` with `uv run python`, loaded round30 JSON and asserted `failed_promotion_checks(evidence) == ['sustain_duration', 'exact_rc_artifact']`: PASS. Observed 420.08 seconds and historical head `c4f45b309fd622f2e8a4b315dad35e721d81aad3`. Also asserted `preflight_artifact_check()['ok'] is False`: PASS.
- Reachability: `packages/maistro-server/src/maistro_server/main.py:648` installs the production middleware tested. `deploy/docker-compose.prod.yml:26-76` declares two application services, not evidence that this RC has run on them.
- `git diff --check`: PASS before final report completion.

## Acceptance matrix

| Criterion from supplied #860 snapshot | Evidence and disposition |
| --- | --- |
| Representative RC load profile | **UNVERIFIED** in full. `m3a-load-profile.md:167-183` acknowledges missing concurrent users/Workspaces, Graph fan-out, successful tool/model calls, Canvas and Goal reconciliation. No selected RC manifest or justified enabled-surface profile was supplied. |
| At least two application replicas | **UNVERIFIED for current RC**. Compose declares two; passing ASGI tests instantiate middleware, not deployed images. Historical host-process evidence cannot establish the selected RC topology. |
| Sustained saturation, queues, reclaim, retries and leaks | **UNVERIFIED**. Executed evaluator rejects the 420.08-second historical run against 14,400 seconds. Pool saturation, reclaim and long-window observations remain absent; ADR fencing does not authorize implicit expiry takeover. |
| No duplicated physical work across schedule/task/Run/Attempt/Goal operations | **UNVERIFIED**. Round30 JSON lines 11-15 cancels the schedule probe Run. Admission uniqueness does not establish physical Attempt fencing or sustained Goal reconciliation. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **NOT PROVEN**. Executed `test_replica_selection_has_an_independent_production_allowance` for both identity classes; `tests/test_soak_promotion_gates.py:477-526` observes `[200, 200, 429]` on each middleware instance for the same identity. `rate_limit.py:32-37` explicitly documents independent allowances. Security/degraded-path unit coverage is not a sustained-concurrency proof. |
| Production telemetry and explicit thresholds | **UNVERIFIED** in full. Profile defines thresholds, but `m3a-load-profile.md:179-183` distinguishes driver loop latency from application latency and lists missing measurements. No fresh RC telemetry captured. |
| Active-work kill/restart and drain/fencing/recovery | **UNVERIFIED**. Historical process exit/rejoin and terminal Run counts do not establish no physical-work loss/duplication. Server regression tests are not a deployed recovery experiment. |
| Long-running exact promoted RC/config | **NOT MET by evaluated evidence**. Round30 JSON lines 217-222 declares non-RC host preflight; current evaluator fails artifact and duration gates. `run_soak.py:744-755` deliberately cannot certify that topology. |
| Findings filed/reclassified to earliest broken invariant | Findings recorded locally here; **external filing/reclassification UNVERIFIED**. No GitHub mutations permitted or performed. Replica budget semantics need an explicit owner decision/fix; no alternative auth path introduced. |
| Published machine/human evidence tied to promoted hashes | **UNVERIFIED for current RC**. Historical JSON contains an older commit; no selected immutable application image/config manifest or new promotion-grade run exists in this work. |

## Outcome / handoff

**BLOCKED**. Previous acceptance block reproduced, not resolved. The CI-repair
subtask found no unbanked vulture identities and no inventory mismatch. Do not
amend a passing ledger, adjust counts, or fabricate evidence merely to produce a
code diff. This round changes only this report; no source, tests, historical
measurements, gates, grants or ledgers changed. No new tests means no inventory
note delta is needed; meaningful existing regressions were executed.

Next required input/work: select immutable RC images and configuration, complete
the representative enabled-surface workload, resolve the cross-replica budget
contract through the canonical limiter/authentication path, and execute a
>=4-hour exact-topology soak observing physical Attempts and Goal reconciliation,
application telemetry and active-work recovery. Running this preflight longer
cannot satisfy exact-artifact acceptance. No live soak was performed this round.
The inherited branch-wide diff is outside this narrow repair and has not received
integration approval.

Progress: checked 1 issue; done 0 acceptance-complete issues; skipped 0 issues;
blocked 1; validation failures 0; exploratory-command errors 1 (corrected above).
Checkpoint to be committed locally; no remote changes.
