# Issue #1893 repair validation — b08ff7d2

## Frozen scope

- Issue: #1893 only; assigned worktree `/home/dev/Git/wt/auto-1893`.
- Starting HEAD: `34bf6b4356296b2b6e4fd7a0a34f51623897462a`; assigned base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Existing worktree was clean. No incoming edits to salvage.
- Inspect existing admission codec, admission identity types, their two test files, relevant ADRs, CI workflows, and existing reachability entries; change only this evidence report unless validation establishes a repair within the assigned scope.
- No GitHub mutations, production activation, authorization changes, or reachability ledger changes authorized. Vulture ledger changes permitted only for actual findings from the prescribed scan.

## Initial evidence / ambiguity

The job's check-0 through check-4 logs report dependency sync, lint, format, focused tests (201 passed, 3 skipped), and core suite inventory (16466) passing. Those supplied results are not independent acceptance evidence. The reported `test: failure` has no failing node/traceback in these logs. Assumption: reproduce focused tests and prescribed gates before changing code; do not invent a repair. Prior reports identify reachability provenance as a distinct blocker; revalidate against the resolved local base without fetching/re-enumerating the dispatch snapshot.

## Independently reproduced gate result

`origin/develop` and the merge base resolve to the assigned base. No sync conflict exists. With a 1200-second timeout:

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS; 1323 findings, zero unclassified. No ledger amendment is justified.
- `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py`: FAIL, exit 1. Both `maistro.runs.admission_identity` and `maistro.tasks.admission_codec` introduce unreachable modules and dispositions without trusted-base authorization (169 -> 171). This reproduces the required exact-debt-ledger blocker, not a dependency failure.

The explicit Vulture exception does not permit reachability authorization edits. Preserve existing work and report BLOCKED rather than invent a consumer or self-authorize. Focused validation completed independently at the starting SHA (1200-second timeout):

- `uv run pytest packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/tasks/test_admission_codec.py -x -q -rs`: 201 passed, 3 skipped, 204 nodes in 1.29s. All three skips require both PostgreSQL DSNs (`test_admission_codec.py:470`). No live durability claim.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3277 files.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`: PASS, two files.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: PASS, 16466 nodes, no duplicate evidence.
- `git diff --check`: PASS.

No test additions or test-count changes; no inventory delta required.

Additional independently executed commands (1200-second timeout):

- `uv run python scripts/check-reachability.py`: PASS candidate accounting, 1396 production modules / 171 unreachable.
- `uv run python scripts/check-reachability-dispositions.py`: PASS candidate accounting, 50 groups / 171 modules.
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- `uv run python scripts/check-promotion-surface.py`: PASS, 74 tolerated modules.
- Import search across `packages/**/*.py`: only the codec imports the identity module, plus the Vulture whitelist and tests. These are not a reachable runtime consumer.

## Architecture and acceptance accounting

Read repository instructions, the full issue body in the frozen dispatch, the prior result (not adopted as fresh evidence), complete codec/identity sources and adjacent tests, and accepted ADR-081226-69ee, ADR-082526-7f02, ADR-083126-5e62. Reconciliation: preserve Goal -> Graph -> Run -> NodeRun -> Attempt and immutable admission provenance. A staged DTO leaf does not authorize production activation. Candidate ledger entries cannot authorize themselves.

| Acceptance | Executed evidence or limitation |
| --- | --- |
| Exact frozen/slotted header/interfaces, named columns, scalar/header agreement, typed error codes | Source inspection plus passing header/schema/mismatch tests. |
| UUID `.hex` only at storage, signed timestamps, #1851 constructors | Passing strict UUID/scalar/identity tests; source uses the existing constructors. |
| Fresh flat SQL mapping, three v2 states, immutable receipt identity | Passing round trips and independent task/run pairing assertions at `test_admission_codec.py:134-137`; type test rejects binding/receipt disagreement. Live schema CHECK UNVERIFIED this round. |
| Legacy bound/unbound/partial, receipt-only and announced-without-Run | Passing legacy tests. A bound pair without explicit receipt cannot satisfy AdmissionBinding and remains partial rather than inventing a receipt. completed_at is not authority. |
| Header expiry/fingerprint preserved despite full-record failures; unknown format fail-closed | Passing prospective header preservation and unsupported-format tests. Replacement/409 ordering is consumer C's behavior, not proven by DTO tests. |
| Strict TEXT snapshots, duplicate/nonobject/bare nonfinite rejection, evidence preservation, unchanged fingerprint | Passing snapshot/error/numeric/Unicode/tagged tests. Snapshot normalization does not recompute fingerprints. |
| Safe error scope/messages/chains | Passing validated-hash, token, malformed snapshot and suppressed-context checks. |
| Existing evidence-json production and model_of/model_of_json materialization | UNVERIFIED: fixtures construct tagged data manually; no real TaskResponse/Run materialization in this slice. |
| Real migrated disposable PostgreSQL, raw/production pools, session/row identity counts | UNVERIFIED: three cases skipped for absent DSNs. No migration, durability, cleanup-count or DB session claim made. |
| Authorized principals/Workspace/Project/registered Graph kinds; Run JSONB object | UNVERIFIED: DTO fixtures are not live authorization/admission or Run INSERT. |
| No SQL mutation, clock, assessment, HTTP/queue/scope/policy changes or competing authority | Complete codec inspection: mapping-only staged leaf, no consumer. This round changes documentation only. |
| Focused pytest, lint, format, mypy and inventory | PASS as independently executed above. No new tests or mutation-proof claim. |
| Unchanged full required CI; no candidate-authorized accounting expansion | FAIL trusted-base gate. Full integration CI UNVERIFIED; candidate accounting success is not authorization. |

The frozen dispatch's check-run objects show `test: failure` at linked head `3f2c79a70d9e1b0b6b6ffc99562cb35db5326828`, not the assigned starting HEAD. At linked head `fcc8b437f209a35aa68a61d6f0a5387414938355`, `test` succeeded and `exact-debt-ledger` failed. Outputs have null summary/text. This was extracted locally from the supplied snapshot, without remote re-enumeration. An assigned-head failing test/traceback remains UNRESOLVED; no guessed repair was made.

## Handoff

**BLOCKED.** Changed file: this report only. Existing source, tests and reachability entries preserved; no grant/gate/ledger changes. No production activation, merge approval or closure implied.

Next: owner-coordinated trusted-base authorization or the separately authorized runtime consumer must precede revalidation. A candidate cannot grant itself permission, and B2 forbids wiring a consumer merely to satisfy reachability. Provide an assigned-head failed-test traceback if the reported test failure persists. Live PostgreSQL and production materialization evidence remains outstanding this round.

Progress: checked 1, done 0, skipped 0, errors 1 (authorization blocker).
