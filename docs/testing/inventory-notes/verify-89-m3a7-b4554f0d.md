---
inventory-delta:
  tests/: +0
  packages/maistro-core/tests: +0
  packages/maistro-server/tests: +0
---

# verify-89-m3a7 — repair-round re-verification at b4554f0d (merge-queue "queued" gate resolved locally)

Repair-round record for issue #89 (M3-A7, parent epic #19) at the exact
starting head `b4554f0ddeaf0cc87070a90a84f1cdfd9124de18` (branch `auto-89`,
base `3be6b6650caaf5e59c1b15ad3096a2631865f6b9`). The merge-queue evaluation of
this head reported **"Validate ADR/spec front-matter: queued"** — a scheduling
state, not a finding — so this round re-ran every step of that gate at HEAD
with the workflow's exact arguments, re-ran the focused release battery
independently (not trusting prior verification claims), and added one fresh
mutation probe against the byte-equivalence mechanism. No code change was
warranted or made; this note is the only file added.

## Named gate — "Validate ADR/spec front-matter" (registry.yml), all 7 steps at HEAD

1. `uv run pytest tests/tools/registry/ tests/tools/test_lint_lifecycle.py
   packages/maistro-registry/tests --confcutdir=tests/tools -p no:cacheprovider
   -q` — **194 passed** (3.16 s).
2. `uv run python tools/lint_lifecycle.py` — exit 0 ("✓ All documents pass
   lifecycle checks (baseline: 0 accepted)").
3. `uv run python -m maistro_registry.cli lint . --strict` — exit 0 (447 files
   checked: 248 clean, 0 errors, 0 warnings, 0 extra).
4. `RATCHET_BASE_REV=origin/develop uv run python
   scripts/check-citation-status-provenance.py` — "OK: 0 citation exception(s),
   no candidate-approved expansion".
5. `uv run python scripts/check-adr-index.py` — "OK: every ADR-INDEX row agrees
   with its ADR's front matter".
6. `uv run python scripts/generate-spec-ac-defined-index.py && git diff
   --exit-code docs/specs/README.md` — regenerated 57 AC Defined specs, zero
   diff.
7. `uv run python scripts/check-adr-status-language.py` — "ok: 0 baselined
   body-status contradiction(s), no new ones, none stale".

Nothing in the tree can fail this gate; the hosted `queued` state is runner
scheduling (the check completed `success` on PR head `5f6bff7d458f` per the
dispatch evidence and is not blocked by any content change since — the only
delta is the `retention-days` bump in `release.yml` plus verify notes).

## Focused battery (independently re-executed at b4554f0d)

- `uv run ruff check .` — exit 0 ("All checks passed!").
- `uv run ruff format --check .` — exit 0 (3682 files already formatted).
- `uv run pytest tests/test_promote_release.py tests/test_release_guard.py
  tests/test_check_license_inventory.py -q` — **163 passed** (1.55 s).
- `uv run pytest tests/release -q` — **308 passed** (31.86 s).
- `uv run pytest tests/test_check_required_checks.py
  tests/test_mutation_targets.py -q` — **123 passed** (3.00 s).
- `uv run python scripts/check-release-consistency.py` — exit 0 (released
  none, shipping 0.9.0, working toward 1.0.0).
- `uv run python scripts/check-workflow-inventory.py` — exit 0 (33 workflows
  dispositioned).
- `uv run python scripts/check-workflow-write-safety.py` — exit 0.
- `uv run python scripts/check-suite-inventory.py` — exit 0 (21 suites match;
  no test added this round, hence the all-zero inventory delta).
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` — exit 0 (1219 reviewed
  identities -> 1219 findings; branch adds none).
- YAML: `release.yml` and `registry.yml` both parse (`yaml.safe_load`).

## Fresh mutation probe (not inherited from any prior round)

`scripts/promote_release.py` `verify_dist` line `if actual != digest:` was
mutated to `if False and actual != digest:` (file backed up with `cp` first,
restored after; `git status`/`git diff` confirm the worktree is byte-identical
to HEAD after the probe).

- `uv run pytest tests/test_promote_release.py -k "mismatch or tampered or
  another_tree" -q` — **`test_verify_dist_rejects_a_hash_mismatch` FAILED**,
  1 failed / 3 passed: the byte-equivalence check is genuinely pinned by its
  dedicated test, not by wall-clock or fixture accident.
- The three survivors exercise sibling guard layers, verified by reading the
  code: `cmd_adopt_wheels` runs `validate_evidence` (tag/version/commit/**tree**
  identity via `git rev-parse HEAD^{tree}`) *before* `verify_dist`, so the
  tamper test fails closed at the tree layer (it does not pin the tree); the
  soak-binding and other-tree tests guard the evidence-schema layer. Layered
  defense confirmed by reading `scripts/promote_release.py:519-547`.
- After restore: full `tests/test_promote_release.py` — **47 passed**.

## Sync and ledger state

- `git fetch origin develop` → `origin/develop` is still `3be6b6650c`, the
  exact merge base of HEAD; branch is 19 ahead / 0 behind — no sync merge owed.
- `git diff --numstat origin/develop -- quality/` — empty; no ledger rows
  added, removed, or rewritten.

## Acceptance disposition

Unchanged from `verify-89-m3a7-5f6bff7d.md`. The in-lane engineering surface —
candidate evidence record, byte-verified wheel/digest adoption
(`adopt-wheels`), routed-findings gate (`adopt-digests`), PyPI sequenced behind
the soak gate (`pypi.needs: [guard, wheels, m1-closeout, images]`), finals-only
evidence attachment, and the RC `dist` artifact lifetime (90 days) aligned to
the soak + approval window it must survive — is tested and gate-clean at this
head. Promotion-scale criteria (cutting the actual RC, the sustained
exact-RC multi-replica soak via still-open child lane #860 / PR #1672, the
final promotion, and external PyPI/GHCR/cosign/install verification) remain
release operations outside lane authority and stay UNVERIFIED at issue level.
