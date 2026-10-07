---
inventory-delta:
  tests/: +18
---
# Reconcile the root-suite inventory after Phase 0 review additions

This is measured inventory evidence for tests already on `develop`, not a
change to a test, collection recipe, quality floor, or authorization. The
shared `inventory/baseline.json` is unchanged. The front matter was generated
with:

```bash
python scripts/check-suite-inventory.py --suite tests/ --update \
  --note merge-queue-root-inventory-reconciliation
```

At `b4b9e187e29b44cc9f567fe9c15c14cb514844cb`, collection returns **4410** root
node IDs while baseline plus existing notes expects **4392**. This is also
the shared failure in merge-group runs for [#1794](https://github.com/Agent-StrongHold/Project-mAIstro/actions/runs/37080575378/job/111079958675),
[#1803](https://github.com/Agent-StrongHold/Project-mAIstro/actions/runs/37083501565/job/111088883492),
and [#1684](https://github.com/Agent-StrongHold/Project-mAIstro/actions/runs/37083502996/job/111088887608).
Those PRs did not introduce these root tests.

## Provenance of the missing +18

The last checked reference used here, `4e50b46153bd7ec174937fcc1f4c69cfee74eba0`,
collects **4305**, exactly its ledger. Comparing complete collected node-ID
sets against `b4b9e187` shows **105 additions and no removals**. Notes added
between those revisions account for only **87**. The difference is fully
accounted for below; it is not a blanket adjustment for unidentified drift.

### #1765: closure-target guard, +11

`feat-cutover-s0-2-closure-guard-5557.md` records the **27** IDs collected at
the initial implementation, `c465940b`. Follow-ups `d40db041` and `838b9fb2`
add **11** IDs without updating that note, giving **38** at squash merge
`059a3e4f`. All are in `tests/test_check_closure_targets.py`:

- `test_missing_repository_argument_fails`
- `test_fetch_target_reads_title_and_sub_issues`
- `test_fetch_target_treats_missing_sub_issues_endpoint_as_empty`
- `test_fetch_target_network_and_shape_errors_raise[side_effect0]`
- `test_fetch_target_network_and_shape_errors_raise[side_effect1]`
- `test_fetch_target_network_and_shape_errors_raise[side_effect2]`
- `test_fetch_target_rejects_a_non_object_issue_payload`
- `test_full_url_closing_reference_is_recognised_for_this_repo`
- `test_full_url_closing_reference_for_another_repo_is_ignored`
- `test_pull_request_title_is_scanned_for_squash_merge_keywords`
- `test_pull_request_event_without_a_pull_request_object_skips`

### #1766: retirement-ledger gate, +5

`feat-cutover-s0-1-retirement-ledger-c421.md` records the **14** IDs collected
at `f4f44bf2`. Follow-ups `4eba7f8d` and `1180d6e3` add five cases, giving
**19** at squash merge `6b74fc14`. All are in
`tests/test_check_workspace_retirement.py`:

- `test_an_importer_the_trusted_base_did_not_list_needs_a_landed_grant`
- `test_dropping_or_keeping_a_tracked_entry_needs_a_landed_grant`
- `test_a_store_missing_from_the_ledger_fails`
- `test_stores_module_aliases_are_tracked`
- `test_a_new_importer_cannot_be_self_authorized_in_the_candidate_ledger`

There is also a zero-count replacement in the same file:
`test_the_current_repository_passes` becomes
`test_the_ledger_matches_the_current_repository`, narrowing its assertion to
ledger consistency while the new tests cover trusted-base authorization.
The original-note-to-final node-ID diff is therefore six additions and one
removal, **net +5**, not six new counted cases.

### #1764: ADR-index completeness, +1

`7062d92d`, squashed as `0976bf98`, adds
`tests/test_check_adr_index.py::test_every_adr_in_the_corpus_is_indexed`
without an inventory delta.

### #1808: generated OpenAPI types exclusion, +1

`s1-3-openapi-types-gate.md` correctly records the seven new
`test_dump_hive_openapi.py` cases. Follow-up `27c922cb`, included in squash
`8c4831c2`, also adds
`tests/test_check_frontend_api_routes.py::TestGeneratedApiTypes::test_types_gen_is_excluded_from_the_scan`
without updating that delta.

## Verification

- Fresh `uv sync --locked --extra dev --extra bootstrap` succeeds.
- `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest tests/ --collect-only -q`
  collects 4410 IDs on the repair tree, unchanged from its base.
- The four affected test modules plus `tests/test_check_suite_inventory.py`
  pass together: **201 passed**. No assertions, skips, recipes, or tests were
  modified for this repair.
- `python scripts/check-suite-inventory.py` passes for **all 14 suites** after
  adding this note; every non-root count is unchanged.
- Full-tree `ruff check .` and `ruff format --check .` pass (2760 files), and
  `check-doc-links.py` reports zero broken relative links in 1500 Markdown files.

This note changes only the expected root-suite count, **4392 -> 4410**. It
does not resolve separate quality-gate failures such as #1684's Radon debt.
