---
inventory-delta:
  tests/: +7
---

# Dockerfile COPY mode normalization guard (#2546)

`tests/test_dockerfile_copy_mode_normalization.py` (7 node IDs) holds the
#2546 image contract closed statically, no Docker/network/build: a build
context checked out under a restrictive umask (e.g. 077) carries mode-600
files into the image, because `COPY` preserves host file modes — and the
shipped images drop to a non-root runtime user, which then cannot read
`alembic.ini`, the agent YAML, or the migrations (the issue's
`No 'script_location' key found in configuration` entrypoint failure). Each
final stage that COPYs from the host context — the engine `Dockerfile`,
`packages/hive-conductor/Dockerfile`, and the sbx seed template
`deploy/sbx/template/Dockerfile` — must run exactly one
`RUN chmod -R a+rX <tree>` normalization step that (a) covers every
host-context COPY destination of the stage, (b) runs after the last of them,
and (c) runs before any non-root `USER` drop. The parser folds backslash
continuations and excludes `--from=` COPYs (build-stage modes, not host
modes); `Dockerfile.research` is out of scope by reviewed decision (its
final stage chowns the tree to the runtime user itself).

Two controls keep the guard honest: a fail-before control rebuilds each
stage with the normalization step stripped and asserts the contract rejects
it (so the assertions cannot pass for a wrong reason), and
`Dockerfile.rsi-runner` — whose final stage copies only from a builder stage
— is pinned to stay that way, so a future host COPY there fails loudly
instead of silently reintroducing the defect class. The mechanism itself was
demonstrated on the real builder during the fix (mode-600 context file ->
`Permission denied` for uid 65532; same context + the chmod step ->
readable), recorded in the test module docstring and the inline Dockerfile
comments. The bind-mount half of #2546 (init-db.sql /
init-replication.sh keep host modes through the mount) is documentation at
the mount sites and README, deliberately not a Dockerfile contract.

No existing test was removed, renamed, or re-counted; `tests/` gains one
suite with 7 node IDs.
