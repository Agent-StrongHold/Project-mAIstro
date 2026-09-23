---
inventory-delta:
  packages/hive-conductor/backend/tests: +15
---
# Conductor frontend on the Workspace design system (ADR-091626-ba4f, #1046)

Fifteen new collected cases in `packages/hive-conductor/backend/tests`:

- `test_workspace_tokens_sync.py` (+2): the frontend's token file is the
  bundled Workspace tokens byte for byte, and the bridge rebinds only the
  three `--font-*` tokens to the shipped faces while no other stylesheet
  redeclares a token.
- `test_themes.py` (+1): the two catalog tests became three; the catalog is
  the bundle manifest's persona templates, and the retired `default`, `dark`
  and `fantasia` ids stay valid and resolve to a template.
- `test_chat_brief_interview.py` (+12): the brief interview (SPEC-091726-7c2a)
  hosted as chat turns. A work request in a workspace opens the interview
  and the model is not called; answers advance it, routed answers repeat the
  question, "commit it" yields the draft with `written: []`, "cancel" drops
  it and hands the next turn back to the model; a turn with no workspace, a
  question, or a non-member's turn reaches the model as before; the
  non-streaming route carries the same `brief` payload. Four more, added
  closing the diff-coverage gate on `brief_chat.py`: "you decide" is refused
  where nothing is defensible and the subject stays open; once ready, a
  vague turn is noted and a named change is applied; dropping the interview
  through the program API hands the next chat turn to the model; a
  whitespace-only turn in a workspace reaches the model unchanged.
