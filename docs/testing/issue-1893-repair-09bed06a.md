# Issue #1893 bounded repair — 09bed06a

## Frozen scope

- Assigned issue: #1893 only; branch `auto-1893`, starting HEAD
  `c0937e83899e0e86e36ee1006112dd3cd2fded35`.
- Dispatch base: `435dc1937e0407ab4de198ffcced49860bb14ad2`.
- Worktree initially clean; no incoming edits to salvage.
- Inspect existing admission codec/identity implementations, their two test files,
  adjacent storage/serialization architecture, ADRs, supplied job logs and CI
  gates. Change production/tests only for reproduced in-scope defects.
- Output file: this note. No GitHub mutations or ledger/grant changes, except a
  vulture ledger correction if the explicitly requested scan demonstrates need.
- Ambiguity: dispatch names `test: failure` without an individual failing test.
  Reproduce focused tests and inspect captured evidence rather than guessing.
- Prior findings are unverified until reproduced in this round. Activation and
  independent integration approval are outside this staged codec repair.

## Results

- Inspected supplied `check-0.log` through `check-4.log`: dependency sync,
  lint, format and suite inventory passed; focused tests were 201 passed and
  three PostgreSQL cases skipped. No failing test traceback was supplied.
- Fresh exact Vulture scan passed: 1323 findings, zero unclassified. No ledger
  correction is warranted.
- Fresh `RATCHET_BASE_REV=435dc1937e0407ab4de198ffcced49860bb14ad2 uv run
  python scripts/check-ratchet-provenance.py` failed (exit 1). It rejects NEW
  unreachable modules and NEW dispositions for `maistro.runs.admission_identity`
  and `maistro.tasks.admission_codec`: 169 trusted entries become 171.
- This is the same prerequisite blocker, not a develop-sync conflict. The
  Vulture-only exception cannot authorize reachability edits. Do not repeat
  provenance checks or attempt a fake production caller to bypass this result.

## Independent focused validation

All commands ran with a 1200-second timeout at the starting source SHA (only
this report was added). The commands and actual outcomes were:

| Command | Outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1323 classified findings, zero unclassified. |
| `RATCHET_BASE_REV=435dc1937e0407ab4de198ffcced49860bb14ad2 uv run python scripts/check-ratchet-provenance.py` | FAIL, exit 1: unauthorized reachability modules and dispositions, as above. |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -r s` | 204 nodes: 201 passed, 3 PostgreSQL cases skipped in 1.27s. |
| `uv run ruff check .` | PASS. |
| `uv run ruff format --check .` | PASS: 3277 files. |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS: two source files. |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS: 16466 nodes, zero duplicate evidence. |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS. |
| `git diff --check` | PASS. |

## Source and acceptance review

Read repository instructions, supplied issue body, latest captured issue status,
prior result artifact, driver logs, exact-debt-ledger workflow, codec source and
tests, identity constructors and adjacent identity tests. Accepted
ADR-082526-7f02 makes admission provenance immutable and dispatch identity
Attempt-owned. Accepted ADR-081426-1f7c confines execution mechanics to the
Attempt. No competing execution, admission or authorization path is justified.
The representation-only scope preserves `Goal -> Graph -> Run -> NodeRun -> Attempt`.

| Criterion | Evidence / limitation |
| --- | --- |
| Frozen/slotted header and exact shared interfaces | Source inspection; scalar/header mismatch, unsupported schema and unknown-format tests passed. |
| Immutable v2 decode and fresh flat encode mapping | Three state round trips and fresh mapping tests passed. Independent binding column assertions enforce task/receipt equality and paired task/run storage. |
| Strict storage UUID hex and signed timestamps | Owner/generation and scalar validation tests passed; receipt mismatch rejected by DTO constructor. |
| No guessed legacy identity | Unbound/bound/partial, receipt-only, pair-without-receipt and invalid evidence tests passed. `completed_at` grants no authority. |
| Separate scalar evidence from full decode | Expiry/fingerprint preservation tests passed despite snapshot or binding failures. Decoder takes no clock or incoming fingerprint and implements no decisions. |
| Strict snapshot JSON and safe typed errors | Duplicate/nonobject/nonfinite, nesting, lossy number and surrogate tests passed, including suppressed chains and validated error scope. |
| Tagged evidence preserved without fingerprint recomputation | Tagged nonfinite, exact number and Unicode tests passed at the representation boundary only. |
| Named SQL fields and TEXT snapshots | Encoder source and flat mapping assertions confirm names and scalar types; live SQL evidence is UNVERIFIED this round. |
| Raw/production pools against the same migrated disposable DB | UNVERIFIED: all three cases skip at `test_admission_codec.py:470` without both required environment variables. No DB session identities or row counts collected. |
| Model materialization, original-model fingerprint and Run JSONB object insert | UNVERIFIED: tagged fixture dictionaries are not production model persistence evidence. |
| Authorized principals, Workspace/Project and registered Graph | UNVERIFIED: representation fixtures do not establish authorization. |
| Reachable production behavior | No codec consumer found by source search. `admission_codec.py:49-52` explicitly documents the inactive leaf. Only codec-to-DTO and whitelist imports exist; neither proves runtime integration. |
| Consumer replacement/409 precedence, crash/dispatch invariants | UNVERIFIED and outside B2 scope; no consumer or admission mutation was added. |
| Full required CI and dispatched `test: failure` | UNVERIFIED: focused tests pass, but provenance fails and supplied logs contain no failing test traceback. |
| Coordination and activation | BLOCKED: repair assignment does not authorize production activation or settle owner policy. |

## Handoff

Only `docs/testing/issue-1893-repair-09bed06a.md` changed. No production, test,
whitelist, ledger, grant or gate edit is justified by the fresh evidence. No new
tests were added, so no inventory delta or new mutation proof is claimed. No
full-suite or database run was started after confirming the prerequisite blocker;
prior durability claims were not adopted as current proof.

The blocker is at `quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:612-613`, enforced by
`.github/workflows/vulture-ratchet.yml:77`. Integration ownership must supply an
already-landed authorization or an independently authorized runtime integration
slice. This lane cannot land that grant, modify reachability ledgers, or invent a
consumer. Provide an actual current-head failing test traceback before another
source repair attempt. Repeating this unchanged lane cannot resolve that owner
prerequisite.

Progress: checked 1 issue, done 0 repairs, skipped 0 issues, errors 1 reproduced
provenance blocker. Next: owner prerequisite and actionable CI test evidence.
This is a blocked local handoff, not integration approval or issue closeout.
