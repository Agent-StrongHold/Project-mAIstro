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
