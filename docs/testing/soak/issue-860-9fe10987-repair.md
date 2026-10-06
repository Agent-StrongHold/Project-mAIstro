# Issue #860 — 9fe10987 repair checkpoint

## Frozen scope

- Issue #860 only; writer lane `auto-860`.
- Starting HEAD: `aff387f6b3ac7a4ce3577347441f7603bb6906fc`.
- Supplied develop base: `a8258ee24dd957d0f0b302db4eee90661fe23439`.
- Worktree was clean; no incoming uncommitted changes to salvage.
- Inputs: supplied job `dispatch-context.json`, prior result if present, repository
  instructions, relevant ADRs, soak runner/profile/evidence/tests, CI vulture
  checker and identities it actually reports. No remote enumeration or mutations.
- Planned edit surface: this report; `quality/vulture-baseline.json` only for
  reviewed retained identities if the requested scan demonstrates drift; dead
  code only if that scan and call-site review prove it dead. Tests/inventory notes
  only if a behavioral repair is required.

## Initial observations and assumptions

The job directory contains no `check-*.log` files at initial inspection. Run
validation locally rather than treating prior verification claims as results.
The lane is explicitly a writer/CI-repair assignment, not a read-only verifier.
The issue requires a long-running exact-RC production soak; unit tests and prior
host-process shakedown evidence cannot establish that acceptance criterion.
No replacement scheduler, Goal store, event authority or authorization path will
be introduced. Remaining production blockers will be reported, not bypassed.

## Results

- Requested vulture command passed (exit 0): 1,336 findings, 1,336 reviewed
  identities; zero unclassified or forbidden findings. No ledger amendment or
  dead-code repair is justified by this scan. Default trusted base printed by
  the checker: `56332162cf63` (not the supplied develop base).
- `git diff --check a8258ee24dd957d0f0b302db4eee90661fe23439...HEAD`
  produced no errors: the historical EOF-whitespace finding is not reproduced.
- Initial ADR filename guesses for numeric 120/121 did not resolve; skipped.
  Read the resolved canonical lifecycle/graph and production-topology ADRs.
- Profile review confirms host-process preflight is explicitly non-promotable,
  with multi-user/Workspace, Graph/tool/Canvas, physical fencing and application
  loop metrics remaining incomplete.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 3,003 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py
  tests/test_prod_stack_boot_contract.py
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  **61 passed in 2.54s**. Includes real production rate-limit middleware showing
  `[200, 200, 429]` independently on each replica for the same identity, and CLI
  rejection of synthetic four-hour evidence without a valid exact-RC artifact.
  ASGI tests are not deployed-replica evidence.
- `docker compose -f deploy/docker-compose.prod.yml config --quiet`: failed
  interpolation because `LITELLM_BASE_URL` is missing. No services started and no
  credentials or RC configuration invented. This is an environment prerequisite,
  not evidence that Compose cannot operate when properly configured.
- Prior result was read as historical evidence only. Its gate and environment
  claims have now been independently checked where noted above.

## Architecture reconciliation

Accepted ADR-081226-69ee and ADR-081226-a66b own Graph snapshots and
Run/NodeRun/Attempt lifecycle; the older ADR-062 traversal design is not a second
execution authority. Admission deduplication cannot establish physical Attempt
fencing. ADR-081 is **Proposed**, not authority to waive #860's explicit production
soak acceptance. The #842 process-local rate budget is documented implementation
behavior, not satisfaction of #860's replica-selection-safe requirement. This
round changes no runtime, gates, thresholds, ledger or authorization path.

## Final acceptance review

The current evaluator was executed against
`evidence/m3a-round6-shakedown.json`: it rejects `sustain_duration` and
`exact_rc_artifact`. That artifact records 90.43 seconds versus 14,400 required
and `git_head=b31c5fdaa63b40506335bbb288889e87bdb9ba0c`, not this lane's HEAD.
A second exact vulture scan with
`RATCHET_BASE_REV=a8258ee24dd957d0f0b302db4eee90661fe23439` also passed;
its provenance output still resolves the trusted merge base to `56332162cf63`.

| Issue acceptance | Executed evidence / remaining status |
| --- | --- |
| Representative RC workload | UNVERIFIED: profile lines 152–164 explicitly omit multi-user/Workspace, Graph/tool/Canvas and Goal workloads. |
| At least two application replicas | UNVERIFIED for current RC: Compose declares two services, but configuration validation fails; ASGI instances are not deployed replicas. |
| Sustained saturation, reclaim, retry, leaks | UNVERIFIED: evaluator rejects the historical 90.43-second shakedown. No long production run executed. |
| Exactly-once/fenced physical work and Goal reconciliation | UNVERIFIED: admission tests do not observe physical work; profile lines 190–200 records one cancelled schedule probe, not sustained reconciliation. |
| Rate/security/degraded behavior across replica selection | Counterexample reproduced by `test_replica_selection_has_an_independent_production_allowance` for both identity classes; broader security under production load UNVERIFIED. |
| Complete metrics with thresholds | UNVERIFIED: process-group sampler tests pass, but application-loop latency, worker counts and full production telemetry remain absent. |
| Active-work kill/restart and drain/fencing/recovery | UNVERIFIED: current tests check gates, not physical recovery of a current RC. Historical process rejoin cannot establish this. |
| Long exact-RC/config soak | UNVERIFIED and blocked: runner lines 635–646 always declares host preflight non-RC; historical evaluator rejection independently reproduced. |
| Findings filed/reclassified at earliest invariant | Local evidence pack has F1–F12 classifications; completeness/current filing UNVERIFIED. No GitHub mutations performed. |
| Machine/human evidence tied to exact artifact hashes | Historical files exist, but no current RC image/config evidence; UNVERIFIED for promotion. |

## Handoff

**BLOCKED**, not merge-ready. No actual vulture failure or whitespace failure was
reproduced, so changing the ledger or unrelated code would be cosmetic. Only this
report changed; no tests added, hence no suite-inventory delta. Existing work was
preserved. Validation logs are `/tmp/issue-860-9fe10987-vulture.log` and
`/tmp/issue-860-9fe10987-tests.log`; durable outcomes are recorded above.

Next: supply a selected immutable RC artifact and complete production configuration
(including reachable model gateway), complete representative workloads/telemetry
and physical-work probes on the canonical spine, resolve the replica-budget
acceptance mismatch, then run at least four hours on that unchanged artifact.
Another host preflight or ledger-only repair cannot satisfy these prerequisites.

Progress: checked 1 assigned issue; done 0 acceptance-complete issues; skipped 0
issues; errors 0 implementation attempts. Environment blocker and acceptance
counterexample are recorded above. Local report commit is the handoff, not
integration approval.

