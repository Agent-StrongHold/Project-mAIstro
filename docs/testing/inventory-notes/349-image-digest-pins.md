---
inventory-delta:
  tests/: +38
---
# 349-image-digest-pins

Issue #349 pins every base/tool image reference in the repository's
Dockerfiles by immutable digest and adds the gate that keeps them pinned. The
+22 collected node IDs in `tests/` are `tests/test_check_image_pins.py`, which
holds `scripts/check-image-pins.py` to its contract:

- `:latest` is rejected everywhere — explicit (`python:latest`) and implicit
  (a bare image name), including a `:latest` tag that is technically immutable
  because a digest rides along (that is not a reviewable version annotation);
- an unpinned base fails in a release-scope Dockerfile (PUBLISHED/DISTRIBUTED
  per `quality/image-inventory.json`) and needs an owned, issue-numbered
  exemption even in an INTERNAL one — mirroring the inventory gate's coverage
  exceptions;
- every digest pin must be registered in `quality/image-pins.json` with the
  exact image, tag and digest, and every registration must name exactly the
  Dockerfiles that use it (`used_by` drift and unused rows both fail), so a
  base update can only land as a reviewable registry-plus-Dockerfile change;
- stage references (`FROM builder`, `COPY --from=0`) are not external images;
- `--base-digests` enumerates the pinned refs (release.yml's provenance check
  consumes this) and refuses unpinned ones;
- `--verify-attestation` proves a cosign-downloaded SLSA attestation names
  every pinned base digest, fails when one is missing, and fails loudly on
  input that is not cosign output — never vacuously. Only structured SLSA
  `resolvedDependencies` digests count: a non-provenance attestation (SBOM,
  license) or free-text mention of the digest cannot vouch for a base;
- a `FROM` alias identical to its base (`FROM ubuntu AS ubuntu`) is still an
  external image — the alias registers only after the ref is classified;
- `FROM 0` (a digit naming the not-yet-declared first stage) is an external
  ref, not silently skipped;
- an exemption must carry `owner`, `issue` and `reason`, and can only shield
  INTERNAL images — a PUBLISHED/DISTRIBUTED Dockerfile must pin, period;
- `ARG` defaults resolve `$VAR` references, and an unresolvable one is a
  recorded parse error, never a silent skip (same fail-closed rule on the
  `COPY --from` side, and for registry rows with malformed digests or
  duplicate rows for one image+digest);
- the attestation reader skips NDJSON separator blank lines and dependency
  entries that are not objects (schema drift cannot crash the gate, and a
  non-object entry cannot stand in for a digest), and fails with the path
  when a Dockerfile has no pinned bases or the attestation file is missing;
- the CLI surface release.yml drives (`--base-digests`,
  `--verify-attestation` with and without `--dockerfile`, and the bare
  invocation) dispatches correctly, and `python scripts/check-image-pins.py`
  (run via `runpy` under `__main__`) ends-to-end passes on the shipped tree —
  every shipped Dockerfile pinned and registered in the same breath;
- Copier conditional filenames (`{% if %}Dockerfile{% endif %}.jinja`) are
  discovered by name containment, so shipped scaffolds cannot sit outside
  the gate (the single-tenant template is pinned in `quality/image-pins.json`).

The negative tests assert on the gate's actual failure text, so a reworded
message cannot silently stop describing the violation.

## Repair-round validation log (2026-10-02, head 21b137fa5)

The prior CI failure (run 36794778316: `check-image-pins.py` at 84.6% of its
changed lines) is closed by 05f77af80 and re-proven locally against the
develop base 4df9dd9bd:

- `coverage run --branch --source=scripts` over the four root test files that
  exercise the two changed scripts (61 passed), then
  `check-diff-coverage.py coverage.xml --base 4df9dd9bd` -> ok; per-file:
  `scripts/check-image-pins.py` 267/267 changed lines (100%) at 98.3% branch
  rate. The publish-set floor is untouched by this branch (no
  `packages/*/src` changes; the floor's producers measure only those trees).
- `python scripts/check-image-pins.py` -> exit 0 on the shipped tree (9 pins,
  10 Dockerfiles); the scan set equals the full `find -name '*Dockerfile*'
  population minus the one `.dockerignore`, so no Dockerfile sits outside the
  gate.
- Fault injection in a sandbox copy: `FROM python:latest`, a tag-move digest
  absent from `quality/image-pins.json`, and an unpinned tag in a PUBLISHED
  Dockerfile are each rejected with the gate's own error text and exit 1.
- `--base-digests Dockerfile packages/hive-conductor/Dockerfile` enumerates
  all four release base digests (release.yml's attestation check input).
- Live registry inspection of the python pin: the digest resolves to an OCI
  image **index** (`application/vnd.oci.image.index.v1+json`) with per-arch
  manifests — the manifest-list claim behind deterministic platform
  resolution holds against the real registry.
- Adjacent gates green: check-image-inventory, check-ratchet-provenance,
  vulture ratchet (1371 identities, no unbanked), ruff check + format,
  tests/test_prepull_copy_sources.py + tests/test_check_diff_coverage.py.

## Repair-round validation log (2026-10-02, merge e4a614e05)

The named CI failure for this round was the `test` job (ci.yml), red on the
merge-queue tree while the branch head itself was clean. Cause: develop moved
ahead — 4e50b46153bd (PR #1709) landed the same #349 content this branch
carries, plus the M7-A3 eval-on-Run work. Resolution: merged origin/develop
(clean — `git merge-tree --write-tree` reports no conflicts, and the shared
#349 files are byte-identical on both sides), then re-ran the whole `test`
job battery locally on the merged tree:

- root suite `tests/ --ignore=tests/tools/registry`: 4103 passed, 126 skipped
  (includes the 38 image-pins gate tests and the shipped-state self-checks);
- `packages/maistro-core/tests`: 11236 passed, 765 skipped, 1 xfailed
  (covers the merged M7-A3 `tests/runs/test_eval_on_run*.py`); bootstrap +
  server + canvas: 1149 passed; turing + turing-backend + design + rsi +
  evolve: 2345 passed; the single-process cross-suite step
  (`tests/` + hive-conductor backend + design): 7807 passed;
- `scripts/check-suite-inventory.py` -> ok (14 suites match);
- `scripts/check-image-pins.py` -> exit 0 on the merged tree (9 pins,
  10 Dockerfiles); `check-ratchet-provenance.py` -> all 9 ratchets OK
  against base 4e50b46153bd; `check-image-inventory.py` -> ok;
- fresh sandbox fault injections re-proved all three rejection classes on
  the merged tree, each with the gate's own error text and exit 1:
  `python:latest` tag annotation, unpinned tag in the PUBLISHED root
  Dockerfile, and a digest absent from `quality/image-pins.json`;
- live registry HEAD of the pinned python digest still resolves to
  `application/vnd.oci.image.index.v1+json` at exactly the pinned digest
  (deterministic multi-arch resolution), and both Copier templates plus all
  release Dockerfiles carry `name:tag@sha256:<digest>` pins;
- ruff check + format --check green (2728 files).

No production code changed in this round: the only tree change is this
branch now containing develop's 4e50b46153bd as an ancestor.
