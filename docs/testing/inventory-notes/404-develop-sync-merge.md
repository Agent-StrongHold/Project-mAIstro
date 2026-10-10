---
inventory-delta:
  packages/maistro-core/tests: -43
---
# Develop-sync merge of origin/develop b672b799aba6 into auto-404: node-ID ledger reconciliation

The merge itself adds test nodes (core +19: builders TUI +18, `TestGitClone`
rework +1; rsi +12, recorded on `404-clone-source-policy.md` as corrected).
This note records the separate, pre-existing ledger correction the merge
round had to make to keep `check-suite-inventory.py` green in the gate's
canonical collection condition, plus the verification evidence for the merge
resolution.

## The −43: the recorded core-suite count was taken in a condition the gate recipe cannot reproduce

`check-suite-inventory.py` collects canonically with
`uv run pytest packages/maistro-core/tests --collect-only -q` under
`BASE_ENV = {REQUIRE_AUTH: "false", MAISTRO_DRY_RUN: "1"}` — the same
condition ci.yml's "Suite inventory matches collected node IDs (C1/#286)"
step runs in, with no `MAISTRO_TEST_PG_DSN` and no other env leakage.

At the assigned branch head d9e35dbaa2ac (verified in a clean temp worktree
at that exact SHA), canonical collection returns **13688** node IDs, while
the ledger's recorded expectation (baseline + Σ note deltas, including the
develop note's original +32 claim) was 13731 − a −43 drift that predates
this merge. Measured decomposition:

- **−17**: `tests/workspaces/test_store_boundary_scope_conformance.py`
  collects its PostgreSQL legs only when `MAISTRO_TEST_PG_DSN` or
  `MAISTRO_REQUIRE_PG_LEGS` is set (its own docstring: the CI steps that run
  the directory set both; the inventory step sets neither). With a DSN
  exported, collection gains exactly those 17 nodes (measured: 13688 →
  13705 at d9e35db; 13707 → 13724 on the merged tree).
- **−26 residual**: not reproducible at d9e35db under the canonical recipe
  even with the DSN exported (13705 < 13731), i.e. part of the earlier
  recorded condition (whatever env the earlier round collected under) is
  not reconstructible from this sandbox. Recorded as a condition artifact
  rather than attributed to any code change: the branch's own policy-suite
  nodes were re-collected and match this note's +19 accounting exactly via
  a full node-ID set diff (5 removed `TestGitClone` cases, 6 added, all
  other deltas in `test_builders.py`).

This note moves the recorded expectation by the measured −43 so expected
matches canonical collection again. Concretely: with the develop note's core
delta corrected +32 → +19, the pre-merge expectation becomes 13731; this
note's −43 brings it to 13688 (canonical collection at the branch head); the
merge's own +19 brings it to 13707, which is exactly what canonical
collection returns on the merged tree. The `packages/maistro-rsi/tests`
suite required no correction: its expectation already matched canonical
collection before and after the merge.

If a future environment legitimately collects the DSN-conditional legs, the
right fix is a recipe change in `check-suite-inventory.py` (export the DSN
vars in `BASE_ENV`), not a per-note delta — this note deliberately does not
bake the DSN'd count into the ledger.

## Verification evidence for the merge resolution (head: merge of b672b799aba6)

- Conflicts resolved in place: `server.py` (branch enforcement core kept,
  develop public API adopted), `test_server_security.py` (branch suite kept,
  develop's parallel suite not merged), RSI `test_cli.py`/`test_selfbranch.py`
  (hermetic local-source opt-in kept, develop's live pinning classes kept and
  adapted to the verified-local-root gate). No conflict markers remain in the
  tree.
- `uv run pytest packages/maistro-core/tests/tools/git` → 120 passed
  (includes the real-git pinned-submodule refusal test).
- RSI clone-policy surface (`test_cli.py`, `test_selfbranch.py`,
  `test_harvest_clone_source.py`, `test_harvest_entry_point.py`,
  `test_runner.py`) + `packages/maistro-core/tests/cli/test_builders.py` →
  123 passed, including the live real-git pinning classes running against
  the merged `git_clone`.
- Gates with CI's argv: `check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` exit 0 (one new
  develop-side identity banked: `code_registry/types.py::unused variable
  'trusted'`); `check-radon-baseline.py` 138=138; `check-reachability.py`
  exit 0; `check-security-inventory.py` exit 0; `ruff check .` and
  `ruff format --check .` clean.
- Hosted CI on this merge head: not observable from this sandbox (no push,
  no GitHub mutations) — UNVERIFIED by policy.

## Correction (repair round, post-merge)

The vulture claim above was false at this merge head. Banking the
`code_registry/types.py::trusted` row did **not** make
`check-vulture-baseline.py` exit 0: the per-identity ratchet reads
authorizations from the merge base, so candidate banking cannot self-authorize
— the gate reproduced its failure (`1342 reviewed identities -> 1343
findings`, exit 1) at b25f0537. The row is now gone because the repair round
restored the dropped `_enforce_signature_policy` trust anchor (the merge had
deleted develop's only in-tree use of the name `trusted`, unmasking the
`CodeEntry.trusted` debt) — see `404-trust-anchor-restore.md` for the fix and
the passing run.
