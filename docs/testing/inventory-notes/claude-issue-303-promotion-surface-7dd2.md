---
inventory-delta:
  packages/maistro-rsi/tests: +25
  tests/: +43
---
# claude-issue-303-promotion-surface-7dd2

Both deltas are new files. Nothing was moved, renamed, split or deleted, so
neither number is hiding a compensating change.

`tests/test_check_promotion_surface.py` (+43) covers the new gate: the
derivation itself against controlled fixture trees (reachability, transitivity,
cycles, third-party names), one case per evasion the issue names (alias,
generated wrapper, rename, symlink, deleted root), the baseline ledger checked
in both directions, and the shipped patterns asserted against the real
repository.

Seven of those arrived after review, pinning fixes that were shipped unpinned
(Codex, #513). Four are evasions the walk did not see: a relative import
resolved against its package, the same from inside a package's own
`__init__.py`, a relative import that climbs past the top level resolving to
nothing rather than to a wrong guess, and a symlinked *package directory*
refused — `rglob` does not descend into one, and a module absent from the index
reads exactly like "not on the promotion path".

The other three derive the roots instead of restating them, because an entry
module is never imported by its own dependencies and so cannot come from the
walk: every `[project.scripts]` target in `packages/maistro-rsi/pyproject.toml`
must be a declared root, every `python -m maistro_rsi` in a workflow implies
`maistro_rsi.__main__` is one, and the Conductor's flat backend must be indexed
at all (`services.rsi` runs `LocalRsiLoop`; `routes.rsi` applies candidate
patches with `git am`). A console script or workflow command added later fails
those tests rather than relying on the broad `maistro_rsi/` pattern that made
the omission invisible.

`maistro/http.py` and `maistro/config/settings.py` moved out of the baseline
and under sensitive patterns in the same review; they need no test of their
own, because removing either pattern makes the module reachable-and-unprotected
and `test_the_real_tree_has_no_gap` fails. Verified by mutation rather than
assumed.

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
