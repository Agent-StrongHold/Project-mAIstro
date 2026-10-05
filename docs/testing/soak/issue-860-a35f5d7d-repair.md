# Issue #860 — a35f5d7d CI repair

## Frozen scope

- Assigned issue: #860 only; branch `auto-860`.
- Starting HEAD: `242915262bfaf7c7bfa955f773cfb3cc1fc836d2`.
- Supplied develop base: `56332162cf636e9a1e8a7e346101803ed6ec7b1f`.
- Initial worktree clean; no salvage required.
- Process only the supplied dispatch snapshot, the exact vulture gate's reported
  identities, their adjacent tests/architecture, the permitted vulture ledger,
  and this report. No GitHub mutation or dependency issue implementation.
- Ambiguity resolved: the explicit CI-repair instruction permits reviewed ledger
  amendments; it does not authorize weakening gates or declaring a soak passed.
- The supplied job directory contained no driver `check-*.log` files at entry.

## Progress

The exact requested vulture command passed (exit 0): 1,342 findings match
1,342 reviewed identities, with zero unclassified or never-allowlist findings.
Its automatically selected base was `c560d4ccad82`; the rerun with
`RATCHET_BASE_REV=56332162cf636e9a1e8a7e346101803ed6ec7b1f` also passed
and resolved to that same merge base. No unbanked/stale identities were reported, so
there is no evidence-based ledger amendment or dead-code repair to make.
`git diff --check 56332162cf636e9a1e8a7e346101803ed6ec7b1f...HEAD`
also passed: the prior whitespace finding does not reproduce at this head.
Focused validation passed: ruff lint and formatting (2,985 files), 74 soak-gate
and production rate-limiter tests, ratchet provenance and shipped-surface truth.
The current evaluator rejected the retained round-6 JSON for `sustain_duration`
and `exact_rc_artifact`. Its recorded head is `b31c5fdaa63b40506335bbb288889e87bdb9ba0c`,
not the assigned head. The production-middleware replica-selection counterexample
passed for both authenticated and unauthenticated identities.

No production code, tests, inventory counts, or ledgers changed. No new tests
are warranted for a non-reproducing scanner failure; existing meaningful tests
were executed rather than duplicated. No inventory-delta note is required.

## Architecture reconciliation

Read repository `AGENTS.md`, `docs/README.md`, ADR-081, ADR-085,
ADR-081426-1f7c and ADR-081626-f383, plus the runner, production Compose,
production middleware and adjacent tests. ADR-081 is **Proposed**, not an
accepted waiver of any issue criterion. The production reference Compose still
names two application replicas, a PostgreSQL primary/replica, Redis and a shared
store. Accepted ADR-085 requires per-principal limits but does not establish a
shared multi-replica counter. Existing process-local semantics must not be
misrepresented as replica-selection non-bypass.

Accepted runtime/fencing ADRs preserve canonical Attempt execution authority;
lease-expiry takeover is explicitly outside ADR-081626-f383's current boundary.
One admitted Run or a restarted process is not proof of unique physical work.
No scheduler, execution authority, Goal store, event authority or authorization
path was introduced or changed.

## Commands executed

All validation commands completed with exit 0 unless explicitly described as a
rejected evidence result. Long validation timeouts were 1,200 seconds.

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  — 1,342 exact identities; no debt/bookkeeping changes.
- Same command with `RATCHET_BASE_REV=56332162cf636e9a1e8a7e346101803ed6ec7b1f`
  — same passing result (trusted merge base `c560d4ccad82`).
- `uv run ruff check .` — passed.
- `uv run ruff format --check .` — 2,985 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_rate_limit.py -x -q`
  — 74 passed in 3.17 seconds. These include subprocess sampler checks,
  fail-closed artifact CLI checks and actual production middleware probes; they
  are not a substitute for deployed multi-replica traffic.
- `uv run python scripts/check-ratchet-provenance.py` — passed, including its
  delegated gates; emitted existing syntax/config warnings, not failures.
- `uv run python scripts/check-shipped-surface-truth.py` — passed.
- `uv run python -` import/evaluation probe — loaded the current runner and
  retained round-6 JSON, asserted `failed_promotion_checks` equals
  `['sustain_duration', 'exact_rc_artifact']`, and asserted the current runner's
  artifact check is false. Assertions passed; the evidence remains rejected.
- `git diff --check 56332162cf636e9a1e8a7e346101803ed6ec7b1f...HEAD`
  — passed.

## Acceptance review (all ten issue criteria)

| Criterion | Executed evidence and remaining gap |
| --- | --- |
| Representative RC profile | **UNVERIFIED**. Read `m3a-load-profile.md`: one API key, no user/Workspace population, Graph fan-out, successful model/tool traffic, Canvas or Goal-worker workload. The definition is explicitly incomplete for promotion. |
| At least two application replicas | **UNVERIFIED for RC**. Inspected `deploy/docker-compose.prod.yml` (two replicas), but historical host-process evidence is not execution of that artifact. Two isolated ASGI middleware instances are only a focused counterexample. |
| Sustained saturation, queue/reclaim/retry/leak observations | **UNVERIFIED**. Current evaluator rejects retained 90.43-second evidence against the 14,400-second minimum. No long-window observations executed this round. |
| Schedule/task/Run/Attempt/Goal uniqueness and fencing | **UNVERIFIED**. Existing admission tests passed; historical schedule probe cancels its Run before execution. Neither proves physical-work uniqueness or sustained Goal reconciliation. |
| Security/degraded behavior and replica-selection non-bypass | **NOT MET for a shared allowance**. Both authenticated and unauthenticated production-middleware tests independently exhaust replica 1 and still get two successful requests at replica 2. `main.py:627` installs that middleware in production. Cluster-wide security/degraded behavior remains unverified. |
| Complete telemetry with thresholds | **UNVERIFIED**. Profile documents thresholds and remaining gaps; driver loop lag is not application loop lag, historical RSS/FD measurements were wrapper-only, and required worker/long-window evidence is absent. |
| Kill/restart during active work with drain/fencing/recovery | **UNVERIFIED**. Retained process-exit/rejoin counters are not physical Attempt recovery evidence. No live RC restart executed. |
| Long-running exact RC artifact/configuration soak | **NOT MET**. Current evaluator rejects duration and artifact; `preflight_artifact_check()` returns false unconditionally for this host-process runner. No duration override can repair artifact identity. |
| Findings classified to earliest milestone invariant | **UNVERIFIED for completeness**. Human evidence pack has historical findings/classifications, but no new RC load run was executed and no GitHub mutation is permitted in this lane. |
| Machine/human evidence bound to exact artifacts/hashes | **UNVERIFIED for RC**. Read both evidence formats; retained machine evidence names `b31c5fdaa63b40506335bbb288889e87bdb9ba0c`, not assigned HEAD, and cannot identify the promoted Compose application images. |

## Handoff

Verdict: **BLOCKED** on the actual issue acceptance, not on vulture CI.
The assigned scanner repair has no reproducible defect at the starting head;
changing the ledger would be unjustified. No new soak, RC image selection or
production-configuration claim is made. Only this report changed. Existing
artifacts and ledgers were preserved.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0}`. Validation is complete;
issue acceptance remains blocked. Next: an authorized release lane must select
and exercise the exact RC topology with a representative workload for at least
four hours, observe physical-work/recovery and full telemetry, and resolve the
replica-budget contract before promotion. Do not rerun this unchanged CI repair
without a failing check log or a changed head. This commit is a handoff, not
integration approval or issue closure.
