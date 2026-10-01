---
inventory-delta:
  packages/maistro-core/tests: +76
---

# #353 — `maistro upgrade` targets the installed repository and rebuilds artifacts

`maistro upgrade` previously ran `git pull` / `uv sync` in the caller's current
directory, reported success for tag/archive installs where the pull failed, and
never rebuilt Compose images. This change gives every supported install type an
explicit, transactional upgrade path driven by durable install metadata.

**`packages/maistro-core/src/maistro/cli/_install_manifest.py` (new)**: the durable
`install-manifest.json` (written by `install.sh`/`get.sh`, wired in the same
change) records `install_type` (git/tag/archive/package/container), the
authoritative `install_root`, ref/revision/image-tag provenance, and the source
URL. `locate_install_root()` resolves the target from that metadata — env
override, parent walk for a manifest or engine checkout, then the default
`~/.maistro` locations — never from the ambient CWD.

**`packages/maistro-core/src/maistro/cli/_upgrade.py` (rewritten)**: a
per-type, phase-ordered driver (`update-source → sync-deps → build-artifacts →
verify-assets → cutover → verify-readiness`) with preflight backup and rollback
on any failure. Images are rebuilt (`compose build`) or pulled and verified
(`docker inspect` / `compose images`) before cutover; readiness is proven by a
health probe plus a per-type version probe (exact tag / HEAD / swapped-in
manifest version / in-image `maistro.__version__`). Archive swaps are
rename-based (`mv` to a retained `<root>.upgrade-old`) so rollback can restore
the previous release wholesale; `rm -rf` is never aimed at the live tree.

**`+76 packages/maistro-core/tests`** (net; 82 collected in the two touched
files, 6 removed with the old CWD-bound tests):

- `tests/cli/test_install_manifest.py` (new): install-type detection, manifest
  round-trips, and root location from unrelated directories for every default
  and override path.
- `tests/cli/test_upgrade.py`: per-type command vocabulary and ordering, all
  driven from an unrelated CWD; transactional guarantees (a failing step never
  prints success and rolls back; preflight failures run no external command);
  regression tests for bugs found while validating this change — the
  manifest-less-checkout `assert` crash, the concatenated-`rm -rf` archive swap
  (which destroyed the install root), the invalid `compose build --pull never`
  flag, and the `.git`-less archive version probe. One test executes the swap
  and rollback with a real shell in `tmp_path` to prove the composed bash, not
  just its vocabulary.
- Gate-repair round additions (+41): the module lives at
  `maistro/cli/_install_manifest.py` — underscore-internal like its CLI
  siblings (`_install.py`, `_upgrade.py`), which is what keeps it out of the
  top-level `CORE_PUBLIC_SURFACE` enumeration instead of claiming public API.
  Two vulture-flagged helpers that no code path reached were deleted
  (`git_latest_tag`, `git_remote_url`: the upgrade flow is deliberately
  subprocess-vocabulary, and the installer records the remote in shell), the
  never-called `install_root` field validator became a reachable
  normalization at the load boundary (a hand-edited `~`/relative root can no
  longer leak into target resolution), and the previously write-only
  `schema_version` field is now genuinely read: a manifest from a NEWER
  installer is treated as absent so the caller reports "no install found"
  instead of misparsing unknown fields. New coverage: packaged/container
  provenance detection (manifest file, corrupt file, booted-container env,
  `importlib.metadata` package detection and its checkout exception),
  subprocess-boundary semantics (transient-failure retries, missing-binary is
  permanent, timeout partial output coercion), compose-runtime resolution,
  preflight rejections per type, rollback with a vanished tree (which
  hardened `restore_config` to recreate the root/plan dir instead of
  crashing mid-rollback), and success reporting without git metadata.
