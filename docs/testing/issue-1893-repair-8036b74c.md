# Issue #1893 repair — 8036b74c

## Frozen scope and initial evidence

- Writer worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`; clean starting source `a4d58d9e0d0c7fbcb43577cacbd40aea8052faed`.
- Assigned base `3c761d14db944a727fa0744444bc67cfe36d49f7`; one issue only. Preserve existing implementation; no activation, GitHub mutations, reachability/grant/gate edits, or speculative scanner fixes.
- Read supplied issue body and driver `check-0.log` through `check-4.log`: dependency sync, lint, format and suite inventory passed; focused tests reported 201 passed, 3 skipped. These skips are not durability evidence. Prior result is historical, not fresh verification.
- Read accepted ADR-081226-a66b, ADR-082526-7f02 and ADR-083126-5e62. Preserve canonical execution hierarchy and immutable admission provenance. Candidate debt bookkeeping cannot authorize itself. The explicit Vulture repair exception does not authorize reachability changes.
- Codec source explicitly documents no production consumer (`admission_codec.py:49-52`). Typed representation readiness is not reachable admission/authorization or integration readiness. Do not add fake callers to evade gates.

## Reproduced blocker

The assigned base resolves and is already the merge base with HEAD; no sync conflict is present. Fresh exact CI Vulture scan passed (1323 reviewed identities, zero unclassified). Fresh `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py` failed, exit 1: both admission modules are NEW unauthorized unreachable modules and NEW unauthorized dispositions (169 trusted versus 171 candidate). Logs: `worker-vulture.log` and `worker-provenance.log` in job `/home/dev/maistro/jobs/8036b74c94e149b583f4aeeefc24f6c0`.

No Vulture ledger change is justified. Reachability authorization must come from the trusted base under the two-merge rule, not this candidate. No source defect has been established; no activation or policy workaround was attempted.

## Executed validation

All worker validation used `uv run`, unchanged source at the starting SHA, and 1200-second timeouts. Exact argv and exit codes are in `worker-checks.json`; individual outputs are `worker-<name>.log` in the job directory.

| Command | Outcome |
| --- | --- |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -rs` | 204 nodes: 201 passed, 3 skipped (missing PostgreSQL DSNs), 1.27s |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS |
| `uv run python scripts/check-reachability.py` | PASS against candidate ledger only |
| `uv run python scripts/check-reachability-dispositions.py` | PASS against candidate ledger only |
| `uv run python scripts/check-promotion-surface.py` | PASS |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1323 exact identities |
| `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py` | FAIL, exit 1, two modules plus two dispositions |

## Acceptance review

Read codec, identity constructors and both focused test files. Passing evidence below is representation-level only, not live service behavior.

| Criterion | Fresh evidence / limitation |
| --- | --- |
| Frozen/slotted header, named columns, exact flat v2 mappings | Source inspection and focused round-trip/fresh-mapping tests PASS. Independent task_id/run_id assertions at test_admission_codec.py:134-137 avoid relying solely on encoder/decoder agreement. |
| Immutable snapshot bytes and original fingerprint | Three in-memory state round trips and tagged nonfinite tests PASS; fingerprints copied, not recalculated. |
| UUID .hex at storage only; safe typed errors and validated scope | Owner-token, strict UUID, header/schema and error-hygiene tests PASS. Parsing errors suppress unsafe displayed chains. |
| Signed timestamps; supplied header must match scalar row fields | Scalar range/type, timestamp inversion and header mismatch tests PASS. Header is scalar-only, takes no clock. |
| Legacy bound/unbound/partial remain distinct; no invented identity | Legacy tests PASS, including receipt-only, one-sided pairs, unreadable evidence and ignored completed_at. Bound pairs without receipt remain typed partial evidence because canonical AdmissionBinding requires a receipt; inventing one would violate the contract. |
| Header survives invalid snapshot/partial binding; unknown format fails closed | Named expiry/fingerprint preservation and unknown-format tests PASS. Replacement/409 ordering belongs to the future consumer, not proven here. |
| Strict JSON rejects duplicate keys, nonobjects, bare nonfinite, lossy numbers and unusable Unicode | Focused storage-boundary injections PASS; valid Unicode and exact numbers also PASS. |
| Actual evidence-json producer and model_of/model_of_json materialization | **UNVERIFIED**: tests hand-build tags and compare stored evidence, not actual request/receipt/Run model materialization. |
| Real migrated PostgreSQL, non-null production/raw pools and same DB | **UNVERIFIED this round**: all 3 pool cases skip at test_admission_codec.py:470. No DB provisioned after independent blocker reproduced; no session identities or final SQL counts claimed. |
| Run JSONB payload is an object; real authorized principals/Workspace/Project/registered Graph | **UNVERIFIED**: DTO fixture identity strings and admission-row inserts cannot establish these criteria. |
| No SQL mutation, queue, HTTP, assessment, scope utility, competing authority or policy change | Codec source is a mapping conversion leaf. This round changes documentation only. Canonical execution remains untouched. |
| Runtime reachability and unchanged full required CI | **BLOCKED / UNVERIFIED**: caller search finds only codec-to-DTO and whitelist imports. Provenance rejects current candidate debt. Full CI not executed. |
| Focused tests, lint, formatting, applicable typing and inventory | Executed successfully as above; no tests added or removed, so no inventory delta is needed. No new pre-fix/mutation claim. |

## Reported test failure ambiguity

Inspected the frozen dispatch's four captured `test` check records (`worker-captured-tests.json`), without refreshing GitHub. Only head `3f2c79a70d9e1b0b6b6ffc99562cb35db5326828` reports failure, with null summary/text. Other captured heads report success; none is this assigned SHA. The supplied driver and fresh focused tests do not reproduce a failure. CI's `test` job deliberately excludes this core suite (`.github/workflows/ci.yml:574-612`), so focused green is not proof that job passes. **UNRESOLVED**: request the assigned-head failing step/node/traceback before another test repair; do not guess.

## Handoff

Only changed file: `docs/testing/issue-1893-repair-8036b74c.md`. No source, test, whitelist, inventory, ledger, grant or gate edits. Commit this report locally; no push or integration approval.

Disposition: **BLOCKED**. Next: trusted-base reachability authorization or separately authorized real consumer integration, plus an assigned-head test traceback. Candidate-ledger green results do not override trusted-base rejection. Progress: checked 1, done 0, skipped 0, errors 1 (required provenance gate); repair is explicitly blocked, not complete.


