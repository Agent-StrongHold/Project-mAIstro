# Issue #860 — repair checkpoint (job 8d50e6eb)

## Frozen scope

- Assigned issue: #860 only; branch `auto-860`, clean starting HEAD
  `5ea204b35ec8ea20db7de0382ee45f4a7db909f0`.
- Supplied comparison base: `6b631928b530daa9de38d5328ce0b66d80898660`.
- Inspect existing `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`,
  `docs/testing/soak/m3a-load-profile.md`, `m3a-soak-evidence.md`, round30 JSON,
  production rate limiter, adjacent tests, relevant ADRs and CI gate configuration.
- Execute assigned vulture gate, lint/format, focused soak and package tests,
  suite inventory gate. Amend only demonstrated issue-related defects, inventory
  notes if justified, and reviewed vulture identities if the scan requires it.
- No GitHub mutations, ref updates, scheduling/authorization redesign, or claimed
  RC certification from unit tests. No changes to unrelated inherited files.

## Initial results / assumptions

- Starting HEAD and clean worktree verified locally.
- Job directory has no `check-*.log` files; prior validation is not assumed true.
- Dispatch issue body read from supplied local snapshot; no remote re-enumeration.
- Ambiguity: assignment says repair, with verifier-only instructions also present.
  Proceed as writer per explicit lane assignment and required local commit.
- Exact RC selection is not supplied by the assignment. Historical shakedown
  evidence cannot by itself prove the current artifact meets acceptance.

## Fresh validation

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1322 findings / 1322 reviewed identities,
  zero unclassified, zero never-allowlist. No demonstrated ledger repair; leave
  `quality/vulture-baseline.json` unchanged (do not fabricate scanner findings).
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3306 files already formatted.
- Prior result read: preceding repair reinstated an attributable inventory note;
  it did not claim an RC soak. Will independently check inventory now.
- Existing profile explicitly distinguishes process-local budgets and host-process
  preflight from acceptance; no acceptance waiver will be introduced.

- `uv run pytest tests/test_soak_promotion_gates.py -x -q`: PASS, 84 tests.
  Includes real production middleware instances reproducing independent allowances
  for both authenticated and unauthenticated clients (not two deployed replicas).
- `uv run python scripts/check-suite-inventory.py`: PASS, all 17 suites,
  31,489 unique IDs, root `tests/` = 5354. Prior 5353/5354 mismatch is resolved
  at the assigned starting head; no further inventory adjustment is justified.
- Read accepted ADR-081626-f383 (durable Attempt fencing, not implicit lease
  takeover) and ADR-082426-82c7 (occurrence identity in canonical Run store).
  Reconciliation: admission uniqueness is not physical-work fencing; #860 cannot
  add a second scheduler or invent reclaim authority to satisfy its wording.
- Attempted ADR-081 filename did not exist: not found; skipped. No ref command
  used that unresolved path. Will use repository-discovered ADR filename.

- `uv run pytest packages/maistro-server/tests -x -q`: PASS, 566 passed,
  8 skipped, 23 warnings, 31.66 s. Warnings include HTTP-status deprecations
  and an aiosqlite worker `Event loop is closed` teardown warning in
  `test_cancel_still_works_and_takes_the_run_with_it`. Skips/warnings are not
  counted as production recovery proof; no unrelated fix attempted.
- `uv run python - <<'PY' ... PY`: imported current `scripts/soak/run_soak.py`,
  loaded round30 JSON, and asserted `failed_promotion_checks(evidence) ==
  ['sustain_duration', 'exact_rc_artifact']`; PASS. Printed actual duration
  420.08 seconds and artifact head `c4f45b309fd622f2e8a4b315dad35e721d81aad3`.
  Also asserted `preflight_artifact_check()['ok'] is False`; PASS.
- Read accepted ADR-085: request limits are principal-keyed and distinct from
  token quotas. It does not establish that this process-local implementation
  satisfies #860's cross-replica non-bypass criterion.
- Read actual ADR-081 (`ADR-081-deployment-backup-dr.md`): **Proposed**, not
  accepted authority overriding #860. Production reference Compose still
  explicitly declares two server replicas and shared services.
- Reachability checked: `packages/maistro-server/src/maistro_server/main.py:648`
  installs the middleware exercised by the independent-allowance tests.

## Acceptance matrix (not a promotion signature)

| #860 criterion | Freshly checked evidence / disposition |
|---|---|
| Representative RC profile | **UNVERIFIED** in full. `m3a-load-profile.md:167-183` explicitly excludes concurrent Workspace populations, fan-out, successful providers/tools/Canvas and sustained Goal reconciliation from current evidence. |
| At least two supported replicas | **UNVERIFIED for current RC**. `deploy/docker-compose.prod.yml:23-80` declares two replicas; ASGI instances in the passing tests are not deployed applications. Historical round30 is a two-host-process preflight. |
| Sustained saturation, queues, reclaim, retry, leaks and restart | **UNVERIFIED**. Evaluated round30 duration is 420.08 s versus 14400 minimum. Current profile admits missing long-window saturation/reclaim/leak observations. |
| Schedule/task/Run/Attempt/Goal physical-work deduplication | **UNVERIFIED**. Round30's schedule claim is cancelled while queued (`m3a-round30-shakedown.json:11-15`); admission uniqueness is not a physical Attempt/reconciliation proof. Canonical Run-store fencing remains authoritative. |
| Replica-selection-resistant rate/security/degraded behavior | **NOT PROVEN**. Passing `test_replica_selection_has_an_independent_production_allowance` (`tests/test_soak_promotion_gates.py:477-526`) observes `[200,200,429]` independently on each real middleware instance for the same identity. `rate_limit.py:32-37` explicitly documents N-times aggregate allowance. Other unit tests cannot complete the sustained concurrency criterion. |
| Required telemetry and explicit thresholds | **UNVERIFIED in production**. Profile defines H/S thresholds; its driver loop lag is not application event-loop latency (`m3a-load-profile.md:179-183`). Current RC telemetry has not been captured. |
| Kill/restart during active physical work, drain/fence/recover | **UNVERIFIED**. Historical exit/rejoin and terminal Run counts do not establish in-flight Attempt fencing or absence of silent physical loss/duplication; passing tests are not a live recovery run. |
| Long-running exact promoted RC/config | **NOT MET by evaluated evidence**. Round30 has a different commit and fails both duration and artifact gates. `run_soak.py:744-755` deliberately cannot certify Compose artifact identity. No selected immutable RC/config manifest supplied. |
| Findings filed/reclassified to earliest invariant | Local evidence-validity findings are classified under M3-A #89/#860 in `m3a-soak-evidence.md`; **external filing UNVERIFIED**. No GitHub mutations permitted or performed. |
| Machine/human evidence tied to promoted hashes | Historical packs exist, but **UNVERIFIED for selected RC**. Round30 hash at JSON line 70 is not assigned HEAD; no newly observed image/config/RC evidence is claimed. |

## Outcome and handoff

**BLOCKED**, not merge-ready. This round changes only this validation/handoff
file. There is no observed vulture or inventory defect to repair; no source,
tests, ledger, grants, or historical evidence were changed. No new tests means
no inventory-delta note is needed. Existing 84 targeted regressions were run.

The previous block is reproduced, not resolved. Do not schedule another identical
CI-only repair as though it could satisfy the soak acceptance. Next required work:
select the immutable RC images/config and provider-enabled representative workload;
resolve the cross-replica allowance mismatch without a second auth path; execute
an exact-topology >=4-hour soak with physical Attempt/reconciliation observations
and complete telemetry. No short preflight was rerun because this runner cannot
satisfy exact-artifact acceptance at any duration. No production soak was run here.

Progress: checked 1 assigned issue; done 0 acceptance-complete issues;
blocked 1; skipped 0 issues; validation command failures 0. No remote/ref mutations.
Local commit required after final `git diff --check`; leave worktree clean.

