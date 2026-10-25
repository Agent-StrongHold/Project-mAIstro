# Issue #1893 repair — frozen job 64a3aae4

Scope: issue #1893 only, branch `auto-1893`, starting head
`bb670999038c30b328dba95ba98f8b53a105e96b`, supplied develop base
`2154f845347c9541016288c760f8da3f5cd2e064`.
Clean initial worktree; no salvage required. Frozen evidence: supplied job's
`dispatch-context.json`, `check-0.log` through `check-4.log`, previous result
`aed7f8d7f77c4b24a2461d4f97d7c5a1/result.json`.

Processing only admission identity/codec, adjacent tests, relevant ADRs and CI
provenance/Vulture gates. No unrelated PRs or issues will be processed.
Potential repair files are the two admission modules and their tests; Vulture
ledger amendment only if the prescribed scan identifies actual retained debt.
No reachability ledger/grant/gate modifications are authorized.

Initial evidence: driver reports dependency sync, Ruff, format, 324 tests
(3 skipped), and core suite inventory passing. Prior result is BLOCKED by
trusted-base reachability provenance. The generic `test: failure` does not
identify a failing node; assume it requires reproduction, not speculative edits.
Validation and acceptance results follow below.

## Reproduced gate results

- Exact prescribed Vulture scan passed: 1322 findings / reviewed identities,
  zero unclassified. No Vulture ledger change is justified.
- `RATCHET_BASE_REV=2154f845347c9541016288c760f8da3f5cd2e064 uv run python scripts/check-ratchet-provenance.py`
  exited 1: both admission modules are NEW unreachable modules and NEW
  dispositions without already-landed authorization (169 trusted -> 171).
  Other wrapper subgates passed. `origin/develop` resolves to that exact base;
  no develop-sync conflict is present.
- Read full supplied issue body and inspected captured failed check summaries.
  The linked #1945 head has an exact-debt-ledger failure. Captured generic test
  failures belong to linked #1855, not this starting head; no failing-node log
  for the assigned head was supplied. This is not grounds for speculative edits.
- Read codec and all codec tests. The module explicitly has no production
  consumer (lines 50–53); adding fake imports or activating admission would
  violate the issue's staged scope. Existing pool tests exercise synthetic
  DTO identities, not authorization or production Run materialization.

The prior trusted-base blocker is independently reproduced. Its resolution
requires coordination beyond this lane, not changes allowed by the Vulture-only
ledger exception. Do not loop on the unchanged gate.

## Focused validation executed

All commands ran in the assigned worktree with a 1800-second timeout:

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3301 files.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`: PASS, 2 files.
- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/extensions/test_cli_lock.py packages/maistro-core/tests/extensions/test_pack_contracts.py -x -q -rs`:
  **324 passed, 3 skipped**, 327 nodes, 1.92s. Skips are the real-pool tests
  at `test_admission_codec.py:470`, requiring both PostgreSQL DSNs. They are
  explicitly NOT durability proof in this round.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`:
  PASS, 16543 nodes, no duplicate evidence.
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.

Read accepted ADR-081226-a66b, ADR-082526-7f02 and ADR-083126-5e62.
Reconciliation: preserve Run lifecycle ownership, immutable admission provenance
and trusted-base gate authority; a candidate ledger edit cannot authorize itself.
No competing execution or authorization authority is introduced. Read the B2
inventory note as historical evidence, not current proof.

Additional executed validation:

- `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs -x -q`:
  **1919 passed, 310 skipped, 5 warnings**, 2229 nodes, 49.00s. Warnings concern
  adjacent aiosqlite worker threads with closed event loops; no assertion failed.
- Runtime import search across `packages/**/*.py`, excluding tests, found
  only codec -> identity and `_vulture_whitelist.py:105` -> identity.
  Neither is a production entry-point consumer. Provenance graph independently
  classifies both modules unreachable.
- `git diff --check`: PASS.

## Acceptance audit at the supplied source SHA

| Criterion | Executed evidence / limitation |
| --- | --- |
| Frozen/slotted header, exact interfaces, fresh flat SQL mapping | Header construction, immutable identity, mismatch and fresh-mapping tests passed. Source inspection confirms required signatures and six error codes. |
| Named SQL fields, strict UUID `.hex`, signed timestamps, prerequisite constructors | Missing-column, UUID, scalar type/range and DTO-constructor tests passed. Physical `request` maps to `request_snapshot`; no ordinal row assumptions. |
| Typed safe errors, validated scope, no leaked snapshot/token chain | Invalid snapshot, invalid UUID, scope-validation and suppressed-context assertions passed. |
| Strict TEXT object JSON, duplicate/nonfinite rejection, arbitrary evidence preservation | Duplicate/nonobject/bare-nonfinite, Unicode, numeric precision and tagged-context tests passed. Evidence is pure codec behavior, not production model materialization. |
| Immutable v2 snapshots and unchanged stored fingerprint | Canonical snapshot round-trip and tagged nonfinite tests passed; no recalculation in codec. Original model fingerprint -> evidence-json -> model_of/model_of_json integration remains UNVERIFIED. |
| Legacy bound/unbound/partial without invented identity | Legacy binding, receipt-only, one-sided pair, unreadable evidence and completed_at tests passed. Pair without receipt remains partial because prerequisite AdmissionBinding requires an explicit receipt; no fabricated receipt. |
| Minimal supported header survives malformed snapshot/partial binding | Expiry/fingerprint preservation, header mismatch and unknown-format tests passed. Consumer expiry/409 precedence is outside B2, not claimed. |
| Raw and production PostgreSQL pool equivalence on migrated disposable DB | UNVERIFIED this round: all 3 real-pool cases skipped for absent DSNs. Prior live DB claims were not adopted as fresh evidence. No DB session IDs or row counts claimed. |
| Actual Run JSONB object, explicit authorized principals/Workspace/Project/Graph | UNVERIFIED: test fixtures are synthetic strings and this inactive codec does not insert Runs or perform authorization. |
| Stage constraints: no SQL mutation, live assessment, clock, HTTP/queue/scope/deletion policy change | Inspected source is representation-only; no source changes made. Canonical Goal -> Graph -> Run -> NodeRun -> Attempt unchanged. |
| Inventory, focused pytest, Ruff/format, mypy and required gates | Listed commands pass except required trusted-base provenance. Full integration CI and reported hosted test failure remain UNVERIFIED. |

## Disposition

**BLOCKED.** Only this report changed; no tests added, no inventory delta,
no source or ledger changes, and no new pre-fix/mutation claim. No justified
Vulture repair exists. Generic hosted `test: failure` is not reproduced locally;
obtain its failing node/log at the assigned head rather than guessing.

The blocking gate requires an independently authorized trusted-base resolution
or a separately approved real consumer integration. Neither may be fabricated
inside this staged codec repair. No push, GitHub mutation, grant/gate edit or
production activation performed. This local documentation commit is a handoff,
not integration approval. Avoid redispatching this same unchanged blocker without
new trusted-base or failing-node evidence.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 1, next: owner coordination on trusted-base provenance and actual failing CI node}`.
