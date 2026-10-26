---
inventory-delta:
  tests/: +2
---
# GHAS scanner plumbing (ace4)

`tests/test_devskim_scan_scope.py` gains:

- `test_directory_globs_are_absolute_path_safe` — every `/**` ignore-glob must
  start with `**/` so DevSkim DenyFilters match absolute `$GITHUB_WORKSPACE`
  paths.
- `test_shipped_template_deploy_stays_in_scope` — a broad `**/deploy/**` deny
  must not hide `templates/**/deploy/**` product compose templates.

The scanner now allowlists `**/packages/**,**/scripts/**,**/templates/**,**/extensions/**`
via `--include-globs` so `.github/`, `deploy/`, `alembic/`, `formal/`, and
`quality/` are never scanned without a deny that would also hit shipped
template deploy trees.
