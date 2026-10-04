# #860 CI repair validation

## Frozen scope

Assigned issue: #860 only. Worktree: `/home/dev/Git/wt/auto-860`, branch
`auto-860`; verified clean starting HEAD
`b107735856e4674bb6e9c7efdf5e58533ce11882`. Supplied develop base:
`4fd7801fb333611955dda962d11845aaf065277c`.

Files in scope: this validation record, `quality/vulture-baseline.json` (explicit
CI-repair exception), and only production identities reported by the prescribed
vulture scan if inspection proves them dead. Adjacent tests, soak evidence,
repository instructions, ADRs and CI scripts are read-only inputs. No new soak,
new scheduler, authorization path, or production deployment is assumed.

Initial results: starting worktree clean; prior result artifact read. The job
directory listing contains no `check-*.log` files, so driver checks are unavailable,
not presumed passing. Previous handoff explicitly reports BLOCKED. Current
profile/evidence already disclaims cluster-wide rate limiting, exact-RC execution,
and >=4-hour soak; historical evidence will not be relabelled.

Assumption: the explicit CI-repair request authorizes reviewing and amending only
the vulture identity ledger, not ratchet grants or promotion requirements. Missing
RC identity/configuration and long-running evidence cannot be repaired by banking
scanner rows. Validation and final acceptance disposition follow below.

## Initial gate result and ADR reconciliation

The exact requested vulture scan exited 0: 1360 findings, 1360 reviewed
identities, zero unclassified/never-allowlist findings, no candidate bookkeeping
delta. Its default trusted base resolved to `045cfdfbe3ea`, not the supplied lane
base; repeat with `RATCHET_BASE_REV` pinned to the verified supplied base before
claiming lane-base validation. No dead-code or ledger change is justified by this
scan. The explicit ledger exception is not a requirement to invent a diff.
The repeat with the supplied `RATCHET_BASE_REV` also passed; the resolver still
reports `045cfdfbe3ea` (the trusted merge base), not the tip of the supplied ref.

Fresh checks (1800-second timeout): `uv sync --locked --extra dev` passed;
`uv run ruff check .` passed; `uv run ruff format --check .` passed (2809 files).
`uv run pytest tests/test_soak_promotion_gates.py
packages/maistro-core/tests/persistence/test_pg_learnings.py
packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py
packages/maistro-server/tests/api/test_rate_limit.py -x -q` passed: **102 passed,
5 skipped**. PostgreSQL integration cases were skipped; they are not live-DB
proof. Existing tests exercise real rate-limit middleware instances, the canonical
admission backpressure seam, gate failure paths, and a real uv child sampler.
No new tests were added, so no inventory delta is required.

Accepted ADR-081226-a66b keeps Run/NodeRun/Attempt lifecycle authority canonical;
accepted ADR-081626-f383 guarantees stale-writer fencing but explicitly does not
establish lease-expiry takeover. This lane must not implement an alternate
scheduler/reclaim authority to satisfy the soak request. ADR-081 (deployment) is
Proposed, not an accepted override of those contracts. Therefore admission-only
and process-restart evidence cannot be upgraded to physical-work/reclaim proof.

## Final validation

- `git merge-base HEAD 4fd7801fb333611955dda962d11845aaf065277c` confirmed
  `045cfdfbe3eaa0c84493eb02754d7410b0c69378`; both vulture invocations above
  therefore used the expected trusted merge base. No merge/sync conflict exists.
- `uv run pytest packages/maistro-server/tests -x -q`: **483 passed, 8 skipped,
  22 deprecation warnings** (40.72 seconds). Skips are not acceptance evidence.
- `RATCHET_BASE_REV=4fd7801fb333611955dda962d11845aaf065277c uv run python
  scripts/check-ratchet-provenance.py`: PASS, 46 consumers checked.
- Same environment prefix with `uv run python scripts/check-shipped-surface-truth.py`:
  PASS. `check-deployment-claims.py`: PASS (component existence only).
  `check-doc-links.py`: PASS, 1611 files / zero broken relative links.
  `check-merge-markers.py`: PASS.
- An executed Python probe imported the current `scripts/soak/run_soak.py`, loaded
  the three known historical packs (`m3a-soak-evidence.json`,
  `m3a-round5-final.json`, `m3a-round6-shakedown.json`), and asserted every one is
  rejected by `failed_promotion_checks` for both `sustain_duration` and
  `exact_rc_artifact`. All assertions passed. Round 5 records 90.17 seconds;
  round 6 records 90.43 seconds. Run 1 has no top-level `sustain_seconds`.
- Local raw command logs: `/tmp/auto-860-{sync,vulture-initial,vulture-base,ruff,format,tests,server}.log`
  and `/tmp/auto-860-check-*.log`. These are validation logs, not soak evidence.

## Every acceptance criterion

| Criterion | Current executed evidence and disposition |
| --- | --- |
| Representative RC profile | PARTIAL: inspected `m3a-load-profile.md`; it explicitly lacks a concurrent user/Workspace population, fan-out, successful tools/models, Design/Canvas, and Goal/background workloads. Applicability to the selected RC remains UNVERIFIED. |
| At least two application replicas | UNVERIFIED: `deploy/docker-compose.prod.yml` defines two services; no current exact-artifact deployment was executed. Two ASGI middleware instances do not count as a deployed soak. |
| Sustained saturation, growth, reclaim, retries, leaks and restart | UNVERIFIED: executed evaluator rejects all three inspected historical packs; round 6 is 90.43 seconds vs 14400 required. A passing live child-sampler regression is not a long-window measurement. |
| No duplicate physical work / Goal reconciliation | UNVERIFIED: admission-oracle/backpressure tests pass, but do not prove physical Attempt effects across deployed replicas. Historical schedule probe cancels its queued Run; accepted fencing ADR does not establish expiry takeover. |
| Rate-limit/security/degraded replica-selection non-bypass | NOT MET for a shared allowance: executed `test_replica_selection_has_an_independent_production_allowance` reproduces `[200,200,429]` independently on both production middleware instances, for authenticated and unauthenticated callers. Current RC security/degraded behavior remains UNVERIFIED. |
| Complete telemetry and explicit thresholds | UNVERIFIED: profile has partial thresholds and host process-group samples; driver-loop latency is not application-loop latency. No exact-RC worker/pool/lease/leak window was measured. |
| Kill/restart during active work with drain/fencing/recovery | UNVERIFIED: no deployed replica was killed/restarted this round; historical process rejoin alone cannot prove physical-effect recovery. |
| Long-running exact RC artifact/configuration soak | BLOCKED: no designated immutable RC image/configuration supplied, and the current runner always fails `exact_rc_artifact`. Executed CLI regressions reject even synthetic four-hour preflight evidence. No new soak was run. |
| Findings filed/reclassified before promotion | PARTIAL: inspected historical local classifications. External filing UNVERIFIED and prohibited in this lane; no GitHub mutation performed. No new runtime defect is claimed from a clean vulture scan. |
| Human/machine evidence bound to exact hashes | PARTIAL: inspected/re-evaluated historical packs, not re-signed. Current promotion-artifact image/package/configuration hash-bound soak evidence UNVERIFIED. |

## Handoff

**BLOCKED for #860.** The requested CI failure did not reproduce; amending an
already exact ledger or changing runtime code would be cosmetic/speculative.
Only this validation record changed. No production/test/ledger/grant edits or
new test counts. Historical raw evidence is untouched. This is a local writer
checkpoint, never integration approval.

Next owner actions: designate the exact RC artifact/configuration, resolve the
rate-limit acceptance mismatch through its owning lane, complete representative
production-path workloads and effect/telemetry oracles, then run and publish a
new >=4-hour exact-artifact soak. Do not substitute a longer host preflight.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: exact-RC prerequisites and sustained soak}`.
Validation completed; issue acceptance remains blocked. Commit this report
locally without pushing, opening a PR, merging, commenting, or closing an issue.

---

# CI-repair round 711010c6

## Frozen scope

- Issue: #860 only; writer lane `auto-860`.
- Starting HEAD: `12789110051af9aab369a039a66350db773765eb`.
- Assigned base: `c0441cf94b9a8e58517da0f4159070b97ea6a706`.
- Initial worktree: clean; no incoming uncommitted work to salvage.
- Candidate edits: this report and `quality/vulture-baseline.json` for reviewed
  identities actually reported by the assigned exact-debt-ledger command.
  Runtime changes require evidence of genuinely dead code before expanding scope.
- Inspect existing soak implementation/tests, relevant ADRs and production seams;
  do not introduce an alternate execution or authorization path.
- Job directory listing contains no `check-*.log` files. Driver checks are not
  available to inspect in this round; execute local validation instead.
- Previous result inspected: prior job ended BLOCKED at this starting HEAD.
  Prior H3 wording is already corrected; do not manufacture another repair.

## Assumptions and limits

The explicit CI-repair instruction permits reviewed vulture ledger amendments,
not new grants or weakening gates. A clean ledger cannot prove #860 acceptance.
The host-process harness is explicitly not an exact-RC production runner. No
exact RC artifact/configuration is identified by this assignment. Do not run a
four-hour emulator and mislabel it promotion evidence. Record unmet acceptance
and remaining prerequisites honestly. GitHub mutations remain prohibited.

## Validation

Initial exact vulture command: PASS (1345 findings / 1345 reviewed identities,
zero unclassified or never-allowlist). No unbanked identities or eliminated rows;
no ledger change justified. Default trusted base reported `1e4933e2a1b7`.

This report path already held a historical round. Its original content is
preserved above; current-round results are appended rather than replacing it.

### Fresh focused checks

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS (2859 files).
- Supplied base resolves; `git merge-base HEAD
  c0441cf94b9a8e58517da0f4159070b97ea6a706` is
  `1e4933e2a1b7a0bc1bdecfdbafca846c7cb458f4`.
- Repeated exact vulture command with
  `RATCHET_BASE_REV=c0441cf94b9a8e58517da0f4159070b97ea6a706`: PASS,
  1345/1345 identities against that trusted merge base.
- `uv run python scripts/check-ratchet-provenance.py`: PASS, 46 consumers.
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- `uv run pytest tests/test_soak_promotion_gates.py
  packages/maistro-core/tests/persistence/test_pg_learnings.py
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py
  packages/maistro-server/tests/api/test_rate_limit.py -x -q`: **102 passed,
  5 skipped**, 4.04 s. PostgreSQL skips are not live database evidence.
  Middleware regressions execute independent production limiter instances;
  sampler regression executes a real uv child. Neither is a deployed RC soak.

### ADR reconciliation

Read accepted ADR-081426-1f7c, ADR-081626-f383, ADR-082426-82c7 and ADR-085,
and Proposed ADR-081. Canonical Attempt runtime identity and Run-store fencing
remain authoritative; lease-expiry takeover is explicitly outside the accepted
fencing contract. Occurrence admission uniqueness cannot prove physical work
uniqueness. Principal-keyed rate limits do not imply shared replica state.
No alternative execution authority or limiter is introduced by this repair.

### Final executed evidence

- `uv run pytest packages/maistro-server/tests -x -q`: **494 passed, 8 skipped,
  22 deprecation warnings**, 43.15 s.
- `uv run python scripts/check-doc-links.py`: PASS, 1646 Markdown files,
  zero broken relative links.
- `uv run python scripts/check-deployment-claims.py`: PASS (component existence,
  not runtime deployment certification).
- `git diff --check`: PASS.
- Executed Python probe imported the current soak evaluator and asserted all four
  frozen historical packs fail both `sustain_duration` and `exact_rc_artifact`:
  `m3a-soak-evidence.json`, `m3a-repair-validation.json`, `m3a-round5-final.json`,
  `m3a-round6-shakedown.json`. PASS. Round 5/6 sustain 90.17/90.43 seconds;
  earlier packs lack top-level observed duration. These are not new soak results.
- The same probe compared this report's prefix to `git show HEAD:<path>`:
  historical content is preserved verbatim (append-only final diff).
- Inspection error: `packages/maistro-server/src/maistro_server/app.py` was not
  found; skipped. Searching the known package directory instead located the live
  registration at `main.py:593` (`app.add_middleware(RateLimitMiddleware)`).

### Acceptance disposition for this round

| #860 criterion | Evidence and disposition |
| --- | --- |
| Representative RC load profile | PARTIAL: inspected profile explicitly lacks multiple users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and background workloads. RC applicability UNVERIFIED. |
| At least two deployed replicas | UNVERIFIED: production Compose declares two services, but no exact-RC deployment executed this round. ASGI instances do not count as replicas under soak. |
| Sustained saturation, queue growth, expiry/reclaim, retries, leaks and restart | UNVERIFIED: all four historical packs fail the executed duration/artifact evaluator; live child-sampler test is not a long-window observation. |
| Exactly-once/fenced physical work and Goal reconciliation | UNVERIFIED: admission and backpressure regressions pass, but schedule probe cancels its queued Run and does not execute physical work. No deployed physical-effect oracle was exercised. |
| Rate/security/degraded non-bypass | NOT MET for a shared budget: real middleware regressions reproduce independent `[200,200,429]` allowances on both instances for both identity classes. This middleware is registered at `main.py:593`; current RC security/degraded behavior under load remains UNVERIFIED. |
| Full telemetry with thresholds | UNVERIFIED: sampler regressions pass, but no RC pool/lock/query/app-loop/worker/leak window was measured. Driver-loop lag is not application-loop latency. |
| Active-work kill/restart, drain/fencing/recovery | UNVERIFIED: historical process exit/rejoin is not proof of physical-effect recovery; no replica killed/restarted this round. |
| Long exact-RC artifact/configuration soak | BLOCKED: current runner always emits `exact_rc_artifact.ok=false`; all four historical packs rejected. No designated immutable RC artifact/configuration or new >=14400-second soak. |
| Findings filed/reclassified before promotion | PARTIAL: local F1–F12 classifications inspected. External filing UNVERIFIED; GitHub mutations prohibited. No new product failure inferred from a passing CI scan. |
| Hash-bound machine/human soak evidence | PARTIAL: historical packs inspected/evaluated, not re-signed. Current exact-RC image/package/commit/config evidence UNVERIFIED. |

### Handoff

**BLOCKED**, not integration approval. The prescribed exact-debt-ledger failure
is not reproducible; there are no unbanked identities to review/amend. No speculative
code deletion, ledger/grant amendment, weakened gate, or fabricated soak is warranted.
Only this report changed; no tests added, so no inventory delta is required.
No historical evidence changed. No branch sync conflict exists in the clean starting
state. Local commit required; no push or GitHub mutation.

Next: designate the exact RC artifact/configuration and provider environment,
resolve the replica-rate-budget acceptance mismatch through its owner, finish the
representative workloads and physical-effect/telemetry oracles, then execute and
publish the >=4-hour production-topology soak. A longer host preflight is not a
substitute. Prior blocked condition remains unresolved.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 1, next: exact-RC prerequisites and sustained soak}`.
The error is the missing inspection path above, not a failed validation gate;
CI-repair validation is complete, but #860 acceptance is not.

---

# #860 CI-repair validation

## Frozen scope

- Issue: #860 only; assigned worktree `/home/dev/Git/wt/auto-860`.
- Starting HEAD: `adfecd15de5288766f0dc31cce8c6f0fb7fb6a8a` (clean).
- Supplied base: `e067b7b0aca01b578f0bf2446dc0864fc4d88d15`.
- Writer repair round: inspect the exact vulture scan, amend only reviewed
  identities if required, and validate existing soak acceptance probes.
- Potential edits: this report and `quality/vulture-baseline.json` only.
  Production/harness changes are not justified by the supplied historical findings.
- Read-only validation scope: existing soak driver/tests/evidence, relevant
  deployment/execution/rate-limit ADRs and production seams, quality gate code/CI.
- No new tests planned; no suite inventory delta expected.

## Initial observations

The supplied job directory `d8335f358ba140409039771d1ffe0545` contains no
`check-*.log` files. Prior job `014700700d6c4a8989d9734a03ba1655/result.json`
reports BLOCKED, not a sync conflict. Its claims will not substitute for fresh
validation. No merge or remote operation is needed.

The existing profile explicitly rejects host-process preflight as exact-RC
promotion evidence and records representative-workload gaps. Historical run 6
lasted 90.43 seconds against the 14400-second minimum. Current H3 prose already
states process-local limits and does not claim a shared cluster-wide budget.
Assumption: the explicit CI-repair instruction permits only evidence-backed
ledger repair; it does not waive any of #860's ten acceptance criteria.

## Results

The prescribed vulture command passed: 1342 findings / 1342 reviewed identities,
zero unclassified and never-allowlist findings; trusted base `e067b7b0aca0`.
CI uses the same arguments in `quality.yml` and `vulture-ratchet.yml`.
No ledger amendment or dead-code deletion is justified by this result.
`uv run ruff check .` passed; `uv run ruff format --check .` passed (2876 files).

This report path already contained earlier rounds. Its original content has been
preserved verbatim above; this round is an append-only addition, not a replacement.
### Executed validation at the assigned head

- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1342/1342 identities.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 2876 files.
- `uv run pytest tests/test_soak_promotion_gates.py
  packages/maistro-core/tests/persistence/test_pg_learnings.py
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py
  packages/maistro-server/tests/api/test_rate_limit.py -x -q`: **102 passed,
  5 skipped**, 3.04 s. PostgreSQL skips are not live database proof.
- `uv run pytest packages/maistro-server/tests -x -q`: **494 passed, 8 skipped**,
  22 deprecation warnings, 39.15 s.
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- `uv run python scripts/check-ratchet-provenance.py`: PASS, 49 consumers.
- `uv run python scripts/check-doc-links.py`: PASS, 1680 Markdown files,
  zero broken relative links.
- `git diff --check`: PASS.
- Executed Python probe imported the current soak evaluator and asserted that
  all four historical packs (`m3a-soak-evidence.json`,
  `m3a-repair-validation.json`, `m3a-round5-final.json`,
  `m3a-round6-shakedown.json`) fail both `sustain_duration` and
  `exact_rc_artifact`: PASS. Round 5/6 observed 90.17/90.43 seconds; the first
  two have no top-level observed duration. These are evaluator checks, not new
  soak measurements.

### Architecture reconciliation

Read repository instructions, Proposed ADR-081, and accepted ADR-085,
ADR-081626-f383, ADR-082426-82c7 and ADR-082526-b36a. The later accepted
ADR-082526-b36a **does** define heartbeat renewal and expiry reclamation through
canonical Attempt execution/store authority. Earlier sections of this historical
report which cite only the initial fencing ADR's deferred takeover boundary
must not be read as saying reclamation remains architecturally undefined.
What remains absent here is a deployed soak observing that contract, not a
reason to create another recovery authority. The canonical
`Goal -> Graph -> Run -> NodeRun -> Attempt` model is unchanged.

Production middleware registration is reachable at `main.py:593`. Its real
instances in `test_replica_selection_has_an_independent_production_allowance`
return `[200, 200, 429]` on each replica for the same identity, for both identity
classes. Accepted principal-keying requirements do not establish shared limiter
state; this passing regression falsifies a shared allowance rather than proving
#860's replica-selection non-bypass acceptance. No alternate authorization or
rate-limit implementation is introduced in this CI-repair round.

### All ten acceptance criteria

| Criterion | Executed evidence / remaining disposition |
| --- | --- |
| Representative release-candidate load profile | PARTIAL: profile inspected; one credential and no sustained multi-Workspace/fan-out/successful model/tool/Design/Canvas/background workload. RC applicability UNVERIFIED. |
| At least two application replicas | UNVERIFIED: inspected production Compose declares two application services; no exact-RC deployment executed. ASGI middleware tests are not deployed replicas. |
| Sustained saturation, queue growth, lease reclaim, retries, leaks and restart | UNVERIFIED: evaluator rejects every inspected historical pack for duration/artifact. Real child sampler regression passes but is not a long window. |
| Exactly-once/fenced physical work and Goal reconciliation | UNVERIFIED: admission-oracle and backpressure tests pass; historical schedule probe cancels the queued Run instead of executing physical effects. |
| Rate limiting/security/degraded replica-selection non-bypass | NOT MET for a shared allowance: real production-middleware regression reproduces independent replica budgets. Exact-RC concurrent security/degraded behavior UNVERIFIED. |
| Complete telemetry and explicit thresholds | UNVERIFIED: profile has partial host-process/DB thresholds, not complete RC worker/pool/query/app-loop/leak observations. Driver-loop lag is not application-loop lag. |
| Active-work kill/restart with drain/fencing/recovery | UNVERIFIED: historical process rejoin does not prove physical-effect recovery; no replica killed/restarted this round. |
| Long-running exact RC artifact/configuration soak | BLOCKED: current driver always emits `exact_rc_artifact.ok=false`; no designated immutable RC image/configuration supplied or new >=14400-second soak executed. |
| Findings filed/reclassified before promotion | PARTIAL: local historical classifications inspected; external filing UNVERIFIED and GitHub mutations prohibited. Clean scanner results do not establish a runtime defect. |
| Hash-bound machine/human evidence | PARTIAL: historical JSON/Markdown inspected and rejected by current evaluator, not re-signed. Current exact-RC image/package/commit/configuration-bound soak UNVERIFIED. |

### Final handoff

**BLOCKED for #860.** Requested exact-debt-ledger failure did not reproduce;
no ledger edit or guessed dead-code deletion is warranted. Only this validation
report changed, preserving prior content. No new tests or inventory delta,
production/config changes, or historical evidence edits. No remote mutations.

Next: designate immutable RC artifact/configuration and provider environment,
resolve the replica-budget acceptance mismatch through its owner, complete
representative workloads and physical-effect/telemetry oracles, then execute
and publish a >=4-hour production-topology soak. A longer host preflight does
not satisfy acceptance. The previous blocked condition remains unresolved.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: exact-RC prerequisites and sustained soak}`.
CI validation is complete; issue acceptance is not. This is a local writer
checkpoint, not integration approval.
