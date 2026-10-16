# Issue #1893 repair checkpoint (job 000e4eb6)

## Frozen scope

Only issue #1893, worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
Starting HEAD verified as `1b3845c8784ed99d7c4f5839d00c419d6dda7e60`;
assigned base `321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62`.
Initial worktree clean; no salvage needed.

Snapshot files: supplied dispatch-context.json, check-0.log through check-4.log,
prior job 4e5c0025 result; repository instructions and relevant admission ADRs;
`runs/admission_identity.py`, `tasks/admission_codec.py`, their two test modules,
existing reachability ledger entries, CI gate scripts/workflows and this report.
Other linked issues/PRs are evidence only, not work items. No remote mutation.

Assumption: this is a writer repair round. Investigate the supplied `test: failure`
and independently validate provenance; do not change production behavior or
ledgers without actual evidence. Vulture-only ledger exception does not authorize
reachability grants. No new tests planned unless a reproducible defect is found.

## Progress

- Verified assigned HEAD and clean starting state; recorded scope before review.
- Read supplied checks: sync, Ruff, format, focused tests (346 passed, 3 skipped)
  and inventory (16567) pass. No failing pytest traceback is present.
- Independently executed exact CI Vulture command: exit 0, 1322 findings,
  zero unclassified. No retained identity needs banking; no ledger edit warranted.
- Independently executed `RATCHET_BASE_REV=321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62 uv run python scripts/check-ratchet-provenance.py`:
  exit 1. Both admission modules are new unreachable modules and have new
  dispositions without trusted-base authorization (169 -> 171). This is an
  actual policy blocker, not an unresolved ref or Vulture finding.
- Codec review confirms no production consumer (module lines 50-54). Adding a
  fake import or activating the C consumer would violate this leaf's scope.
  The assigned round permits Vulture ledger amendments only, not reachability
  authorization. Proceed with focused validation and a blocked handoff.
- Read accepted ADR-081226-69ee (canonical Graph/Run/NodeRun/Attempt ownership),
  ADR-082526-7f02 (immutable admission provenance), ADR-083026-aba1 (state absent
  callers), and ADR-083126-5e62 (protected-base policy authority). Reconciliation:
  preserve the inactive leaf; no competing execution/authorization path and no
  candidate-authored policy exemption.
- Production-source grep finds only the codec importing identity types and a
  whitelist import; no runtime consumer. Adjacent identity/codec tests reviewed.
- Snapshot check-run extraction initially assumed a mapping, but `data` is a
  list; corrected locally without refetch. Captured `test` failure is for
  #1855 head `3f2c79a70d9e1b0b6b6ffc99562cb35db5326828`, with null summary/text.
  #1945 head `973772507c94428dba24fad7d9530490688d59e2` has coverage and
  exact-debt-ledger failures, likewise without traceback. These do not establish
  a failing test at this assigned HEAD. After two bounded checks, generic
  `test: failure` is UNRESOLVED; request the actual failing node/log.

## Independently executed focused validation

All commands ran in the assigned worktree with 1800-second timeouts.

- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/extensions/test_cli_lock.py packages/maistro-core/tests/extensions/test_pack_contracts.py -x -q`:
  exit 0, 349 nodes, **346 passed, 3 skipped**, 2.80 seconds.
- `uv run ruff check .`: exit 0.
- `uv run ruff format --check .`: exit 0, 3301 files unchanged.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`:
  exit 0, two source files.
- Exact Vulture/provenance commands and results recorded above.

No source or test change is justified by these results. No new regression or
mutation run is claimed. No tests added/removed; inventory delta is zero and
no inventory note is required for this documentation-only handoff.

- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`:
  exit 0, 16567 unique identities, no copied-file duplicate evidence.
- `uv run python scripts/check-shipped-surface-truth.py`: exit 0.
- `git diff --check`: exit 0.

## Acceptance audit

| Criterion | Evidence / limitation |
| --- | --- |
| Shared frozen/slotted header, exact interfaces and six error codes | Source review and executed focused DTO/codec tests. No clock or incoming fingerprint arguments. |
| Header matches row scalars; signed timestamps; strict UUID hex; unknown format fails closed | Executed scalar mismatch, invalid header, generation/token and unknown-format tests. |
| Safe diagnostic messages, validated hash only, suppressed parser chains | Executed invalid JSON, UUID, numeric, nesting and surrogate rejection tests. |
| Named columns and fresh flat SQL mapping | Executed encoding tests; independent task_id/run_id assertions at test_admission_codec.py:134-137. Physical request TEXT maps to DTO request_snapshot. |
| Duplicate/nonobject/nonfinite JSON rejected; arbitrary permitted context/tag evidence retained; fingerprint unchanged | Executed canonical JSON, tagged nonfinite and snapshot round-trip tests. Real model_of/model_of_json materialization and original-model fingerprint-before-tagging remain UNVERIFIED; fixtures are synthetic pre-tagged snapshots. |
| Legacy bound/unbound/partial/receipt-only shapes; no guessed identity | Executed legacy distinction and corruption tests. A pair without receipt evidence is rejected rather than fabricating the receipt required by the canonical binding. |
| Header expiry/fingerprint survives malformed snapshot or partial binding | Executed named header-separation and expired-legacy tests. Replacement/409 precedence remains C/F2 behavior, not claimed here. |
| Raw and production pools, same disposable migrated PostgreSQL schema, TEXT durability | UNVERIFIED: all three PG cases skipped. No DB created/migrated, no session identities or SQL row counts claimed. |
| Authorized principals, Workspace/Project, registered Graph, object-valued Run JSONB | UNVERIFIED: synthetic DTO tests do not establish admission authorization or Run persistence. |
| No SQL mutation, HTTP/queue/scope/assessment/decision change; preserve canonical execution authority | Source review: mapping-only inactive codec. No Python modifications this round. |
| Truthful inventory and focused pytest/Ruff/format/mypy | Independently pass above; no test-count change. |
| Unchanged integration gates without baseline/grant workaround | Exact Vulture, inventory and shipped-surface pass; trusted-base provenance FAILS. Full required integration CI and current generic test failure remain UNVERIFIED/UNRESOLVED. |
| Coordinated base/ownership and rollout constraints | Assigned local HEAD verified; external coordination release and activation permission UNVERIFIED. No remote action or activation performed. |

## Disposition and next action

**BLOCKED**, not repaired or integration-approved. Only this report changed.
Actual inherited blocker: `quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:612-613`. The mandatory CI provenance
step (`.github/workflows/vulture-ratchet.yml:77`) rejects these entries.
Candidate ledger amendments cannot authorize them. No sync conflict exists;
no fetch or merge is warranted by the supplied conditional instruction.

Owner action required: separately reviewed protected-base authorization or
coordinated real integration, consistent with the issue's scope and gate policy,
plus the exact failing CI test log. Neither is authorized as an implementation
workaround in this lane. Do not repeatedly redispatch this unchanged blocker as
an unspecified test repair. Preserve existing code and all prior evidence.

Progress: checked 1, done 0, skipped 0, errors 1 (provenance blocker).
Next: owner resolves the policy/coordination dependency and supplies CI failure
traceback. This handoff is committed locally; no push or GitHub mutation.

