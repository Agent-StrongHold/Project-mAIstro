# Issue #860 repair — job 090405c9

## Frozen scope

- Only issue #860; branch `auto-860`, clean starting head
  `b432120b35a8df825cc80cdc88b814637ccb181b`.
- Supplied base `420d503d4156225907ec673b1e70caa19101241d` resolves.
- Inspect supplied dispatch/prior result, repository guidance, relevant ADRs,
  `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`,
  `docs/testing/soak/m3a-load-profile.md`, round30 evidence,
  server rate limiter and adjacent tests, inventory gate/note conventions,
  vulture gate/workflow and any identities it actually reports.
- Candidate edits limited to this report, evidence-backed issue-local repairs,
  associated tests/inventory notes, and reviewed vulture identities if required.
- No GitHub mutations, new issue enumeration, or unrelated baseline edits.

## Initial observations

The starting worktree is clean. The supplied job directory contains no
`check-*.log` files; driver validation therefore cannot be independently read.
The base-to-head diff includes extensive inherited unrelated changes and hundreds
of prior handoffs; these are preserved, not treated as work of this round.
Assumption: this is a writer CI-repair assignment, not read-only verification.
Validation and acceptance results will be recorded below before local commit.

## Executed validation

- Read all ten acceptance criteria from the supplied issue snapshot and the
  supplied prior result. No external issue state was fetched.
- Requested exact vulture command: PASS, 1322 reviewed identities and 1322
  findings, zero unclassified/never-allowlist. No unbanked identity exists to
  repair or amend. The scanner reports merge base `2f56be40ad24`, distinct from
  the dispatch base; no ledger or authorization edits are justified.
- Current load profile explicitly identifies the runner as a host-process
  preflight, not an exact RC soak, and lists missing representative workloads.
- `uv run ruff check .`: PASS. `uv run ruff format --check .`: PASS,
  3306 files. `uv run python scripts/check-suite-inventory.py`: PASS, all 17
  suites; root tests count 5354, 31489 unique identities. The dispatched
  inventory mismatch does not reproduce; no inventory edit is warranted.

## Architecture reconciliation

Read accepted ADR-081426-1f7c (Attempt execution identity), ADR-081626-f383
(durable lease/fence authority), its renewal/reclaim extension ADR-082526-b36a,
ADR-085 (canonical principal rate limits), and ADR-073126-c4e1 (immutable RC
provenance). Admission deduplication cannot substitute for physical Attempt
fencing/recovery. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`; do not
add another scheduler or authority. The limiter's documented process-local
N-times-limit budget is not an ADR waiver of #860's stronger replica-selection
criterion. No release artifact may be manufactured or relabeled as promoted
merely to pass the soak gate.

## Focused acceptance validation

- `uv run pytest tests/test_soak_promotion_gates.py -x -q`: PASS, 84 tests
  in 1.53s. The real middleware regression at lines 477–526 reproduces
  `[200, 200, 429]` independently on each replica for the same principal/IP.
  These are ASGI middleware instances, not deployed RC replicas.
- `uv run pytest packages/maistro-server/tests -x -q`: PASS, 566 passed,
  8 skipped in 32.22s. There were 25 warnings: 22 status-code deprecations
  and three aiosqlite worker-thread `Event loop is closed` warnings during
  `test_cancel_still_works_and_takes_the_run_with_it`. These remain a test
  cleanup risk; no claim of warning-free validation is made.
- Executed `uv run python` loading the actual driver and round30 JSON,
  asserting `failed_promotion_checks(evidence)` equals
  `['sustain_duration', 'exact_rc_artifact']` and
  `preflight_artifact_check()['ok'] is False`: PASS (expected rejection).
- Requested scanner arguments match `.github/workflows/vulture-ratchet.yml:82-85`.

## Acceptance audit

| Issue criterion | Evidence and result |
| --- | --- |
| Representative RC profile | **UNVERIFIED as complete**. `m3a-load-profile.md:167-183` omits multi-user/Workspace population, Graph fan-out, successful model/tool/Canvas work and Goal/background reconciliation. |
| At least two application replicas | **UNVERIFIED for the RC**. Executed tests cover two middleware instances only; historical host-process evidence is not a deployed current RC. |
| Sustained saturation, queue growth, expiry/reclaim, retry/backoff and leaks | **UNVERIFIED**. Evaluated round30 ran 420.08s versus the 14400s minimum; profile explicitly retains saturation/reclaim/long-window gaps. |
| No duplicated physical work across replicas | **UNVERIFIED**. Round30 JSON lines 11–15 cancel the schedule probe Run after admission, without physical Attempt execution; admission uniqueness is insufficient. |
| Replica-selection-resistant rate/security/degraded enforcement | **Counterexample reproduced** by executed middleware regression. `api/rate_limit.py:32-37,93-100` documents/constructs independent local allowances. Sustained security and degraded behavior remain UNVERIFIED. |
| Complete PostgreSQL/application/process/queue/error telemetry and thresholds | **UNVERIFIED**. Profile lines 167–183 explicitly lack application event-loop, worker, saturation and long-window observations. No new production telemetry collected. |
| Active-work kill/restart proves drain/fencing/recovery | **UNVERIFIED**. Exit/rejoin and terminal Run counts do not demonstrate physical-work fencing/recovery. |
| Long-running exact RC artifact/configuration | **NOT MET by evaluated evidence**. `run_soak.py:744-755` rejects the host-process artifact; round30 JSON lines 217–222 identifies 420.08s and non-RC topology. No immutable promoted RC identity/configuration is supplied. |
| Findings filed/reclassified before promotion | Local blockers recorded here; external filing/reclassification **UNVERIFIED**, GitHub mutations forbidden. |
| Machine/human evidence tied to promoted hashes | **UNVERIFIED for the RC**. Round30 JSON line 70 names `c4f45b309fd622f2e8a4b315dad35e721d81aad3`, not this branch's head or a supplied promoted image. |

## Disposition

**BLOCKED**, not merge-ready. The requested CI repair has no reproduced scanner
or inventory defect. No ledger amendment, gate change, new test or inventory-delta
note is warranted. Changed file in this round: this report only. No sync conflict
exists and no fetch/merge was performed. All inherited work is preserved.

No fresh live soak was attempted: a longer run of the preflight cannot pass its
explicit exact-artifact rejection or supply its missing workloads. Required next
inputs/work are a selected immutable RC/configuration, a representative production
workload and telemetry runner, replica-selection-resistant enforcement using the
canonical identity path, then a >=4-hour run with physical fencing/reclaim/recovery
observations. Those are acceptance blockers, not reasons to weaken gates or mint
another execution/authorization authority. Repeating a vulture-only repair without
these prerequisites cannot resolve #860.

Progress: checked 1 issue, done 0 acceptance-complete issues, skipped 0 issues,
errors 0 validation commands, blocked 1. Local commit records this handoff only;
no push, PR, issue mutation, integration approval or closure action.
