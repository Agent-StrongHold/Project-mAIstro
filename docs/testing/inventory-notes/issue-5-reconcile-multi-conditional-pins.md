---
inventory-delta:
  tests/: +2
---

# issue-5-reconcile-multi-conditional-pins

CI-repair round for issue #5 (M1 architecture convergence) in worktree
`auto-5`. The merge-queue `security` / **Container scan + SBOM + cosign**
job failed on its last step, **Reconcile installed packages to uv.lock**:

```
image maistro-engine:pr-2262 does NOT reconcile to the lock:
  version mismatch     : beartype==0.22.9 (image) != beartype==0.23.1
```

This is not a dependency-supply-chain problem. `uv.lock` legitimately
resolves one name to several marker-conditional versions — beartype
`0.22.9` for `python_full_version < '3.15'` and `0.23.1` for
`>= '3.15'` (forced by fastmcp-slim 4.1.3's metadata). The image ships the
`0.22.9` branch (Python 3.13) and is correct.

## Root cause (two compounding bugs in `scripts/check-image-lock-reconciliation.py`)

1. `parse_expected` collapsed every pin to a `dict[str, str]` keyed by
   canonical name, so a name with two conditional branches kept only the
   last branch — the installed branch vanished from the parsed expected set.
2. `main` rebuilt `expected_by_name` from that already-collapsed set, so the
   installed branch was compared against the *other* branch. Because the map
   is built from a `set`, which branch won was set-iteration order, so the
   gate was also hash-seed flaky.

The script's own docstring says conditional pins "gate nothing"; the code
contradicted it for multi-branch names.

## Fix

- `parse_expected` now keeps every pin (a `set`), marking only the
  marker-conditional pins, so both branches survive.
- `main` builds `expected_versions: name -> set[version]` and accepts the
  image when it carries **any** version the lock names for that name. A
  version the lock does not name is still a `version mismatch`, printed with
  the full acceptable set. All pre-existing strictness tests
  (`test_version_skew_*`, `test_conditional_pin_version_is_checked_when_it_ships`,
  `test_member_version_skew_*`) still pass unchanged.

## Evidence

- Focused suite: `uv run pytest tests/test_check_image_lock_reconciliation.py -q`
  → **29 passed** (27 pre-existing + 2 new regressions).
- Real gate, local Docker (images rebuilt at this head, tagged `pr-2262`):
  all four reconciliations in the workflow step exit 0:
  - `maistro-engine` — 128 distributions, 14 conditional pins
  - `hive-conductor` — 72 distributions, 3 conditional pins
  - `maistro-engine-research` — 148 distributions, 178 conditional pins
  - `maistro-rsi-runner` — 220 distributions, 14 conditional pins
- Reproduced the original failure before the fix against the freshly built
  engine image (`beartype==0.22.9 (image) != beartype==0.23.1`, exit 1).
- `uv run ruff check` / `ruff format --check` on the two changed files: clean.

`tests/: +2` for the two regressions: one pins that either branch reconciles,
one pins that a third, unnamed version is still reported as a mismatch.
