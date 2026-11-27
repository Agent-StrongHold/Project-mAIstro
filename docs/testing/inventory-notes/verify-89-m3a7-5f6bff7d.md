---
inventory-delta:
  tests/: +0
  packages/maistro-core/tests: +0
  packages/maistro-server/tests: +0
---

# verify-89-m3a7 — salvage round at 5f6bff7d (dist artifact retention for the soak window)

Salvage-round record for issue #89 (M3-A7, parent epic #19) at the exact
starting head `5f6bff7d458f6d24f80a46a84983b6cf1b61ca1f` (branch `auto-89`,
base `3be6b6650caaf5e59c1b15ad3096a2631865f6b9`). This round adopted the one
uncommitted change the previous attempt left in the worktree — the RC/final
`dist` artifact upload in `.github/workflows/release.yml` raised
`retention-days: 7` → `90` — proved it against the workflow's own contract,
re-ran the battery plus the Registry CI gate ("Validate ADR/spec
front-matter", the check the merge queue saw stuck `queued`), and committed.

## Why the retention change is load-bearing, not cosmetic

`adopt-wheels` (final runs) downloads the RC run's `dist` artifact through the
Actions artifacts API (`gh api repos/<repo>/actions/artifacts/<id>/zip`,
`scripts/promote_release.py:391`) and verifies every file byte-for-byte
against the recorded sha256. With `retention-days: 7` the RC `dist` artifact
could expire before the sustained multi-replica soak (#860) plus approval
window completes, making byte-equivalent promotion impossible after the fact —
the exact failure mode the issue's acceptance criterion ("final tag/tree is
byte-equivalent to the soaked RC tree") forbids. 90 days matches the
`release-evidence-wheels` artifact uploaded next to it (lines following the
changed step) and the 90-day evidence records the promotion is verified
against. The sibling `sboms`/`license-inventory` uploads at lines 782/892 stay
at 7 days: they are consumed within the RC run itself, not adopted across the
soak boundary, so no blanket bump was made.

## Battery (all executed at 5f6bff7d + retention change)

- `uv run ruff check .` — exit 0 ("All checks passed!").
- `uv run ruff format --check .` — exit 0 (3682 files already formatted).
- `uv run pytest tests/test_promote_release.py tests/test_release_guard.py
  tests/test_check_license_inventory.py -q` — **163 passed** (1.61 s).
- `uv run pytest tests/release -q` — **308 passed** (33.01 s).
- `uv run pytest tests/test_check_required_checks.py
  tests/test_mutation_targets.py -q` — **123 passed** (2.99 s).
- `uv run python scripts/check-release-consistency.py` — exit 0 ("released
  none, shipping 0.9.0, working toward 1.0.0").
- `uv run python scripts/check-workflow-inventory.py` — exit 0 (33
  workflows dispositioned).
- `uv run python scripts/check-workflow-write-safety.py` — exit 0.
- `uv run python scripts/check-suite-inventory.py` — exit 0 (21 suites match;
  this round adds no test, hence the all-zero inventory delta).

## Registry CI gate ("Validate ADR/spec front-matter") — every step re-run

1. `uv run pytest tests/tools/registry/ tests/tools/test_lint_lifecycle.py
   packages/maistro-registry/tests --confcutdir=tests/tools
   -p no:cacheprovider -q` — **194 passed** (3.03 s).
2. `uv run python tools/lint_lifecycle.py` — "✓ All documents pass lifecycle
   checks (baseline: 0 accepted)."
3. `uv run python -m maistro_registry.cli lint . --strict` — "447 files
   checked: 248 clean, 0 errors, 0 warnings, 0 extra …".
4. `RATCHET_BASE_REV=origin/develop uv run python
   scripts/check-citation-status-provenance.py` — "OK: 0 citation
   exception(s), no candidate-approved expansion".
5. `uv run python scripts/check-adr-index.py` — "OK: every ADR-INDEX row
   agrees with its ADR's front matter".
6. `uv run python scripts/generate-spec-ac-defined-index.py && git diff
   --exit-code docs/specs/README.md` — regenerated 57 AC Defined specs, zero
   diff.
7. `uv run python scripts/check-adr-status-language.py` — "ok: 0 baselined
   body-status contradiction(s), no new ones, none stale".

Both modified workflow files parse as YAML (`yaml.safe_load`).

## Sync and ledger state

- `git fetch origin develop` → `origin/develop` is still `3be6b6650c`, the
  exact merge base of HEAD — no sync merge owed, no conflicts.
- `git diff --numstat origin/develop -- quality/` — empty; no ledger rows
  added, removed, or rewritten by this branch.

## Acceptance disposition

Unchanged from `verify-89-m3a7-839ab09f.md`: the in-lane engineering surface
(candidate evidence record, byte-verified wheel/digest adoption, routed-
findings gate, PyPI sequenced behind the soak gate, finals-only evidence
attachment) remains tested and gate-clean, now with the RC `dist` artifact
lifetime aligned to the soak + approval window it must survive. Promotion-
scale criteria (cutting the actual RC, the sustained exact-RC multi-replica
soak via the still-red child lane #860 / PR #1672, the final promotion, and
external PyPI/GHCR/cosign/install verification) remain release operations
outside lane authority and stay UNVERIFIED at issue level.
