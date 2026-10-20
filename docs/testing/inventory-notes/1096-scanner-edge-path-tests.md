---
inventory-delta:
  tests/: +5
---
# 1096-scanner-edge-path-tests

## What moved

`tests/test_check_security_inventory.py`, a new class
`TestTheBypassScannersEdgePaths` (+5 node IDs, no parametrization).

## Why

CI run 36243700637 at head `0525645bf1` failed the **Coverage gate (publish-set
floor + diff coverage)** on exactly one file:

```
scripts/check-security-inventory.py: 87.7% of 114 changed lines (need 90%);
uncovered 299, 303, 304, 346, 357, 358, 400, 401, 402, 403, 425, 435, 436, 438
```

Every uncovered line was an edge path of the three #1096 bypass scanners
(`_sibling_unguarded_httpx_calls`, `_self_authorized_fetch_helpers` /
`_self_authorized_fetches_in_file` / `_request_target`, and
`_repo_unguarded_httpx_constructors`): the existing tests drove them only over
the real repository, where all five sibling roots exist, every file parses, and
no self-authorized fetch or private constructor is present to find — so the
missing-directory skips, the `SyntaxError` skips, the `url=` keyword form of
`_request_target`, and the constructor-census append path had never executed.

## The tests

- **`test_a_missing_root_and_an_unparseable_file_are_skipped`** — a vanished
  sibling root and a file that cannot be parsed are skips, not crashes; the
  census still reports the finding it could read (`httpx.get` in the clean
  sibling file).
- **`test_the_self_authorized_census_detects_the_keyword_form`** —
  `configure_outbound_policy(url=dest)` followed by `client.post(url=dest)` is
  the same self-allowlist bypass as the positional spelling the autorun probe
  closed (`f44d1ec1c`); the scanner must read the `url` keyword, not only
  `call.args[0]`. The vanished root beside the real one keeps the
  missing-directory skip honest too.
- **`test_a_call_whose_target_cannot_be_named_is_left_alone`** —
  `client.post(timeout=5)` names no destination; `_request_target`'s contract
  is to stay quiet rather than guess.
- **`test_an_unparseable_file_reports_no_self_authorized_fetches`** — the
  per-file helper returns no findings for a `SyntaxError` file.
- **`test_the_repo_census_reports_a_constructor_and_survives_broken_trees`** —
  the repo-wide constructor census had only ever been asserted on its *empty*
  result over the real tree; a synthetic production root holding one private
  `httpx.Client()` must be reported (the append is the scanner's whole point),
  while a vanished root and an unparseable file are skipped.

## Evidence

Local reproduction of the CI step at the same base
(`a71fc2e434a8c9525eef8ac3abbb666d944fb2cb`, the run's own `DIFF_BASE_SHA`):
`coverage run --branch --source=scripts` over the full root `tests/` suite
plus the changed-file package producers (evolve, rsi, bootstrap, design,
registry, hive-conductor), then
`scripts/check-diff-coverage.py coverage.xml --base a71fc2e43` →
*"ok: every measured file this change touches is at or above 90% lines / 80%
branch arcs"*, exit 0.
