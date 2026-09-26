---
inventory-delta:
  packages/maistro-core/tests: +1
---
# auto-74 CI-gate repair round (post-develop-sync)

## Develop sync conflict resolution

Merged `origin/develop` (176043b01) into auto-74. Two test files conflicted;
both conflicts sit on the security seam upstream touched with 031bd0746
(fail closed at the Agent tool seam without Sentinel or auth) while this branch
touched with #74's fail-closed ImportError handling:

- `packages/maistro-core/tests/agents/test_base.py`: the merged body uses both
  `Sentinel` (the governed-executor product-path tests) and develop's
  `RealSentinel` alias (upstream authorization tests), so the import block now
  binds both names from the same module.
- `packages/maistro-core/tests/agents/strategies/test_react.py`: develop's
  `test_no_sentinel_fallback_pii_filter_import_error_passes_through_unredacted`
  pinned the *old* pass-through contract for a broken `pii_filter` module. The
  merged product path fails closed (`react.py` returns
  `Error: [BLOCKED: output sanitization unavailable]` on `ImportError`), so the
  pass-through assertion contradicted reachable production behavior and would
  have failed. Resolved by keeping this branch's fail-closed
  `strategy.reason` test and rewriting develop's direct-seam test to the new
  contract as `test_no_sentinel_fallback_pii_filter_import_error_blocks_unredacted`
  (the +1 in the delta): same setup, same seam, fail-closed assertion, with the
  reconciliation recorded in its docstring.

Evidence: `uv run pytest packages/maistro-core/tests/agents/test_base.py
packages/maistro-core/tests/agents/strategies/test_react.py -x -q` → 104 passed.

## Radon ratchet repair (real Quality-gate failure, not a ledger grant)

`scripts/check-radon-baseline.py` failed after the sync: the branch's
`detector._scan_semantic_windowed` was a new D (21) block — unbaselined, hence
a hard gate failure. No ledger grant was sought (grants are out of scope for
this round); the function was decomposed behavior-preserving instead:

- `_SemanticWindowAggregate` (dataclass) holds the running cross-window state
  and a `complete` early-exit property;
- `_fold_semantic_window` merges one window's boolean signals and capture
  positions into the aggregate;
- `_merge_position` folds a window-local offset into the running global
  extreme (`lt` earliest capture / `gt` latest conversation), preserving the
  positional first-capture < last-conversation pairing exactly.

`_scan_semantic_windowed` dropped from D (21) to B (10); the ratchet now
reports `67 reviewed C-or-worse blocks -> 67`. Behavior is pinned by the
existing product-path tests, all executed after the refactor:
`test_sentinel_policy.py` (-k "post_call_real_warden or pii_match", 8 passed),
`packages/maistro-core/tests/security/` (1325 passed, 19 skipped),
`tests/orchestrator/test_output_security_gate.py` (26 passed),
`tests/security/test_warden_regex_equivalence.py` (7 passed),
`tests/security/warden/` (89 passed), `packages/maistro-turing/tests`
(190 passed), `tests/agents/` (104 passed). `uv run mypy` over all six package
src trees: no issues in 722 files. Vulture per-identity ledger re-run after the
refactor: 1406 reviewed identities → 1406 findings, 0 unclassified,
0 never-allowlist. Xenon: 0 blocks (baseline 77). Reachability, wiring-reads,
enumerations, doc-links, security-inventory, convergence, dispositions,
contract-markers, credential-authority, backlog-consistency, image-inventory,
release-consistency, IFEval/BFCL provenance, execution-lifecycles: all pass.

## Not run locally (environment-bound)

The acceptance-state ratchet step (`check-ac-state.py --run-tests --ratchet`)
requires the full CI battery incl. Postgres and re-measures the base revision;
it was not executed in this worktree. This round's diff touches no AC-state
notes and only adds a test plus a complexity-reducing refactor, so the
ratcheted/floored counters cannot regress from it.
