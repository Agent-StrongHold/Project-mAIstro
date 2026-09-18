---
inventory-delta:
  packages/hive-conductor/backend/tests: +3
---
# Conductor frontend on the Workspace design system (ADR-091626-ba4f, #1046)

Three new collected cases in `packages/hive-conductor/backend/tests`:

- `test_workspace_tokens_sync.py` (+2): the frontend's token file is the
  bundled Workspace tokens byte for byte, and the bridge rebinds only the
  three `--font-*` tokens to the shipped faces while no other stylesheet
  redeclares a token.
- `test_themes.py` (+1): the two catalog tests became three; the catalog is
  the bundle manifest's persona templates, and the retired `default`, `dark`
  and `fantasia` ids stay valid and resolve to a template.
