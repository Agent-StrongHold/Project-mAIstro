# Repair notes: #2304 round 18 — the 3 `test`-job reds the 80c837d578 develop sync stranded

Starting state: head `2f0cc467e4` (the bd96877ed8 develop-base merge, tree clean,
no unmerged paths — the round-17 "develop sync conflict" block was already
resolved by that merge commit). CI's last merge-queue evaluation named exactly
one red gate for this round: **`test`**, failing
`tests/test_dockercli_vendored_cve_patch.py` at `0e06a07309` and still failing
at HEAD (reproduced locally: 3 failed / 2 passed before this repair).

## Root cause (verified against both parents, not guessed)

The `0e06a07309` merge carried develop's `80c837d578` (#2110), which reworked
the shared `dockerclibuild` stage in `Dockerfile` + `Dockerfile.research` from
the inline override form the round-10/16 guards assert —

```
go get golang.org/x/net@v0.62.0 github.com/klauspost/compress@v1.20.2 && \
go mod vendor && \
```

— into an ARG-indirection form —

```
ARG X_NET_MODULE_UPGRADE=golang.org/x/net@v0.62.0
RUN ... go get "${X_NET_MODULE_UPGRADE}" github.com/klauspost/compress@v1.20.2 && go mod vendor && \
```

The CVE posture is byte-for-byte the same contract (x/net pinned to
CVE-2026-78661's fix v0.62.0; klauspost/compress v1.20.2; re-vendor;
`-mod=mod`), but three guards read the old literal shape and failed for parse
reasons, not posture reasons. This is the same develop-sync stranding class
rounds 10/14/16 already repaired; the same policy applies: re-target the
guards at the current mechanism, never weaken to pass.

## Change (test-only; no Dockerfile, no ledger, no gate edit)

`tests/test_dockercli_vendored_cve_patch.py` (5 → 6 node IDs, +1 recorded in
`docs/testing/inventory-notes/2304-x-net-arg-indirection-retarget.md`):

- override guard now asserts both halves of the indirection (ARG present AND
  consumed by the `go get` line), so a defined-but-unused ARG fails the same
  as a deleted one;
- version guard resolves the pin through the ARG via a new `_x_net_upgrade_pin`
  helper (== v0.62.0) and additionally pins the belt-and-braces
  klauspost/compress@v1.20.2;
- re-vendor guard accepts both chain forms (single line and `&& \`-continuation);
- new `test_x_net_upgrade_pin_resolves_through_the_arg_indirection` proves the
  helper catches drift (→ v0.60.0, the version v29.9.3 vendors), deletion
  (→ None), and the merged form on synthetic stage bodies.

## Validation battery (executed 2026-11-25, this worktree, head + this change)

- `tests/test_dockercli_vendored_cve_patch.py`: **6 passed** (was 3 failed).
- Regression proofs (mutate both real Dockerfiles → named guard fails →
  restore to HEAD bytes; worktree verified clean afterwards): pin drift
  v0.62.0→v0.60.0 reds only `test_override_versions_...`; unconsumed ARG reds
  only `test_every_docker_cli_stage_still_overrides_x_net`; dropped
  `go mod vendor` reds only `test_stage_revendors_and_builds_the_patched_module_set`.
- CI-exact one-process suite: `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run
  pytest tests/ packages/hive-conductor/backend/tests packages/maistro-design/tests
  -q --timeout=60` → **11270 passed, 223 skipped, 0 failed** (689.9s).
- `python scripts/check-suite-inventory.py` → ok, 21 suites match (rc 0).
- `python scripts/check-test-duplicates.py` → ok, 0 duplicates (rc 0).
- `uv run ruff check .` → All checks passed; `uv run ruff format --check .` →
  3658 files already formatted.
- Vulture ledger, CI-exact args: `uv run python scripts/check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'` →
  1221 reviewed == 1221 findings (rc 0). No ledger edit made or needed.

## Residual risks

- The other historically red gates (Container scan + SBOM + cosign, docker-build,
  Coverage floor, e2e, Gate C) are image/aggregation jobs: this round changes no
  image input (Dockerfiles are byte-identical to the develop-merged state, which
  develop validated), so their inputs are unchanged by this diff; their verdicts
  need the next CI evaluation to confirm.
- The coverage-gate log excerpt shared the same three pytest failures; the test
  leg is green here, but the floor/diff-coverage aggregation itself is judged in CI.
