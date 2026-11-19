---
inventory-delta:
  tests/: +1
---

# The sbx-tests seed's base interpreter must be a line the lock can serve

One static test pins the #2136/#2376 wheel-ceiling contract: parse the CPython
minor from the digest-pinned `FROM` line of `deploy/sbx/template/Dockerfile.tests`,
walk every registry entry in `uv.lock` whose marker is satisfiable on
linux/cpNNN, and require each to ship a binary artifact installable there
(cpNNN wheel, abi3 wheel floored at or below the line, or pure wheel).

It fails at authoring time for exactly the failure #2136 documented and #2376
re-raised: Dependabot jumps the base to the newest published line, the digest
is real, the registry row is the only thing `check-image-pins.py` flags — and
the seed image is unbuildable because `uv sync --frozen` (#351 removed the
`|| true`) needs cpNNN wheels the lock does not carry and the image installs no
C compiler to build sdists from. On today's tree the test passes at cp312 (zero
offenders); re-counted 2026-11-19 against the develop-synced lock (post-#2377
uv.lock), the same checker flags 21 distributions at cp315 (coincurve, cffi,
pyyaml, uvloop, psycopg-binary, …) and coincurve alone at cp314, matching both
the 2026-10-25/26 empirical replays (#2136) and the 2026-11-18 re-verification
(#2376): with psycopg-binary raised to a cp315-wheel release the sync fails
next on cffi 2.0.0's sdist (no libffi headers in the image), and coincurve
21.0.0 is still the latest release without cp315 wheels.

Deliberately scoped against develop's #2377, which DID move
`packages/hive-conductor/tests/Dockerfile` to python:3.15-slim: that harness
`pip install`s three pure-wheel packages (pytest/httpx/tzdata) and never syncs
the workspace lock, so it has no wheel ceiling. This contract governs only the
sbx seed, whose entire purpose is a warm `uv sync --frozen` cache over the
locked workspace set.

Deliberately narrower than "the lock is universal": entries with no linux
wheels at all (sdist-only publishes such as crcmod) are outside the contract —
either not selected by the seed sync or already source-built on every line.
Docker, uv and network are not needed; the check is deterministic against the
committed lock.
