# Issue #1893 — bounded repair evidence (job 7db542ad)

## Snapshot and disposition

- Assigned worktree/branch: `/home/dev/Git/wt/auto-1893`, `auto-1893`.
- Verified clean starting HEAD: `cbae5a6c7a1e499083d9cdc55cab382b5a8612fa`.
- Verified supplied base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- One item: #1893, reported `test` and exact-debt-ledger failures. No remote
  refresh, GitHub mutation, production activation or ownership change.
- Inputs: supplied dispatch snapshot, check-0 through check-4 logs, prior
  result artifact. Prior verification claims were not counted as new evidence.
- Candidate source scope: admission codec, immutable identity constructors,
  adjacent tests; Vulture ledger only if an actual scan warranted amendment.
  No source, test, inventory, ledger, whitelist or gate changes were warranted.
  This report is the only repository change.

**BLOCKED:** the independently executed provenance gate still rejects the two
new admission modules and their dispositions. The explicit Vulture-ledger
exception does not authorize reachability grants or consumer activation.
No merge conflict exists. A speculative develop merge is not a repair for
missing trusted-base authorization.

Read repository instructions, codec and adjacent tests, identity constructors,
exact-debt-ledger workflow and accepted ADRs 081226-a66b, 082526-7f02 and
083126-5e62. Reconciliation: preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`,
immutable admission provenance and protected-base quality authority. Test
imports and DTO construction are not production admission or authorization.

## Executed validation

Commands ran against the unchanged starting source with 1200/1800-second
validation timeouts. Logs live under job directory
`/home/dev/maistro/jobs/7db542ad36c24de99418ff18a30ec8de/`.

| Command | Result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1323 reviewed identities / 1323 findings; `worker-vulture.log` |
| `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py` | FAIL, exit 1: two unauthorized unreachable modules and two unauthorized dispositions; `worker-provenance.log` |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -r s` | 204 nodes: 201 passed, 3 PostgreSQL skips, 1.29s |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS: 3277 files |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS: two source files |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS: 16467 nodes, no duplicate evidence |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS |

Focused results are recorded in `worker-focused.log`. No tests added; no
inventory delta or new pre-fix/mutation evidence claimed.

Production import search finds only codec-to-DTO and Vulture-whitelist imports.
`admission_codec.py:50-53` explicitly documents the absent production consumer.
The failing entries are `quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:612-613`; the required gate runs at
`.github/workflows/vulture-ratchet.yml:77`.

The captured failed `test` check is qualified by head
`3f2c79a70d9e1b0b6b6ffc99562cb35db5326828`, not this assigned HEAD, and its output
summary/text are null. Captured failed-check extraction is recorded in
`worker-captured-failures.json`. Attribution of the generic reported failure to
this candidate remains **UNRESOLVED**; no guessed scanner or cosmetic repair.

## Acceptance audit

- Required frozen/slotted header, interfaces, enum/error contracts, strict
  `.hex` UUID and signed timestamps: inspected and focused tests pass.
- Named-column mapping and fresh flat encoding; binding columns emitted
  together from existing receipt/Run identity: tests pass, including independent
  SQL-shape assertions at `test_admission_codec.py:134-137`.
- Legacy bound/unbound/partial, receipt-only and announced-without-Run evidence:
  tests pass; no inferred identity. A bound pair without receipt evidence stays
  partial rather than fabricating a canonical binding.
- Header/full-decode separation, preserved scalar expiry/fingerprint across
  corrupt snapshot/partial binding, mismatched header and unknown-format
  rejection: tests pass. Clock, replacement and HTTP 409 decisions belong to
  the later consumer, not B2.
- Strict TEXT JSON and duplicate/nonobject/bare nonfinite rejection, safe
  suppressed parsing chains, numeric and Unicode corruption: tests pass.
- Canonical snapshot bytes/tags and stored fingerprint preservation: tests pass.
  Original-model fingerprinting, actual `encode_evidence` and
  `model_of`/`model_of_json` materialization end-to-end are **UNVERIFIED**;
  handwritten tags and synthetic DTO fixtures do not establish these paths.
- Real migrated PostgreSQL raw/production pool contrast: **UNVERIFIED this
  round**. Three tests skip at `test_admission_codec.py:470` because both DSNs
  are absent. After reproducing the independent mandatory blocker, no DB was
  provisioned. No session, final row-count, durability or migration claim.
- Run JSONB object insertion, real authorized principals/Workspace/Project and
  registered Graph admission: **UNVERIFIED**; no runtime consumer reaches this
  codec, and the fixtures do not prove authorization.
- No SQL mutation, HTTP mapping, queue, scope utility, live assessment, policy
  or competing execution authority introduced: source remains unchanged.
- Focused lint/type/inventory validation: passes above. Full unchanged
  integration CI and coordination/activation prerequisites: **UNVERIFIED**;
  independent mergeability is blocked by the reproduced mandatory gate.

## Handoff

The next action requires an authorized integration owner: supply a trusted base
with the separately approved reachability authorization, or separately reviewed
consumer integration consistent with #1845. This lane must not manufacture that
permission. Supply a candidate-qualified failing node/traceback to justify any
additional `test` repair. Do not repeat this identical repair dispatch without
one of those new inputs.

Progress: checked 1; repaired 0; skipped 0 issues; blocked 1; mandatory gate
errors 1. Commit this evidence locally; no push, merge or issue closure.
