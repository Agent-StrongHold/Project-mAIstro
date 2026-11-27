---
inventory-delta:
  tests/: +0
  packages/maistro-core/tests: +0
  packages/maistro-server/tests: +0
---

# verify-89-m3a7 — verification round at 6d38bd2 (diff-coverage gate re-proved at the merge base; both named gates green)

Verification record for issue #89 (M3-A7, parent epic #19) at the exact
starting head `6d38bd20030513e497b062bcb48145e91ec5769a` (branch `auto-89`,
merge base with `origin/develop` = `69b41dd3af32e10f69afc50aceb0c9aeeea41864`;
`origin/develop` = `80242f28521bba184f4d5d62cda972c1c8928f36`, i.e. the
merge-queue judgment base resolves to `69b41dd3af` for both the stored base and
the fetched develop tip). The prior round ended BLOCKED on operational
acceptance (a real RC soak/promotion cannot execute locally), with the
merge-queue evaluation reporting **"Validate ADR/spec front-matter: queued"**
(a scheduling state, not a finding) and with the **"Coverage gate
(publish-set floor + diff coverage)"** red from the earlier evaluation. This
round re-proves both gates at HEAD with the workflows' exact arguments, runs
the focused release battery independently, and adds fresh fail-closed probes
against the soak-evidence and byte-identity validators. No code change was
warranted or made; this note is the only file added.

## Changed-surface audit (what the gates actually score)

`git diff --stat 69b41dd3af...HEAD`: `.github/workflows/release.yml`,
`scripts/promote_release.py`, `scripts/release_guard.py`, three test files,
and docs/inventory notes only. `scripts/check-diff-coverage.py` classifies the
two `scripts/` files as **measured** (scored) and the three test files as
**exempt**; the workflow and docs are not Python. Nothing else in the diff is
scorable, so a scoped but gate-exact reproduction is sound: per-file coverage
only accumulates hits, so the targeted producer below is a lower bound for the
full root producer CI runs.

## Named gate — "Validate ADR/spec front-matter" (registry.yml), all 7 steps at HEAD

1. `uv run pytest tests/tools/registry/ tests/tools/test_lint_lifecycle.py
   packages/maistro-registry/tests --confcutdir=tests/tools
   -p no:cacheprovider -q` — **194 passed** (3.41 s).
2. `uv run python tools/lint_lifecycle.py` — exit 0 ("✓ All documents pass
   lifecycle checks (baseline: 0 accepted)").
3. `uv run python -m maistro_registry.cli lint . --strict` — exit 0 (447 files
   checked: 248 clean, 0 errors, 0 warnings, 0 extra).
4. `RATCHET_BASE_REV=origin/develop uv run python
   scripts/check-citation-status-provenance.py` — "candidate: 6d38bd200305 …
   OK: 0 citation exception(s), no candidate-approved expansion".
5. `uv run python scripts/check-adr-index.py` — "OK: every ADR-INDEX row
   agrees with its ADR's front matter".
6. `uv run python scripts/generate-spec-ac-defined-index.py && git diff
   --exit-code docs/specs/README.md` — regenerated 57 AC Defined specs, zero
   diff (byte-identical, no drift).
7. `uv run python scripts/check-adr-status-language.py` — "ok: 0 baselined
   body-status contradiction(s), no new ones, none stale".

Nothing in the tree can fail this gate; the hosted `queued` state is runner
scheduling, and this head will report green when it executes.

## Named gate — "Coverage gate (publish-set floor + diff coverage)", diff half at HEAD

Exact producer shape from `quality.yml` (scoped to the tests that exercise the
two measured files, which is a sound lower bound because coverage only
accumulates):

- `uv run coverage run --branch --source=scripts -m pytest
  tests/test_promote_release.py tests/test_release_guard.py
  tests/test_check_license_inventory.py --timeout=120 -q` — **183 passed**.
- `uv run coverage xml -o coverage.xml`.
- `uv run python scripts/check-diff-coverage.py coverage.xml --base
  origin/develop` — **exit 0**: "ok: every measured file this change touches
  is at or above 90% lines / 80% branch arcs". Scope printout: 2 changed
  file(s) measured (`scripts/promote_release.py`,
  `scripts/release_guard.py`), 3 exempt (the test files, by declaration).

The publish-set floor (87%) is computed over producer artifacts for the
publish-set packages; this PR changes no publish-set package code, so it
cannot move that floor. The red state named in the earlier evaluation was the
diff half, which commit `87ce1ab3de` repaired and this round re-proves green
with the gate's own scorer.

## Focused battery and fresh probes

- `uv run pytest tests/test_promote_release.py tests/test_release_guard.py
  tests/test_check_license_inventory.py -q` — **183 passed** (1.61 s).
- `uv run ruff check .` — "All checks passed!"; `uv run ruff format --check .`
  — "3682 files already formatted".
- Fresh CLI-level probe (run from `/tmp`, tree untouched) against
  `scripts/promote_release.py` production functions, not test fixtures:
  `validate_soak` fails closed on a foreign schema, a missing required check,
  a failing check, an invariant-invalidating finding without `routed_issue`,
  and stale/mismatched `artifact_binding` digests; `verify_dist` accepts
  exactly the recorded bytes and rejects tampered wheel bytes.
  `REQUIRED_SOAK_CHECKS` = `backup_restore`, `clean_install`,
  `multi_replica_soak`, `real_model`, `security_hot_path` — i.e. the soak
  contract pins exactly the acceptance criteria (clean install, real-model
  execution, security hot path, backup/restore, #860 multi-replica soak).
- Workflow wiring re-inspected at HEAD: `release.yml` emits `rc_tag` from the
  guard (`--verify-rc-tree`), adopts the RC wheels/digests on finals
  (`adopt-wheels`/`adopt-digests`, both fail-closed on tampered bytes per
  tests), gates PyPI publication on `soak-evidence.json` bound to the adopted
  artifacts, retains the RC dist artifact across the soak window, and
  preserves the gating evidence as run assets (`finalize-evidence`).

## Acceptance posture (unchanged verdict basis)

All locally provable criteria are enforced by production seams that are tested
and re-probed above. The operational criteria — executing the hosted RC build,
running the #860 sustained multi-replica soak, and performing the actual final
promotion — remain **UNVERIFIED by construction**: they require release
infrastructure and maintainer authority this worker does not hold (no GitHub
mutations, no releases). Residuals: `origin/develop` has advanced three
commits past the merge base (`8d8f10616f`, `4f8f40352d`, `80242f28`) on
disjoint surfaces (RSI promotion/proactive discoveries/M8-A); GitHub reports
the PR mergeable, so no sync merge was warranted this round.
