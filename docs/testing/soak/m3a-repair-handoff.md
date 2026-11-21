# Issue #860 repair checkpoint

## Frozen scope

- Assigned item: #860 only, branch `auto-860`, starting HEAD
  `5fc5b52f839c70c277f48b38dbf6414ba29f1565`, base
  `5ea8ef71ad6a7a1fb93f914a76028f1e914bc875`; both refs resolved.
- Initial worktree clean; no incoming uncommitted work to salvage.
- Process the supplied prior findings only: RC soak missing; rate-limit
  evidence overclaim; exact-artifact mismatch; required exact-debt-ledger check.
- Candidate edit scope frozen: this handoff, `m3a-soak-evidence.md`,
  `m3a-load-profile.md` (in this directory), `scripts/soak/run_soak.py`,
  `tests/test_soak_promotion_gates.py`,
  `docs/testing/inventory-notes/m3a-860-rate-evidence-repair.md`, and
  `quality/vulture-baseline.json` only if the required check identifies reviewed
  retained debt. Adjacent production code/tests and ADRs are read-only.

## Initial evidence and assumptions

- Current job directory has no `check-*.log` files. Prior result JSON is present
  and references previous-job logs; its success claims are not current validation.
- This is a writer repair round, not the read-only verifier role.
- An emulator run cannot satisfy the required exact production RC soak, even
  when run for four hours. Do not manufacture promotion evidence or weaken gates.
- No designated immutable RC image/configuration is supplied in the assignment.
  Treat exact-RC acceptance as blocked pending real artifact evidence.
- No GitHub mutation is authorized; findings can be reclassified locally only.

## Progress

Repository instructions, prior result, load profile/evidence, adjacent gate
tests, production rate-limit middleware, and relevant ADRs reviewed.

- Required vulture command executed: PASS, 1402 findings / 1402 reviewed
  identities, zero unclassified. No ledger amendment is warranted.
- H3's shared-store/replica-selection assertion is false: production middleware
  instantiates `InMemoryRateLimiter` separately in each process. Repair the
  evidence interpretation, not the #842 production contract.
- Current gate tests permit wholly passing synthetic evidence with no artifact
  identity. Inspect driver emission before adding a fail-closed preflight gate.
- ADR-085 requires principal identity, not a specified cluster coordinator;
  ADR-081 is Proposed, not an accepted production-soak waiver. Preserve canonical
  Run/Attempt authority (ADR-081426-1f7c / ADR-081626-f383) and occurrence admission
  (ADR-082426-82c7); admission-only evidence is not physical-work proof.

## Focused repair validation

- Added explicit negative `exact_rc_artifact` emission to the actual preflight
  driver and made missing/null artifact records fail its promotion evaluator.
  No CLI override or replacement production authority was introduced.
- Corrected H3 shared-store and historical six-path implications. Preserved all
  historical raw evidence. Narrowed H2 to admission, not physical work.
- Added five tests and matching `inventory-delta: tests/: +5` note.
- Executed targeted pytest (gate tests + pg_learnings + tasks backpressure):
  **62 passed, 5 skipped**, 232.19 seconds. Skipped cases require PostgreSQL;
  this is not a live RC soak.
- `uv run ruff check .`: PASS. First format/diff checks found only new-test
  formatting and one trailing space in the profile; correcting before rerun.
- Previous-job check-0..5 logs read: green at the old head only. Current job
  still has no driver check logs; results here come from fresh execution.

## Final validation results

Commands executed from the assigned worktree with `uv run`:

| Command | Result |
|---|---|
| `python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1402 findings / 1402 reviewed identities; zero unclassified; ledger unchanged |
| `pytest tests/test_soak_promotion_gates.py packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | 62 passed, 5 skipped (PostgreSQL-dependent), 232.19 s |
| `pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_rate_limit.py -x -q` | 56 passed, 193.83 s |
| `ruff check .` | PASS |
| `ruff format --check .` | Initial new-test formatting failure fixed; final PASS, 2624 files |
| `git diff --check` | Initial trailing whitespace fixed; final PASS |
| `python scripts/check-suite-inventory.py --suite tests/ --suite packages/maistro-core/tests --suite packages/maistro-server/tests` | TIMEOUT at 1200 s after reporting core PASS (11531); root and server inventory completion UNVERIFIED |

The three mocked-load CLI tests execute `main()` and require exit 1 for an
otherwise-passing four-hour record without a valid artifact check. The real
middleware tests reproduce independent per-replica allowances for the same
identity. Neither is presented as a load run. No new soak was executed.

## Acceptance disposition (all ten supplied criteria)

1. **Representative profile: PARTIAL.** Profile exists, but the actual driver
   uses one key and lacks a concurrent user/Workspace population, Graph fan-out,
   successful tool/model traffic, Design/Canvas and background/Goal workloads.
   Applicability must be resolved against the selected RC, not silently waived.
2. **Two application replicas: UNVERIFIED for RC.** Historical round-6 records
   two host processes; Compose reference defines two services, not executed here.
3. **Sustained observation: UNVERIFIED.** Round-6 JSON records 90.43 s against
   14400 s required. No long-window saturation/reclaim/leak evidence added.
4. **Exactly-once/fenced physical work: UNVERIFIED.** Historical H1/H2 measure
   admission; H2 cancels its queued Run. No physical Attempt side-effect oracle
   or sustained Goal reconciliation proof exists in this validation.
5. **Replica-selection security: NOT MET for a cluster-wide allowance.** The
   executed production-middleware counterexample gets another allowance from
   replica 2 after exhausting replica 1. #842 process-local semantics preserved;
   #860's stronger claim remains unresolved. Local limiter tests pass.
6. **Full metric/threshold capture: UNVERIFIED.** Historical RSS/FD/PG and
   latency samples are provisional; driver-loop lag is not app-loop latency.
   Worker counts, sustained pool/reclaim pressure and exact-RC thresholds remain.
7. **Kill/restart physical-work recovery: UNVERIFIED.** Historical process drain
   and rejoin are not correlated physical-work/fencing evidence under RC load.
8. **Long-running exact RC soak: BLOCKED.** No designated immutable promotion
   image/config supplied; host emulator cannot meet the contract at any duration.
   Actual driver now emits an explicit failing artifact check. Every code/config
   change still requires new evidence; no stale soak was relabelled.
9. **Findings classified/filed: PARTIAL.** F1–F10 remain documented in the
   existing evidence/notes. This round reclassifies the H3 claim as an evidence
   overstatement and unresolved deployment-rate-limit acceptance mismatch.
   GitHub filing UNVERIFIED and forbidden in this lane; none attempted.
10. **Hash-tied evidence: PARTIAL.** Historical JSON/human pack retained
    unchanged apart from corrected human interpretation; no immutable RC image
    evidence or new RC soak is claimed.

## Handoff

Changed files: `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`,
`docs/testing/inventory-notes/m3a-860-rate-evidence-repair.md`,
`docs/testing/soak/m3a-load-profile.md`,
`docs/testing/soak/m3a-soak-evidence.md`, and this handoff.
No production runtime, scheduler, Goal store, event authority, authorization
path, or quality ledger changed. Raw historical evidence was preserved.

Final disposition: **BLOCKED**, not promotion approval. Focused repair is
committed locally; the assigned issue is not complete. Campaign progress:
`{checked: 1, done: 0, skipped: 0, errors: 1, next: exact-RC runner/profile and >=4h soak; inventory timeout follow-up}`.
Stop starting new work: the inventory timeout consumed the validation budget.
Supply the exact promotable artifact/configuration, resolve rate-limit semantics,
complete the workload/metric/physical-work oracles, and run a new >=4h soak before
requesting promotion review. No push, PR, merge, comment, or issue closure done.

## Assigned-head validation: `028cb44e11b7`

Job `cba8c1ff61c84d3fa57cd180efddbf64` rechecked #860 only in the assigned
`auto-860` worktree. Starting HEAD and supplied base `e2b2dfa02822` resolve;
the initial tree was clean. No sync conflict or uncommitted salvage was present.
No `check-*.log` files were present in this job directory; prior-job success
claims were not reused as current evidence. Fresh logs are in that job directory.

### Executed checks

All Python commands below used `uv run`; command timeouts were 600–1800 seconds.

| Command | Observed outcome / log |
| --- | --- |
| `python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1402 reviewed identities / 1402 findings, zero unclassified or never-allowlist; `vulture-repair.log`. No ledger amendment justified. |
| `pytest tests/test_soak_promotion_gates.py packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests -x -q` | 506 passed, 5 PostgreSQL-dependent skips, 21 deprecation warnings in 114.89 s; `writer-pytest.log`. Includes all server tests, real middleware replica-allowance regressions and live uv-child sampler regression; not a deployed soak. |
| `ruff check .` | PASS; `writer-ruff-check.log`. |
| `ruff format --check .` | PASS, 2624 files; `writer-ruff-format.log`. |
| `python scripts/check-doc-links.py` | PASS, 1394 Markdown files, zero broken relative links; `writer-doc-links.log`. |
| `python scripts/check-merge-markers.py` and `git diff --check` | PASS; `writer-merge-markers.log` and clean whitespace check. |
| `python scripts/check-deployment-claims.py` | PASS; `writer-deployment-claims.log`. Checks named components exist, not production behavior. |
| Inline Python importing the real driver and evaluating round-6 JSON | PASS: asserted 90.43 < 14400 seconds, current evaluator rejects `sustain_duration` and missing `exact_rc_artifact`, current driver artifact check is false; `writer-evidence-check.log`. Historical evidence unchanged. |

### Acceptance and architecture reconciliation

| Criterion | Current disposition |
| --- | --- |
| Representative RC workload | PARTIAL: existing profile explicitly lacks concurrent users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas and Goal/background traffic. Applicability to the selected RC is UNVERIFIED. |
| Two production application replicas | UNVERIFIED: reference Compose defines two services; this validation does not deploy them. Middleware instances are not deployed replicas. |
| Sustained saturation/reclaim/retry/leak observations | UNVERIFIED: executed JSON check confirms only 90.43 seconds for historical round 6; sampler regressions do not establish long-window behavior. |
| No duplicated physical work; Goal reconciliation | UNVERIFIED: driver schedule probe checks occurrence admission then cancels the queued Run (`run_soak.py:1052`); no physical Attempt/effect or Goal reconciliation soak. |
| Rate-limit/security/degraded non-bypass | NOT MET for one cluster-wide allowance: executed `test_replica_selection_has_an_independent_production_allowance` confirms `[200,200,429]` separately on both instances for the same authenticated or unauthenticated identity. Full RC security/degraded behavior UNVERIFIED. |
| All required metrics and thresholds | PARTIAL: sampler tests pass, but driver-loop lag is not application-loop lag; complete RC worker/pool/queue/leak/timeout observations and thresholds remain UNVERIFIED. |
| Active-work kill/restart, drain/fencing/recovery | UNVERIFIED: no new deployed restart, physical Attempt correlation or recovery observation. |
| Long-running exact-RC soak | BLOCKED: no designated immutable promotion artifact/configuration supplied. `run_soak.py:635` rejects artifact equivalence for the host emulator regardless of duration; no qualifying soak executed. |
| Findings filed/reclassified | PARTIAL: existing local classifications preserved; no new runtime defect discovered in this validation. External filing UNVERIFIED; GitHub mutations prohibited. |
| Hash-tied human/machine RC evidence | PARTIAL: historical pack retained unchanged; fresh validation logs identify this checkout but are not RC soak evidence. Exact promoted image/configuration evidence UNVERIFIED. |

Re-read repository instructions, accepted ADR-081426-1f7c, ADR-081626-f383,
ADR-082426-82c7 and ADR-085, plus Proposed ADR-081. Admission uniqueness is
not physical execution uniqueness. ADR-085's principal identity does not make
process-local limiter state cluster-wide. ADR-081626-f383 itself does not
establish lease-expiry takeover. None is an acceptance waiver; no alternative
scheduler, Goal store, execution/event authority or authorization path was added.

This checkpoint changes only this handoff. No production code, harness, tests,
inventory counts, ledger or historical evidence changed, so no inventory delta
is required. The requested ledger repair has no failing identity to repair.
Do not manufacture one or rerun the host emulator for four hours as a substitute.

Disposition: **BLOCKED**. Next owner must designate the exact RC image/config,
resolve cluster-wide rate-limit semantics, complete representative workloads and
physical-work/metric oracles, then execute and publish a fresh >=4-hour soak.
Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: exact-RC prerequisites and sustained soak}`.
This is a locally committed validation handoff, not completion of #860 or
integration approval. No push, PR, merge, comment or issue closure performed.
