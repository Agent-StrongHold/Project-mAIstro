# Issue #860 — repair checkpoint (8803be39)

## Frozen scope

- Issue: #860 only; writer lane `auto-860`.
- Starting head: `70b1b64216da8ea6a852ac36c270298afe86c354`.
- Supplied base: `b672b799aba6d3db9edc3e1be18b1a3335dd3bc0`.
- Supplied dispatch snapshot: job `8803be3976aa44ebbaa5c43f6e55eabd`;
  no GitHub refresh or mutation.
- Clean incoming worktree; no uncommitted salvage needed.
- Review scope: repository instructions and relevant ADRs; `scripts/soak/`,
  adjacent `tests/test_soak*`, existing `docs/testing/soak/` evidence;
  production rate-limit middleware; exact vulture gate and reviewed identities
  it reports in `quality/vulture-baseline.json`. Change scope is this report,
  verified gate repairs, and inventory notes only if tests change.
- No supplied `check-*.log` files exist in the job directory snapshot.
- Assumption: this is a writer repair, not a read-only verifier, as explicitly
  assigned. Prior BLOCKED verdict is evidence to recheck, not proof.
- Canonical execution authority remains Goal -> Graph -> Run -> NodeRun ->
  Attempt. No new scheduler, authorization path, or event authority.

## Progress

Exact requested vulture gate PASS (exit 0): 1338 reviewed identities match
1338 findings; zero unclassified and zero never-allowlist findings. The gate
selected base `cd5618223cbd` and candidate `70b1b64216da`. No unbanked
identity exists to amend: conditional ledger repair skipped rather than
inventing debt. `git diff --check` against the supplied base also passes;
the prior whitespace defect does not reproduce. The profile still explicitly
limits the runner to host-process preflight rather than production Compose.
Root ruff check, root ruff format --check, and focused soak/rate-limit/task
backpressure pytest all returned exit 0 (outputs inspected: 75 passed in
3.49 seconds; 2943 Python files already formatted). Production
`maistro_server/main.py:593` installs the reviewed middleware, whose constructor
creates a process-local limiter. Accepted ADR-081626-f383 places physical
execution fencing in the canonical Run store; admission deduplication cannot
substitute for physical-work proof. ADR-081 is Proposed, not an acceptance
waiver. One attempted ADR filename (`ADR-085-resource-caps-rate-limits.md`)
was not found and skipped; the discovered filename is
`ADR-085-cost-quota-rate-limiting.md`. That accepted ADR requires per-principal
limiting. It does not establish that the present per-process implementation
satisfies #860's replica-selection non-bypass criterion. No policy waiver or
competing authorization path is introduced.

## Executed validation

Commands ran locally in the assigned worktree, with 600/1200-second validation
timeouts; no earlier pass claims were substituted for execution.

| Command | Result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS; 1338 exact reviewed identities. Matches `.github/workflows/vulture-ratchet.yml:82-85`. |
| `uv run ruff check .` | PASS. |
| `uv run ruff format --check .` | PASS; 2943 files already formatted. |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_rate_limit.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | PASS; 75 tests. |
| `uv run python scripts/check-ratchet-provenance.py` | PASS; 49 quality JSON consumers have explicit provenance. |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS. |
| `uv run python scripts/check-suite-inventory.py` | PASS; 15 suites, 26365 unique test identities, no duplicate evidence. |
| `uv run python scripts/check-backlog-consistency.py` | PASS; 168 items. |
| `git diff --check b672b799aba6d3db9edc3e1be18b1a3335dd3bc0...HEAD` | PASS before this documentation-only commit. |

Fresh `uv run python` import of `scripts/soak/run_soak.py` evaluated retained
`docs/testing/soak/evidence/m3a-round6-shakedown.json`:

- `failed_promotion_checks`: `sustain_duration`, `exact_rc_artifact`.
- Sustained duration: **90.43 seconds**, required minimum **14400**.
- `hashes.git_head`: `b31c5fdaa63b40506335bbb288889e87bdb9ba0c`, not assigned HEAD.
- `preflight_artifact_check()`: `ok=false`, `topology=host-uvicorn-preflight`.

The middleware counterexamples in `tests/test_soak_promotion_gates.py:437-489`
execute the production class installed at `maistro_server/main.py:593`.
Both authenticated and unauthenticated identities get `[200, 200, 429]` on
replica 1 and then another `[200, 200, 429]` on replica 2. These are ASGI
counterexamples, not evidence of a successful concurrent production deployment.
CLI fail-closed tests and real child-process resource sampling also pass.

Local raw validation logs: `/tmp/860-8803be39-*.log`. This committed report
preserves their outcomes. No source, test, ledger or grant changes were warranted
by the CI checks. No test additions means no inventory delta is required.

## Acceptance disposition

| #860 criterion | Executed evidence / remaining gap |
| --- | --- |
| Representative RC load profile | UNVERIFIED: `m3a-load-profile.md:152-160` omits user/Workspace populations, Graph fan-out, successful tools/models, Canvas, and Goal/background workloads. No representative deployment workload executed here. |
| At least two supported production application replicas | UNVERIFIED: profile lines 19-24 and the executed artifact check identify host-process preflight, not the selected production artifact. |
| Sustained saturation, queues, reclaim, retries, leaks and restart | UNVERIFIED: retained evidence fails minimum duration; no fresh sustained run performed. |
| Schedule/task/Run/Attempt/Goal physical-work fencing | UNVERIFIED: profile lines 197-200 correctly distinguish admission deduplication from execution/reconciliation proof. No physical-work race/reclaim soak performed. |
| Replica-selection-safe rate limiting/security/degradation | NOT MET for non-bypass: two passing production-middleware counterexamples demonstrate fresh peer allowance. Local security and backpressure tests pass; complete concurrent production behavior remains UNVERIFIED. |
| Complete thresholded production telemetry | UNVERIFIED: sampler regression passes but driver loop lag is not application loop latency; pool saturation, workers and long-window measurements remain absent. |
| Kill/restart during active work; drain/fencing/recovery | UNVERIFIED: gate regression tests pass, but no production active-work recovery run was performed. |
| Long-running exact RC artifact/configuration | NOT MET: current evaluator rejects the retained 90.43-second host preflight for both artifact and duration. A longer run of this driver cannot satisfy the artifact criterion. |
| Findings classified to earliest broken invariant | Backlog consistency gate passes; classification completeness remains UNVERIFIED. No GitHub actions authorized or performed. |
| Machine/human evidence bound to exact image/package/commit/config | Historical evidence exists but is tied to an older commit. Current production RC-bound evidence remains UNVERIFIED. |

## Final handoff

**BLOCKED.** The explicit CI failure does not reproduce; a speculative ledger
amendment or cosmetic source repair would not address actual evidence. This
round does not resolve #860's production acceptance blockers and claims no new
soak. Select the immutable RC image/configuration, reconcile the documented
per-process rate-limit semantics with non-bypass acceptance, complete the
representative workload and production telemetry/fencing probes, then execute
a fresh >=4-hour production soak. Any runtime/config change needs another soak.
No production resources were started or changed.

Changed file: `docs/testing/soak/issue-860-8803be39-repair.md` only; local commit
required for handoff. No push, PR, issue mutation, fetch or merge performed.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "resolve RC and
production acceptance blockers"}`. The assigned item is explicitly finalized
as blocked; no additional item was started.
