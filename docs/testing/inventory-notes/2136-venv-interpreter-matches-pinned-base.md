---
inventory-delta:
  tests/: +4
---

# The interpreter uv selects in a build must be the pinned base's own

Four parametrized cases — root `Dockerfile`, `Dockerfile.research`,
`Dockerfile.rsi-runner`, `packages/hive-conductor/Dockerfile` — assert that
every `uv venv --python` / `uv sync --python` spec inside a Dockerfile names
the same major.minor as the file's digest-pinned `FROM python:` base, that
all python base stages in a file agree (a partial bump is the same defect one
stage later), and that the selection exists at all (dropping it would make uv
fall back to discovery instead of failing loudly).

The root `Dockerfile` case fails against the #2136 head as Dependabot shipped
it: both FROM lines moved 3.13.16 -> 3.15.0 while the venv creation still said
`--python 3.13`. In that state uv cannot find a 3.13 in the image and falls
back to downloading an unmanaged interpreter outside the pinned digest — the
venv's python symlinks then point outside every path the runtime stage COPYs,
so the shipped image either has no working interpreter or the build fails
closed on a restricted network. The three other images pass and pin the
contract they already honored.

No wall-clock, no fixture pinning: the assertions read the Dockerfiles the
way `test_image_lock_contract.py` always has, naming the string that would
have to change for the defect to come back.
