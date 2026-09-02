---
inventory-delta:
  tests/: +21
---
# fix-canonical-installer-repository-c5ee

Twenty-one new node IDs, all additive. Nothing removed or parametrized.

**`tests/test_installer_repository.py` (+20)** is the contract gate for the
public installers' canonical GitHub repository. It pins `get.sh`, `get.ps1`, and
the release workflow to `Agent-StrongHold/Project-mAIstro`, rejects stale
`maistro-engine` URLs, validates `MAISTRO_REPO` / `-Repo` overrides before
shell handoff, and exercises the override path against a fork without letting a
bad default slip through.

**`tests/test_release_guard.py` (+1)** asserts release notes link artifacts
against the canonical repository — ADR anchors and workflow paths must resolve
under `Agent-StrongHold/Project-mAIstro`, not the retired `maistro-engine` name.
