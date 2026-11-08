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

## Outcome (2026-10-26 repair round): the bump was rejected, the test stays

The wheel-ceiling verification held up — the locked, hash-pinned image set
has no cp315 artifacts (psycopg-binary 3.3.4: no cp315 wheel and no sdist;
coincurve 21.0.0: cp313 max, which also rules out 3.14; bitarray 3.9.2:
cp314 max) and the builder installs no compiler — so #2136's 3.15.0 base is
unbuildable and the branch reverted to the 3.13.16 pin (both FROM lines and
`uv venv --python 3.13`), with the rejection recorded in
`quality/image-pins.json` and the Dockerfile header. This contract is
version-agnostic and pins no version: the root-Dockerfile case passes with
base 3.13 == spec 3.13, and it stays as the guard that any future digest
bump across a minor must move the interpreter spec in the same change — or
be rejected like this one.

### Independent reproduction (2026-10-26 repair round, this environment)

The stranded prior round's claims were re-derived first-hand at the repaired
tree (2539eea82), not trusted: inside the actual Dependabot base
(`python:3.15.0-slim-bookworm@sha256:0e019bb...`) with the builder's own
pinned uv 0.12.21, the locked `psycopg-binary==3.3.4` pin fails closed exactly
as recorded — `no wheels with a matching Python ABI tag (e.g., cp315)` — and
PyPI's live index confirms no cp315 artifact exists upstream for that release
at all (not merely in our lock), while coincurve's latest upstream release is
still 21.0.0 with cp313 as its newest ABI (ruling the 3.14 line out too).
The repaired tree's functional Dockerfile lines are byte-identical to
develop's (comment-only diff), so the docker-dependent gates return to
develop's green behavior. Gate evidence re-run at CI's exact arguments:
check-image-pins OK (9 pins / 10 Dockerfiles), check-suite-inventory OK,
check-doc-links OK, check-image-inventory OK, vulture ledger rc=0
(1248 reviewed, unclassified 0 — no amendment needed),
mypy over CI's ten package targets Success (1121 files), and
`test_image_pins_supported_python_and_installs_identity` +
`test_smoke_control_image_is_the_dockerfiles_own_base` green by name. The
interpreter contract was replayed against the original Dependabot commit
(22d8ad503: bases `[3.15, 3.15]` vs spec `[3.13]`) and fails there, passing
only on the repaired tree.
