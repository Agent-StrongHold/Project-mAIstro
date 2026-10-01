---
inventory-delta:
  packages/maistro-core/tests: +8
---

# #353 repair round — custom plan-dir installs and source-build image rollback

Follow-up to `auto-353-5ded.md`. Validation of the upgrade driver surfaced two
reachable gaps in the committed behavior, each closed with a regression test
plus the production fix it pins:

**Custom `--plan-dir` installs were invisible to `maistro upgrade`.** The
installer can materialize its plan artifacts outside the default
`.maistro-install` (`install.sh --plan-dir`), and it writes the manifest into
that selected directory. Discovery only reads the canonical
`<root>/.maistro-install`, so a custom plan-dir install upgraded as if no
manifest existed (git fell back to guessed compose defaults; archive was
rejected at preflight). Fix: the manifest gains a `plan_dir` field,
`install.sh` records it and leaves a pointer copy at the canonical location,
and `_Upgrade` resolves every compose-artifact path (override file, backup dir,
archive-swap carry, manifest refresh) through `plan_dir_for_root()`.

**A source-build rollback restarted the new images, not the previous release.**
`compose build` retags the fixed local image tags before cutover, so the
advertised post-cutover rollback (`down` + `up -d`) silently restarted the
failed release. Fix: the pre-upgrade images are snapshotted under
`*-pre-upgrade-rollback` tags before the build, restored before the
post-rollback `up -d`, and dropped once the upgrade commits. Additionally,
rollback now treats any cutover *attempt* (not only a successful one) as
having touched the stack — a failed `compose up -d` can still have recreated
services — and `rollback` was decomposed (`_rewind_source`,
`_restart_previous_stack`) to stay under the radon per-block threshold without
a ledger grant.

**`+8 packages/maistro-core/tests`:**

- `tests/cli/test_install_manifest.py::TestPlanDirResolution` (4): default
  resolution, relative and absolute recorded plan dirs, and the canonical
  pointer's discovery round-trip.
- `tests/cli/test_upgrade.py` (4): a custom plan-dir install's override file is
  honored by the compose args; the archive swap carries the recorded plan dir
  and the refreshed manifest round-trips to both the plan dir and the
  canonical pointer; a failing readiness probe after a source build restores
  the pre-upgrade image snapshot before the restart; a committed source build
  cleans the rollback tags up.
