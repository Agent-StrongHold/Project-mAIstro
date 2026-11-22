---
inventory-delta:
  packages/maistro-core/tests: +9
---
# auto-1094-scan-string-keys

Repair-round addition to the #1094 fix set: the tool-result scan
representation inside the core Agent pipeline (`maistro.agents`) is now a
deterministic JSON serialization (`to_scan_string` in
`maistro.security.normalize`) instead of `str()`, so mapping keys are
guaranteed present in the scanned text even when an SDK mapping subclass
hides its contents from `repr`. The Conductor chat boundary already scanned
the exact `json.dumps` string and the shared `_text_leaves` traversal already
yielded mapping keys; this closes the same gap in the core-agent seam.

## Tests added

- `packages/maistro-core/tests/security/test_normalize_scan_string.py` (7):
  `to_scan_string` string passthrough; hostile nested mapping key present;
  hostile key survives a repr-hiding mapping; deterministic sorted
  representation; scalar/sequence handling; unserializable fallback to
  `str`; mixed-type keys still land in the scanned text.
- `packages/maistro-core/tests/agents/test_base.py` (+1):
  `test_hostile_mapping_key_reaches_the_tool_result_boundary` — the governed
  tool executor hands the warden the exact model-visible text, including a
  hostile Airtable-style field-name key hidden by a lying `__repr__`.
- `packages/maistro-core/tests/agents/artificer/test_strategy.py` (+1):
  `test_hostile_mapping_key_survives_repr_hiding_result` — the Artificer
  `_handle_tool_call` result string (which the sanitizer/warden see) contains
  mapping keys of a repr-hiding result.

## Validation evidence (head 36b6eb61a + this change set)

- `uv run --no-sync pytest` (backend workdir):
  `test_capabilities_routes.py test_chat_voice_gates.py test_legacy_dag_node.py`
  → 78 passed; the 13 named #1094 acceptance / prior-finding tests pass
  individually; `packages/maistro-core` security/agent suites → 193 passed;
  core `test_inbox_approval.py test_durable_approval.py` → 21 passed.
- `uv run --no-sync ruff check .`: passed; `ruff format --check .`: 2535
  files formatted.
- `uv run --no-sync mypy packages/maistro-core/src`: only the five
  pre-existing `maistro_bootstrap` import-not-found errors; none in changed
  files.
- `scripts/check-suite-inventory.py --suite
  packages/hive-conductor/backend/tests`: ok (2685).
- Mutations (all applied via a /tmp pytest plugin; tree untouched, `git
  status` verified clean of mutation effects):
  - A: mapping-key yields dropped from `_text_leaves` →
    `test_scan_config_visits_nested_airtable_field_name_keys` FAILED.
  - B: `TOOL_EFFECTS["run_workflow"] = TOOL_EFFECT_NETWORK` →
    `test_run_workflow_is_privileged_and_requires_scoped_approval` and
    `test_workflow_forged_evidence_never_reaches_handler` FAILED.
  - C: tool_result gate scans a values-only representation while the full
    `json.dumps` string is re-fed →
    `test_airtable_field_name_in_nested_mapping_key_is_withheld` FAILED.
  - D (new this round): core-agent `to_scan_string` reverted to `str()` →
    both new repr-hiding-key tests FAILED.
- `scripts/check-gates-ran.py` without `--check-runs`: usage error only
  (integration-time gate needing GitHub check-run JSON), matching prior
  findings; not a code defect.

## Repair round (develop sync to 031bd0746; fail-closed tool seam)

Merging `origin/develop@031bd0746` ("fail closed at the Agent tool seam
without Sentinel or auth") made two #1094 regression tests deny their tool
calls before the executor ran (`sentinel=None, auth=None` now refuses), so
their serialization assertions saw `"Error: Permission denied ..."` instead
of the tool result:

- `test_strategy.py::test_hostile_mapping_key_survives_repr_hiding_result`
  now runs under `_grant("write_file", warden=<recording double>)` — a real
  `Sentinel` grant whose Warden records scanned text. Assertions: the
  injection survives repr-hiding into the model-visible string AND the gate
  scanned exactly that string. `_grant` gained a keyword-only `warden=`
  parameter (default keeps the real `Warden`).
- `test_base.py::test_hostile_mapping_key_reaches_the_tool_result_boundary`
  now wires `RealSentinel(warden=warden, permission_table={...})` and an
  `AuthContext` with the granting role, matching the in-file precedent.
- Out-of-scope-but-blocking: `test_log_redaction.py::test_install_is_idempotent`
  (untouched since initial release; pre-existing at develop base — neither
  the module nor its test changed on this branch) asserted on the global
  wrap count, which pytest's logging plugin breaks by attaching
  `LogCaptureHandler`s to the named logger mid-test. The test now asserts
  the actual idempotency property: the fixture's already-wrapped handler is
  not double-wrapped. No production change.

No test counts changed (0 added, 0 removed); inventory delta unchanged.

Re-validation at this head:

- `uv run ruff check .` / `ruff format --check .`: pass.
- Verifier's exact failing selection (check-3 argv) → 131 passed.
- `packages/maistro-core/tests/agents` + `tests/security` → 2111 passed,
  19 skipped.
- `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'`: exit 0, no unbanked identities; no ledger
  amendment needed.
- Conductor acceptance tests: `test_chat_voice_gates.py -k
  "scan_config_visits_nested_airtable_field_name_keys or
  airtable_field_name_in_nested_mapping_key_is_withheld or
  run_workflow_is_privileged_and_requires_scoped_approval or
  workflow_forged_evidence_never_reaches_handler"` → 4 passed.
- Mutations reproduced at this head (each applied to the tree, executed,
  then reverted by exact byte restore from backup; `git diff --stat` and
  per-file `diff` verified only the four intended files changed):
  - keys dropped (`to_scan_string` → `str()` in
    `ArtificerStrategy._truncate_result`) →
    `test_hostile_mapping_key_survives_repr_hiding_result` FAILED;
  - `TOOL_EFFECTS["run_workflow"]` `TOOL_EFFECT_MUTATE` →
    `TOOL_EFFECT_NETWORK` (`chat_gate.py:259`) →
    `test_run_workflow_is_privileged_and_requires_scoped_approval` FAILED;
  - mapping-key yield removed from `_text_leaves`
    (`agent_materialization.py`) →
    `test_scan_config_visits_nested_airtable_field_name_keys` FAILED
    (`test_airtable_field_name_in_nested_mapping_key_is_withheld` still
    passed — it guards the exact-`json.dumps` scan path, independent of the
    config traversal).
