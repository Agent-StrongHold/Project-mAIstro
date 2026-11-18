---
inventory-delta:
  packages/hive-conductor/backend/tests: +11
---
# 1050-landing-preference-degenerate-paths

Eleven `test_workspace_landing_preference.py` cases covering the degenerate
paths the diff-coverage gate scored dark on the A2 parity slice (PR #2362) —
`routes/profile.py` PUT audit loop and 40 uncovered lines in
`services/workspace_preferences.py`:

- `interpret_restore_aggressiveness_request` — non-string/blank requests name
  no band; a "brief restore" phrase maps to `brief` (and "brief" alone is not
  a policy phrase)
- `normalize_restore_path` — non-strings, non-root-relative and
  scheme-relative paths, and well-formed non-surfaces are refused; query and
  fragment are stripped from eligible surfaces
- `decide_landing` — empty/absent observation → `default`; bad path, bad
  timestamps, and a future `left_at_ms` → `invalid`; inside-window control
  still restores
- `record_immediate_landing_hop` — Home hops and non-surfaces preserve the
  prior pattern object; a junk streak restarts at 1; control increments
- `decide_landing_suggestion` — missing/empty pattern, Home or non-surface
  path, unreadable streak → `(False, reason)`; eligible control proposes
- `normalize_suggestion_cooldown` / `suggestion_on_cooldown` — unusable map
  entries (default path, unknown surface, non-integer, non-positive) dropped;
  a map without the path never suppresses; expired untils stop suppressing
- preference validation — non-string landing/restore values and cooldown maps
  with non-path keys, non-integer or non-positive untils raise
  `PreferenceValueError` (the 400 path), matching the refuse-don't-coerce
  contract
- `PUT /v1/profile` preference writes are audited (`source=api`), and the
  cooldown-map audit row carries the sorted path list instead of every
  until-ms

All cases pin behavior, not implementation: each helper is driven through its
public surface, and every refusal asserts the reason string the product
surface reports. No production code changed in this delta.
