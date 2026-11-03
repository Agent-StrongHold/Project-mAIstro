# Issue #860 bounded CI repair

## Frozen scope

- Issue: #860 only; job `14368c0665b944ff98a9cf45e477044a`.
- Worktree: `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Verified starting HEAD: `0d391da999df13bdbe2391e5672b45f945c84a85`; initially clean.
- Assigned base: `2154f845347c9541016288c760f8da3f5cd2e064`.
- Inspect repository instructions, ADRs governing soak/runtime, existing soak scripts/tests, supplied dispatch snapshot and prior check-3.log. No GitHub refresh or mutation.
- Edit scope: this report; `quality/vulture-baseline.json` only if the requested exact scan identifies reviewed retained debt; production/test edits only if that scan demonstrates an issue in the assigned soak surface. No speculative runtime redesign.

## Initial evidence / ambiguity

The supplied prior result reports BLOCKED, not an unresolved merge. Starting tree is clean, so there is no incoming work to salvage. The current job directory has no check-*.log files at initial inspection; the explicitly supplied prior check log will be inspected. Prior acceptance claims are not adopted as fresh validation.

## Progress

Exact requested vulture scan PASS: 1323 findings matched 1323 reviewed identities; zero unclassified or never-allowlisted findings. No ledger amendment is warranted by this scan. Supplied prior check-3.log is a schema-fence test failure (24 statements observed versus 21 expected), not a vulture failure. Current reproduction PASS: 117 passed / 6 skipped across the schema, soak-gate and boot-contract test files. Current schema expectations explicitly include all three Gauntlet audit columns. Ruff check, format check (3277 files), backlog consistency (168 items) and ADR index all PASS.

Read accepted ADR-081226-a66b (canonical lifecycle), ADR-081626-f383 (store-owned execution fences; no implicit lease-expiry takeover), ADR-085 (principal-keyed rate control), and proposed ADR-081 (deployment topology). No competing execution authority or acceptance waiver is introduced. The profile itself describes omitted representative workloads; current runner refuses exact-RC artifact equivalence and its schedule probe does not execute physical work. Fresh tests reproduce a separate rate allowance on each production middleware instance. The acceptance table below distinguishes these observations from actual deployed soak evidence.

## Executed validation

Commands executed in the assigned worktree with 1200-second timeouts:

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1323/1323 identities.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q`: PASS, 117 passed / 6 skipped. Skipped live database coverage is not claimed.
- `uv run pytest packages/maistro-server/tests/api/test_rate_limit.py -x -q`: PASS, 26 passed.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3277 files already formatted.
- `uv run python scripts/check-backlog-consistency.py`: PASS, 168 items.
- `uv run python scripts/check-adr-index.py`: PASS.
- `uv run python` with `runpy.run_path('scripts/soak/run_soak.py')`: asserted the current artifact check returns `ok=False`; evaluated `docs/testing/soak/evidence/m3a-round6-shakedown.json` and asserted rejection for duration and artifact identity. Actual failed checks: `sustain_duration`, `exact_rc_artifact`. This is fresh evaluator validation of historical evidence, not a new soak.

Production reachability was inspected: `packages/maistro-server/src/maistro_server/main.py:648` installs `RateLimitMiddleware`; its constructor at `api/rate_limit.py:93` creates an `InMemoryRateLimiter` per instance. Existing tests at `tests/test_soak_promotion_gates.py:439` execute that production middleware and freshly reproduce `[200, 200, 429]` independently on both instances for the same authenticated or unauthenticated identity. Those tests demonstrate an additional allowance through replica selection, not a cluster-wide limit.

## Acceptance audit

| #860 acceptance criterion | Executed evidence / disposition |
| --- | --- |
| Representative RC load profile | Profile read; it explicitly omits concurrent user/Workspace populations, fan-out, successful model/tool calls, Design/Canvas and Goal/background workloads. Complete RC profile UNVERIFIED. |
| At least two deployed application replicas | Boot-contract and two-instance middleware tests passed, but no deployed exact-RC pair exercised this round. UNVERIFIED. |
| Sustained saturation, queue growth, expiry/reclaim, retries, leaks | Historical evidence rejected for duration; no fresh sustained run. UNVERIFIED. |
| No duplicate physical work, including Goal reconciliation | Admission tests passed; `scripts/soak/run_soak.py:1067` cancels the probe without execution. Physical-work uniqueness and Goal reconciliation UNVERIFIED. |
| Replica-selection non-bypass, security and degraded behavior | Fresh production-middleware counterexample above shows independent allowances. Non-bypass NOT MET; full deployed security/degraded behavior UNVERIFIED. |
| Complete telemetry and explicit thresholds | Profile has partial thresholds, but driver-loop latency is not application-loop latency. No new RC telemetry. UNVERIFIED. |
| Active-work kill/restart, graceful drain/fencing/recovery | No current production active-work restart performed. Unit/admission checks cannot prove physical recovery. UNVERIFIED. |
| Long-running exact RC artifact/configuration soak | Current `preflight_artifact_check` at `run_soak.py:744` returns false; historical evidence also rejected. No >=4-hour exact-RC soak. UNVERIFIED. |
| Classify findings to earliest broken milestone invariant | Backlog consistency passed, but completeness of production-load findings/classification UNVERIFIED. No GitHub mutations permitted or performed. |
| Publish hash-bound machine/human production evidence | This report is local validation only; no new hash-bound production soak pack. UNVERIFIED. |

## Disposition and handoff

**BLOCKED** on production acceptance, not on the requested vulture gate. The historical schema regression is already repaired at the starting head. No evidence justifies another ledger amendment, gate change or cosmetic source edit. Only this report changed; no source/tests changed, so no inventory delta is required.

Next prerequisites: an identified exact-RC artifact/config manifest, a production-capable representative workload with physical-effect and recovery observations, and resolution of the process-local rate policy versus #860's replica-selection requirement, followed by the >=4-hour soak. ADR-081626-f383 does not authorize inventing lease-expiry takeover to satisfy the issue; reconciliation must preserve the canonical Goal -> Graph -> Run -> NodeRun -> Attempt model. The proposed deployment ADR does not waive the issue's acceptance criteria.

Residual risks are the unverified acceptance surfaces above. Repeating the clean ledger repair cannot supply production evidence. No merge conflict exists, no fetch/merge was needed, and no push, PR, comment or closure action was performed.

Progress: checked 1 issue; done 0 acceptance-complete; skipped 0; failed validation commands 0; blocked 1. This report is committed locally as a handoff, not integration approval.
