---
inventory-delta:
  packages/maistro-rsi/tests: +25
  tests/: +36
---
# claude-issue-303-promotion-surface-7dd2

Both deltas are new files. Nothing was moved, renamed, split or deleted, so
neither number is hiding a compensating change.

`tests/test_check_promotion_surface.py` (+34) covers the new gate: the
derivation itself against controlled fixture trees (reachability, transitivity,
cycles, third-party names), one case per evasion the issue names (alias,
generated wrapper, rename, symlink, deleted root), the baseline ledger checked
in both directions, and the shipped patterns asserted against the real
repository.

`packages/maistro-rsi/tests/test_sensitive_paths.py` (+25) covers the
classifier now that it is its own module: that it imports only the standard
library and loads under `python -I` with nothing on the import path — the gate
depends on that — that the directory patterns cover everything the per-file
entries they replaced covered, and that ordinary application surface still does
not escalate.

Two of the 36 arrived after the first CI run, which died on
`ModuleNotFoundError: No module named 'structlog'`: the gate loaded the
classifier as `maistro_rsi.sensitive_paths`, and the dotted form runs
`maistro_rsi/__init__.py` -> `coordinator` -> `structlog`, which the lint job
does not have. It now loads the file by path, and
`TestTheMatcherIsReachableWithoutTheWorkspace` puts a `maistro_rsi` package
that raises on import ahead on `sys.path` so the failure cannot come back.

`packages/maistro-rsi/tests/test_quarantine.py` is unchanged and still passes:
`quarantine.py` re-exports `SENSITIVE_PATH_PATTERNS` and
`matches_sensitive_pattern`, so its 17 tests exercise the moved code through
the same names as before.
