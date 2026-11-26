# Issue #1893 — repair validation, job 0f166c29

## Frozen scope

Assigned worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`, starting
head `714677150487e97b85468dff46963534d7b33879`; verified clean on entry.
Supplied base and locally resolved `origin/develop` both equal
`3c761d14db944a727fa0744444bc67cfe36d49f7`. No sync conflict was present.
Only #1893 is processed. No remote enumeration, GitHub mutation, activation,
merge or push was performed.

Read repository instructions, the issue body in the supplied dispatch snapshot,
check-0 through check-4 logs, previous result/report, codec and identity modules,
both adjacent test files, and applicable workflow definitions. Read accepted
ADRs 081226-a66b, 082526-7f02 and 083126-5e62. Reconciliation: immutable admission
history does not own execution or dispatch; Goal -> Graph -> Run -> NodeRun ->
Attempt remains canonical. Candidate ledger entries cannot authorize themselves.
The explicit Vulture repair exception does not authorize reachability grants.

Ambiguity: the generic `test: failure` supplies no failing node or traceback in
the prompt/driver logs. Focused validation cannot establish the unrelated CI
`test` job is green. Do not invent a repair from this status. A bounded lookup
for direct check-run collections in the frozen dispatch sources yielded none;
no claim is made about every nested historical check record.

## Fresh validation at the starting head

Commands used 1200-second timeouts. These results were independently executed,
not copied from previous verification claims:

| Command | Outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1323 reviewed findings, zero unclassified. No ledger amendment justified. |
| `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py` | FAIL: two new unreachable modules and two new dispositions lack trusted-base authorization. Other component provenance gates passed. |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -rs` | 201 passed, 3 skipped in 1.26s; 204 nodes selected. Skips explicitly require both PostgreSQL DSNs. |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS: 3277 files |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS: two files |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS: 16466 nodes, zero duplicate evidence |

Driver logs independently reported successful dependency sync, lint/format,
201 passed / 3 skipped and matching inventory. Skipped database cases prove no
durability. No tests were added or changed, so no inventory delta is required.

## Acceptance evidence and limits

| Criterion | Evidence or explicit limit |
| --- | --- |
| Frozen/slotted header, required interfaces, six typed codes, immutable #1851 DTO constructors | Inspected implementation and passing focused tests. |
| Named storage mapping; UUID `.hex` only at storage; signed timestamps; header mismatch rejection; fresh flat mapping | Passing strict UUID/header/encode tests. Binding task_id equals receipt_id and both binding columns are asserted separately from encode/decode agreement at test_admission_codec.py:134-137. |
| Strict TEXT JSON: duplicates, nonobjects, bare nonfinite values rejected; safe error message and suppressed parser chains; only validated scope hashes | Passing malformed JSON, excessive nesting, lossy numbers, Unicode, scope and error tests. |
| Canonical snapshot bytes and stored fingerprint retained; tags not decoded twice | Passing round-trip and tagged-evidence tests. Tests use manually tagged evidence, not full model materialization. |
| Legacy bound/unresolved/partial and receipt-only evidence remain distinct; no invented identity; completed_at grants no authority | Passing legacy tests, including missing receipt and partial pairs. A pair without receipt fails explicitly because the canonical binding requires receipt evidence. |
| Header preserves expiry/fingerprint despite malformed snapshots or partial bindings; unknown format fails closed | Passing separation and unsupported-format tests. No clock or request fingerprint enters the decoder; consumer replacement/409 ordering is outside B2 and UNVERIFIED here. |
| Evidence-json serializer and model_of/model_of_json materialization, original-model fingerprinting, arbitrary permitted program_context | UNVERIFIED end-to-end: fixtures preserve tags but do not materialize production request/receipt/Run models. |
| Raw and production pool contrast on the same real migrated disposable PostgreSQL database | UNVERIFIED this round: three database tests skipped for missing DSNs. No database was provisioned; no migration, session identity, final row count or durability result is claimed. |
| Run JSONB remains an object, authorized principals/Workspace/Project and registered Graph kinds | UNVERIFIED: codec fixtures are synthetic DTOs, not authorized production Run admissions. |
| No SQL mutation, HTTP mapping, queue change, live assessor/scope utility change, new decision or authority | Source inspected: mapping-only staged codec. No production changes this round. |
| Production reachability and unchanged integration CI | NOT established: required provenance gate fails. Source import search finds only codec-to-DTO and Vulture whitelist references; tests/exports do not establish runtime use. Full integration CI is UNVERIFIED. |
| Coordinated owner/base and activation choices | Assigned head/worktree honored; external coordination/activation decisions UNVERIFIED. No rollout or integration approval. |

No new regression or mutation test was added because no in-scope implementation
failure was reproduced. The existing tests inject malformed storage values and
binding shapes; this execution does not claim a fresh pre-fix mutation run,
transaction/crash boundary, or dispatch invariant.

## Blocked handoff

The failing required gate is `.github/workflows/vulture-ratchet.yml:77`:

- `quality/reachability-baseline.json:131,147`: `maistro.runs.admission_identity`
  and `maistro.tasks.admission_codec` are new unreachable modules without
  trusted-base authorization.
- `quality/reachability-dispositions.json:612-613`: both associated dispositions
  are absent from the trusted ledger and not previously authorized.

The allowed Vulture repair cannot resolve this reachability failure. Preserve
existing source/ledger work; do not activate a fake consumer, remove evidence,
or weaken a gate. Required next action is owner-coordinated trusted-base
reachability authorization/integration outside this lane, plus the actual
assigned-head failing test step/node/traceback. The generic test failure remains
UNRESOLVED, not disproven by focused passes.

Only this report changed. No code, tests, inventory, ledgers, grants or gates
were edited. Report committed locally after `git diff --check`; source remains
at the validated implementation. Progress: checked 1 issue, done 0 repairs,
skipped 0 issues, errors 1 required gate; next: external blocker resolution.
