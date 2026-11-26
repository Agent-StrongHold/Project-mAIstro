# Issue #1893 — bounded repair recheck bc3f86a5

## Frozen scope and initial evidence

- Assigned worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Confirmed clean starting HEAD `a542df770843ce015c6e50fa9c37c9026e712a4e`; supplied base `ac7370141e8e61bd6f352bca35ed0b505104aadb`.
- Only issue #1893. Inspect existing admission codec/identity implementation, adjacent tests, accepted ADRs, and required gates. Candidate edits: this handoff; the existing two admission modules/tests only upon a reproduced in-scope defect, with inventory note if tests change. Vulture ledger only upon unbanked retained identities from the required exact scan. No other ledger/grant edits or production activation.
- Read supplied check-0 through check-4 logs: sync/lint/format/inventory pass; focused tests 346 passed, 3 skipped. These are driver results, not fresh proof of PostgreSQL or the reported hosted test failure.
- Read captured issue body and previous checkpoint. The issue forbids production activation and adding baseline/grant entries to green an unwired slice. Previous attempts report a reachability provenance blocker; this needs fresh execution, not another speculative repair.
- Ambiguity: dispatch provides only `test: failure`, without a traceback. Inspect the captured check-run output once; if absent, leave hosted failure UNRESOLVED. An initial extraction assumed a check-run object but encountered a list (AttributeError); no repository change resulted.
- No supplied or local merge conflict. Do not fetch/re-enumerate already captured scope or change ownership to bypass the blocker.

## Results

Fresh validation resolves both local `origin/develop` and the HEAD/base merge-base to the supplied `ac7370141e8e61bd6f352bca35ed0b505104aadb`. No sync conflict is present.

- Exact Vulture scan: PASS, 1322 findings, zero unclassified. No ledger amendment is justified.
- `RATCHET_BASE_REV=ac7370141e8e61bd6f352bca35ed0b505104aadb uv run python scripts/check-ratchet-provenance.py`: FAIL (exit 1). Both `maistro.runs.admission_identity` and `maistro.tasks.admission_codec` are new unreachable modules absent from the trusted base, and both have unauthorized new dispositions. Other aggregate subchecks passed.
- Read accepted ADR-081226-a66b, ADR-082826-b601 and ADR-083126-5e62; complete codec, identity constructors and adjacent tests. The codec explicitly has no production consumer. Eligibility cannot be inferred, and candidate ledger entries cannot authorize themselves. Preserve the canonical execution hierarchy and the staged activation boundary; no manufactured runtime call or new authorization is an acceptable repair.

This reproduces the prerequisite blocker independently. No source/test/ledger changes are warranted by this evidence. Remaining focused checks and acceptance limits are recorded below.

## Focused execution

Executed at starting source HEAD plus this report only, with 900-second validation timeouts:

| Command | Result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1322 findings, zero unclassified. |
| `RATCHET_BASE_REV=ac7370141e8e61bd6f352bca35ed0b505104aadb uv run python scripts/check-ratchet-provenance.py` | FAIL: the four reachability/disposition violations above. |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/extensions/test_cli_lock.py packages/maistro-core/tests/extensions/test_pack_contracts.py -x -q -rs` | 349 cases: 346 passed, 3 skipped in 2.88 seconds. Skips require both PostgreSQL DSNs at codec test line 470. |
| `uv run ruff check .` | PASS. |
| `uv run ruff format --check .` | PASS: 3301 files. |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS: two source files. |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS. |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS: 16567 collected unique identities, no duplicate evidence. |
| Source import search with `rg -n` for both admission modules under `packages/*/src` | Only codec-to-identity import and Vulture whitelist reference; no production consumer. |

Captured dispatch evidence adds a useful distinction: PR #1945 check runs at `80171ce1cff9ca45eaf000bf52569875643a5ba0` report **test success** (check-run 117010602704) and **exact-debt-ledger failure** (117010602424). Neither contains summary/text with a failing-test traceback. This does not prove a different merge-queue candidate passed: the generic dispatched `test: failure` remains UNRESOLVED for lack of its exact failing SHA/step/traceback. No further remote enumeration was performed.

## Acceptance audit

| Criterion | Evidence and limit |
| --- | --- |
| Exact immutable header/DTO interfaces, named fields, fresh flat encode mapping | Definitions inspected; focused round-trip, schema, mismatch, identity and fresh-mapping tests pass. Header is frozen/slotted. `request` TEXT maps to `request_snapshot`. |
| UUID storage `.hex`, signed scalar timestamps, matching header | Owner/generation, invalid scalar and header mismatch tests pass. |
| Six decode codes and safe error diagnostics | Enum inspected; typed invalid-header/snapshot/v2/schema/format/partial tests pass, including suppressed unsafe chains and validated-hash scope. |
| Legacy bound/unbound/partial evidence without invented identity | Distinction, receipt-only, missing receipt, whitespace, expired-header and ignored-completed-at cases pass. Prerequisite binding requires a receipt ID: a task/run pair without receipt evidence fails rather than inventing a receipt. |
| Header preserves expiry/fingerprint when full decode fails; unknown formats fail closed | Both named separation tests and unknown-format cases pass. No clock, incoming fingerprint or assessment is accepted by the codec. Replacement/409 precedence remains C/F2 responsibility. |
| Canonical snapshot bytes, invalid/duplicate/nonobject/bare nonfinite rejection, arbitrary permitted context | Canonical fixture round-trip, tagged nonfinite, numeric-loss, nesting and Unicode tests pass. Arbitrary noncanonical bytes normalize by the prerequisite DTO contract; unchanged original formatting is not claimed. |
| Existing evidence-json/model_of materialization and fingerprint-before-tagging | UNVERIFIED as production behavior: fixtures supply tagged data and a stored fingerprint, and no production codec consumer exists. Pure tests prove no fingerprint recalculation, not the originating model pipeline. |
| Real migrated disposable PostgreSQL and raw/production pool contrast | UNVERIFIED this round: all three DB cases skipped, no DSNs configured. No new migration, session-identity or final-row-count evidence. Historical live claims are not counted. |
| Run INSERT JSONB object, explicit authorized principals/Workspace/Project and registered Graph | UNVERIFIED: codec DTO fixtures and direct table INSERT tests are not real authorized admission or Run materialization. |
| No mutation, scheduler, HTTP, queue, policy or premature activation change | Source remains conversion-only and this round changes documentation only. Canonical Goal → Graph → Run → NodeRun → Attempt authority is untouched. |
| Truthful inventory and focused validation | Commands above pass except required aggregate provenance; no tests changed, inventory delta zero, no new inventory note required. |
| Unchanged required full integration CI and debt gates | Full integration CI UNVERIFIED. Required trusted-base reachability/disposition gate actually FAILS; Vulture, promotion subcheck and shipped-surface checks pass. |

No implementation defect was reproduced or patched, so no new pre-fix/mutation-test claim is made. Creating tests merely to repeat this blocker or modifying policy would not repair the reported failure.

## Blocked handoff

Only changed file this round: `docs/implementation/issue-1893-job-bc3f86a5.md`. Preserve all existing source, tests and ledgers. Commit this handoff locally; do not mistake it for a functional repair or merge approval.

Concrete blocker: `quality/reachability-baseline.json:131,147` and `quality/reachability-dispositions.json:612-613`, enforced by `.github/workflows/vulture-ratchet.yml:77`. The permitted Vulture exception does not authorize reachability policy changes. Re-dispatching the same base without resolving this prerequisite cannot fix it. The integration owner must resolve the staged-code/trusted-base prerequisite through the approved coordination process (not candidate self-authorization), and supply the actual merge-queue failing-test SHA, step and traceback if it still fails. Production activation remains separately blocked.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 1, next: coordinated trusted-base prerequisite and exact failing-test evidence}`. No push, merge, GitHub mutation, destructive git operation or background command was performed.
