# Issue #860 — repair validation, job 697fd82d

## Frozen scope

- Only issue #860, branch `auto-860`, assigned worktree `/home/dev/Git/wt/auto-860`.
- Starting HEAD verified: `149843c2709b447615e1ce3bec9f0840735b5cd6`.
- Provided comparison base: `045cfdfbe3eaa0c84493eb02754d7410b0c69378` (resolved by `git diff`).
- Initial working tree clean; no incoming edits to salvage.
- Review inputs: repository instructions; relevant execution, fencing, recurrence,
  deployment and rate-limit ADRs; `scripts/soak/run_soak.py`;
  `tests/test_soak_promotion_gates.py`; `tests/test_prod_stack_boot_contract.py`;
  `docs/testing/soak/m3a-load-profile.md`, `m3a-soak-evidence.md`;
  four historical JSON evidence packs (`m3a-soak-evidence`,
  `m3a-repair-validation`, `m3a-round5-final`, `m3a-round6-shakedown`);
  production rate middleware and adjacent tests; task backpressure and PostgreSQL
  learning-schema regression tests; CI vulture script/workflow and ledger.
- Planned edit surface: this report; `quality/vulture-baseline.json` or genuinely
  dead source only if the requested exact scan supplies actionable evidence.
  No scheduler, store, authorization or runtime configuration changes planned.
- Prior job result inspected: `62822668dc244ad4887e11f6e3becade/result.json`
  reports BLOCKED, but its checks are not treated as current verification.
- Current job directory listing contains no `check-*.log` files. Driver evidence
  is unavailable; execute local validation rather than invent results.

## Ambiguity and assumption

The assignment is a writer/CI-repair round, not a read-only verifier round.
No merge conflict exists. The provided base comparison includes unrelated
historical divergence; do not repair or merge unrelated items. No exact immutable
RC artifact/configuration was supplied. Do not promote a host-process preflight
or manufacture a passing soak. Any new promotion claim needs fresh RC evidence.

## Results

- Exact assigned vulture command executed with a 600-second timeout:
  `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`:
  PASS, 1361 findings / 1361 reviewed identities; zero unclassified and zero
  never-allowlist findings. No ledger amendment is justified by this scan.
- Current profile and evidence already disclaim the false shared-store H3 claim.
  The production middleware still constructs an `InMemoryRateLimiter` per instance.
  Next: execute the existing production-middleware regressions independently.
- ADR reconciliation: ADR-085 requires canonical principal keys, but does not
  prove shared state; ADR-081 is Proposed deployment guidance. Accepted
  ADR-081626-f383 and ADR-082126-f69c require canonical Attempt fences and
  schedule-to-Run admission, not another scheduler. An admission-only race is
  not physical-work recovery evidence. No architectural exception is introduced.
- `uv run ruff check .`: PASS. `uv run ruff format --check .`: PASS,
  2802 files already formatted (1200-second command timeout).
- Docker availability rechecked: daemon 29.7.2 reachable. Created only this
  job's scratch PostgreSQL container `maistro-860-697fd82d-pg`
  (`2568e9bfce00`), image `pgvector/pgvector:pg18`, loopback-only ephemeral
  port, database `maistro_860`. No RC application deployment is claimed.
- Scratch PostgreSQL ready at `127.0.0.1:45517`. With
  `DATABASE_URL=postgresql://postgres@127.0.0.1:45517/maistro_860`,
  `uv run alembic upgrade head`: PASS, complete migration chain through 050.
- With `MAISTRO_TEST_PG_DSN` set to that scratch DSN,
  `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q -rs`:
  **93 passed in 2.41s, zero skipped** (1200-second timeout).
  These exercise live persistence, canonical task admission/backpressure,
  production rate middleware, process-group sampling and promotion rejection.
  They are not an RC soak or a live two-application deployment.
- The two replica-selection regressions reproduce `[200, 200, 429]` on each
  independent production middleware instance for the same authenticated or
  unauthenticated identity. Replica 1 remains exhausted while replica 2 grants
  another allowance (`tests/test_soak_promotion_gates.py:439–488`).
- Executed an independent `uv run python` audit importing current
  `failed_promotion_checks` against all four frozen historical packs.
  Every pack fails `sustain_duration` and `exact_rc_artifact`.
  Runs 5/6 record 90.17/90.43 seconds versus the 14400-second minimum;
  the earlier packs lack duration gate records. Assertions PASS; promotion
  does not. `scripts/soak/run_soak.py:635–645` deliberately returns a failed
  exact-artifact gate for its host-process topology. No new soak was run.
- Production reachability confirmed at
  `packages/maistro-server/src/maistro_server/main.py:588`:
  the shipped app installs `RateLimitMiddleware`.
- CI arguments verified in `.github/workflows/quality.yml:960–965` and
  `vulture-ratchet.yml:76–85`. Also executed:
  `uv run python scripts/check-ratchet-provenance.py`: PASS (45 consumers and
  delegated checks); `uv run python scripts/check-shipped-surface-truth.py`:
  PASS. These gates resolve their own baseline to `8c8fc8d6706a`; do not
  confuse that with the assignment's comparison base or integration approval.
- Stopped only `maistro-860-697fd82d-pg`; its container/data are retained.
  No other Docker resources were changed. `git diff --check`: PASS.

## Acceptance assessment

| Issue criterion | Current evidence and verdict |
| --- | --- |
| Representative RC load profile | PARTIAL; completion UNVERIFIED. `m3a-load-profile.md:151–166` explicitly lacks multiple users/Workspaces, Graph fan-out, successful model/tool work, Design/Canvas and Goal/background-worker coverage. No selected RC configuration justifies exclusions. |
| At least two application replicas | UNVERIFIED under RC load. Boot-contract tests pass but are configuration checks, not a deployed two-replica run. Only scratch PostgreSQL was deployed here. |
| Sustained saturation, queue growth, lease expiry/reclaim, retries and leaks | UNVERIFIED. The four-pack audit rejects historical duration evidence. Short focused tests do not establish sustained behavior. |
| No duplicate physical work; task/Run/Attempt/schedule and Goal correctness | UNVERIFIED under multi-replica load. Admission-oracle tests pass; the existing schedule probe cancels its queued Run without physical execution (`m3a-load-profile.md:191–196`). No Attempt-correlated recovery experiment was run. |
| Rate/security/degraded behavior cannot be bypassed through replica selection | NOT MET for a shared principal allowance: real middleware regressions reproduce independent replica budgets. Broader security/degraded behavior under exact-RC load is UNVERIFIED. |
| Complete telemetry and explicit pass/fail thresholds | UNVERIFIED for the RC. Sampler regressions pass, but no fresh application event-loop, pool saturation, queue/lease and long-window process/descriptor telemetry exists in the inspected evidence. |
| Active-work replica kill/restart; drain, fencing and recovery | UNVERIFIED. No production-artifact failure injection executed; historical process rejoin does not prove physical Attempt fencing. |
| Long-running soak of exact RC artifact/configuration | NOT MET. All four packs fail both artifact and duration gates. No immutable RC/configuration was supplied; current driver explicitly cannot certify it. |
| Findings filed/reclassified at earliest milestone invariant | PARTIAL; external filing UNVERIFIED. Existing F11/F12 are classified locally as M3-A evidence validity. No new load run/finding and no prohibited GitHub mutation performed. |
| Machine/human evidence bound to exact image/package/commit/config hashes | UNVERIFIED for promotion. Existing historical packs are retained, but rejected by current gates. This report is focused validation, not a soak signature. |

## Handoff

**BLOCKED for #860 acceptance.** The assigned exact-debt-ledger CI check is
already green; there is no evidence-backed ledger or dead-code repair to make.
The prior false H3 claim is already corrected in the current evidence document.
Only `docs/testing/soak/issue-860-697fd82d-repair.md` changes in this round.
No production, test, runtime-config, ledger or grant change; no test inventory
delta and therefore no new inventory note. Existing meaningful tests were rerun,
not replaced by cosmetic new tests.

Required next work: supply the immutable RC image/configuration that #89 intends
to promote; complete a representative production-path runner and telemetry;
resolve the replica-budget/non-bypass mismatch through canonical enforcement;
then execute a qualifying ≥14400-second exact-artifact soak with physical Attempt
correlation and active-work fault injection. Any code/runtime-config change
requires another soak. A short host-process run or another passing ledger scan
cannot resolve these prerequisites.

Canonical execution remains Goal → Graph → Run → NodeRun → Attempt. No competing
scheduler, authorization path or execution authority was introduced. This report
is committed locally as a blocked handoff, not integration approval.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "#860 RC identity, representative production runner, replica non-bypass, qualifying soak"}`.
