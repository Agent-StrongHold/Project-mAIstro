# Issue #1893 repair checkpoint — f5202349

## Frozen scope

- Assigned issue: #1893 only; worktree `/home/dev/Git/wt/auto-1893`.
- Starting HEAD: `fde6532b47b9f05e88da5f1321f23126dfecb7b0` (verified); clean worktree.
- Dispatch base: `3c761d14db944a727fa0744444bc67cfe36d49f7` (resolved).
- Inspect existing `admission_codec.py`, `admission_identity.py`, their two test files,
  repository instructions/relevant ADRs, CI workflows, supplied job logs/context,
  and the named vulture/provenance gates. Only this report and evidence-supported
  repairs to those implementation/test files are potential changes. No reachability
  baseline/disposition/grant changes are authorized.
- Ambiguity: dispatch says `test: failure` without a failing node. Treat this as
  a request to reproduce, not permission to invent a repair. The preceding worker's
  reachability authorization blocker must be independently checked.
- This is staged B2 work, not permission to introduce runtime activation or another
  execution authority. No remote mutation, branch sync, or issue closure is planned.

## Progress

Fresh validation reproduces the trusted-base reachability blocker. Vulture passes
with 1323 reviewed identities and 1323 findings; no ledger amendment is justified.
The focused test command returned 0; ruff, format, targeted mypy, inventory and
shipped-surface checks pass. No production or test changes are justified by the
supplied `test: failure` label alone.

## Executed validation

Commands ran with 1200-second timeouts against the unchanged source at the
starting HEAD. Driver `check-0.log` through `check-4.log` were also read; their
results are not substituted for these independent executions.

| Command | Result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS; 1323 identities; `/tmp/1893-f520-vulture.log` |
| `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py` | FAIL (exit 1); two unauthorized unreachable modules and two unauthorized dispositions; `/tmp/1893-f520-provenance.log` |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -r s` | 204 nodes: 201 passed, 3 skipped in 1.25s; `/tmp/1893-f520-focused.log` |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS; 3277 files |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS; 2 files |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS; 16466 nodes |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS |
| `rg -n 'admission_codec\|admission_identity' packages/*/src` | Only codec-to-identity and Vulture whitelist imports; no runtime consumer |
| `git diff --check` | PASS |

No new tests or inventory changes; existing inventory notes remain unchanged.
No new pre-fix or mutation claim is made.

## Acceptance audit

| Criterion | Evidence / limitation |
| --- | --- |
| Exact frozen/slotted header, interfaces, six decode codes, immutable #1851 constructors | Source inspection and focused contract tests pass. Header scalar validation and row/header mismatch tests pass. |
| Named columns, UUID .hex only at storage, signed timestamps, fresh flat SQL mapping | Storage/encode/scalar tests pass, including independent task_id/receipt_id binding assertions at `test_admission_codec.py:134-138`. |
| Legacy bound, unbound, partial, receipt-only and announced-without-Run | Focused legacy tests pass; source invents no identity. Existing interpretation requires receipt evidence for a canonical binding, otherwise partial. |
| Header/full-decode separation; preserve expiry/fingerprint on corrupt snapshots or partial bindings; unknown format fails closed | Named prospective tests pass. Inclusive expiry and changed-payload 409 decisions belong to C/F2 and are NOT proven by this B2 leaf. |
| Strict TEXT JSON, duplicates/nonobjects/nonfinite rejection, safe errors | Focused tests pass, including precision loss, recursion, surrogate and error-chain hygiene. |
| Preserve tagged evidence and fingerprint | Codec byte/tag preservation tests pass. Actual evidence encoder plus model_of/model_of_json materialization and original-model fingerprinting are UNVERIFIED: fixtures manually construct tags and fingerprints. |
| Real migrated disposable PostgreSQL, raw and production pool contrast | UNVERIFIED this round: 3 tests skipped for missing DSNs. No database durability, session identity or residue-count claim. No database provisioned after the independent required gate failure. |
| Run JSONB object, explicit authorized principals, Workspace/Project and registered Graph kinds | UNVERIFIED; DTO fixtures are not authorization or Run-insertion evidence. |
| No SQL mutation, HTTP mapping, queue/assessment/scope/policy changes, competing authority | Codec is mapping-only and has no production consumer; no source modifications this round. |
| Focused validation and inventory | Commands above pass except provenance; no inventory delta. |
| Unchanged full integration CI and no gate/grant workaround | BLOCKED by mandatory provenance gate. Full integration CI remains UNVERIFIED. |
| Coordination and activation | No integration/activation approval inferred; external ownership and policy prerequisites remain UNVERIFIED. |

Read accepted ADR-081226-a66b, ADR-082526-7f02 and ADR-083126-5e62.
Reconciliation: retain Goal → Graph → Run → NodeRun → Attempt and immutable
admission provenance. Candidate bookkeeping cannot authorize its own reachability
debt. The Vulture-only exception cannot authorize reachability grants or fake imports.

## Failure attribution and handoff

The frozen dispatch contains four captured `test` checks. The failure is at
`3f2c79a70d9e1b0b6b6ffc99562cb35db5326828`, with null summary/text; the checks at
`5d835338f7fa45b62d6361c9f3eddc5faf14284a`,
`fcc8b437f209a35aa68a61d6f0a5387414938355` and
`d0a03c8db5c49c4756a1dc231a7bdc31f731f105` succeeded. None is the assigned HEAD.
After two bounded inspections: **UNRESOLVED**, not evidence for a speculative
production repair. The actual assigned-head failing step/node/traceback is needed.
CI's `test` job excludes the core suite (`.github/workflows/ci.yml:574-612`), so
focused success is not a claim that the entire job passes.

The reproduced blocker is `quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:612-613`, enforced by
`.github/workflows/vulture-ratchet.yml:77`. An external trusted-base authorization
or separately authorized real consumer integration is required. Neither is allowed
in this B2 repair. No grant, ledger, whitelist, gate, production or test edits made;
existing work preserved. No conflict exists and no fetch/merge is justified.

Only changed file: this report, committed locally as a blocked handoff. No GitHub
mutations. Do not repeat unchanged repair rounds without the external prerequisite
and assigned-head CI failure evidence.

Progress: checked 1; done 0 repairs; skipped 0 issues; errors 1 required gate;
next: supply authorized integration base and actual failing CI evidence.
Verdict: **BLOCKED**.
