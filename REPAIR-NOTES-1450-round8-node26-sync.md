# Repair notes — issue #1450 round 8 (develop sync to d0e8e235a8, #2120 node 26-alpine)

Branch `auto-80`. Head before this round: `c11c61136a` (round 7). The prior
attempt (`cb5b46df`) died 0.8 s in on a provider model-deprecation error and
performed no work; an earlier crashed attempt left a mid-flight
`git merge origin/develop` with one unresolved conflict. This round completes
that merge, re-proves every gate at the merged head, and re-verifies the
issue-#80 acceptance anchors against reachable behavior. Nothing is trusted
from prior rounds' claims.

## Develop sync (merge commit `10f96ad501`)

`origin/develop` advanced one commit past the round-7 base: `d0e8e235a8`
("Build(deps): bump node from 22-alpine to 26-alpine in /packages/hive-conductor
(#2120)"), which also carries #2120's own repair stack (CPython 3.13.18 /
3.12.16 pin refresh with re-resolved digests, docker-CLI v29.9.3 with
go-jose/klauspost/x-net vendored fixes, research-image trivy lock bumps,
frontend lock refreshes, and the node 26-alpine digest registration).

Single conflicted file: `quality/image-pins.json` — two note hunks on the
python pin rows. Resolution: adopt develop's `#2120` canonical note text
(lane-brief rule: develop wins on style/structure; the superseded #1450
CI-repair provenance sentences remain durable in
`REPAIR-NOTES-1450-container-scan-round{3,4,5,6}.md`). The auto-merged
`used_by` keeps this branch's
`packages/maistro-bootstrap/tests/Dockerfile.sandbox` on python:3.12-slim.

Row-integrity proof: pin multiset 9 = 9 = 9 across HEAD, MERGE_HEAD, and the
resolved file; the only delta is node 22-alpine -> 26-alpine (deliberate
supersession, present in the result). `quality/vulture-baseline.json` is
byte-identical to `origin/develop`'s after the merge; no other quality/ file
lost rows (`git diff --numstat origin/develop HEAD -- quality/` shows only
this branch's additive ac-state/image-inventory rows plus the 2/1 pin swap).

## Gates re-executed at merged head `10f96ad501` (none assumed)

- `uv sync --locked --extra dev` -> environment OK.
- `uv run ruff check .` -> All checks passed; `uv run ruff format --check .`
  -> 3573 files already formatted.
- CI-exact `uv run python scripts/check-image-pins.py` -> 9 pinned images
  across 11 Dockerfiles, all registered (this merge's conflict surface).
- CI-exact `uv run python scripts/check-image-inventory.py` -> OK.
- `uv run pytest tests/test_prepull_base_images.py
  tests/test_check_image_pins.py tests/test_distribution_contract.py -q`
  -> 75 passed (node 26-alpine fixtures, pin registry, distribution contract).
- `uv run pytest tests/test_devskim_scan_scope.py -q` -> 21 passed.
- Driver-exact `uv run pytest
  packages/maistro-bootstrap/tests/test_container_lane.py
  packages/maistro-bootstrap/tests/test_container_sandbox.py -q`
  -> 18 passed, 1 skipped (the lane-gated rootless-lane test;
  `test_container_lane.py:19`, by design — CI's rootless lane executes it).
- CI-exact `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` -> RC 0, 1236 = 1236
  findings vs base `d0e8e235a8` (the new develop tip).
- Core sandbox conformance/escape (issue-#80 suite):
  `uv run pytest packages/maistro-core/tests/sandbox
  packages/maistro-core/tests/extensions/test_sandbox_conformance.py -q`
  -> 258 passed, 38 skipped (hardware/profile-gated live lanes, by design).
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-bootstrap/tests` -> ok 279 = 279.
- Full `uv run python scripts/check-suite-inventory.py` -> ok 21/21 suites,
  35492 collected node IDs, all unique, 0 duplicate evidence. No tests were
  added or removed this round, so no suite-inventory delta note is required.

## Acceptance anchors re-verified against reachable behavior

- CI lane: `.github/workflows/ci.yml` `sandbox-conformance` builds the real
  Builder image from `packages/maistro-bootstrap/tests/Dockerfile.sandbox`
  (build context = the test dir, never the repo) and proves fail-closed
  selection; not re-derived here, re-read at this head.
- Fail-closed refusal proof: executed the CI job's exact python locally —
  it **starts** on this host because both `bwrap` and `kata-runtime` are
  evidenced binaries, so the selector legitimately returns a backend
  (`selector.select` picks the strongest evidenced tier). The proof is
  environment-conditional by design and its own message documents that: on
  the GitHub runner (no evidenced backend) it prints the refusal; the CI
  merge-queue evaluation of this stack was green. Not a regression: this
  merge touches no Python runtime code.
- Production instantiation: `test_escape_conformance.py` spawns the shipped
  `BubblewrapSandboxBackend`; bootstrap tests instantiate the production
  `ContainerBuilderSandbox`; confirmed by reading the test sources at this
  head, plus the 258-test live run above.
- SECURITY.md L368–397 cites the SPEC-190 conformance/escape suite, the
  Builder reconciliation, and the fail-closed selector — re-read at this head.
- Stale-reference sweep: no `node:22-alpine` references remain in code,
  Dockerfiles, workflows, or registries (only historical notes).

## Residual risks

- The 38 core-suite skips and the 1 bootstrap skip are the documented
  hardware/profile-gated live lanes; CI's rootless lane covers them.
- CI has not yet evaluated merge commit `10f96ad501`; the local battery above
  is the pre-push evidence.
