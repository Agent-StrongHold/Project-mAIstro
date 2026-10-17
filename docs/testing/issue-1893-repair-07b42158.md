# Issue #1893 repair checkpoint — 07b42158

## Frozen scope

- Issue: #1893 only; assigned branch/worktree: `auto-1893`.
- Starting HEAD: `e24103575b965be35e6ffda67b439a4cdb21230d`.
- Supplied develop base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Initial worktree clean; no incoming edits to salvage.
- Read-only evidence: job `07b421587f964768b22385e3031ef537` dispatch snapshot,
  five driver check logs, supplied prior result, repository instructions,
  relevant ADRs and CI workflows.
- Production/test inspection scope: admission codec, admission identity,
  adjacent task/identity tests and associated inventory notes. Validation:
  named vulture gate, provenance gate, ruff, focused tests and applicable mypy.
- Only this report and evidence-backed repairs within that scope may change.
  No grants, reachability ledgers, gates, runtime activation or unrelated fixes.

## Ambiguity

Dispatch names only `test: failure`, with no failing test node. Treat it as an
unverified failure report, not permission to guess a repair. Prior evidence
also reports an unauthorized reachability floor increase; verify it afresh.
The supplied base/head resolve. No develop-sync conflict exists in the clean
starting tree, so no fetch or merge is warranted.

## Progress

- Snapshot inspected; issue requires a pure staged codec, not production
  activation. Acceptance includes actual migrated PostgreSQL evidence; skipped
  database tests cannot establish durability.
- Driver check logs inspected: dependency sync, Ruff, format and suite inventory
  pass; focused tests report 311 passed / 3 skipped. These are not PG proof.
- Independently executed named Vulture command: PASS, 1323 findings match 1323
  reviewed identities. No unbanked identity exists to amend.
- Independently executed provenance with `RATCHET_BASE_REV` set to the supplied
  base: FAIL (exit 1). Two unauthorized unreachable modules and two unauthorized
  dispositions remain. Logs: `worker-vulture.log`, `worker-provenance.log` in
  this job directory.
- Captured failed checks extracted once to `worker-captured-failures.json`.
  The captured `test` failure is for `3f2c79a70d9e1b0b6b6ffc99562cb35db5326828`,
  not this candidate; output title/summary/text are null. Attribution remains
  UNRESOLVED; no guessed source repair is justified.
- Read accepted lifecycle ADR-081226-a66b and trusted-base quality authority
  ADR-083126-5e62. Candidate ledger edits cannot authorize this reachability
  increase. B2 explicitly forbids activation; adding fake runtime imports is
  not a permissible repair. Preserve Goal -> Graph -> Run -> NodeRun -> Attempt.

## Executed validation

All commands below were independently executed with 1800-second timeouts at
starting HEAD, with only this report modified. Logs are in the assigned job
directory. Driver checks are additional evidence, not substituted execution.

| Command | Result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1323 reviewed identities / 1323 findings (`worker-vulture.log`). |
| `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py` | FAIL: exit 1, two new unauthorized modules and two new unauthorized dispositions (`worker-provenance.log`). |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -r s` | 204 nodes: 201 passed, 3 skipped in 1.21s (`worker-focused.log`). |
| `uv run ruff check .` | PASS (`worker-quality.log`). |
| `uv run ruff format --check .` | PASS: 3277 files (`worker-quality.log`). |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS: two source files (`worker-quality.log`). |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS: 16467 collected identities, zero duplicate evidence (`worker-quality.log`). |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS (`worker-quality.log`). |

No tests were added or changed, so no inventory delta is required. No new
pre-fix/mutation failure is claimed. Existing binding tests independently
assert migration-055's task/receipt equality, rather than merely asserting
that encoder and decoder agree.

## Acceptance audit

PASS here means a tested **codec contract**, not reachable admission behavior.

| Criterion | Evidence / limitation |
| --- | --- |
| Shared frozen/slotted header, record interfaces, six typed decode codes, validated scope and safe errors | Source inspection of `admission_codec.py` and passing schema/scalar/error tests. Error paths suppress parsing context and do not quote raw snapshots or owner tokens. |
| Strict UUID `.hex`, signed timestamps, prerequisite constructors, fresh flat named-column encoding | Passing `test_owner_token_is_hex_at_storage_only`, strict-generation/scalar tests, `test_encode_returns_a_fresh_flat_mapping`; source uses immutable #1851 constructors. |
| Preserve v2 snapshot bytes, binding pairs and acknowledgements | Passing three-state `test_v2_round_trip_preserves_all_snapshot_bytes`; independent task/run/receipt assertions at test lines 134-137. Live migration constraint proof is UNVERIFIED in this run. |
| Legacy bound/unbound/partial remain distinct without invented identities | Passing legacy-binding, receipt-only, pair-without-receipt and unreadable/whitespace evidence tests. A pair without receipt remains partial because #1851's constructor requires receipt identity; none is fabricated. |
| Header/full-record separation, preserved expiry/fingerprint despite corrupt snapshot or partial binding | Passing the three named header-preservation/expired-legacy tests and scalar mismatch tests. Inclusive expiry/replacement and 409 precedence belong to C/F2, not B2; not claimed here. |
| Unknown schema/format and invalid scalar headers fail closed | Passing unknown-format (including bool/float), missing-column, invalid-header and mismatched-header tests. |
| Strict TEXT JSON rejects duplicate keys, nonobject roots, bare nonfinite values and invalid original evidence | Passing invalid/duplicate JSON, excessive nesting, lossy-number, non-UTF8 and predecoded-value tests; corruption injected directly at the row boundary. Valid Unicode/exact-number controls also pass. |
| Tagged nonfinite snapshots and unchanged fingerprint | Passing handwritten-tag round-trip test. Original-model fingerprint -> production evidence-json -> `model_of`/`model_of_json` materialization is UNVERIFIED; the fixture pins a fingerprint and does not prove that integration. |
| Same migrated disposable DB through raw and production-codec pools; TEXT snapshots and actual object-valued Run JSONB | UNVERIFIED: all three PG cases skip at test line 470 because the required DSNs are not configured. No DB was provisioned after the mandatory provenance blocker reproduced. No DB sessions, final row counts, migration/downgrade or Run INSERT proof claimed. |
| Authorized explicit principals, Workspace/Project and registered Graph kinds | UNVERIFIED by these synthetic DTO fixtures; no admission transaction is exercised. |
| No SQL mutation, HTTP mapping, queue/clock/assessment/claim changes or competing execution authority | Codec source inspection: mapping/DTO translation only. This repair round changes only this report. No activation or legacy/deletion-policy choice made. |
| Actual production reachability | NOT SATISFIED: production import search finds only codec-to-identity and Vulture-whitelist references. `admission_codec.py:50-53` explicitly documents no production consumer. Test imports are not runtime reachability. |
| Focused tests, lint, types, inventory and unchanged full integration CI | Focused commands PASS above. Full integration CI UNVERIFIED; mandatory provenance FAILS. Driver additionally ran pack-contract tests: 311 passed / 3 skipped across its three files. |
| Coordinated base/ownership and activation choices | Assigned isolated repair head verified; broader integration/activation authorization remains UNVERIFIED. Passing tests grants no activation authority. |

## Blocker and handoff

`quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:604-614` retain unauthorized candidate
additions. `.github/workflows/vulture-ratchet.yml:77` requires the failing
provenance gate **before** Vulture. Passing Vulture therefore cannot fix this
failure, and there is no retained unbanked Vulture identity to amend.

Resolving this dependency requires separately reviewed real consumer
integration consistent with #1845, or separately landed trusted-base
reachability authorization followed by an owner-supplied updated base. Neither
is authorized in this lane. The generic test failure additionally requires
candidate-qualified failing-node/traceback evidence. No source, test, ledger,
whitelist, grant or gate changes were made; all incoming work is preserved.

Only changed file: `docs/testing/issue-1893-repair-07b42158.md`. Commit locally,
never push. Verdict: **BLOCKED**, not integration approval or issue closeout.

Progress: checked 1, done 0, skipped 0, errors 1 (mandatory provenance).
Next: owner action on trusted-base integration and candidate-qualified CI
failure evidence; do not repeat speculative repairs against identical inputs.
