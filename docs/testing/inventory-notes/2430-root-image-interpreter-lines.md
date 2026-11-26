---
inventory-delta:
  tests/: +2
---

# The three root images' base interpreters must be lines the lock can serve

`tests/test_root_image_interpreter_lines.py` generalizes the
`test_sbx_seed_interpreter_line.py` wheel-ceiling contract to the three root
Dockerfiles #2430 touched (`Dockerfile`, `Dockerfile.research`,
`Dockerfile.rsi-runner`), all of which install from the committed `uv.lock`:

1. Every digest-pinned `FROM python:` line in each file must be a CPython
   line the linux-relevant lock entries can serve with a binary artifact
   (cpNNN wheel, abi3 wheel floored at/below the line, or pure wheel) — the
   same static algorithm as the sbx-seed guard, no Docker/uv/network.
2. Each file's own install line (`uv venv --python 3.N` /
   `uv sync --locked --python 3.N`) must be one of the base lines its FROMs
   name, so a lone-FROM Dependabot jump fails as a named interpreter-desync
   instead of silently pulling an un-pinned managed interpreter into the
   build (or shipping pip via the research runtime's hard-coded python3.12
   cleanup path).

Context: #2430 jumped all three FROMs to the 3.15 line in one commit. The
digests are real (all successor indexes resolve, linux/amd64 present,
verified 2026-11-21), but the images are unbuildable there: psycopg-binary
3.3.4 ships no cp315 wheel and no sdist at all (pinned resolution fails
closed in every one of the three installs), coincurve 21.0.0 stops at cp313,
cffi 2.0.0 at cp314 with sdists no builder can compile. Counted 2026-11-21:
20 cp315-unservable lock entries, zero on the pinned 3.12/3.13 lines. The
repair rejected the bump in-tree per the #2136/#2376 doctrine (FROMs back to
the registered digests, rejection recorded in quality/image-pins.json and
inline at each FROM).

Demonstrated non-vacuous at authoring time: with the dependabot head's FROM
lines (3.15.2 / 3.15) in place the base-line test names 20 offenders, and the
identity test fails on all three files (`cp313` installed under `cp315` FROM,
`cp312` under `cp315`); at the repaired tree both pass and cp312/cp313 count
zero offenders. Deliberately scoped to the three root images: the sbx seed
keeps its own module, the pure-wheel hive-conductor api-tests harness has no
ceiling (#2377), and the installer templates resolve their own sets (#2375
accepted 3.15.0 there). Entries with no linux wheels at all (crcmod-class
sdist-only publishes) are outside the contract, as in the sbx-seed module.
