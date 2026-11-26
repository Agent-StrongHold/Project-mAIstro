---
inventory-delta:
  tests/: +11
---

# Issue #89: fail closed on RC-to-final source-tree drift

Scope: the existing release guard and its shipping-workflow invocation only.
ADR-073126-c4e1 §6 requires final artifacts validated by the last RC; ADR-095
permits a different promotion merge commit on `main`. Compare git **trees**,
not commit IDs, against the numerically latest same-version candidate.
No metadata exception is granted: even mode/config/documentation differences
require a new candidate. Candidate tags themselves still build without any
previous candidate. No competing runtime execution authority is introduced.

Eleven new collected cases exercise the CLI with real temporary git repositories
(and one workflow-wiring test): identical trees on different commits; absent
same-version RC; runtime/configuration/executable-bit changes; rc10 vs rc2
selection without fallback; lightweight RC; missing final ref; wrong checkout;
first RC; mandatory shipping invocation before builds.

This is a necessary source-integrity check, **not proof** of sustained soak,
artifact byte identity across rebuilds, signature/install success, or a release
approval. The shipping workflow still rebuilds final wheels/images; exact-RC
artifact/config-bound evidence and external execution remain required for #89.

## Focused validation

Executed in `auto-89`, not inherited from previous verification claims:

- Before implementation: the missing-candidate CLI test and workflow-wiring
  test both failed (`2 failed, 33 deselected`); the flag and invocation did
  not exist.
- `uv run pytest tests/test_release_guard.py tests/test_check_release_consistency.py tests/test_check_image_inventory.py -x -q`
  → **139 passed**.
- In-memory mutation of only `verify_rc_tree` to return success (no tree edits):
  missing RC, three runtime/config/mode cases, and latest-RC selection all
  failed (**5 failed, 30 deselected**). This proves the negative cases detect
  a bypassed promotion check, not merely a missing CLI option.
- `uv run ruff check .` and `uv run ruff format --check .` → exit 0.
- `uv run python scripts/check-release-consistency.py`,
  `scripts/check-image-inventory.py`, `scripts/check-workflow-inventory.py`
  → exit 0 each.
- `uv run python scripts/check-suite-inventory.py --suite tests/` → exit 0;
  **5885** collected root tests match the inventory, including these eleven cases.

- Coverage rerun of `tests/test_release_guard.py` → **35 passed**; XML
  reports `release_guard.py` at **96.04% lines / 88.89% branches**. The
  `check-diff-coverage.py --base e0b427fefa8c252b28881731f97a8179d0065574`
  command exited 0 but measured **zero files** (scripts are outside its
  measured scope), so that gate is not additional coverage proof here.
- `git diff --check` → exit 0.

Raw logs are retained in job
`8f98fc5ca26143489617901cda699d23`; no driver `check-*.log` files were supplied.
No release tag push, publication, environment approval, or remote mutation was
performed. All tags made by tests exist only in pytest temporary repositories.

## Acceptance handoff — BLOCKED, not integration approval

The assigned issue remains incomplete. Local `git tag --list 'v*'` returned no
release tags; `scripts/soak` and `docs/testing/soak` are absent in this checkout.
Those are local observations, not claims about unseen remote releases. Frozen
dispatch evidence records #860 open and its PR #1672 open/unmerged at
`edbc2f4e43f3d094baa7e569498a66d4c6869986` (**not draft**); older verification
notes claiming it is draft are historical, not current evidence.

| Issue #89 criterion | This attempt's evidence |
|---|---|
| Candidate-only RC artifacts | UNVERIFIED: no candidate artifacts built or designated in this attempt. |
| Clean install, real-model, security, backup/restore soak | UNVERIFIED: not executed; release fixture tests are not product soak. |
| #860 exact-RC sustained multi-replica/crash/fencing/resource/duplicate-work coverage | UNVERIFIED: no exact-RC workload executed here; child PR remains unmerged in the frozen dispatch. |
| Findings reclassified to earliest broken invariant before promotion | UNVERIFIED: no load findings or promotion in this attempt; no issue mutations permitted. |
| Runtime/config changes force new RC and applicable soak | PARTIAL: real-git tests reject committed source/config/mode drift; external runtime configuration and renewed soak remain UNVERIFIED. |
| Final tree byte-equivalent to soaked RC | PARTIAL: mandatory production guard compares latest same-version RC trees and permits different commit IDs; actual final/soaked-RC equality remains UNVERIFIED. |
| External package/image/signature/install verification | UNVERIFIED: no publish, remote verification, or approval performed. |
| Machine-readable artifact/config-bound soak evidence | UNVERIFIED: not supplied or generated; tree equality is not soak evidence. |

Residual production gap: `release.yml` still builds wheels and container images
again for a final tag rather than reusing the exact soaked RC artifacts. Equal
git trees alone cannot establish artifact equivalence (build metadata, time,
network resolution, and runtime configuration are separate inputs). Do not
promote on the strength of this guard or its passing tests. An authorized
release operator must designate immutable RC artifacts/configuration, complete
#860 and the install/model/security/restore checks, and verify exact-artifact
promotion plus external signatures/install. This worker cannot perform those
publishing/approval actions under its no-GitHub-mutations assignment.

Progress: `{checked: 8, done: 0, skipped: 0, errors: 0, next: exact-artifact
promotion and operator-designated RC/config → complete soak → external checks}`.
One independently testable source-integrity repair is complete; none of the
eight milestone criteria is claimed fully proven.
