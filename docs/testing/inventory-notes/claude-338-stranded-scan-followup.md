---
inventory-delta:
  packages/maistro-core/tests: +3
---

Follow-up to #1280 (#338): two defects a Codex review found in the stranded-admission tick after it had already been queued, so the fix could not land in that PR (`GH006`: a branch queued for merging cannot be updated).

The sweep asked the store for `RunStatus.RUNNING` and left the ownership fact to the per-candidate check, so a deployment whose RUNNING set is mostly scheduled work read unboundedly many rows that could never be eligible. `list_by_status` takes `admission_source` and both SQL backends push it into the query, so the scan now asks for `CHAT_SOURCE`. Two cases: the predicate reaching the query, and — because the per-candidate source check is defense in depth rather than a duplicate — a store that ignored the predicate still sparing a foreign Run. The second passes against the pre-fix code by design; it exists so the new query filter does not make that branch unreachable.

`list_node_runs()` calls `_require_run()` on all three backends and `RunNotFound` is a `KeyError`, so it was caught by neither arm below it, and the first of the two absence reads sat outside the `try` entirely. One Run terminalized by another worker and swept by retention therefore abandoned every later stranded Run in the same tick. Both reads are inside the `try` now and a vanished Run is skipped as the settled race it is; the case fails against the pre-fix code by letting `RunNotFound` escape.
