# Issue #1893 repair checkpoint — 1408f25b

## Frozen scope and initial evidence

- Assigned worktree/branch: `/home/dev/Git/wt/auto-1893`, `auto-1893`.
- Starting HEAD: `3083a7c727d371d518e770770c0d05516578912a`.
- Supplied base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- One item: #1893 admission codec/identity and adjacent tests; verify reported
  `test: failure`, Vulture, and the previously reported provenance blocker.
- Initial tree clean. No incoming edits to salvage. No remote mutations.
- Read the captured issue body and driver check-0 through check-4 logs. Driver
  reports Ruff/format/inventory passing and 311 passed / 3 skipped; these are
  not live PostgreSQL durability evidence.
- Ambiguity: dispatch names no failing test node. Do not infer a code repair
  from a generic job conclusion. No develop-sync conflict exists locally.
- The issue expressly permits a staged pure codec but forbids production
  activation or fake reachability. Reachability authorization is not covered
  by the narrow Vulture-ledger repair permission.

## Validation

- Named Vulture command PASS: 1323 reviewed identities, 1323 findings. No
  unbanked identity exists to amend under the repair exception.
- `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python
  scripts/check-ratchet-provenance.py` FAIL (exit 1): both admission modules
  are new unauthorized unreachable modules and new unauthorized dispositions.
- Verified `origin/develop` resolves to the supplied base. No sync conflict or
  newer local base is available; do not repeatedly fetch or speculate.
- Read accepted lifecycle ADR-081226-a66b and trusted-base quality authority
  ADR-083126-5e62. Preserve Goal -> Graph -> Run -> NodeRun -> Attempt;
  candidate evidence cannot authorize its own policy exception.
- `.github/workflows/vulture-ratchet.yml:77` requires provenance before Vulture.
  Passing Vulture cannot resolve that failing required gate.

Commands independently run with 1800-second timeouts:

| Command | Result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1323 identities |
| `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py` | FAIL, four unauthorized additions described above |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/extensions/test_pack_contracts.py -x -q -r s` | 314 nodes: 311 passed, 3 skipped in 1.62s |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3277 files |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS, 2 files |

## Acceptance audit

All passing evidence here is a **staged contract**, not production admission.

- Frozen/slotted header, six typed error codes, scalar/header matching, named
  columns, UUID hex storage, safe exception messages, fresh flat encoding:
  inspected codec and passing focused tests, including unknown formats and
  invalid scalar/schema cases.
- Snapshot bytes, binding and acknowledgement preservation: passing three-state
  round-trip test. Lines 134-137 independently assert task/run pairs; identity
  constructor at lines 291-292 rejects a different binding receipt.
- Legacy bound/unbound/partial, receipt-only and announced-without-Run evidence:
  passing legacy tests. A pair lacking receipt remains partial under #1851's
  constructor rather than inventing receipt identity.
- Header expiry/fingerprint survive corrupt snapshots/partial bindings: named
  tests pass. Inclusive replacement and 409 precedence belong to C/F2 and are
  not claimed as B2 behavior.
- Duplicate/nonobject/bare-nonfinite JSON, lossy numbers, non-UTF8 and excessive
  nesting: passing storage-boundary corruption tests with valid controls.
- Tagged nonfinite snapshots and fingerprint pass-through: fixture-level test
  passes. Original-model fingerprint -> production evidence serialization ->
  `model_of`/`model_of_json` materialization remains UNVERIFIED; a handwritten
  tag and pinned fingerprint do not prove that integration.
- Raw/production pools on the same migrated disposable database: UNVERIFIED.
  All three cases skipped at `test_admission_codec.py:470` for absent DSNs.
  No migration/downgrade, DB sessions, final SQL counts or object-valued Run
  JSONB INSERT is claimed in this round. Stopped at mandatory provenance
  blocker rather than provisioning a database for an ineligible candidate.
- Real explicit principals, authorized Workspace/Project and registered Graph
  kinds: UNVERIFIED by synthetic DTO fixtures; no admission is exercised.
- No SQL mutation, HTTP/queue/clock/assessment/claim behavior or competing
  execution authority in the codec: source inspection. This round changes
  only this report, not activation or legacy/deletion policy.
- Reachable production behavior: absent. Source import search finds only
  codec-to-identity and the Vulture whitelist; codec lines 50-53 explicitly
  state no production consumer. That is allowed staging, not runtime proof.
- Focused validation passes as above; inventory driver check-4 reports 16467
  identities and zero duplicates. Full integration CI remains UNVERIFIED;
  required provenance fails independently. Generic `test: failure` is not
  reproduced by the focused command and supplies no candidate failing node
  in the lane brief; attribution remains UNRESOLVED, not repaired.
- Assigned base/worktree verified; broader ownership coordination and
  production activation authorization remain UNVERIFIED and are not inferred
  from tests. No mutation/pre-fix proof claimed because no repair was made.

## Handoff

Only changed file: this report. No tests added or changed, hence no inventory
note/delta required. All incoming source, tests, ledgers and gates preserved.
No speculative source repair or Vulture amendment is warranted by these results.

BLOCKED by `quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:604-614`. Resolution requires an
owner-supplied authorized integration base/real consumer consistent with #1845,
not candidate-side reachability grants, fake imports or waived gates. A
separately landed grant would also require owner reconciliation with #1893's
explicit no-grant staging constraint. Do not repeat this repair on identical
inputs; provide a changed trusted base and candidate-qualified test traceback.

Progress: checked 1, done 0, skipped 0, errors 1 (provenance blocker).
Commit this checkpoint locally; no push, integration approval or issue closure.
