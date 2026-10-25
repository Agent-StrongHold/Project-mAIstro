# Issue #1893 repair handoff — 0595f971

## Frozen scope and decision

- Worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`; clean at start.
- Tested source HEAD: `cc10bc2c9107b1398d205d199b15252f25f232b2`.
- Resolved trusted base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Only #1893: admission codec/identity, their adjacent tests, supplied dispatch/check logs, associated quality gates. This report is the only edit. No source, tests, inventory counts, gates, grants or ledgers changed.
- Evidence directory: `/home/dev/maistro/jobs/0595f971c9324708b1be1fbf1063cae8`.

**BLOCKED, not repaired.** Exact Vulture validation passes. The required provenance gate independently reproduces unauthorized reachability additions. The permitted Vulture-ledger exception cannot authorize reachability/disposition changes. A report commit is a handoff, not integration approval.

Read repository instructions, documentation authority map, and accepted ADRs `081226-a66b`, `082526-7f02`, `083126-5e62`. Reconciliation: preserve Goal -> Graph -> Run -> NodeRun -> Attempt and immutable admission provenance. An inactive contract leaf does not authorize a candidate-controlled quality waiver or a fake runtime caller. Production activation remains outside this issue's scope.

## Executed validation

Commands ran in the assigned worktree with 1200-second command timeouts.

| Command | Result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1323 reviewed identities/findings, zero unclassified; `repair-vulture.log`. No ledger amendment warranted. |
| `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py` | FAIL, exit 1: both admission modules have new unauthorized unreachable-module and disposition entries; `repair-provenance.log:20-29`. |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -rs` | 204 collected outcomes: 201 passed, 3 skipped in 1.32s; `repair-pytest.log`. Missing both PG DSNs caused skips at `test_admission_codec.py:470`. |
| `uv run ruff check .` | PASS. |
| `uv run ruff format --check .` | PASS: 3277 files already formatted. |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS: 2 source files. |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS; `repair-shipped-surface.log`. |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS: 16466 collected nodes, zero duplicate evidence; `repair-inventory.log`. |
| `git diff --check` | PASS before this report was written; checked again before commit. |

Driver `check-0.log` through `check-4.log` were inspected: sync, lint, format, focused tests and inventory passed, also with three PG skips. The supplied prior result was read, but its live-PG and mutation results are historical evidence, not executions in this round. No tests added or removed: no inventory-delta note is required.

## Acceptance audit

| Criterion | Evidence / limit |
| --- | --- |
| Frozen/slotted header, public signatures, six typed error codes, #1851 immutable constructors | Source inspected; focused codec and identity tests passed. Header immutability is source-verified, not separately mutation-tested this round. |
| Exact named SQL columns, fresh flat mappings, signed timestamps, strict UUID `.hex` at storage | Focused mapping/scalar/owner/generation cases passed. Bound mapping test independently asserts migration-055 `task_id == receipt_id` and paired `run_id`, rather than relying solely on encoder/decoder agreement. |
| Header-row mismatch rejected; malformed record preserves expiry/fingerprint; unknown formats fail closed | Focused mismatch, legacy-header and format cases passed. Decoder takes neither clock nor incoming fingerprint. |
| Legacy bound/unbound/partial/receipt-only evidence without guessing | Focused cases passed. Bound pair lacking receipt evidence fails partial instead of fabricating the receipt required by the canonical binding. Optional `completed_at` conveys no authority. |
| Strict TEXT JSON, duplicate/nonobject/bare nonfinite rejection, safe errors | Focused tests passed, including directly injected deep nesting, decimal precision loss, escaped surrogate and whitespace-corrupt identity cases. Messages omit private evidence and suppress parsing causes/context display. |
| Snapshot preservation and no fingerprint recalculation | Canonical snapshot bytes and hand-constructed nonfinite tags round-trip in passed tests; stored fingerprint is passed through. Arbitrary raw JSON formatting is canonicalized, not byte-preserved. |
| Existing evidence-json serialization, model_of/model_of_json materialization, arbitrary permitted program_context | UNVERIFIED: these tests use manually constructed tags and fixed fingerprints, not a production model round trip. No new materialization path exists in this leaf. |
| Raw and production asyncpg against one real migrated disposable database; session identity and final row counts | UNVERIFIED this round: all three PG cases skipped. No database created, migrations executed, session identities recorded or durability claim made. |
| Run JSONB is an object, authorized explicit principals/Workspace/Project/registered Graph | UNVERIFIED: DTO tests do not create or authorize a canonical Run. |
| No SQL/HTTP/queue/claim/assessment/scope/policy changes | Source inspection confirms representation-only leaf; this round changes only this report. Consumer expiry/409 precedence is not B2 behavior and is UNVERIFIED here. |
| Reachable production behavior, not test imports/exports | NOT satisfied: source import search finds codec -> identity plus the Vulture whitelist, no production consumer. Codec docstring explicitly acknowledges this at lines 51-54. |
| Focused tests, lint, format, scoped mypy, inventory | PASS with explicit PG skips above. No new pre-fix/mutation/crash/transaction proof claimed. |
| Unchanged full required integration CI, no gate workaround | BLOCKED by provenance; complete integration CI UNVERIFIED. No baseline/grant/gate workaround made. |
| Coordinated base/ownership and activation choices | External coordination and policy release UNVERIFIED. Repair assignment is not production activation permission. |

## Actual blocking evidence and next action

`quality/reachability-baseline.json:131,147` and `quality/reachability-dispositions.json:612-613` add the two admission modules. Required job `exact-debt-ledger` runs the failing provenance checker at `.github/workflows/vulture-ratchet.yml:77`. Trusted-base authorization must be resolved by the owning integration process before a subsequent coordinated sync; this worker cannot grant it. No merge conflict existed, so the conditional fetch/merge instruction did not apply.

The generic `test: failure` remains **UNRESOLVED**. Inspection of frozen dispatch check-run records found a failed `test` check for linked head `3f2c79a70d9e1b0b6b6ffc99562cb35db5326828`, not this assigned HEAD, with no diagnostic output. The linked `fcc8b437f209a35aa68a61d6f0a5387414938355` failure is `exact-debt-ledger`. These records cannot justify a guessed codec repair. `.github/workflows/ci.yml:574-612` partitions core tests out of the hosted `test` job, so focused success is not proof that job passes. Obtain the failing assigned-head step/node/traceback before changing unrelated code.

Progress: checked 1 issue; done 0 repairs; skipped 0 issues; errors 1 required gate. Next: owner-controlled trusted-base resolution and attributable CI failure evidence. No GitHub mutations, source activation or issue closure actions. Commit this report locally and leave the worktree clean.
