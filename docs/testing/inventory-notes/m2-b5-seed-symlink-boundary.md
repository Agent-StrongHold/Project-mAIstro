---
inventory-delta:
  packages/maistro-bootstrap/tests: +1
---

# M2-B5 — the seed never materializes what a worktree symlink points at

Round-40 repair on PR #1450 (issue #80, M2-B5). The M2-B1 develop-sync
(#2241, merged in `ec9dd31316`) replaced the index-driven seed (and its
indexed-path hardening from `l80-seed-path-replacement.md`) with a plain
host-side `tar` traversal (`tar -C repo .`), deleting the old sentinel tests
with the implementation they pinned. Under the new implementation the
"unrelated host secrets" half of the acceptance criterion ("the supported
Builder sandbox does not receive `.env`, `.git`, or unrelated host secrets
when seeding") is protected by tar's no-dereference default — but nothing
pinned that property anymore.

`packages/maistro-bootstrap/tests/test_container_sandbox.py::
test_seed_never_materializes_what_a_worktree_symlink_points_at` pins it as a
property of construction, on the production seed path (real `tar`, real
filesystem, production `ContainerBuilderSandbox` behind a real selector):
a worktree directory symlink to an external directory and a leaf symlink to
an external secret must both arrive in the seed **as symlinks**
(`stat.S_ISLNK` on the seed entries) — never as materialized copies. A
dereferencing seed (`tar -h`, `shutil.copytree(symlinks=False)`) fails the
assertions with the external secret materialized; teeth verified in a
scratch reproduction (production layout passes; `tar -h` layout turns
`link-dir` into a DIR and `leaf-link` into a REG file carrying the sentinel).

Suite inventory delta: `packages/maistro-bootstrap/tests` +1 node (278 → 279
collected on this host; CI's ubuntu-runner expectation moves 318 → 319 via
this note's delta). The pre-existing ~40-node host-vs-CI collection gap is
environmental and reproduces on untouched origin/develop (verified in
`l80-verifier-round39.md`); this change moves both sides by exactly one.
