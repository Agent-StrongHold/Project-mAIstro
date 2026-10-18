# Issue #860 — repair checkpoint (job 3ab68c8d)

## Frozen scope

Only issue #860, branch `auto-860`, starting HEAD
`be919c47e9e9981f9914a388e7ee1599c0562b63`, supplied base
`ce2048cd2430bf99a5896b229fd1999976dc07dd`. Initial worktree clean.
No GitHub mutations, new scheduling/authorization authority, or promotion claims.

Inspection scope: supplied dispatch context and previous result; repository
instructions; relevant execution/deployment ADRs; `docs/testing/soak/m3a-load-profile.md`,
`docs/testing/soak/evidence/m3a-round30-shakedown.json`,
`scripts/soak*`, `scripts/check-vulture-baseline.py`,
`scripts/check-suite-inventory.py`, `tests/test_soak*`, rate limiter and adjacent
server tests, inventory notes and CI gate definitions. Candidate edits limited to
this checkpoint, evidence-backed soak/inventory repairs, and reviewed vulture
identities if the explicitly requested scan reports debt. Do not process linked
issues/PRs as separate work items.

## Initial findings / assumptions

- Exact starting HEAD verified; no incoming uncommitted changes to salvage.
- Supplied job directory has no `check-*.log` files at inspection time; driver
  verification is unavailable, not a pass.
- Assignment is writer/CI repair, not verifier-only. A final exact-RC soak cannot
  be inferred from old shakedown evidence. Verify the existing gates before
  selecting any repair; do not invent scanner findings.

## Results

- Exact requested vulture command passed (1322 findings / 1322 reviewed
  identities; unclassified 0, never_allowlist 0). No ledger amendment justified.
- Prior result read: previous attempt was blocked, not a develop merge conflict.
- Profile explicitly marks host-process runner non-promotional and documents
  missing representative workloads / exact-RC soak. No acceptance waiver inferred.

- `uv run python scripts/check-suite-inventory.py --suite tests` failed:
  expected 5353, collected 5354. Investigating provenance, not blindly banking +1.
- `uv run pytest tests/test_soak_promotion_gates.py
  packages/maistro-server/tests/api/test_rate_limit.py -x -q`: **110 passed**.
  Includes the real production middleware replica-selection allowance test for
  authenticated and unauthenticated clients. Each replica accepts two requests
  then rejects the third independently; this does not meet cluster-budget AC.
- Accepted lifecycle ADR-081226-a66b and execution fencing ADR-081626-f383 read;
  ADR-081 is Proposed, not authorization to relax canonical execution ownership.
  Later accepted reclaim ADR must also govern recovery conclusions.

- `uv run ruff check .`: passed. `uv run ruff format --check .`: passed,
  3306 files already formatted.
- Inventory provenance **UNRESOLVED** after two bounded inspections. Recent
  soak additions have corresponding +12/+7/+9 notes; supplied develop is not
  this branch's merge base (actual merge base is
  `2f56be40ad241262b0384ab0b97834ebd37fe4d7`). The diff includes unrelated
  CI tests/notes, so no safe attribution to a missing soak node is established.
  Do not add an unexplained +1 or touch unrelated tests to silence the gate.
- A guessed reclaim ADR filename was not found; skipped. Locate its actual
  registry path before reading it; no conclusion is based on that missing file.

- Current `failed_promotion_checks` executed against
  `docs/testing/soak/evidence/m3a-round30-shakedown.json`: rejects
  `sustain_duration` and `exact_rc_artifact`; duration is 420.08 s and historical
  code hash is `c4f45b309fd622f2e8a4b315dad35e721d81aad3`, not this candidate.
- `uv run pytest tests/test_prod_stack_boot_contract.py -x -q`: **8 passed**.
- `uv run pytest packages/maistro-server/tests -x -q`: **566 passed, 8 skipped**,
  22 deprecation warnings. Skips are not evidence of production acceptance.
- Actual reclaim ADR path located and read completely:
  `docs/adr/ADR-082526-b36a-a-lease-that-stops-being-renewed-is-reclaimed.md`.
  This accepted extension defines TTL renewal/reclaim on the canonical Attempt
  seam (including transient renewal retry). The older fencing ADR's original
  deferral is not current proof that reclaim is absent. Conversely, the accepted
  contract alone does not prove physical work is fenced during a production soak.
- No new tests or runtime changes; no inventory delta is due for this attempt.
  Existing tests were executed, not counted as new soak observations.

## Acceptance matrix (issue body order)

| Criterion | Checked evidence / conclusion |
| --- | --- |
| Representative RC users/Workspaces, request mix, fan-out, schedules, queue, tools/models, Canvas, workers | **UNVERIFIED**: profile lines 167–183 explicitly retain these representative workload gaps. Existing driver is a preflight emulator. |
| At least two production application replicas | **UNVERIFIED** for candidate RC: 8 boot-contract tests pass; historical host-process evidence is not a fresh production topology run. |
| Sustained saturation, reclaim, retry, growth/leaks and restart | **UNVERIFIED**: executed evaluator rejects the 420.08 s historical run; no 4-hour exact-RC run performed. |
| Schedule/task/Run/Attempt admission, Goal reconciliation, physical-work fencing | **UNVERIFIED** at soak grade: HTTP identity probes pass but profile lines 215–217 explain the one-occurrence probe cancels its Run without physical execution; not sustained Goal/Attempt evidence. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **NOT MET** for a shared principal budget: executed middleware tests show [200, 200, 429] independently on both replicas for the same identity. Local enforcement remains tested; it does not satisfy this stronger criterion. |
| Required DB/app-loop/process/RSS/fd/queue/error metrics with thresholds | **UNVERIFIED** for exact RC: process sampler tests pass; profile distinguishes driver loop lag from application loop lag and retains saturation/leak gaps. |
| Kill/restart during physical work proves drain/fence/recovery | **UNVERIFIED**: historical process exit/rejoin and terminal counts are not physical-work proof; no new live restart run. |
| Long soak of exact promoted artifact/config; rerun after changes | **NOT MET** by supplied evidence: current evaluator rejects duration and artifact; `preflight_artifact_check()` always returns false for this runner. Immutable promotion selection/configuration is not established in this attempt. |
| Load findings filed/reclassified to earliest invariant | **UNVERIFIED**: local findings recorded here only. No GitHub mutation or issue closure performed. |
| Machine/human evidence tied to exact image/package/commit/config | **UNVERIFIED** for candidate RC: old JSON has historical commit/config identity, not candidate application-image identity or a new soak. This handoff is validation evidence, not promotion evidence. |

## Disposition and next steps

**BLOCKED; not an implementation repair or promotion approval.** Exact vulture
CI repair is already clean at the assigned HEAD; fabricating a ledger amendment
would be incorrect. Remaining root inventory provenance is unresolved. No
unsupported shared limiter, scheduler, Goal store, or recovery authority was added
merely to manufacture acceptance.

The next authorized implementation needs an immutable RC image/configuration,
a production-topology load driver covering the documented workload/measurement
and physical-work gaps, and a new >=4-hour run. The replica-budget mismatch must
be resolved through the canonical identity/enforcement path and revalidated,
not waived by the local H3 result. Root inventory repair needs attributable node
provenance before changing its delta ledger. These requirements remain open;
repeating the same preflight cannot close them.

Only changed file in this attempt:
`docs/testing/soak/issue-860-3ab68c8d-repair.md` (validation/handoff).
No production code, tests, inventory counts, quality ledger, or gate changed.

Progress: checked 1 assigned issue; done 0; skipped 0; errors 1 (root inventory
gate). Validation checkpoint completed; issue repair remains blocked.

