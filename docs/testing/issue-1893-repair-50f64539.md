# #1893 repair handoff — 50f64539

## Scope and decision

Sole assigned item: #1893, worktree `auto-1893`, starting source
`d46665299e1deb8dc7713cbf59831cbe98a9a210`, supplied base
`3c761d14db944a727fa0744444bc67cfe36d49f7`. Initial worktree was clean.
Frozen scope: admission codec/identity modules, adjacent tests, applicable
ADRs, inventory evidence and CI test/exact-debt-ledger checks. No other issue
was worked. This report is the only edit; no tests or inventory counts changed.

**BLOCKED: independently reproduced trusted-base authorization failure.**
No scoped failing test or unbanked Vulture identity was demonstrated, so no
speculative code repair or ledger amendment is justified. Existing reachability
ledger/disposition edits are preserved, not approved by this report.

Read repository instructions, full issue body in the supplied dispatch snapshot,
complete codec/identity source and adjacent tests, and accepted ADR-081226-69ee,
ADR-082526-7f02 and ADR-083126-5e62. Reconciliation: keep
Goal -> Graph -> Run -> NodeRun -> Attempt; never rewrite admission provenance
or activate an unauthorized consumer to appease reachability. Candidate accounting
cannot authorize itself. The explicit Vulture exception does not extend to
reachability grants or dispositions.

## Evidence, not inherited claims

Driver `check-0.log` through `check-4.log` were read: sync/lint/format/inventory
pass; focused tests report 201 passed and three skipped PostgreSQL cases.
The previous job result and report were read, not treated as current validation.

The frozen dispatch check-run objects identify `test: failure` at
`3f2c79a70d9e1b0b6b6ffc99562cb35db5326828`, not this assigned head.
At linked head `fcc8b437f209a35aa68a61d6f0a5387414938355`, `test` succeeds
and `exact-debt-ledger` fails. Both check outputs have null summary/text.
An assigned-head failed-test traceback is **UNRESOLVED**; no remote enumeration
or guessed test repair was performed.

Local `origin/develop` and the assigned-base merge base both resolve to the
supplied base. No develop sync conflict exists. No fetch, merge, push or GitHub
mutation was needed or performed.

## Independently executed validation

Commands ran with 1200-second timeouts at the starting source SHA:

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: **PASS**, 1323 reviewed findings, zero unclassified. No retained identity needs banking.
- `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py`: **FAIL**, exit 1. Two NEW unreachable modules and two NEW dispositions lack trusted-base authorization: `maistro.runs.admission_identity` and `maistro.tasks.admission_codec`. Candidate accounting is 171 versus 169 on the base. This is the required `.github/workflows/vulture-ratchet.yml:77` check, not an installation error.
- `uv run pytest packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/tasks/test_admission_codec.py -x -q -rs`: **201 passed, 3 skipped**, 204 nodes, 1.31s. Skips at `test_admission_codec.py:470` require both PostgreSQL DSNs.
- `uv run ruff check .`: **PASS**.
- `uv run ruff format --check .`: **PASS**, 3277 files.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`: **PASS**, two files.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: **PASS**, 16466 collected nodes, zero duplicate evidence.
- `uv run python scripts/check-reachability.py`: **PASS** candidate accounting, 1396 production modules / 171 unreachable.
- `uv run python scripts/check-reachability-dispositions.py`: **PASS** candidate accounting, 50 groups / 171 modules.
- `uv run python scripts/check-shipped-surface-truth.py`: **PASS**.
- `uv run python scripts/check-promotion-surface.py`: **PASS**, 74 tolerated modules.
- `git diff --check`: **PASS**.

Import search corroborates staged inactivity: the only production-source import
sites found are the codec importing identity and `_vulture_whitelist.py`
importing `AdmissionAssessment`. Test imports and whitelist references are not
runtime reachability. An initial tool glob returned no matches; the subsequent
`rg` search found these actual paths and the test imports.

## Acceptance accounting

| Criterion | Current evidence / limit |
| --- | --- |
| Frozen/slotted header, exact interfaces/error codes, named columns and matching scalar header | Complete source inspection and passing header/schema/mismatch tests. |
| Strict UUID `.hex`, signed timestamps and #1851 constructors | Passing owner/generation/scalar/identity tests. |
| Fresh flat mapping, all v2 binding states and receipt identity consistency | Passing three-state round trips; assertions independently require paired task/run columns and task = receipt. Live migration CHECK remains UNVERIFIED this round. |
| No invented legacy identity; bound/unbound/partial and receipt-only distinction | Passing legacy tests. Bound pair lacking a receipt stays partial because the canonical binding requires an explicit receipt; no receipt is inferred. completed_at grants no authority. |
| Header expiry/fingerprint survive full-decode errors; unsupported formats fail closed | Passing named header preservation, unknown-format and malformed snapshot tests. No clock or incoming fingerprint enters the codec. Actual expiry replacement/409 precedence belongs to consumer C and is UNVERIFIED here. |
| Strict snapshot JSON and preserved arbitrary tagged evidence/fingerprint | Passing duplicate/nonobject/nonfinite, numeric-loss, Unicode and tagged snapshot tests. No recomputation of fingerprint. |
| Safe errors: validated scope, no raw snapshot/owner token or displayed parse chain | Passing typed-error, suppress-context and token tests; source uses `raise ... from None`. |
| Existing evidence-json producer plus model_of/model_of_json materialization | UNVERIFIED: focused fixtures hand-build tagged snapshots, not real TaskResponse/Run materialization. |
| Same migrated disposable PostgreSQL DB, raw and production pools, row/session identity counts | UNVERIFIED: three skipped cases. No DB durability, migration-chain or cleanup-count claim is made. |
| Real authorized principals, Workspace/Project, registered Graph kind and Run JSONB object | UNVERIFIED: DTO tests do not execute admission authorization or Run INSERT. |
| No SQL mutation, HTTP/queue/scope/live assessor/policy or alternate execution authority | Codec source remains an inactive mapping/DTO leaf. This round changes documentation only. |
| Focused tests, lint, format, applicable mypy | PASS as recorded; no test additions, so no inventory delta. |
| Unchanged integration CI and no unauthorized accounting expansion | FAIL trusted-base provenance. Full required CI and assigned-head reported test failure remain UNVERIFIED; passing candidate accounting is not authorization. |

No production behavior or mutation-test success is claimed from DTO tests.
The existing ten prospective test contracts were inspected; nine pure contracts
execute, while the real-pool contract skips in three parametrized states.
The production consumer is intentionally deferred in this issue and cannot be
introduced as a repair for the gate failure.

## Handoff

Next owner action: independently reviewed trusted-base authorization or a
coordinated runtime consumer outside B2's scope; then revalidate the integrated
head and provide an assigned-head traceback if `test: failure` persists.
The current writer cannot resolve that coordination by editing its own grants.
No acceptance/integration approval or issue closure is implied.

Progress: checked 1, done 0, skipped 0, errors 1 (provenance blocker).
