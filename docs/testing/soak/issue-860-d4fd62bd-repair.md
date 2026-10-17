# Issue #860 — d4fd62bd CI repair

## Frozen scope

- Assignment: issue #860 only, branch `auto-860`, starting head
  `221e0e0c2212850953a906b0f8f0d50b62700c8c`, supplied develop base
  `56332162cf636e9a1e8a7e346101803ed6ec7b1f`.
- Worktree was clean at start; no incoming edits needed salvage.
- Process the exact vulture per-identity gate results once; review reported
  production identities and amend `quality/vulture-baseline.json` only as
  explicitly authorized by this CI-repair assignment.
- Inspect repository instructions, applicable ADRs, existing soak runner/tests,
  supplied dispatch and acceptance evidence. Do not broaden into other issues,
  a new execution authority, or a speculative distributed-rate-limit redesign.
- Expected edits: this report and the vulture ledger if actual results justify
  amendment; production changes only for genuinely dead reported identities.
  Any added tests require an inventory delta note.
- Ambiguity resolved: this is the writer lane (explicit repair + local commit),
  not the read-only verifier lane. No driver `check-*.log` files were present in
  the supplied job directory at initial inspection.

## Results

The exact assigned vulture command passed (exit 0): **1336 reviewed identities
and 1336 findings**, zero unclassified and zero never-allowlist findings, against
base `56332162cf63`. There are no reported unbanked identities to repair, so no
ledger amendment is justified. Log: `/tmp/issue-860-d4fd62bd-vulture.log`.
The supplied previous result is BLOCKED on soak acceptance, not a merge conflict.
No develop sync is indicated.

Fresh validation (all exit 0):

- `uv run ruff check .` — all checks passed.
- `uv run ruff format --check .` — 3003 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py -x -q` — 52 passed.
  This includes real production `RateLimitMiddleware` instances giving the same
  principal a fresh allowance on replica 2, for both authenticated and anonymous
  requests. These ASGI tests are counterexamples to cluster-wide budgeting, not
  evidence of a deployed RC soak. CLI regressions also reject four-hour
  host-process evidence without an exact-RC artifact record.
- Logs: `/tmp/issue-860-d4fd62bd-{ruff-check,ruff-format,pytest}.log`.

Additional fresh validation:

- `uv run pytest packages/maistro-server/tests/api/test_rate_limit.py -x -q`
  — 22 passed (exit 0).
- `uv run python scripts/check-doc-links.py` — 1851 Markdown files, zero
  broken relative links (exit 0).
- Imported the current `scripts/soak/run_soak.py` and evaluated
  `evidence/m3a-round6-shakedown.json` with `failed_promotion_checks`;
  asserted both `sustain_duration` and `exact_rc_artifact` fail, and asserted
  the evidence commit differs from the assigned head (exit 0).
- `git diff --check 56332162cf636e9a1e8a7e346101803ed6ec7b1f...HEAD`
  — exit 0. The supplied old whitespace findings do not reproduce against
  this assignment's base/head.

No source or test changes are warranted by these checks. Existing regression
coverage was executed rather than duplicated; no inventory delta is needed.

An initial instruction-file search accidentally listed sibling worktree paths;
no sibling file was read or changed. All implementation remains in this worktree.

## Architecture reconciliation

Read repository `AGENTS.md`, `docs/README.md`, `docs/quality-gates.md`,
ADR-081, ADR-096, and ADR-081626-f383. ADR-081 is **Proposed**, not an
accepted waiver of release evidence. Accepted ADR-096 assigns production
execution to maistro-server, not a second Conductor executor. Accepted
ADR-081626-f383 assigns Attempt leases/fences to the canonical Run store;
admission uniqueness alone does not establish physical-work uniqueness.
No authority, scheduler, authentication path, or execution-model change is made.
The canonical `Goal -> Graph -> Run -> NodeRun -> Attempt` model is preserved.

Production reachability was inspected: `maistro_server/main.py:628` installs
`RateLimitMiddleware`; `api/rate_limit.py:72-77` constructs its process-local
limiter. The reference Compose file defines two application services, but the
soak driver explicitly reports a host-uvicorn preflight, not those RC images.
The exact vulture invocation matches both blocking workflow definitions.

## Acceptance review

All ten criteria from the supplied frozen issue body were checked. Historical
observations below are read from retained evidence, not new deployment runs.

| Criterion | Evidence and disposition |
| --- | --- |
| Representative RC profile | **UNVERIFIED.** `m3a-load-profile.md:152-165` names missing multi-user/Workspace, Graph/tool/Canvas and reconciliation workloads. |
| At least two application replicas | Historical two-replica preflight exists; **UNVERIFIED for the production RC**. `run_soak.py:635-646` rejects artifact equivalence. No deployed topology was exercised in this round. |
| Sustained saturation, reclaim, retry, leak and shutdown observations | **UNVERIFIED.** Round-6 JSON records 90.43 seconds against 14400 required (`:221-225`); current evaluator rejects it. |
| Exactly-once/fenced physical work, including Goals | **UNVERIFIED.** Round-6 schedule probe cancels its admitted Run (`:12-16`); no physical Attempt work is thereby proven. Profile explicitly acknowledges this (`:197-200`). |
| Security/degraded behavior without replica-selection bypass | **Not proven; independent allowance counterexample reproduced.** Both parametrizations of `test_replica_selection_has_an_independent_production_allowance` passed (`tests/test_soak_promotion_gates.py:439-489`): same identity gets `[200, 200, 429]` on each replica. Local enforcement is intentional, not cluster-wide enforcement. |
| All required telemetry and thresholds | **UNVERIFIED.** Profile identifies driver-loop rather than application-loop latency, missing worker counts and unvalidated repaired process sampling (`:157-165`). Historical wrapper-only RSS cannot certify application leaks. |
| Kill/restart during physical work with fencing/recovery | **UNVERIFIED.** Historical exit/rejoin/drain counters are not proof of physical-work recovery; no new active-work recovery run was executed. |
| Long soak of exact promoted RC/config | **UNVERIFIED and blocked.** Current evaluator rejects retained evidence with `['sustain_duration', 'exact_rc_artifact']`; increasing host-preflight duration cannot satisfy artifact identity. |
| Findings classified to earliest invariant | Human evidence pack contains F-series findings/classifications, but completeness and external filing are **UNVERIFIED**. No GitHub mutation was performed. |
| Machine/human evidence tied to exact artifact/config | Historical machine and human packs exist. **UNVERIFIED for this RC**: round-6 `hashes.git_head` is `b31c5fdaa63b40506335bbb288889e87bdb9ba0c`, not the assigned head, and lacks exact production image/config proof. |

## Handoff

**BLOCKED**, not merge-ready. The requested vulture failure did not reproduce;
changing a matching ledger or the fail-closed soak gate would be unjustified.
This round changes only this report and commits it locally. No tests were added,
no ledger or grants changed, no historical evidence overwritten, no RC soak run,
and no release acceptance waived.

Next: the release owner must select the immutable RC image/configuration and
resolve the representative workload and replica-budget contract gaps, then run
and publish the exact production-topology soak with physical-work recovery and
application telemetry. Repeating this already-green vulture scan is not a remedy
for those missing acceptance observations.

Progress: checked 1 assigned issue; done 0 acceptance closures; skipped 0;
validation command errors 0; CI failure not reproduced. All ten acceptance
criteria are accounted for above.
