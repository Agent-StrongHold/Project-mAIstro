# Issue 76 develop sync: merge origin/develop 157c3f61 (M1-E2) into auto-76

No inventory delta: the merge changes no test this branch owns. develop's M1-E2
tests arrive already counted — the merged tree collects 35,459 node IDs and
`check-suite-inventory.py` (full run) reports **21 suite(s) match the recorded
inventory**, so the staged `docs/testing/inventory/baseline.json` (develop's)
plus the existing notes already cover every count. Per the directory README, a
note with no front matter records no delta.

## What was merged and why

The branch tip `6eb523e44f` predates develop's M1-E2 convergence
(`157c3f61`, #1373), which independently landed a 2026-11-16 container-gate
repair touching the same six files this branch's own CI-repair round touched
(see `76-container-gate-repair.md`). The driver's launch preflight failed on
the resulting sync conflict (`git exited 1` on an unmerged index); this round
completed the in-progress merge (`MERGE_HEAD = 157c3f615bee…`) and resolved
all six conflicts in place.

Resolution rule: where both sides recorded the *same* fix independently, take
develop's side (trunk-proven, zero divergence); keep the branch's side only
where it was the superset. Ground truth for the one real semantic conflict —
the dockerclibuild stage — was established by cloning both release tags:

| vendored module        | v29.9.1 (branch patched) | v29.9.3 (develop) | advisory            |
|------------------------|--------------------------|-------------------|---------------------|
| go-jose/go-jose/v4     | 4.1.5 → patched 4.1.6    | **4.1.7**         | CVE-2026-116587, fixed ≥4.1.6 |
| golang.org/x/net       | 0.60.0 → patched 0.62.0  | 0.60.0 → patched **0.62.0** | CVE-2026-78661, fixed ≥0.62.0 |
| klauspost/compress     | 1.20.1 → patched 1.20.2  | **1.20.2**        | GO-2026-6865, fixed ≥1.20.2 |

v29.9.3 (commit `5457199`, asserted in the Dockerfile and verified against the
clone) vendors two of the three fixed upstream and needs only the x/net patch
develop already carries — so develop's dockerclibuild covers everything the
branch's 29.9.1 + three-patch variant covered, on the newer tag, byte-identical
to trunk. Both tags' commit assertions were verified from the clones
(v29.9.3 → `5457199`, v29.9.1 → `dfc520d`).

- `Dockerfile`, `Dockerfile.research` → develop's side (dockerclibuild 29.9.3 +
  x/net patch; identical base-image FROM digests both sides).
- `quality/image-pins.json` → develop's side: both lanes recorded the *same*
  refresh (3.13.18-slim-bookworm @ `a5a7017e…`, 3.12-slim @ `5e2bdb1b…`,
  recorded 2026-11-16, resolving CPython 3.13.18 / 3.12.16 per the independent
  verification round in `76-container-gate-repair.md`); develop's rows carry
  trunk provenance (`recorded_in: "#1373"`). The file is byte-identical to
  `origin/develop` after resolution.
- `tests/test_distribution_contract.py` → develop's side (same
  `["3.13.18", "3.13.18"]` assertion plus the CVE rationale comment).
- `deploy/sbx/template/Dockerfile.tests`,
  `packages/hive-conductor/tests/Dockerfile` → develop's side (both sides
  bumped only the digest; identical value).
- The branch's variant of all six files is preserved at
  `/tmp/l76-merge-salvage/*.ours` for this round and in git at `6eb523e44f`.

## Ledger integrity (AGENTS.md row-loss rule)

`git diff --numstat` of the merged tree against **both** parents for
`quality/`:

- vs ours (`6eb523e44f`): `image-pins.json` 4/4 (the two row rewrites, now
  identical to develop's) and develop's new `ac-state-notes/auto-62.json`.
  Nothing else.
- vs theirs (`157c3f61`): only `vulture-baseline.json` −2 rows, and the rows
  are the branch's own intentional deletions for identities the merged code no
  longer contains: `tools/sandbox/microvm.py::unused variable 'memory_mib'`
  (retired with the direct microVM surface, #76 cutover) and
  `sandbox/selector.py::unused method 'build_config'` (now called from
  production, so vulture no longer reports it). develop's rows for M1-E2's
  code are all preserved; no develop row was lost.

## Re-executed evidence (this host, this round, merged tree)

- `uv sync --locked --extra dev` exit 0; `uv lock --check` consistent
  (the auto-merged `uv.lock` resolves).
- `uv run ruff check .` exit 0; `uv run ruff format --check .` exit 0
  (3569 files).
- `scripts/check-image-pins.py` exit 0 (9 pins / 10 Dockerfiles registered).
- `pytest tests/test_distribution_contract.py`: 6 passed.
- Vulture gate, CI-exact arguments
  (`check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'`): exit 0, 1238 reviewed identities → 1236 findings.
- `scripts/check-suite-inventory.py` (full): ok, 21 suites match;
  35,459 collected node IDs, 0 duplicates.
- `pytest packages/maistro-core/tests/sandbox/
  packages/maistro-core/tests/extensions/test_sandbox_conformance.py`:
  258 passed, 38 skipped (host-capability skips).
- develop's M1-E2 surface on the merged tree: `pytest
  packages/maistro-core/tests/graph/durable_runs/
  packages/maistro-core/tests/a2a/
  packages/maistro-core/tests/graph/nodes/test_agent_delegate_remote.py
  packages/maistro-core/tests/runs/`: 2621 passed, 446 skipped, 4 xfailed;
  hive recovery (`test_dag_recovery.py`, `test_registered_dag_recovery.py`):
  28 passed.
- Live Kata (DOCKER_HOST set, `kata` runtime present in `docker info`):
  `test_kata_live_conformance.py` **10 passed / 0 skipped** (36.2s);
  evolve `benchmarks/test_sandbox_exec.py` **33 passed** (the file behind the
  prior round's check-3 failure — its Kata probe timed out without
  DOCKER_HOST; with it, green);
  `packages/maistro-server/tests/test_sigterm_shutdown.py` 3 passed
  (orphan-cleanup stop/restart).
- mypy (AGENTS-exact, 7 package trees): Success, 955 source files.

## Residuals (not repairable on this host, unchanged by this merge)

- **No local image rebuild:** the daemon host's root filesystem is at 100%
  (574 MB free; the same ENOSPC that killed a prior verify job mid-battery).
  Building any gate image here risks killing the host. The container-gate
  proof for this merge is structural instead: the resolved
  Dockerfile/Dockerfile.research/image-pins.json are byte-identical to
  `origin/develop`, whose exact configuration passed the "Container scan +
  SBOM + cosign" gate on trunk, and the vendored CVE fixes were verified from
  the upstream tag clones above. CI's fresh buildx run remains the final
  authority.
- **Three merge-queue checks were red at `6eb523e44f`** before this merge
  (check-run snapshot, 2026-11-16 15:53–16:42 UTC): "Coverage gate (publish-set
  floor + diff coverage)", "hive-conductor-e2e-ui", and the
  "integration-scope" aggregator that waits on them. Neither this merge nor
  the six resolved files can affect them (no test, no production line moved
  outside develop's own code). The diff-coverage half was proven green on the
  same implementation content in the earlier M2-A round; the publish-set floor
  needs the archive/postgres producers this host cannot safely run at 100%
  disk. The driver's named failure for this round ("Container scan + SBOM +
  cosign") is the *stale* one from the `d1ce53600c` evaluation that dropped
  the implementation diff — at `6eb523e44f` and in this merged tree that gate's
  inputs are trunk-identical.
