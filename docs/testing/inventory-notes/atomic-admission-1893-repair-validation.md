# Issue #1893 repair validation

## Frozen scope

- Assigned worktree: `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Starting source: `d644afbd1af19ca7e602af97d52f8bbf9655ffed` (clean).
- Supplied develop base: `321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62`.
- One item: repair #1893's reported test failure and inspect exact-debt-ledger evidence.
- Implementation scope: admission codec and adjacent identity types/tests; only amend code
  if a concrete defect is reproduced. Record validation in this file. No activation,
  reachability/grant changes, GitHub mutations, or unrelated repairs.
- Evidence snapshot: job `e5cfe740313d4730a7318b0248b097df` dispatch-context.json,
  check-0.log through check-4.log, and supplied prior result if present.
- Ambiguity: the dispatch reports only `test: failure`, without a failing node.
  Proceed by inspecting supplied logs and running focused tests; do not guess a repair.

## Results

Supplied driver logs inspected: dependency sync, Ruff check, format check, and
suite inventory passed. Focused tests report 346 passed / 3 skipped, not a test
failure. Prior result records the same unresolved trusted-base provenance blocker;
it is historical evidence, not validation of this head. No tests added or removed.
The codec explicitly remains unconsumed (module docstring); do not manufacture a
runtime caller to satisfy reachability.

Fresh execution at the starting source:
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3301 files.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`:
  PASS, 1322 findings / 1322 reviewed identities, zero unclassified. No Vulture
  ledger amendment is justified.
- `RATCHET_BASE_REV=321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62 uv run python scripts/check-ratchet-provenance.py`:
  FAIL (exit 1): both `maistro.runs.admission_identity` and
  `maistro.tasks.admission_codec` are new unreachable modules and new dispositions
  absent from trusted authorization. All other invoked provenance checks passed.

Architecture reconciliation: accepted ADR-081226-a66b leaves lifecycle authority
with Run/NodeRun/Attempt; accepted ADR-083126-5e62 forbids candidate evidence
from authorizing itself. The issue explicitly prohibits activation and fake runtime
callers. Its staged-leaf permission does not override trusted-base authorization.
The existing reachability changes are preserved, not edited or self-authorized.
The policy blocker cannot be repaired in this lane.

## Focused validation and acceptance

Executed at `d644afbd1af19ca7e602af97d52f8bbf9655ffed`:

```text
uv run pytest packages/maistro-core/tests/extensions/test_cli_lock.py packages/maistro-core/tests/extensions/test_pack_contracts.py packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/tasks/test_admission_codec.py -x -q -rs
346 passed, 3 skipped in 2.82s (349 nodes)

uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py
Success: no issues found in 2 source files

uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests
PASS: 16567 collected nodes; zero duplicate evidence

uv run python scripts/check-shipped-surface-truth.py
PASS: Shipped-surface truth matrix is complete.
```

| Criterion | Evidence / boundary |
| --- | --- |
| Immutable header, shared interfaces, constructors, fresh flat mapping | Inspected codec and adjacent identity types; focused tests pass, including scalar mismatch, encode freshness and constructor tests. |
| v2 snapshot round trip and exact binding | `test_v2_round_trip_preserves_all_snapshot_bytes` passes for unbound, bound and acknowledged; independently asserts both binding columns and receipt identity. Pure storage mapping evidence, not a transaction proof. |
| UUID storage-only owner token | `test_owner_token_is_hex_at_storage_only` and strict generation tests pass; safe token-free errors and repr are asserted. |
| Legacy bound/unbound/partial, receipt-only, no invented identity | `test_legacy_binding_unbound_and_partial_are_distinct`, expired-header test and legacy evidence tests pass. |
| Header expiry/fingerprint survive full decoding failures | Both named header-preservation tests pass; no clock, incoming fingerprint, classifier or claim mutation exists in the codec. |
| Unknown format and bad scalar headers fail closed | Unknown-format, mismatched-header and invalid-scalar tests pass. |
| Strict JSON and tagged nonfinite data, unchanged fingerprint | Tagged round trip, duplicate/nonobject/bare nonfinite, lossy-number, recursion and Unicode tests pass. These inspect stored evidence; not production model materialization. |
| Safe typed parsing failures | Focused failure tests assert error codes, validated scope, suppressed exception chains and no private snapshot content. |
| Named TEXT SQL parameters and schema constraints | Mapping inspected; live round trip UNVERIFIED this round. Three real-PG cases skipped at test_admission_codec.py:470 because both DB variables are absent. No session identities or final SQL counts claimed. |
| Real raw/production pool equivalence, migrated schema | UNVERIFIED; all three PG cases skipped. No SQLite/fake pool was substituted. |
| Production evidence-json/model_of materialization and JSONB Run object | UNVERIFIED. Codec tests manually construct tagged evidence; they do not execute a materializing production consumer or Run INSERT. |
| Real authorized principals, Workspace/Project and registered Graph | UNVERIFIED; DTO fixture identity strings do not establish authorization or admission. |
| No new execution/HTTP/queue/authorization authority | Source inspection: codec only reads mappings/returns DTOs or parameters. Source search finds no production caller of the codec; only its import of the identity module and the whitelist reference. |
| Required integration gates and reachability | Ruff, format, scoped mypy, Vulture, inventory and shipped-surface pass. Trusted-base provenance FAILS. Full integration CI UNVERIFIED; generic `test: failure` has no supplied failing node and is not reproduced by the focused command. |
| Inventory and pre-fix regression evidence | No test or source changes this round, no inventory delta, no new mutation/pre-fix claim. Existing tests are meaningful contract checks, not reachable production behavior. |
| Coordination / activation | No release of coordination or activation policy verified or implied. No HTTP mapping, assessment, deletion policy, scope utility or fingerprint algorithm changed. |

## Disposition / handoff

**BLOCKED**, not merge-ready. One assigned item checked, zero repairs completed,
one blocked/error item, zero skipped items. Only this validation note changed.
No speculative code repair or Vulture ledger edit was justified by fresh evidence.

Next: the authorized integration owner must resolve trusted-base reachability
policy (a separately approved, already-landed authorization or separately scoped
real consumer integration), and supply the actual failing CI test log. Do not
repeat candidate-side banking or add fake callers. Live PostgreSQL validation and
production materialization remain unverified here. No claim of parent closeout,
integration approval, or rollout readiness is made.
