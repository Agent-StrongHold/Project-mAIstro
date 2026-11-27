---
inventory-delta:
  tests/: +0
  packages/maistro-core/tests: +0
  packages/maistro-server/tests: +0
---

# verify-89-m3a7 — deep-review round at 4f01f11b (develop sync + independent re-proof)

Deep-review record for issue #89 (M3-A7, parent epic #19) on branch `auto-89`.
The previous evaluation blocked with "worker requested attention:
NEEDS-DEEP-REVIEW" and reported **"Validate ADR/spec front-matter: queued"**.
This round resolved both: (1) executed the deep review independently — no
prior verification claim was trusted; every gate below was re-run at HEAD with
CI-exact arguments; (2) synced the branch with `origin/develop`, which had
advanced to `69b41dd3af` ([M5] Optional Turing autonomous cognition, PR
#2534) — a disjoint file set (`packages/maistro-turing/**`, two
`9-turing-*` inventory notes), merged conflict-free as `4f01f11b56`. The job
directory contained **no `check-*.log` files**, so the deterministic verifier
logs referenced by dispatch could not be inspected; all validation here is
freshly executed.

## The "queued" front-matter gate (registry.yml), all 7 steps at HEAD

1. `uv run pytest tests/tools/registry/ tests/tools/test_lint_lifecycle.py
   packages/maistro-registry/tests --confcutdir=tests/tools
   -p no:cacheprovider -q` — **194 passed** (3.11 s).
2. `uv run python tools/lint_lifecycle.py` — exit 0 ("✓ All documents pass
   lifecycle checks (baseline: 0 accepted)").
3. `uv run python -m maistro_registry.cli lint . --strict` — exit 0 (447
   files: 248 clean, 0 errors, 0 warnings, 0 extra).
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

Dispatch evidence independently confirms the hosted check completed
`success` on PR head `5f6bff7d458f`; `queued` was runner scheduling, and the
steps above prove the current tree cannot fail it.

## Deep-review battery (independently re-executed at 4f01f11b56)

- `uv run pytest tests/test_promote_release.py tests/test_release_guard.py
  tests/test_check_license_inventory.py -q` — **163 passed** (1.60 s).
- `uv run pytest tests/release -q` — **308 passed** (31.11 s).
- `uv run pytest tests/test_check_required_checks.py
  tests/test_mutation_targets.py -q` — **123 passed** (2.96 s).
- `uv run ruff check .` — exit 0 ("All checks passed!").
- `uv run ruff format --check .` — exit 0 (3682 files already formatted).
- `uv run python scripts/check-release-consistency.py` — exit 0 (released
  none, shipping 0.9.0, working toward 1.0.0).
- `uv run python scripts/check-workflow-inventory.py` — exit 0 (33 workflows
  dispositioned).
- `uv run python scripts/check-workflow-write-safety.py` — exit 0.
- `uv run python scripts/check-suite-inventory.py` — exit 0 (21 suites match;
  the develop sync added no test files to any inventoried suite root of this
  branch).
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` — exit 0 (1219 reviewed
  identities -> 1219 findings; CI-exact arguments).
- `uv run python scripts/check-doc-links.py` — exit 0 (every relative
  markdown link resolves).
- `uv run python scripts/check-backlog-consistency.py` — exit 0 (167 items).
- `git diff --check HEAD~1..HEAD` — clean; `git diff --numstat
  origin/develop -- quality/` — **empty** (no ledger rows added, removed, or
  rewritten).
- YAML: `release.yml` and `registry.yml` both parse (`yaml.safe_load`).

## Fresh mutation probe (this round's own, not inherited)

`pypi.needs` in `.github/workflows/release.yml` was mutated from
`[guard, wheels, m1-closeout, images]` to `[guard, wheels, m1-closeout]`
(file backed up with `cp` first, restored after; `git status`/`git diff`
confirm byte-identical restoration):

- `uv run pytest
  tests/test_promote_release.py::test_pypi_waits_for_the_soak_gate_before_irreversible_publication`
  — **FAILED** under the mutation ("PyPI can publish before images rejects
  missing/failed soak evidence").
- After restore, full `uv run pytest tests/test_promote_release.py -q` —
  **47 passed**. The soak-gate ordering — the defect repaired in `684e9fa5ea`
  — is pinned by structure, not by fixture accident. Together with the
  b4554f0d round's `verify_dist` probe, both load-bearing promotion
  mechanisms (soak-before-PyPI ordering and byte-equivalence verification)
  now have independent mutation proof.

## Review conclusion (no code change warranted)

The branch's engineering surface — candidate-only builds with frozen
artifact identity, `--verify-rc-tree` final source-tree guard, byte-verified
wheel adoption (`adopt-wheels`), routed-findings soak gate (`adopt-digests`),
PyPI sequenced behind the soak gate, finals-only evidence attachment, and the
90-day RC artifact/evidence retention window — is implemented in
`scripts/promote_release.py`, `scripts/release_guard.py` and
`.github/workflows/release.yml`, and every reachable mechanism is pinned by
tests that demonstrably fail under targeted mutations. No new defect was
reproduced, so per the repair contract no speculative code change was made;
the only tree changes this round are the develop sync merge and this note.

## Acceptance disposition (unchanged in kind, re-proven at this head)

Promotion-scale criteria remain release operations outside lane authority and
stay UNVERIFIED at issue level: cutting the actual RC, the sustained exact-RC
multi-replica soak (owned by the still-open child lane #860 / PR #1672 on
branch `auto-860` — a separate lane whose CI failures, captured on its head
`c5d4a6b38f7`, are not this branch's), the final promotion, and external
PyPI/GHCR/cosign/install verification. All eight criteria map to executed
local mechanism evidence plus an explicit operational disposition in
`docs/testing/issue-89-71864dc4-validation.md`; that mapping was re-checked
against the merged tree this round and remains accurate.
