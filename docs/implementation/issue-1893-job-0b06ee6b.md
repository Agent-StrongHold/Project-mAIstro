# Issue #1893 repair checkpoint — job 0b06ee6b

## Frozen scope

- Issue #1893 only; assigned worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Starting HEAD `b984d26799c4660e3720b0e82a8a93ac9c342e2b`; dispatch base `ac7370141e8e61bd6f352bca35ed0b505104aadb`.
- Starting worktree clean; no salvage required.
- Inspect existing admission codec, identity DTOs, their tests, relevant ADRs and CI gate configuration. No new activation, policy, or ledger authorization.
- Candidate edit scope: this report; implementation/test changes only if executed evidence identifies an in-scope defect (with inventory note for new tests). Vulture ledger edits only if the mandated exact scan identifies retained unbanked identities.

## Initial evidence and ambiguity

Read the supplied dispatch issue body and prior result artifact. Driver check-0 through check-4 logs report dependency sync, ruff, formatting and inventory success; focused tests: 346 passed, 3 skipped. These logs do not prove real PostgreSQL behavior or reproduce the unspecified hosted `test: failure`.

The previous result reports unauthorized reachability entries. Assumption: re-execute the exact current gate against a resolved local base; do not create an authorization or activate this explicitly staged codec to bypass the gate. No develop-sync conflict has been supplied or exists in the initial clean worktree. No remote enumeration or GitHub mutation will be performed.

## Results

Fresh exact Vulture scan passes: 1322 findings, zero unclassified; no ledger change justified. Local `origin/develop` and merge base resolve to the supplied base. `RATCHET_BASE_REV=ac7370141e8e61bd6f352bca35ed0b505104aadb uv run python scripts/check-ratchet-provenance.py` exits 1: both admission modules are new unauthorized unreachable modules and new unauthorized dispositions. Other aggregate provenance subchecks pass. This is an actual blocker, not a missing dependency or guessed scanner finding. No authorized local repair can create the missing trusted-base grant.

## Focused validation

Executed against the starting source SHA plus this report only, with 600-second timeouts:

| Command | Outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1322 reviewed findings; no unbanked identities. |
| `RATCHET_BASE_REV=ac7370141e8e61bd6f352bca35ed0b505104aadb uv run python scripts/check-ratchet-provenance.py` | FAIL, exit 1: two unauthorized unreachable modules and two unauthorized dispositions. |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/extensions/test_cli_lock.py packages/maistro-core/tests/extensions/test_pack_contracts.py -x -q -rs` | 349 cases: 346 passed, 3 skipped in 2.87s. All skips at codec test line 470 require both PostgreSQL DSNs. |
| `uv run ruff check .` | PASS. |
| `uv run ruff format --check .` | PASS, 3301 files. |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS, two source files. |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS. |
| `rg -n 'admission_codec\u007cadmission_identity' packages/*/src --glob '*.py'` | No production codec consumer; codec imports identity, whitelist imports identity. |

Driver inventory check-4 independently reports 16567 unique core test identities and no duplicates. No tests added or modified this round; inventory delta is zero, so no new inventory-delta note is needed. No new mutation/pre-fix failure is claimed: no implementation defect was reproduced or patched. The generic hosted `test: failure` remains UNRESOLVED, not disproven by focused success.

## Acceptance audit and architecture reconciliation

Read repository AGENTS.md, accepted ADR-081226-a66b, ADR-082826-b601 and ADR-083126-5e62, the captured issue body, complete codec and identity constructors, adjacent codec tests and exact-debt-ledger workflow. Preserve Goal → Graph → Run → NodeRun → Attempt. Canonical consumer eligibility is explicit; manufacturing an import or execution path solely to pass reachability would violate both stage constraints and canonical ownership. The explicit Vulture exception does not authorize reachability ledger/grant edits.

| Criterion | Current executed evidence / limit |
| --- | --- |
| Frozen/slotted header, exact interfaces, immutable DTO construction, fresh flat SQL parameters | Focused header/round-trip/fresh-mapping and identity tests pass; source definitions inspected. Physical `request` TEXT maps to `request_snapshot` DTO field. |
| Strict UUID `.hex`, signed scalar timestamps, header-row agreement, named columns | Focused owner-token, generation, scalar-header, schema and mismatch cases pass. No ordinal row access in codec. |
| Six typed error codes, validated scope hash only, safe snapshot/token diagnostics | Focused invalid snapshot/header/v2, Unicode, numeric-loss, nesting and partial legacy cases pass; parse failures suppress unsafe chains. |
| Legacy bound, unbound, partial, receipt-only and completed-at evidence without guessing identity | Named legacy tests pass. A task/run pair lacking receipt evidence is rejected, because the prerequisite binding constructor requires a receipt identity and none may be fabricated. |
| Header preserves expiry and fingerprint even if full decode fails; unknown formats fail closed | Both named header-separation tests and unknown-format cases pass. Decoder accepts no clock or incoming fingerprint; replacement/409 behavior belongs to C/F2, not B2. |
| Reject duplicate/nonobject/bare nonfinite JSON; preserve permitted context/tagged evidence without changing stored fingerprint | Pure snapshot and corruption cases pass, including canonical fixture bytes. Arbitrary noncanonical input bytes normalize; these tests do not prove unchanged original byte formatting. |
| Existing evidence-json serialization, model_of/model_of_json materialization and fingerprint before tagging | UNVERIFIED as a production path: fixtures supply tagged snapshots and stored fingerprint, and no production codec consumer exists (`admission_codec.py:50-53`). |
| Real migrated disposable PostgreSQL; raw and production pool contrast; session identities and final row counts | UNVERIFIED this round: all three DB legs skipped for missing DSNs. No DB setup, migration or SQL command executed; historical PG claims are not current proof. |
| Run payload stored as JSONB object; explicit authorized principals, Workspace/Project and registered Graph | UNVERIFIED: synthetic codec fixtures are not production admission or Run INSERT evidence. |
| No SQL mutation, HTTP/queue/claim/assessment/scope/policy or activation changes | Codec remains pure row/DTO conversion. This round changes only this report; no competing execution or authorization authority introduced. |
| Focused tests, Ruff, format, applicable mypy and truthful inventory | Executed checks above pass with PostgreSQL skips explicitly disclosed; zero test delta. |
| Unchanged full required CI and reachability/disposition/promotion gates | Full CI UNVERIFIED. Actual required aggregate provenance fails; promotion subcheck and exact Vulture pass. No gate, ledger or grant modified. |

## Blocked handoff

Disposition: **BLOCKED**, not merge-ready. The concrete gate errors refer to `quality/reachability-baseline.json:131,147` and `quality/reachability-dispositions.json:612-613`, enforced by `.github/workflows/vulture-ratchet.yml:77`. There is no supplied develop-sync conflict to resolve, and the local develop/base refs are identical. No fetch, merge, push, GitHub mutation, destructive git operation or background command was performed.

Only changed file this round: `docs/implementation/issue-1893-job-0b06ee6b.md`. Existing source/tests and all prior work preserved. Commit this evidence locally as required; no speculative/cosmetic repair is offered as a fix for the CI failure.

Next owner action: resolve the trusted-base reachability prerequisite through the coordinated authorization/integration process, then provide the actual hosted failing test step, source SHA and traceback. Re-dispatching the same head/base with only `test: failure` cannot resolve that prerequisite. Live PostgreSQL, production materialization/admission evidence and full integration CI remain outstanding.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 1, next: trusted-base prerequisite and concrete hosted test evidence}`.
