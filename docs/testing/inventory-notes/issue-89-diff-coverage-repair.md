---
inventory-delta:
  tests/: +20
---

# Issue #89: cover the fail-closed promotion seams the diff-coverage gate named

## Reproduced gate failure (not a scanner guess)

The merge-queue/PR evaluation of #2536 at head `5f6bff7d458f6d24f80a46a84983b6cf1b61ca1f`
(run 45893503850, job 140175737147) red **"Coverage gate (publish-set floor +
diff coverage)"**, the only failed required check on that head. Reproduced
locally with CI's exact gate mechanics at this branch's head:

- root producer shape: `uv run coverage run --branch --source=scripts -m pytest
  <focused release battery> --timeout=60 -q`, then `coverage xml`;
- `uv run python scripts/check-diff-coverage.py coverage.xml --base 8d8f10616f`
  (the current `origin/develop` tip; `git merge-base` is `69b41dd3af`, so the
  three-dot diff is exactly the branch's own changes — the same set the next
  PR/merge-queue evaluation scores) — **FAIL**: `scripts/promote_release.py:
  86.5% of 327 changed lines (need 90%); uncovered 244, 251, 252, 261, 265,
  288, 289, 308, 309, 312, 313, 315, 317, 321, 342, 344, 376-379, 440, 448-451,
  454, 458, 466-470, 476-477, 491-492, 523-524, 564-565, 569-571, 688`.

Every named line is a fail-closed rejection arm the existing tests never
reached because they stub the GitHub seams (`_fetch_run_id`, `_artifact_id`,
`_download_artifact`) wholesale: malformed-evidence type rejections
(`validate_evidence`/`validate_soak`/binding/checks/findings non-object arms,
foreign soak schema, non-boolean `invalidates_invariant`), the `_gh` wrapper's
failure path, `_fetch_run_id`'s parse + fail-closed SystemExit, `_artifact_id`'s
expired-skip and missing-artifact SystemExit, `_load_json`'s unreadable-file
SystemExit, `record-evidence`'s present-but-empty dist arm, both subcommands'
missing repository-identity arms, `adopt-digests`' per-error `::error::` loop,
and the `__main__` entrypoint's exit-code propagation.

## Repair: tests only; production and gates unchanged

Twenty tests appended to `tests/test_promote_release.py` drive the REAL seam
bodies with GitHub access injected one layer lower (fake `subprocess.run` for
`_gh`, NDJSON fixtures for `gh api` output), asserting each rejection message
and exit path. `scripts/promote_release.py`, `scripts/release_guard.py`,
`.github/workflows/release.yml` and every gate script are untouched. The
promotion evidence schema is unchanged; no gate is weakened and no line is
exempted.

## Verification

- Focused battery after repair: `uv run coverage run --branch --source=scripts
  -m pytest tests/test_promote_release.py tests/test_release_guard.py
  tests/test_check_release_consistency.py tests/test_check_compliance.py
  tests/test_check_license_inventory.py tests/test_release_publish_metadata.py
  tests/test_soak_compose_pressure.py tests/release/
  tests/test_verify_wheel_imports.py --timeout=60 -q` — **703 passed**
  (683 before + 20 new).
- Same coverage run piped through the gate: **"ok: every measured file this
  change touches is at or above 90% lines / 80% branch arcs"**, exit 0 — the
  reproduced failure no longer reproduces.
- Suite inventory: `tests/` count moves by +20 (683→703 in the release subset;
  root-suite identities +20), recorded in the front matter above.
