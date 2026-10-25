# Issue #1893 repair validation

## Frozen scope

- Assigned item only: #1893, branch `auto-1893`, starting HEAD `ef25b5b21d2f571830d0372c51005576966e42eb`, supplied base `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Starting worktree is clean; no incoming edits to salvage.
- Inspect the supplied dispatch snapshot and check logs, repository instructions, relevant ADRs, admission codec/identity implementation and adjacent tests, CI workflows and directly relevant gates. No GitHub re-enumeration or mutations.
- Repair only reproduced evidence. No activation, alternate execution authority, or reachability/grant/gate edits. The explicit vulture-ledger exception applies only if that gate produces genuine findings.
- Ambiguity: the dispatch requests repair of `test: failure` but supplies no failing test name. Proceed by examining supplied logs and running focused validation; do not invent a repair.

## Results

- Independently reproduced the mandatory blocker: `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py` exits 1. Both admission modules have unauthorized new unreachable-module rows and dispositions. See `worker-provenance.log` in the supplied job directory.
- Exact requested Vulture command passes: 1323 reviewed identities / 1323 findings, no unbanked identities. No Vulture ledger amendment is justified.
- Focused codec, root identity and pack tests: 311 passed, 3 PostgreSQL tests skipped (both required DSNs absent). Logs: `worker-focused.log`. No durability claim.
- Driver check-0 through check-4 logs inspected: dependency sync, Ruff, format, focused tests and core inventory pass; none identifies the reported failing CI test.
- Source explicitly documents that no production consumer reaches this codec (`admission_codec.py:50-53`). Adding a fake caller or authorizing new reachability debt is forbidden, and actual consumer activation is outside B2 scope.
- Existing historical `issue-1893-repair-validation.md` was briefly overwritten by this checkpoint due to a filename collision; its exact HEAD content was immediately recovered, this new note moved to a job-specific name, and a zero diff verified. No original work discarded.

Disposition: **BLOCKED** pending trusted-base authorization or separately reviewed consumer integration, plus candidate-qualified test-failure evidence. No source defect was reproduced that would justify an in-scope repair.

## Architecture and evidence reconciliation

Read repository instructions, `docs/README.md`, `docs/quality-gates.md`, accepted ADRs 081226-a66b (Run/NodeRun/Attempt lifecycle), 082826-b601 (canonical Run consumer), and 083126-5e62 (trusted-base quality authority), both admission modules and their adjacent tests. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`; immutable DTO construction is not authorization or admission. B2 explicitly forbids activation, so a passing unit contract cannot be presented as reachable production behavior. The explicit Vulture-ledger exception does not extend to reachability ledgers or grants.

The supplied dispatch snapshot's associated PR bodies and failed check records were extracted once into `worker-captured-evidence.json`. Its failed `test` check names head `3f2c79a70d9e1b0b6b6ffc99562cb35db5326828`, not this lane's starting HEAD, and has null summary/text. Attribution to this candidate remains **UNRESOLVED**. No remote refresh or speculative develop merge: there is no merge conflict to resolve.

Source import search finds only codec-to-identity and Vulture-whitelist imports, not a production consumer. Against the supplied base, `quality/reachability-baseline.json:131,147` adds the two admission modules and `quality/reachability-dispositions.json:604-614` adds their CONNECT group. The required workflow invokes provenance at `.github/workflows/vulture-ratchet.yml:77`; its failure cannot be repaired by rebanking Vulture.

## Commands executed

All validation used 1800-second command timeouts against unchanged source at starting HEAD. Logs are in `/home/dev/maistro/jobs/687ea5da39244baaa6e705896b6cfefb/`.

| Command | Outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1323 identities; `worker-vulture.log` |
| `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py` | FAIL, exit 1, two unauthorized modules plus two dispositions; `worker-provenance.log` |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/extensions/test_pack_contracts.py -x -q -r s` | 314 nodes, 311 passed, 3 skipped, 1.53s; `worker-focused.log` |
| `uv run ruff check .` | PASS; `worker-quality.log` |
| `uv run ruff format --check .` | PASS, 3277 files; `worker-quality.log` |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS, two source files; `worker-quality.log` |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS, 16467 nodes, zero duplicate evidence; `worker-quality.log` |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS; `worker-quality.log` |

## Acceptance audit

All PASS entries below mean executed **codec/type contract** tests, not an activated production path.

| Criterion | Evidence / limitation |
| --- | --- |
| Frozen/slotted header, shared signatures, enum/error shape; signed timestamps and strict storage UUID `.hex` | Source inspection and focused scalar/schema, owner-token and generation tests PASS. Validated scope only; safe messages and suppressed parsing chains tested. |
| Exact v2 DTO and fresh named-column SQL mapping | `test_v2_round_trip_preserves_all_snapshot_bytes` (three states), `test_encode_returns_a_fresh_flat_mapping`, `test_owner_token_is_hex_at_storage_only` PASS. Independent assertions at `test_admission_codec.py:134-137` check migration-055 binding shape rather than encode/decode agreement alone. |
| Bound, unbound, partial legacy; receipt-only/announced-without-Run fail without invented identity | `test_legacy_binding_unbound_and_partial_are_distinct`, receipt-only, missing-receipt, unreadable-evidence and whitespace tests PASS. Both IDs without receipt remain partial: the prerequisite constructor requires receipt identity, which cannot be guessed. |
| Header survives expiry/fingerprint evidence despite full-decode failure | `test_expired_legacy_header_does_not_invent_missing_identity`, `test_header_preserves_expiry_even_when_legacy_snapshot_decode_fails`, `test_header_preserves_fingerprint_even_when_legacy_binding_is_partial` PASS. No clock, incoming fingerprint or decision is added. |
| Header must match row; unknown format never becomes legacy | `test_header_scalar_mismatch_is_invalid_header`, `test_unknown_format_cannot_be_reinterpreted_as_legacy`, missing-column and malformed-scalar tests PASS. |
| Strict TEXT JSON; reject duplicate keys, nonobjects, bare nonfinite tokens and invalid original evidence | `test_invalid_and_duplicate_json_is_rejected`, numeric-loss, nesting, Unicode and predecoded-value tests PASS. Storage corruption is injected after fixture construction; header evidence remains intact. |
| Canonical snapshot bytes/tags and stored fingerprint unchanged | `test_tagged_nonfinite_snapshots_round_trip_without_fingerprint_change`, v2 round-trip and exact-number tests PASS. Full original-model fingerprint -> `encode_evidence` -> `model_of`/`model_of_json` materialization is **UNVERIFIED**; handwritten tags do not prove that production path. |
| Raw and production pools against the same genuinely migrated PostgreSQL DB | `test_raw_and_production_pool_codecs_read_identical_text_snapshots` **UNVERIFIED**, three skips at `test_admission_codec.py:470`; DSNs absent. No disposable DB provisioned after mandatory blocker reproduced. No session identities, persisted-row counts or durability claimed. |
| Run payload remains a JSONB object; positive production admission uses authorized principals, Workspace/Project and registered Graph kinds | **UNVERIFIED** by these synthetic DTO tests. B2 does not perform Run insertion or authorization. |
| No SQL mutation, live `_assess`, scope utility, queue/HTTP change, expiry/mismatch classification, new admission/deletion policy or alternate authority | Codec source inspected; this round changes only this evidence note. C/F2 replacement and HTTP 409 precedence are outside B2 and not claimed. |
| Inventory, focused lint/type validation and unchanged full required integration CI | Focused checks PASS above; no new tests or inventory delta. Full integration CI **UNVERIFIED** and mandatory provenance gate FAILS. Existing unreachable-module banking cannot authorize itself. |
| Coordinated base/owner and activation policy | Lane owns only this isolated repair. Wider coordination and owner policy choices remain **UNVERIFIED**; no integration, rollout or issue-closure approval. |

No new tests were added because no code repair was justified; no pre-fix or mutation evidence is claimed. Historical notes, source, tests, ledgers, grants, whitelists and gates are preserved.

## Handoff

Only changed file: `docs/testing/issue-1893-repair-687ea5da.md`. Commit this evidence locally; do not push. The authorized integration owner must provide a trusted base with separately landed reachability authorization, or a separately reviewed real consumer integration consistent with #1845. A further test repair needs a failing node/traceback tied to this candidate. Repeating this dispatch with identical inputs cannot remove the blocker.

Progress: checked 1, done 0, skipped 0, errors 1 (mandatory provenance gate), next: owner-supplied authorization/integration and candidate-qualified CI evidence.
