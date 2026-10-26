---
inventory-delta:
  packages/maistro-core/tests: +5
---

# 1084 pyright ratchet repair

CI merge-queue evaluation of `auto-1084` failed `Quality / Pyright` with
"pyright regression: 22 errors exceeds baseline of 21". This round repairs the
gate by fixing real diagnostics rather than touching the workflow baseline.

## Why the count moved

Two independent effects stacked on top of the fixed baseline of 21:

1. **Analyzer drift on the base itself.** With pyright 1.1.414 in a
   CI-equivalent environment (`uv sync --locked --all-extras` +
   `maistro-evolve`), `origin/develop` (`b1c89cdb`) already measures 22 errors.
   The ratchet baseline predates the analyzer version, so the whole gate floor
   had drifted above the line.
2. **Two genuine branch regressions.** `stream_chunks` and its helper
   `_pump_chunks` in `capabilities/model_chat.py` are async generators
   annotated `-> Any`; pyright resolves those as coroutines, so both
   `async for` consumers were flagged ("CoroutineType ... is not iterable").

## Source fixes (all behavior-preserving)

- `capabilities/model_chat.py`: `stream_chunks` →
  `AsyncIterator[dict[str, Any]]`, `stream` → `AsyncIterator[str]`,
  `_pump_chunks` → `AsyncIterator[Any]`. The governed streaming lifecycle
  (SPEC-285) is untouched; only the declared shapes became truthful.
- `capabilities/providers/subprocess_harness.py`, `tools/browser/guard.py`:
  duck-typed `getattr` handles (`destroy`, `fetch`, `fulfill`) given explicit
  `Callable[..., Awaitable[Any]] | None` locals so the awaited calls are
  known-awaitable; the runtime `callable()` guards are unchanged.
- `security/warden/detector.py`: provenance validation extracted into
  `_coerce_provenance(value: object) -> Literal["trusted", "untrusted"]`,
  raising the same `ValueError` for anything outside the union. Validation now
  produces the typed value instead of hoping the analyzer narrows `object`.
- `security/warden/_regex.py`: the RE2 branch keeps `_RE2_AVAILABLE` as the
  semantic switch (tests force the fallback by clearing it) and adds a
  `_re2 is not None` conjunct purely to narrow the optional import; the stdlib
  fallback returns through an explicit `cast(PatternLike, ...)` because pyright
  cannot bind `re.Pattern`'s `self` parameters to the protocol (mypy accepts
  the plain annotation; runtime object is identical).
- `tasks/runner.py`: `_execute_task` initializes `result` to `None` and asserts
  it is set exactly when the run was not claim-lost, encoding the invariant the
  try/except structure already guarantees.
- `cli/_upgrade.py`: the unreachable tail of `_run` raises `AssertionError`
  instead of reading the possibly-unbound `outcome`.

## Tests

`packages/maistro-core/tests/security/warden/test_detector.py` gains
`TestCoerceContextItemProvenance` (5 node IDs): explicit provenance carried
through, role-derived defaults, invalid provenance rejected with the exact
message, and a truthy non-string rejected rather than stringified or
defaulted. The last two pin the degenerate paths of the extraction above.

## Gate evidence at the repaired head

- `pyright --outputjson packages/maistro-core/src`: **11 errors** (CI-exact
  env) → `check-pyright-report.py --baseline 21` exits 0 with 10 errors of
  headroom; the 2 branch regressions are gone (11 < develop's 22 floor).
- `mypy --strict packages/maistro-core/src`: Success, 827 files.
- `ruff check .` / `ruff format --check .`: clean.
- `pytest packages/maistro-core/tests/{capabilities,security,tools,tasks,cli}`:
  3646 passed, 52 skipped (before the new detector tests); warden suite
  re-run after the test addition: 121 passed.

This note moves no existing node IDs; it adds 5 to `packages/maistro-core/tests`.
