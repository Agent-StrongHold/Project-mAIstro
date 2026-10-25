# #917 CI repair — DevSkim GHAS check failure (1 alert on the speculative-parallel bench)

Repair round for the finding recorded at head `d7e69dea2`: the GitHub Advanced
Security `devskim` check-run failed with "1 new alert in code changed by this
pull request" (run 111582698432), while the Actions DevSkim workflow itself
succeeded — the same split observed in the #817 round. No test counts moved in
this round (the bench suite stays at 28 tests), so this note carries no
`inventory-delta` block.

## The alert

| Location | Rule | Text DevSkim matched |
| --- | --- | --- |
| `scripts/bench_speculative_parallel.py:75` | DS137138 (Insecure URL) | `http://simulated-gateway` |

The URL is a routing label, not a destination: `_SimulatedGateway.transport`
replaces the wire with an `httpx.MockTransport` ("No socket is opened"), so no
traffic ever leaves the process and TLS is meaningless for a host that does
not exist. DevSkim's rule (`http://[^/^\s^"]+`, scope `code`) pattern-matches
the scheme prefix and cannot see the stub. This is the same false-positive
family as the compose-internal hostnames already carried under dated
suppressions (`hive-conductor` `http://maistro-litellm:4000` rows).

`scripts/**` is not in the workflow's `ignore-globs` (those name non-shipped
locations only), and the alert sits on a line the PR added — hence "new".

## Reproduction (the engine, not a guess)

DevSkim CLI 1.0.100 (`Microsoft.CST.DevSkim.CLI`, the `microsoft/DevSkim-Action@v1`
engine line, run via `mcr.microsoft.com/dotnet/sdk:8.0` + dotnet tool) on the
pre-fix tree returned exactly one finding in the PR's changed files:

```
bench_speculative_parallel.py:75:37:75:61 [Moderate] DS137138 Insecure URL
```

matching the GHAS check's "1 warning" precisely (every other finding in a
full `scripts/` scan is in files pre-existing on develop, i.e. not new).

## The fix

A single same-line suffix comment on the finding line, in the #817-verified
syntax (`devskim: ignore` with whitespace, same line, dated expiry; a
standalone comment above the line does not suppress in this engine):

```python
ENDPOINT = GatewayEndpoint(
    base_url="http://simulated-gateway"  # DevSkim: ignore DS137138 until 2027-12-31
)
```

with a comment above documenting why the rule is a false positive here. The
ruff-format-pinned exploded call keeps the URL and the phrase on one line
within the 100-column limit; a future re-flow that separates them would
reintroduce the alert loudly rather than silently, which is the intended
failure direction. No behavior, payload, or measurement changed.

## Validation

- `devskim analyze` (1.0.100, default rules) on the post-fix script:
  **zero findings**, exit 0 (pre-fix: the DS137138 alert above).
- `uv run ruff check .` / `uv run ruff format --check .`: pass (2915 files).
- `uv run pytest tests/test_bench_speculative_parallel.py -q`: 28 passed.
- Benchmark reproducibility at the recorded parameters
  (`--tasks 120 --seed 917 --scale 0.01`): regenerated payload identical to
  `docs/benchmarks/speculative-parallel-baseline.json` modulo `generated_at`.
- `scripts/check-workflow-inventory.py`: clean (24 workflows).
- `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` (CI's exact arguments): ratchet green,
  1338 → 1338, no ledger change (a comment-only fix in `scripts/` eliminates
  no reviewed identities).

The GHAS check-run itself can only be re-evaluated after the fix is pushed;
the local reproduction is the evidence available inside the worktree.
