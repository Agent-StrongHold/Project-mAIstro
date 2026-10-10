---
inventory-delta:
  tests/: +1
---
# Retire stale workspace-member dependency locks

Dependabot alerts #66, #69, #70, #71, #72, and #73 identify AnyIO in the
independent `maistro-evolve` and `maistro-registry` lock snapshots. Those files
record 13-package standalone graphs that omit the members' current
`maistro-core` dependency. The workspace has one 256-package resolution in
root `uv.lock`, already using AnyIO 4.14.2. Both member-directory
`uv lock --check` commands resolve that root graph. Repository install docs,
Dockerfiles, and the shared setup-uv action use the root resolution; no live
consumer references either nested lock path.

Remove the two obsolete snapshots instead of maintaining a second, invalid
resolution. Root lock and dependency manifests are unchanged. The new
regression test rejects independent lockfiles for configured workspace members;
it fails against the original tree. The existing root resolution is AnyIO 4.14.2, covering GHSA-82r6-8w77-94w6 (TLS hostname spoofing),
GHSA-3w57-8xmc-8v26 (supplementary child groups), and GHSA-5p39-cfhj-2xmp
(stderr draining). One test is added; no existing tests or gates are removed.

This is stale-input remediation, not an application runtime upgrade. GitHub's
alert closure remains to be verified after the fix reaches the default branch.
