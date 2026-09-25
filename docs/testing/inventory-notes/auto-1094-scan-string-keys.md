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
