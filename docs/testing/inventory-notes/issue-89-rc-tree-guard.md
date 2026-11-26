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

## Writer validation checkpoint — job `79e1cf64459449e486a4af0d24366a60`

Starting HEAD: `3268605879822bd5b9ee9eb7fd69db2feac1bd74`, branch `auto-89`,
clean worktree. Scope frozen to #89 and the supplied dispatch snapshot; no
live GitHub queries or mutations. The preceding job `f642fd40c32e48f0b8475a0aca611552`
exited with `worker_error` before executing checks, not a demonstrated source
failure. This job supplied no driver `check-*.log` files either.

Re-read repository instructions, accepted ADR-073126-c4e1 and ADR-095, the
entire shipping workflow, release guard and adjacent tests. ADR §6 requires
shipping the artifacts the last RC validated; ADR-095 allows a different
promotion merge commit. The existing tree comparison correctly accommodates
that distinction, but is not artifact/configuration-bound soak proof. No
runtime execution, scheduling, event or authorization authority is changed.

Freshly executed at the starting HEAD (not inherited verification claims):

| Command | Outcome |
|---|---|
| `uv sync --locked --extra dev` | exit 0; 218 installed packages checked |
| `uv run pytest tests/test_release_guard.py tests/test_check_release_consistency.py tests/test_check_image_inventory.py -x -q` | **139 passed**, 1.34s |
| `uv run ruff check .` | exit 0 |
| `uv run ruff format --check .` | exit 0; 3484 files formatted |
| `uv run python scripts/check-release-consistency.py` | exit 0; released none, shipping 0.9.0, working toward 1.0.0 |
| `uv run python scripts/check-image-inventory.py` | exit 0; 9 Dockerfiles inventoried |
| `uv run python scripts/check-workflow-inventory.py` | exit 0; 31 workflows dispositioned |
| `uv run python scripts/check-suite-inventory.py` | exit 0; 21 suites, 34136 unique test identities, no duplicates |
| `git tag --list 'v*'` | no local release tags |
| Local evidence paths | `scripts/soak` and `docs/testing/soak` absent |
| `git diff --check` | exit 0 before this documentation-only update |

Logs are retained as `validation-{sync,release-tests,gates,inventory}.log` in
`/home/dev/maistro/jobs/79e1cf64459449e486a4af0d24366a60/`. No tests were added
or removed; the existing inventory delta above remains unchanged.

### Acceptance recheck — BLOCKED

All eight issue criteria remain **UNVERIFIED end-to-end** in this attempt:

1. Candidate-only artifacts: workflow checkouts/build logic inspected; no
   designated candidate artifacts were built or supplied.
2. Clean install/model/security/restore soak: not executed against an RC.
3. Exact-RC sustained multi-replica/crash/fencing/pressure/duplicate-work soak:
   not executed. Frozen dispatch (2026-11-26T16:55:15Z) records child PR #1672
   open/unmerged at `edbc2f4e43f3d094baa7e569498a66d4c6869986`, with 75 successful,
   3 failed and 3 skipped check-runs. Failures are Quality gate, test, and
   Documentation links. Those are snapshot observations, not freshly run CI.
4. Earlier-invariant finding routing: no load experiment or issue mutation
   performed; cannot certify filing/reclassification from local unit tests.
5. New RC after runtime/config changes: existing real-git negative cases pass
   for committed source/config/mode drift; external configuration changes and
   renewed applicable soak are not proven.
6. Final/soaked-RC equivalence: mandatory latest-RC tree guard passes its tests;
   no actual final/soaked-RC pair exists locally. More importantly,
   `.github/workflows/release.yml:273` rebuilds wheels and `:492`/`:532` build
   fresh images on **both** RC and final runs. The digest-preserving promotion
   at `:678` preserves that run's scanned build, not the earlier soaked RC's
   artifacts. Equal trees do not close this ADR §6 gap.
7. External package/image/signature/install verification: not executed. The
   workflow's cosign verification at `:729` is a mechanism, not evidence of
   an externally verified release in this attempt.
8. Machine-readable artifact/config-bound soak evidence: none supplied or
   generated; local test/inventory logs do not substitute for it.

No speculative repair was made: changing the source guard or fabricating a
soak manifest would not address these missing operational proofs. Preserve
this lane's existing repair; next owner must establish an exact-RC artifact
reuse path under the sole shipping workflow, designate immutable RC/config,
complete #860 and product soak, then perform authorized release and external
verification. No approval, publish, tag push or integration action was taken.

Checkpoint: `{checked: 8, done: 0, skipped: 0, errors: 0, next: exact-artifact
promotion implementation and authorized RC/soak/release evidence}`.
