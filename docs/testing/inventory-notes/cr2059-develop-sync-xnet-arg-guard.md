---
inventory-delta:
  tests/: +0
---
# cr2059-develop-sync-xnet-arg-guard

Develop-sync repair round for #2059 on `fix/vulture-single-owner-1357`
(merge of origin/develop `d5eea94329` + `80c837d578` into the branch, resolved
at `8ba96661a5`). Test count unchanged: this round **modifies**
`tests/test_docker_cli_vendored_advisory_floors.py::test_docker_cli_stage_raises_go_jose_and_x_net_to_fixed_releases`,
it adds no test.

## What broke

`tests/test_docker_cli_vendored_advisory_floors.py` is branch-only (absent
from origin/develop). The branch merge with develop's #2110 round
(`80c837d578`) auto-merged `Dockerfile` / `Dockerfile.research`, whose
dockerclibuild stage now pins the x/net raise behind a named exact-pin ARG:

```
ARG X_NET_MODULE_UPGRADE=golang.org/x/net@v0.62.0
RUN ... go get "${X_NET_MODULE_UPGRADE}" github.com/klauspost/compress@v1.20.2 ...
```

The branch test asserted the literal `golang.org/x/net@v0.62.0` inside the
first `go get` capture, so the indirection read as a dropped raise and both
parametrizations failed (2 failed, 324 passed in the branch-ownership battery
at the merged head).

## The reconciliation

Same floor, two spellings: the test now accepts either the literal module ref
inside the `go get`, or develop's `ARG X_NET_MODULE_UPGRADE` form — but only
when the ARG pins **exactly** `golang.org/x/net@v0.62.0` **and** the same
stage's `go get` actually consumes `"${X_NET_MODULE_UPGRADE}"`. A downgraded
pin, an unconsumed ARG, or a removed raise still fails, with the failure
message naming both accepted spellings.

## Evidence

- `uv run pytest tests/test_docker_cli_vendored_advisory_floors.py -q` →
  7 passed at the merged head.
- Degenerate paths exercised against mutated copies of `Dockerfile`:
  downgraded pin (`v0.61.0`), unconsumed ARG, removed ARG — all three raise
  AssertionError.
- Suite inventory unaffected (`inventory-delta: tests/: +0`);
  `scripts/check-suite-inventory.py` re-run green.
