---
inventory-delta:
  tests/: +66
---
# 406-dependency-namespaces

Issue #406: `pytoniq-core-fork` — the locked identity stack's transitive
dependency (`maistro-core[identity]` → `bip-utils`) — installs a generic
top-level `examples` namespace package (`examples/boc/*`,
`examples/hashmaps/dict.py`, `examples/tl/*`, `examples/tlb/*`) into every
environment that resolves it. The +42 collected node IDs in `tests/` are
`tests/test_dependency_namespaces.py`, which holds
`scripts/check-dependency-namespaces.py` and
`scripts/prune-dependency-namespaces.py` to their contract:

- the gate inventories every top-level importable name each installed
  distribution contributes, from `*.dist-info/RECORD` — packages, namespace
  portions, bare modules (keyed by import name, extension stripped), and
  top-level extensions; installer metadata, wheel data trees, scheme
  directories, `.pth` config, and extensionless root files are excluded with a
  stated reason, and a distribution with no RECORD is a finding, not silence;
- generic names (`examples`, `tests`, `utils`, ...) from a dependency are
  rejected unless `REVIEWED_NAMESPACES` names exactly that (name,
  distribution) pair — the review is distribution-keyed, so a second
  distribution shipping a reviewed name is a new unreviewed event;
- two distributions contributing one top-level name is a collision finding
  unless the split is reviewed (`jaraco`, `google`, `opentelemetry` are
  upstream-coordinated PEP 420 namespace splits — verified against the pinned
  wheels — and `py` is accepted, owned debt: pytest's bare `py.py` shim vs the
  legacy `py` distribution the rsi-runner's unpinned fitness tools pull,
  #348); a namespace-split review dies the moment a contributor ships a
  regular `__init__.py`, and the `py` debt dies the moment a third
  contributor appears;
- any non-entitled distribution contributing a `FIRST_PARTY_OWNERS` name is a
  `first-party-shadow` finding with no review escape; a test holds that map
  against the real `packages/*/src` trees so it cannot drift from the
  workspace;
- the shadowing claim itself is proven with a real interpreter: a first-party
  regular package beats a dependency's namespace portion from any
  `sys.path` position, and the dependency's payload cannot leak into it;
- the real synced environment is scanned by a subprocess test (the dev/CI
  disposition is real, and `examples` is attributed to exactly
  `pytoniq-core-fork`);
- the prune deletes exactly the rows the target distribution's RECORD lists
  — file-by-file, never an `rmtree` of the shared namespace directory, which
  would destroy a co-owner's files — rewrites the RECORD (so the syft SBOM
  keeps recording `pkg:pypi/pytoniq-core-fork` with the patched file
  inventory), is idempotent, is keyed to the distribution, and passes through
  when the distribution is absent;
- the wiring tests hold the mitigation in place: both shipped images
  (Dockerfile, packages/hive-conductor/Dockerfile) and the RSI runner prune
  and re-check in `--production` mode in one build layer, Dockerfile.research
  stays off the `identity` extra (adding it fails the test until the prune
  arrives), and ci.yml runs the gate on the dev environment and asserts the
  built images have no importable `examples`;
- the repair wiring holds the prune tool reachable to
  `scripts/check-reachability.py`'s import graph: the scanner roots tooling
  from workflow text only, and the prune runs from the shipped-image
  Dockerfiles, so the gate names it at runtime (`PRUNE_TOOL_STEM`, printed in
  the `pruned-present` finding and the report remediation) and a test holds
  that edge with the scanner's own `_tooling_edges` — dropping the reference
  re-banks a live tool as a new unreachable identity and fails here, named;
- the merge-queue repair round raised the two scripts to the diff-coverage
  floor (90% lines / 80% branch arcs, per file) and the new tests caught a
  real deletion-escape while doing it: a hostile RECORD row like
  `examples/../../outside.txt` sailed past `relative_to` (which compares parts
  lexically and keeps `..`), so `_delete_payload` now resolves each candidate
  and requires containment in the scanned site-packages before unlinking —
  mirroring the scanner's treatment of the same row as an inventory escape.
