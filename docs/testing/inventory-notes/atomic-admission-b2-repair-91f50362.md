---
inventory-delta:
  packages/maistro-core/tests: +0
---

# #1893 CI repair verification (91f50362)

Frozen scope: issue #1893 only; admission_codec.py, its existing tests,
admission_identity.py and adjacent tests as read-only dependencies, existing B2
inventory evidence, and the reported test/exact-debt-ledger checks. This note is
the only planned edit unless an executed check demonstrates a scoped defect.
No new tests or inventory count changes are planned.

Starting head: 70892d81d3d43d0b64788eb2bce68e74475807bd.
Supplied base: 3c761d14db944a727fa0744444bc67cfe36d49f7.
Worktree was clean. Supplied check-0 through check-4 logs report dependency sync,
ruff lint/format, 201 passed / 3 skipped, and suite inventory passing. These are
driver results, not independent database verification.

Initial ambiguity: the first base-to-head diff command displayed no file names.
Resolved by explicit `git --no-pager diff --stat <supplied-base> HEAD`: the
starting branch has 114 changed files, including both admission modules and
reachability accounting. The merge base is the supplied base. Historical
findings were rechecked rather than treated as permission to change ledgers or
activate admission. No develop sync conflict is present.

Independent result: the named vulture scan passed (1323 findings, none
unclassified). No ledger amendment is justified. With RATCHET_BASE_REV set to
the supplied exact base, check-ratchet-provenance.py exited 1: both admission
modules are NEW unreachable modules and NEW dispositions without trusted-base
authorization. origin/develop resolves to the supplied base; the merge base is
also that exact SHA. This is not a sync conflict. The vulture-only exception
does not authorize reachability ledger/grant edits, and B2 forbids activating
the C consumer. This blocker requires coordination outside this writer lane.
Focused independent checks (1200-second timeout) at the starting source SHA:

- `uv run pytest packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/tasks/test_admission_codec.py -x -q -rs`: 201 passed, 3 skipped in 1.45s (204 nodes). All three skips require both PostgreSQL DSNs at test_admission_codec.py:470. No database durability proof is claimed.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 3277 files.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`: passed, 2 files.

No scoped code failure reproduced; no pre-fix or mutation result claimed.
The first inventory run rejected this new note's inline empty delta mapping;
changed it to the required indented suite `+0` block. No gate was changed.

Read accepted ADR-081226-69ee (canonical execution), ADR-082526-7f02
(immutable admission provenance), and ADR-083126-5e62 (trusted-base authority).
Reconciliation: neither staged inactive implementation nor candidate ledger
accounting overrides trusted-base authorization. No alternate scheduler,
authorization path, or production activation is introduced.

Frozen dispatch check-run inspection independently confirms the only failed
`test` check belongs to #1855 head 3f2c79a70d9e1b0b6b6ffc99562cb35db5326828.
For #1945 head fcc8b437f209a35aa68a61d6f0a5387414938355, `test` succeeds and
`exact-debt-ledger` fails. Their output summary/text fields are null.
UNRESOLVED: no assigned-head failed test node or traceback is supplied.
Assumption: do not guess a runtime repair from an unattributed failure label.

Production-source import search finds only codec-to-identity and Vulture
whitelist imports. Tests and exports are not production reachability; this
round does not claim the codec is reached by ordinary admission.

Additional independent checks (all passed, 1200-second timeout):

- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: 16466 nodes, zero duplicate evidence; corrected note accepted.
- `uv run python scripts/check-reachability.py`: 1396 production modules, 171 unreachable, candidate accounting passes.
- `uv run python scripts/check-reachability-dispositions.py`: 50 groups cover 171 modules.
- `uv run python scripts/check-shipped-surface-truth.py`: complete.
- `uv run python scripts/check-promotion-surface.py`: 74 tolerated modules, passed.

## Acceptance review and handoff

The 201 passing tests are DTO/codec evidence, not an activated admission path.
Source and existing test inspection support these boundaries:

| Criterion | Executed evidence or limitation |
| --- | --- |
| Shared interfaces, frozen/slotted header, six error codes, named columns | Source inspected; header/schema/format/mismatch contract tests passed. |
| Strict UUID hex, signed scalar timestamps, immutable #1851 construction | Owner/generation/scalar and identity tests passed. |
| Fresh flat SQL mapping and bound task/Run identities | Round-trip tests passed in three states, including independent task_id = receipt_id assertions at test_admission_codec.py:134-137; live SQL CHECK proof UNVERIFIED this round. |
| Exact legacy bound/unbound/partial and receipt-only evidence without identity invention | Legacy tests passed. A pair without receipt evidence is partial because the binding DTO needs a receipt; no receipt is fabricated. completed_at grants no authority. |
| Header/full-decode separation and unknown-format fail-closed behavior | Named expiry/fingerprint/header and format tests passed; codec takes no clock or incoming fingerprint. Consumer replacement/409 precedence is outside B2 and UNVERIFIED. |
| JSON duplicate/nonobject/bare nonfinite rejection; safe errors and validated scope | Existing corruption, nesting, decimal-loss and Unicode boundary tests passed, with valid controls; source suppresses unsafe exception display chains. |
| Tagged nonfinite snapshots and fingerprint preservation | Tagged-fixture round trips passed; actual evidence-json producer and model_of/model_of_json materialization are UNVERIFIED. |
| Both raw and production pools, migrated disposable DB and same-DB DSNs | UNVERIFIED: three skips, no session or SQL residue counts claimed. No DB was provisioned after the governance blocker reproduced. |
| JSONB Run object, real explicit principals, authorized Workspace/Project, registered Graph kind | UNVERIFIED: codec fixtures neither insert Runs nor perform admission authorization. |
| No mutation, HTTP mapping, queue/scope utility/live assessor or policy changes | Pure codec source inspected; this round changes this note only. No runtime activation or alternate execution authority. |
| Focused tests, lint, format, mypy and inventory | Passed as listed above; no tests added, inventory delta zero. |
| Unchanged required integration gates | Provenance FAILS; other named gates pass. Full required CI and the unattributed test failure remain UNVERIFIED. No ledger/grant/gate edits. |

**BLOCKED**, not merge-ready. Required next input: separately reviewed trusted-base
resolution of the two unreachable-module/disposition authorizations, or authorized
real consumer integration; plus assigned-head failed-test evidence if that label
remains. The vulture-only repair permission cannot satisfy this requirement.
No GitHub mutation, merge, push, issue closure, or destructive git action.
This evidence-only commit does not claim a runtime repair or integration approval.

Progress: checked 1, done 0, skipped 0, errors 1 (provenance blocker); next:
external coordination on trusted-base authority and attributable test failure.
