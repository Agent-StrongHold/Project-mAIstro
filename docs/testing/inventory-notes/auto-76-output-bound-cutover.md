---
inventory-delta:
  packages/maistro-bootstrap/tests: +0
---

# auto-76-output-bound-cutover

`test_container_sandbox_output_bound.py` still pinned the removed private
Docker path (fake `docker` on PATH + `_cid` bypass), so it failed everywhere
the #76 cutover landed ("ContainerBuilderSandbox used outside its context
manager" — the `_require_live` guard replaced the `_cid` check). Rewritten for
the canonical-substrate seam: 7 tests replaced 7 tests (count unchanged), now
pinning the adapter-side half of the #1197 output-bound contract — spawned
config carries bounded per-stream retention, over-limit (125) / timeout (124)
statuses survive the merge without laundering or fabricated notices, output
crosses verbatim, missing files raise through the bridge, and `edit_file`
fails closed on an ambiguous match. Bounding enforcement itself lives in the
backends and is pinned in `packages/maistro-core/tests/sandbox`.
