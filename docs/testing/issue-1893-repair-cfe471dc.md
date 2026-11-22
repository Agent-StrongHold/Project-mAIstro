# Issue #1893 repair checkpoint — cfe471dc

## Frozen scope

- Assigned issue: #1893 only; branch `auto-1893`.
- Starting head: `439db463f6903e87cffdb5ac7fb9a50040e7ee3f` (verified).
- Supplied develop base: `2154f845347c9541016288c760f8da3f5cd2e064`.
- Worktree clean at entry; no incoming changes to salvage.
- Inspection scope: supplied job `dispatch-context.json`, `check-0.log` through
  `check-4.log`, prior result c05e013d; repository instructions, relevant ADRs,
  admission codec/identity implementation and tests, CI workflows, reachability
  and vulture gate evidence. No linked issue or PR implementation is assigned.
- Potential edits: codec/identity implementation and adjacent tests only if a
  defect is reproduced; corresponding inventory note if tests change; vulture
  ledger only if the explicitly permitted scan identifies retained debt.
  This report records results even if no safe code repair is available.

## Ambiguity and assumption

The dispatch says `test: failure` without naming a test. Treat it as requiring
local reproduction, not permission to guess a fix. Prior reachability findings
are hypotheses until rerun. Production activation is expressly out of scope;
no synthetic runtime caller, grant, reachability baseline or gate changes will
be used to make this staged codec appear integrated.

## Results

- Inspected all five supplied driver logs: sync, Ruff, format and inventory
  passed; focused tests reported 324 passed, 3 skipped. These are driver
  observations, not live PostgreSQL proof.
- Independently ran `uv sync --locked --extra dev`: passed.
- Independently ran the exact prescribed Vulture scan: passed, 1322 findings,
  1322 reviewed identities, zero unclassified. No ledger edit is warranted.
- Resolved `origin/develop` to the supplied base, then ran
  `RATCHET_BASE_REV=2154f845347c9541016288c760f8da3f5cd2e064 uv run python scripts/check-ratchet-provenance.py`:
  exit 1. Both admission modules are new unreachable modules and new
  dispositions without already-landed authorization (169 -> 171). Other
  provenance checks passed. This reproduces the blocker; do not rerun it
  unchanged or attempt candidate self-authorization.
- Read accepted ADR-081226-a66b (single execution lifecycle), ADR-082526-7f02
  (immutable admission provenance), and ADR-083126-5e62 (candidate evidence
  cannot authorize itself). The Vulture-only exception does not authorize
  reachability grant changes or premature production activation.
- Codec inspected: representation only, no clock, fingerprint recomputation,
  SQL execution or HTTP mapping. Its module documentation explicitly states
  that production does not yet consume it.

## Focused validation (independently executed)

All commands below ran against the starting source SHA with 1800-second
command timeouts. Only this Markdown report has changed.

| Command | Result |
| --- | --- |
| `uv run ruff check .` | Passed |
| `uv run ruff format --check .` | Passed; 3301 files |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | Passed; 2 modules |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/extensions/test_cli_lock.py packages/maistro-core/tests/extensions/test_pack_contracts.py -x -q -rs` | 327 collected; 324 passed, 3 skipped; 1.74s |
| `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs -x -q` | 2229 collected; 1919 passed, 310 skipped; 6 aiosqlite closed-event-loop thread warnings; 49.01s |
| `uv run python scripts/check-shipped-surface-truth.py` | Passed |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | Passed; 16543 nodes, no duplicate evidence |

The exact Vulture command was:
`uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`.

Production import search (`rg -n 'admission_codec|admission_identity' packages
--glob '*.py' --glob '!**/tests/**'`) found only codec -> identity and the Vulture
whitelist -> identity import. There is no reachable production consumer.
The generic hosted `test: failure` was not reproduced by these scoped tests;
no specific hosted failing test node was provided. The aiosqlite warnings are
reported, not silently treated as evidence that all CI is green.

## Acceptance audit

| Criterion | Executed evidence / limitation |
| --- | --- |
| Exact frozen/slotted header, two decode interfaces, fresh flat encoder, six error codes | Interfaces inspected in codec; focused mismatch/schema/encode tests passed. DTO immutability tests passed. |
| Named fields, strict UUID `.hex`, signed timestamps, prerequisite constructors | Storage hex, nil UUID, int64, identity and constructor rejection tests passed. Physical `request` maps to DTO `request_snapshot`. |
| Safe typed errors containing only validated scope | Invalid-scope, invalid-JSON, excessive nesting, lossy-number, Unicode and owner-token hygiene tests passed; parsing chains suppressed. |
| Strict JSON objects and evidence tags without fingerprint recalculation | Duplicate/nonobject/bare-nonfinite tests passed; tagged data preserved and supplied fingerprint unchanged. Original model -> fingerprint -> evidence-json -> model_of/model_of_json integration remains UNVERIFIED; fixtures construct tags directly. |
| v2 unbound/bound/acknowledged round trips preserve snapshots | Three pure state cases passed, independently asserting both binding columns and receipt identity; real DB cases skipped. |
| Legacy bound, unresolved and partial remain distinct without inventing identity | Bound/unbound/one-sided/receipt-only tests passed. A pair lacking receipt evidence is partial because the prerequisite binding constructor requires a receipt; none is invented. |
| Supported header survives snapshot/binding failure; unknown formats fail closed | Named expiry/fingerprint preservation tests and unknown-format/header-mismatch tests passed. No clock or request fingerprint accepted. Consumer expiry/409 ordering is not B2 behavior and remains UNVERIFIED. |
| TEXT independence across raw/production pools on real migrated DB | UNVERIFIED this round: three tests skipped at test_admission_codec.py:470 because DSNs are unset. Prior c05e013d live claims were inspected but not adopted as independently executed evidence. No DB session identities or row counts claimed. |
| Authorized principals, Workspace/Project, registered Graph and Run JSONB object | UNVERIFIED: synthetic codec DTO fixtures are not admission authorization or Run materialization proof. |
| No SQL mutation, HTTP mapping, queue change, assessor change or competing authority | Source inspected; functions only decode/encode mappings. Production import search confirms inactive contract leaf. Canonical Goal -> Graph -> Run -> NodeRun -> Attempt remains unchanged. |
| Inventory, focused pytest, Ruff/format/mypy and unchanged gates | Passed as above except required trusted-base provenance, which failed. Full integration CI remains UNVERIFIED. No tests added or changed; no inventory delta needed. |
| Coordinated implementation ownership/base and activation policy | Lane authorizes this isolated repair only. Parent owner coordination and production activation remain unresolved, not overridden by a passing codec test. |

No new pre-fix/mutation failure is claimed: no source/test fix was justified
by the executed evidence. No ledger, grant, gate or production code was changed.
After reproducing the trusted-base blocker, no additional live DB setup or full
integration battery was started; neither can authorize unreachable modules.

## Disposition / next action

**BLOCKED**. `quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:606-613` contain unapproved additions,
rejected by the required exact-debt-ledger provenance command. The permitted
Vulture ledger exception does not remedy this separate gate.

Owner coordination must supply a trusted-base resolution consistent with the
issue's staging constraints; alternatively supply the actual hosted failing
node and log if a separate test repair is required. Do not repeatedly dispatch
this unchanged blocker as a Vulture repair. No push or GitHub mutation occurred.

Changed file: `docs/testing/issue-1893-repair-cfe471dc.md` only (local handoff).
Progress: `{checked: 1, done: 0, skipped: 0, errors: 1, next: trusted-base owner coordination and concrete hosted failing-test evidence}`.

