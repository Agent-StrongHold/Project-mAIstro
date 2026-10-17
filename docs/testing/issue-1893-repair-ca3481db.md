# Issue #1893 repair — ca3481db

## Frozen scope

- Assigned worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Starting HEAD `0a9d3fc54694e13a43dd0b79e3d75eecb457fe98`;
  supplied develop base `435dc1937e0407ab4de198ffcced49860bb14ad2`.
- One item: #1893 B2 immutable admission codec, its identity prerequisites,
  adjacent tests, supplied check-0 through check-4 logs, and named CI gates.
- Initial worktree clean; no incoming edits to salvage.
- Source/test repair candidates are `maistro/tasks/admission_codec.py`,
  `maistro/runs/admission_identity.py`, and their two existing test files.
  This report records validation; inventory notes change only if tests change.
  Vulture ledger amendments only for actual reported retained identities.
- No GitHub mutations, production activation, or reachability grant edits.

## Ambiguities and assumptions

The supplied generic `test: failure` does not identify a failing node. Treat it
as unverified until local checks or captured job evidence identify a failure.
Previous reachability authorization failure is not a develop-sync conflict;
reproduce against the frozen base without fetching or selecting a new base.
Staged codec correctness is not production reachability or parent closeout.

## Progress

Inspected supplied check-0 through check-4 logs: sync, lint, format, focused
201-pass/3-skip tests and core inventory passed in the driver. These are not
new worker execution or real PG proof.

Independently executed (1,200-second timeout):

- Required Vulture scan: PASS, 1,323 findings, zero unclassified. No ledger
  amendment is warranted.
- `RATCHET_BASE_REV=435dc1937e0407ab4de198ffcced49860bb14ad2 uv run python
  scripts/check-ratchet-provenance.py`: FAIL, exit 1. Both
  `maistro.runs.admission_identity` and `maistro.tasks.admission_codec` add
  unauthorized unreachable modules and dispositions (169 -> 171).
- `git rev-parse origin/develop`: same SHA as the supplied base. There is no
  develop-sync conflict or new resolved base to merge.

The existing branch adds reachability baseline rows at
`quality/reachability-baseline.json:131,147` and dispositions at
`quality/reachability-dispositions.json:604-614`. This is a trusted-base
prerequisite, not a Vulture issue. The permitted Vulture exception cannot
repair it. No code or ledger edit is justified by this failure; leave existing
work intact. Additional focused acceptance review follows.

Independently executed focused commands (1,200-second timeout):

| Command | Result |
| --- | --- |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3,277 files |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS, two source files |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -r s` | 201 passed, three PG skips, 204 collected |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS, 16,466 nodes, no duplicate evidence |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS |

Read both complete source modules and their adjacent tests. Accepted
ADR-081426-1f7c keeps execution mechanics Attempt-owned; ADR-082526-7f02 keeps
admission provenance immutable and dispatch identity on Attempt. No competing
scheduler, authorization path, Goal store or event authority is introduced.
The legacy-pair-without-receipt case remains a typed partial disposition:
constructing the prerequisite binding requires a receipt, and inventing one
would violate the explicit no-inference constraint. No policy reinterpretation
or production activation is attempted in this round.

## Acceptance evidence at the assigned source SHA

| Criterion | Evidence / limit |
| --- | --- |
| Shared APIs, frozen/slotted scalar header and six error codes | Complete source review; header mismatch/schema/format tests pass |
| Strict storage UUID .hex, signed timestamps and prerequisite constructors | Token, generation, scalar boundary and identity DTO tests pass |
| Exact v2 snapshots and fresh flat named-column mapping | Three in-memory states pass (unbound, bound, acknowledged); independent assertions require task_id = receipt_id when bound |
| No inferred legacy identity; bound/unbound/partial and receipt-only distinctions | Named legacy pairing, missing-receipt, whitespace and unreadable-evidence tests pass; neither ID stays absent |
| Header evidence survives malformed snapshots and partial binding | Expiry/fingerprint preservation tests pass; decoder takes no clock or incoming fingerprint |
| Unknown formats and invalid scalar headers fail closed | Unsupported-format and scalar/mismatched-header tests pass; no fallback to legacy |
| Strict TEXT JSON, duplicate/nonobject/bare-nonfinite rejection and safe errors | Malformed/nested/lossy-number/surrogate tests pass; errors suppress parsing chains and do not quote snapshot/token data |
| Tagged evidence, permitted program_context and unchanged stored fingerprint | Tag/nonfinite and Unicode/numeric tests pass for encoded fixtures; no fingerprint recomputation in source |
| Existing evidence-json serialization and model_of/model_of_json materialization | UNVERIFIED end-to-end: fixtures manually construct tagged dictionaries; no TaskResponse or Run model persistence proof |
| Real raw/production pools against the same migrated disposable PG schema | UNVERIFIED this round: three tests skipped for absent DSNs. Prior worker's live-PG claim was read but is not reused as executed proof |
| Run payload bound text::jsonb INSERT is an object, not double-encoded JSON | UNVERIFIED: focused codec suite does not insert canonical Run models |
| Explicit authorized Workspace/Project, principals and registered Graph kinds | UNVERIFIED: fixture strings establish representation, not authorization or registered graph admission |
| No SQL mutation, HTTP/queue mapping, assessment/claim decision or policy changes | Complete source review: pure mapping/DTO layer; no source change this round |
| Expiry replacement and 409 precedence | UNVERIFIED consumer behavior; explicitly belongs to later C/F2, not B2 |
| Canonical Goal -> Graph -> Run -> NodeRun -> Attempt | Accepted ADRs reviewed; no competing runtime authority introduced |
| Production reachability | NOT ESTABLISHED: source import search finds only codec -> identity and Vulture whitelist -> identity; no production codec caller; provenance gate rejects the inactive modules |
| Focused lint, format, mypy, tests, inventory, Vulture and shipped surface | Independently PASS as recorded above; no new tests, no inventory delta |
| Full unchanged required CI / supplied generic test failure | UNVERIFIED: no current-head failing node or traceback in supplied check logs. Provenance gate independently FAILS |
| Coordination, stage constraints and activation | BLOCKED: this lane does not authorize production activation or reachability grants |

Production import search: `admission_codec|admission_identity` under
`packages/**/src/**/*.py` finds only
`packages/maistro-core/src/_vulture_whitelist.py:105` and
`packages/maistro-core/src/maistro/tasks/admission_codec.py:67` as imports.
Codec lines 49–52 explicitly document its future consumer; test imports are
not runtime reachability. `.github/workflows/vulture-ratchet.yml:77` enforces
provenance before Vulture. `.github/workflows/ci.yml:573-612` assigns core tests
to the coverage producer, not the reported `test` job; this focused rerun does
not claim to reproduce all of that job's other packages/frontends/integration
checks. The latest captured issue comments likewise report a blocker, not a
new test traceback. No unrelated suite or speculative scanner fix is warranted.

## Handoff

**BLOCKED.** Changed only this report; no source, tests, ledgers, grants or gates
changed. No regression was repaired and no pre-fix/mutation proof is claimed.
Existing uncommitted report will be committed locally; no push or GitHub action.

The owner must resolve the trusted-base reachability prerequisite through the
existing two-merge authorization process or separately authorized integration.
That cannot be supplied by this lane's Vulture-only exception. Repeating the
same checks or merging the identical base cannot resolve it. Supply the actual
current-head `test` failure traceback if another code repair is expected.

Progress: checked 1, done 0 code repairs, skipped 0 issues, errors 1 required
gate. Next: owner prerequisite resolution; then real PG/full CI validation on
the authorized integration head. Local commit is evidence handoff, never
integration approval.
