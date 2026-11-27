---
inventory-delta:
  tests/: +0
---

# verify-89-m3a7 — coverage-gate repair round (the reproduced red gate, fixed)

Round record for issue #89 (M3-A7, parent epic #19) on branch `auto-89`,
starting head `9b35a6e1f188468e6efa988dae710c52f62d683a`, develop base
`8d8f10616fb7ae984a02bf84553489470d03c726` (= local `origin/develop`).
Unlike the three preceding rounds, this round **found a reproduced CI
failure and repaired it with tests**; it did not stop at "queued is a
scheduling state".

## The actually-red gate, identified from the captured evidence

PR #2536's pushed head `5f6bff7d458f` (behind this branch by seven commits)
has every required check green except **"Coverage gate (publish-set floor +
diff coverage)"** — check run 140175737147 of actions run 45893503850,
conclusion `failure`, 7 annotations. That is the gate the merge-queue
evaluation blocked on; "Validate ADR/spec front-matter: queued" was an
in-flight state, and all seven of its steps are re-proven green below.

## Reproduction with CI's exact gate mechanics

`scripts/check-diff-coverage.py` scores the three-dot diff against the base
the next PR/merge-queue evaluation will use (`origin/develop` =
`8d8f10616f`; merge-base `69b41dd3af`, so the diff is exactly this branch's
own changes). Measured files: `scripts/promote_release.py` (327 changed
lines) and `scripts/release_guard.py` (+79, passing). Running the root
producer shape (`coverage run --branch --source=scripts` over the focused
release battery) and piping `coverage.xml` through the gate reproduced the
failure exactly:

- **FAIL** — `scripts/promote_release.py: 86.5% of 327 changed lines
  (need 90%)`, 44 uncovered lines, all fail-closed rejection arms or GitHub
  seam bodies the existing CLI tests stub out. Exit 1.

## Repair: 20 tests, production untouched

`tests/test_promote_release.py` gains a fail-closed-seams section driving the
REAL seam bodies (fake `subprocess.run` under `_gh`; NDJSON `gh api`
fixtures): malformed-evidence type rejections (evidence/soak/binding/checks/
findings non-object arms, foreign soak schema, non-boolean
`invalidates_invariant`), `_gh` success + failure wrap, `_fetch_run_id`
parse/latest-success/fail-closed SystemExit, `_artifact_id` expired-skip +
missing-artifact SystemExit, `_load_json` unreadable SystemExit,
`record-evidence` present-but-empty dist arm, both subcommands' missing
repository-identity arms, `adopt-digests`' per-error loop, and the `__main__`
exit-code propagation via `runpy`. Delta recorded as `tests/: +20` in
`issue-89-diff-coverage-repair.md`. No gate, ledger, workflow or production
file changed; no exemption was added.

## Fresh validation (all at this round's commit)

- Diff-coverage gate after repair: **"ok: every measured file this change
  touches is at or above 90% lines / 80% branch arcs"**, exit 0.
- Focused release battery: **703 passed** (was 683; +20 new), plain and under
  coverage.
- "Validate ADR/spec front-matter" (registry.yml), all 7 steps with CI's
  arguments: registry/lifecycle tests **194 passed**; `tools/lint_lifecycle.py`
  ✓ baseline 0; `maistro_registry.cli lint . --strict` 447 files, 0 errors /
  0 warnings (199 baselined test-evidence debts);
  `RATCHET_BASE_REV=origin/develop scripts/check-citation-status-provenance.py`
  OK 0 exceptions; `check-adr-index.py` OK; spec-index regeneration zero diff
  (57 specs); `check-adr-status-language.py` ok 0.
- `check-suite-inventory.py`: **all 21 suites match** — 37257 collected
  identities (37237 + the recorded +20), no duplicates.
- `ruff check .` and `ruff format --check .` pass (3682 files).
- Lane-named vulture gate: `check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` — 1219 reviewed identities
  = 1219 findings, 0 unclassified; no ledger amendment warranted or made.
- `check-release-consistency.py`, `check-workflow-inventory.py` (33
  workflows), `check-workflow-write-safety.py` (33), `check-doc-links.py`
  (every relative link resolves) — pass.
- Gate-policy tests `tests/test_check_required_checks.py`,
  `tests/test_mutation_targets.py`, `tests/test_check_diff_coverage.py` —
  **141 passed**.

## Acceptance state

The repair closes the reproduced CI blocker on this branch. The issue's
operational acceptance criteria (a real candidate build, the four functional
soak checks plus #860's sustained exact-RC multi-replica workload, routing of
real findings, byte-equivalent final promotion through the protected
pipeline, and external package/image/signature/install verification) remain
**UNVERIFIED in this lane** for the reason the prior rounds documented: they
require program-owned release operations this lane must not perform, and the
promotion schema deliberately rejects synthetic evidence
(`scripts/promote_release.py:45-57` requires a `soak-evidence` Actions
artifact on the selected RC run). No gate was weakened to manufacture that
evidence. Writer handoff only — not integration approval, no issue closure,
no GitHub mutation.
