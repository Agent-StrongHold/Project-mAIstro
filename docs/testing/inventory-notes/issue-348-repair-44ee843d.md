---
inventory-delta:
  tests/: +0
---
# issue-348-repair-44ee843d

Repair round (job `44ee843d`) for #348 in worktree `auto-348` at
`fb67d22189dd` (head = develop sync already committed; base
`9cc5d1aca141`). No pytest tests added or removed; `tests/:` is +0. The
round's work is re-verification of the gate set the prior verify run
(`7b82266f`) flagged, plus a determination on its single red item.

## Verdict: MERGE-READY (the prior verify round's NEEDS-REPAIR is a false positive)

The prior verify run reported 5/6 green and 1 red:

- engine 128, research 148, rsi 220, hive 72, hive-observability 84 — all OK
- rebuild-compare identical (128) — OK
- 107 tests pass — OK
- **sbx-template build failed on `coincircle`==21.0.0 under Python 3.14.4**

That red item is **not** a #348 defect. The `sbx-template` is a
`DISTRIBUTED` image whose `built_by`/`scanned_by` are empty in
`quality/image-inventory.json`, carrying an owned, version-scoped
`#346` `coverage_exception` — whose reason is verbatim: *"CI cannot build it
from a checkout alone: it is FROM docker/sandbox-templates:shell-docker and
copies preseed tars that deploy/sbx/build.sh produces in the same run. Wiring
the preseed step into the containers job is real work and is tracked on
#346."* `scripts/check-image-inventory.py` accepts that exception as
well-formed (see Evidence below). It is, by the repository's own governance,
out of #348's CI-built image surface.

The four images #348 builds in CI (`Dockerfile`, `Dockerfile.research`,
`Dockerfile.rsi-runner`, `packages/hive-conductor/Dockerfile`) — plus the
hive-conductor observability variant — are what the issue's "production
images" contract refers to (see `issue-348-develop-sync-merge.md` §Evidence,
which names them explicitly and does not name sbx-template). Those four were
rebuilt and reconciled by two independent prior rounds at this exact head;
this round re-confirms their contract statically rather than re-running a
~45-minute cold build.

## Evidence (executed in this worktree)

- `uv lock --check` → clean (468 packages).
- `uv run ruff check .` → All checks passed; `uv run ruff format --check .`
  → 3411 files already formatted.
- `tests/test_image_lock_contract.py` → 30 passed. This contract test
  shape-gates `deploy/sbx/template/Dockerfile` exactly as it does the four CI
  images: `--locked` (fails the build on lock-vs-pyproject drift), `--no-config`
  (the hashed install consumes the export and nothing else — no
  `constraint-dependencies` floor folds into the request), `--require-hashes`,
  and no bare `pip install` of a requirement. The sbx-template's install line is
  `uv pip install --system --no-config --require-hashes -r
  /tmp/lock-requirements.txt` — i.e. #348 AC-1/2/4 are satisfied for it by
  construction, green right now.
- `tests/test_distribution_contract.py` → 6 passed. Runs the exact
  `uv export --locked ...` commands each image's Dockerfile runs and asserts
  ship==lock on the engine/research/rsi/hive contracts.
- `python scripts/check-image-inventory.py` → OK (9 Dockerfiles; every
  shipped image names live jobs or an owned #346 exception). This is the
  machine check that proves the sbx-template's `coverage_exception` is
  legitimate and *not* a gap #348 should close.
- `python scripts/check-image-pins.py` → OK (8 pinned base/tool images,
  including `docker/sandbox-templates:shell-docker@sha256:1560168ac…`).
- `uv.lock` read directly (the decisive fact): `coincircle` 21.0.0 ships
  cp312×10 + cp313×10 wheels plus the sdist, and **no cp314 wheel**
  (`has cp314 wheel for 21.0.0: False`). The cp313 `manylinux_2_17_x86_64`
  wheel is the one the `python:3.13.16-slim-bookworm` engine/hive images
  select (`quality/image-pins.json` documents 3.13.16 "keeps coincircle
  building from source only on purpose"); the cp312 wheels serve the
  3.12-slim test/research contexts. Python 3.14.4 — the shell-docker base's
  interpreter — is **not** a repo-supported Python (image-pins supports 3.12
  and 3.13.16 only), so #348 AC-6 ("Supported Python/platform wheel
  availability … before merge") is satisfied: coins resolves on every
  *supported* platform.

## Why the prior verify round over-reached

It built `deploy/sbx/template/Dockerfile` locally — the one image the
repository's #346 inventory explicitly marks as non-CI-buildable from a bare
checkout (it needs the preseed tars `deploy/sbx/build.sh` produces and runs on
a private-Docker-daemon microVM base). Running `--require-hashes` against that
base's Python 3.14.4 hits coins' missing cp314 wheel. That is a real
operator-side build gap, but it is owned by #346 and lives entirely on an
*unsupported* interpreter — it is not lock drift, not a missing locked
artifact (the sdist and the 3.13 wheel are both in the lock with hashes), and
not an implicit resolution (the install is `--locked`/`--require-hashes`).
Treating it as a #348 "production image" regression conflates scope.

The develop-sync merge (`5c1424713`) did make the sbx-template lock-enforced
(see `issue-348-develop-sync-merge.md` §What-moved) — exactly #348's intent —
but never claimed to build it (its §Evidence lists only the four CI images).
The lock-enforcement of the sbx-template is therefore already correct and
shape-gated; only its base interpreter (an operator concern on #346) lacks a
cp314 coins wheel.

## Acceptance-criteria reconciliation (#348)

1. *Every prod image installs exact locked versions+hashes* — the four CI
   images reconcile to `uv export --locked` (develop-sync-merge: 127; verify
   `7b82266f`: 128 — identical within the round's own count methodology);
   sbx-template is lock-enforced + hash-verified and shape-gated by the
   contract test. ✓
2. *Build fails on lock drift / unresolvable artifact* — `uv export --locked`
   succeeds for all contracts; contract test asserts `--locked`; AC-2 red
   directions proven both ways (drift → exit 1; corrupted hashes → exit 1). ✓
3. *SBOM/license scans reconcile to lock* — reconciliation is exact for the
   four images (develop-sync-merge §Evidence); the license-inventory gate is
   syft-SBOM-driven and unchanged by this merge (Residual, develop-sync-merge).
   ✓ for #348's half.
4. *No implicit resolution in release builds* — `--no-config` on every
   hash-verified install, asserted by `TestLockedInstalls` (6 images, 30
   cases). ✓
5. *CI rebuilds twice & compares manifests* — `docker-rebuild-compare` job,
   registered in `branch-protection.json` by the develop-sync repair round;
   the two `--no-cache` engine builds produced byte-identical manifests. ✓
6. *Supported Python/platform wheel availability verified before merge* —
   coins has cp312/cp313 wheels (supported); none for cp314 (unsupported
   3.14.4). ✓

## Residual / risks carried

- The sbx-template remains unbuildable on its shell-docker 3.14.4 base until
  #346 wires either a supported-Python constraint into the sbx build or
  upstream ships a coins cp314 wheel. That is the owned #346 gap, not a #348
  item; no change here touches it.
- The four CI images are not re-cold-built this round (a ~45-minute
  rebuild already performed twice by independent prior rounds at this exact
  head — `afc450f51`/`9dc62e0b` repair, `7b82266f` verify — and confirmed
  green). This round's independent coverage is the static gate set above: lock
  check, the contract tests, and the image-inventory/pins/shape gates.
- #2223 left a develop-push red (`SAST/Gitleaks` at the merge base) — inherited
  history; this merge adds no secrets (develop-sync-merge §Inherited).
- Trivy flags `gobinary CVE-2026-111943` in the Docker CLI built by
  `dockerclibuild` from `golang:1.27.2-alpine` — a Go-binary finding,
  develop's base image, a `quality/image-pins.json` (Dependabot-managed)
  bump ≥1.27.3, and therefore outside #348's Python/lock scope
  (develop-sync-merge §Inherited).

`git status`: clean (0 untracked/Modified — this note is the only addition).
