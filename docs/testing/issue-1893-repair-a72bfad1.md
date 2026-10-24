# Issue #1893 repair — a72bfad1

## Frozen scope and initial evidence

- Sole item: issue #1893, assigned worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Starting HEAD: `b047b144fb7976817d210081bebbfc7d33901738`; supplied develop base: `ac7370141e8e61bd6f352bca35ed0b505104aadb`. Initial worktree clean.
- Inspect only admission codec/identity implementations, their focused tests, adjacent persistence/evidence serialization, relevant ADRs and CI gate definitions. Candidate change file is this report; production/test changes only if those checks identify an in-scope defect. No unrelated repair or GitHub mutation.
- Read supplied issue body and prior result from dispatch snapshot and job `6c87f7509a35467b8ba1abb334076c64`. Earlier execution claims are not current validation.
- Driver check logs inspected: dependency sync, ruff check, format and suite inventory passed; focused tests 346 passed, 3 skipped. These are driver results, not independent execution or PostgreSQL proof.
- Ambiguity: hosted `test: failure` is supplied without a failing node/traceback. Proceed by checking focused acceptance and exact named gates, not guessing an unrelated repair.
- Ownership assumption: the lane assignment authorizes local repair/validation on this exact branch, not production activation or new ownership of the coordinated stack.

## Independent validation

- Exact Vulture command `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1322 reviewed identities / findings, zero unclassified. No Vulture ledger amendment warranted.
- `git rev-parse --verify origin/develop`: resolves to the supplied base. No develop-sync conflict exists.
- `RATCHET_BASE_REV=ac7370141e8e61bd6f352bca35ed0b505104aadb uv run python scripts/check-ratchet-provenance.py`: FAIL (exit 1), four authorization violations: two new unreachable modules and two new dispositions for `maistro.runs.admission_identity` / `maistro.tasks.admission_codec`. The required workflow invokes this checker at `.github/workflows/vulture-ratchet.yml:77`.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3301 files.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`: PASS, two files.
- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -rs`: 204 nodes, 201 passed, 3 skipped. PG pool tests skip for missing DSN/database URL; not durability evidence.
- Production-source import search finds only the codec importing the identity module and the Vulture whitelist importing its enum. No production codec consumer exists.

Commands used 600–1800 second timeouts. Read both implementation files and both focused test files completely. Read accepted ADRs 081226-69ee, 082826-b601 and 083126-5e62. Reconciliation: preserve canonical execution and explicit opt-in consumption; do not fabricate a caller to pass reachability. Candidate quality evidence cannot authorize itself. The Vulture-repair exception does not permit reachability authorization edits.

Confirmed blocker is unchanged source/policy state, not guessed dead code. No source, test, gate, authorization or ledger changes made.

Additional focused validation:

- `uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs -x -q`: 2229 nodes, 1919 passed, 310 skipped, five aiosqlite closed-event-loop thread warnings. No reproduced test failure; warnings do not establish the cause of the hosted failure.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: PASS, 16567 nodes, zero duplicate evidence.
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- `git diff --check`: PASS.

## Acceptance audit

| Criterion | Current evidence |
| --- | --- |
| Frozen/slotted header; named columns, strict UUID hex, signed timestamps; exact public interfaces | Source inspection and passing focused scalar/UUID/schema/immutability tests |
| Header rejects scalar mismatch and survives invalid snapshot/partial binding | Passing mismatch, expiry-preservation and fingerprint-preservation tests; no clock or request fingerprint input |
| V2 snapshots, binding and fresh flat mapping | Passing three-state round trips and independent task_id/run_id storage-shape assertions at test_admission_codec.py:134-137; DTO checks receipt identity equality |
| Legacy bound/unresolved/partial distinctions without invented identity | Passing both/neither/partial pair, receipt-only, missing receipt, whitespace evidence and ignored completed_at tests; no guessed receipt when a legacy pair lacks one |
| Six typed decode errors, validated scope only, safe error messages/chains | Passing corrupt snapshot, token, numeric loss, deep nesting and Unicode tests; source uses suppressed chains |
| Strict TEXT object JSON, no duplicate keys or bare nonfinite values; preserve tags/fingerprint | Passing JSON rejection and tagged nonfinite tests; corrupt storage strings injected directly, not transaction mocks |
| Existing evidence-json/model_of materialization, original-model fingerprinting and arbitrary permitted program_context | UNVERIFIED end-to-end: tests preserve synthetic tags and fixed fingerprints, not production model admission |
| Real migrated disposable PG, both pools reading TEXT; actual Run JSONB object and SQL row/session counts | UNVERIFIED: three PG tests skipped; no database setup pursued after the independent authorization blocker. No SQLite/fake durability claim |
| Explicit authorized principals, Workspace/Project and registered Graph kinds | UNVERIFIED production admission: synthetic DTO strings do not prove authorization |
| No mutation, HTTP/queue mapping, new classifier, scope utility or policy change | Source inspection: codec converts mappings/DTOs only. This round changes only this report. Consumer replacement/409 precedence remains outside B2 |
| Inventory/lint/format/types and integration gates | Focused commands above pass; provenance fails. Full integration CI and standalone promotion/disposition/reachability commands UNVERIFIED; provenance's promotion subcheck passes |
| Staged coordination and runtime reachability | Assigned head/base verified; no production caller. No activation or independent merge approval claimed |

No tests added or changed; inventory delta is zero and no inventory-note addition is needed. No new pre-fix/mutation experiment is claimed.

## Final handoff

**BLOCKED.** `quality/reachability-baseline.json:131,147` and `quality/reachability-dispositions.json:606-613` require trusted-base authorization that this lane cannot supply. Vulture is already exact. No sync conflict exists. Do not re-dispatch this unchanged state as a Vulture repair: it cannot resolve a reachability authorization dependency.

Hosted `test: failure` remains **UNRESOLVED** without the actual command, tested SHA and failing traceback. Focused and adjacent runs do not reproduce it. Need that evidence before making a code repair. Full CI, PostgreSQL and production integration remain unverified.

Changed file: only `docs/testing/issue-1893-repair-a72bfad1.md`; commit is an evidence handoff, not a source fix. No GitHub mutations, protected-ledger edits, gate changes or activation.

Progress: checked 1, done 0 repairs, skipped 0 items, errors/blockers 1. Next: integration owner resolves the trusted-base authorization dependency outside this lane and provides the hosted test failure evidence.
