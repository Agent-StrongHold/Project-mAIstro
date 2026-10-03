# #860 repair checkpoint

## Frozen scope

- Assigned issue: #860 only; branch `auto-860`, initial HEAD
  `01834c586ab41935a4a10030f9f98088bb8221d1` (verified); initial worktree clean.
- Review existing `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`,
  `docs/testing/soak/`, adjacent persistence/backpressure tests and production
  deployment/rate-limit configuration. No unrelated base-diff reconciliation.
- Required CI repair: execute `scripts/check-vulture-baseline.py`; change only
  demonstrated dead code or reviewed identities in `quality/vulture-baseline.json`.
- Potential edits limited to those scope files, a corresponding inventory note
  if tests change, and this handoff. No production topology redesign or invented
  promotion evidence.

## Initial evidence / assumptions

- Assigned job directory has no `check-*.log` files in its initial listing;
  driver validation claims cannot be independently inspected there.
- Starting commit resolves; no uncommitted work or merge conflict to salvage.
- The supplied develop base differs broadly from this branch; assumption: this
  is an issue repair, not authorization to reconcile unrelated changes.
- Prior blocked result will be inspected before deciding what is repairable.

## Progress

- Fresh required vulture check PASS: 1402 findings / 1402 reviewed identities,
  zero unclassified/never-allowlist. No ledger amendment is justified.
- Prior result inspected: BLOCKED; no immutable promotion RC designated. The
  former H3 shared-store claim is already corrected in current documentation.
- Confirmed actual remaining sampler defect: `start_replica` launches a `uv`
  wrapper plus application child, but `sample_once` measures only `proc.pid`.
  Historical flat RSS/FD results therefore do not establish application health.
  Proceed with a focused process-group sampling repair and regression tests,
  without changing runtime topology or claiming production soak acceptance.
- Read accepted ADR-081626-f383, ADR-082426-82c7 and ADR-085. Attempt fencing and
  occurrence admission stay with canonical stores; no scheduler, execution or
  authorization authority will be introduced. Cluster-limit acceptance remains
  unmet rather than reinterpreted as process-local enforcement.

- Reproduced F12 before repair with a live `uv run` wrapper/child: allocating
  32 MiB in the child left sampled RSS unchanged at 25952 KiB; the new regression
  failed against the old implementation. After the repair all 52 soak regressions
  pass, including six new sampler cases. Targeted ruff lint passed; format check
  found two files needing formatting (subsequently fixed before final validation).
- Sampler now observes the replica process group including application children,
  records per-PID values and process counts, and leaves incomplete aggregates
  null. Historical S1/S2 application-health conclusions are explicitly invalidated;
  raw JSON/logs stay untouched. See F12 in the evidence pack. No external filing.

## Fresh validation

Commands executed in the assigned worktree (1800-second timeouts):

| Command | Result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1402 reviewed identities, zero unclassified/never-allowlist |
| `uv run pytest tests/test_soak_promotion_gates.py -k sampler_observes_uv_child_memory_and_descriptors -x -q` before implementation | EXPECTED FAIL: wrapper RSS 25952 -> 25952 despite child's 32 MiB allocation |
| `uv run pytest tests/test_soak_promotion_gates.py -x -q` after repair | 52 passed |
| `uv run ruff format scripts/soak/run_soak.py tests/test_soak_promotion_gates.py` | Formatted both files after targeted format-check failure |
| `uv run ruff check . && uv run ruff format --check .` | PASS; 2624 files formatted |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q` | 102 passed, 5 skipped in 9.04s; skips are PostgreSQL-dependent and not live validation |
| `uv run python scripts/check-suite-inventory.py --suite tests/` | PASS: 4198 collected, matches inventory (+6 sampler cases) |
| `uv run python -` (import actual driver, evaluate historical round-6 JSON, assert negative preflight artifact verdict) | PASS: 90.43 seconds; failures exactly `sustain_duration`, `exact_rc_artifact` |
| `git diff --exit-code 01834c586ab41935a4a10030f9f98088bb8221d1 -- docs/testing/soak/evidence` | PASS: historical raw evidence untouched |
| `git diff --check` | PASS |

## Acceptance disposition

| Criterion | Fresh evidence / remaining gap |
| --- | --- |
| Representative RC load profile | PARTIAL: existing profile inspected; concurrent users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas and Goal workers are explicitly missing. Applicability to a designated RC remains UNVERIFIED. |
| Two production replicas | UNVERIFIED: Compose defines two application services, but this round executes only a uv wrapper/child sampler fixture and in-process middleware tests, not the production topology. |
| Sustained saturation/reclaim/retries/leaks | UNVERIFIED: current evaluator rejects preserved 90.43-second evidence against 14400 seconds; no new soak. |
| Exactly-once/fenced physical work, Goal reconciliation | UNVERIFIED: 12 admission-oracle cases pass, but observed Run identity is not physical-effect deduplication. Historical schedule probe cancels its queued Run. Canonical Attempt/occurrence authority is unchanged. |
| Rate-limit/security/degraded non-bypass | NOT MET for cluster-wide allowance: executed production middleware regression still observes `[200,200,429]` independently on each replica for the same identity, for both identity classes. Local identity/security tests pass; full RC degraded behavior UNVERIFIED. |
| Required metrics and thresholds | PARTIAL repair: live uv child memory/descriptor growth now reaches the sampler; per-process observations and counts are recorded. Complete RC metrics/thresholds, application-loop lag, container/detached-worker coverage and long-window stability remain UNVERIFIED. |
| Kill/restart active-work recovery | UNVERIFIED: sampler retains child observations after wrapper exit in a regression, not an application shutdown/fencing/recovery proof. No replica kill/restart under RC traffic performed. |
| Long-running exact-RC soak, repeated after changes | BLOCKED: no immutable promotable image/configuration designated. Existing driver is host preflight, and its artifact gate still rejects even four-hour emulator evidence. This sampler code change requires a new run; no old evidence is credited. |
| Findings filed/reclassified before promotion | PARTIAL: F12 classified locally at earliest broken invariant M3-A evidence validity. External filing UNVERIFIED and prohibited in this lane. |
| Machine/human evidence tied to artifact/config hashes | PARTIAL: historical pack preserved byte-identically, human claims corrected; exact-RC hash-tied soak evidence UNVERIFIED. |

## Changed files and residual risks

- `scripts/soak/run_soak.py`: process-group sampling; no runtime topology changes.
- `tests/test_soak_promotion_gates.py`: six sampler regressions, including real uv child.
- `docs/testing/inventory-notes/m3a-860-process-group-metrics.md`: +6 inventory delta.
- `docs/testing/soak/m3a-load-profile.md`: precise sampling scope/limitations.
- `docs/testing/soak/m3a-soak-evidence.md`: F12 and invalidated historical S1/S2 conclusions.
- This handoff: fresh validation, acceptance disposition and next actions.

Linux process-group enumeration is non-atomic; shared RSS may be double-counted,
and detached workers/container metrics are not covered. Process counts are
observed membership, not proof of correct execution or recovery. None of the
short regression traffic is a sustained load test. No production, ledger, grant,
authorization, scheduler, event-store or historical raw-evidence edits were made.

## Disposition

**BLOCKED** for #860. The evidence-backed sampler repair is ready for handoff,
not integration approval. Next: owner designates immutable RC images/config,
resolves cluster allowance semantics, completes production-path workload and
physical-effect/metric oracles, then executes/publishes a new >=4-hour soak.
Do not rerun the emulator and call it promotion evidence.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: exact-RC prerequisites and sustained soak}`.
Focused repair and validation complete; all six changed files will be committed
locally. No promotion soak was executed and no GitHub mutation was made.
