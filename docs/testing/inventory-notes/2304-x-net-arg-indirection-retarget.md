---
inventory-delta:
  tests/: +1
issue: 2304
tests-added: 1
---

# #2304 — re-target the dockercli vendored-CVE guards at develop's X_NET_MODULE_UPGRADE ARG form

## Why

The `test` job went red on `tests/test_dockercli_vendored_cve_patch.py` after
the develop sync merge (`0e06a07309`, carrying `80c837d578` / #2110): that
commit reworked the shared `dockerclibuild` stage in `Dockerfile` and
`Dockerfile.research` from the inline override the guards were written for —

```
go get golang.org/x/net@v0.62.0 github.com/klauspost/compress@v1.20.2 && \
go mod vendor && \
```

— to an ARG-indirection form —

```
ARG X_NET_MODULE_UPGRADE=golang.org/x/net@v0.62.0
RUN ... go get "${X_NET_MODULE_UPGRADE}" github.com/klauspost/compress@v1.20.2 && go mod vendor && \
```

The pins and the re-vendor-then-`-mod=mod` posture are unchanged (the same
CVE-2026-78661 fix version, v0.62.0), but three guards read the old literal
shape and failed for parse reasons, not posture reasons — reproduced locally
at HEAD `2f0cc467e4`:

- `test_every_docker_cli_stage_still_overrides_x_net` — greped the `go get`
  line for the literal `golang.org/x/net@`, which now lives in the ARG;
- `test_override_versions_are_the_trivy_reported_fixed_versions` — same
  literal-text assumption;
- `test_stage_revendors_and_builds_the_patched_module_set` — required the
  two-line `&& \`-continuation form; develop merged the chain onto one line.

## Change

Test-only re-target, same round-10/16 policy: assert the same CVE posture
through the current mechanism rather than weakening to pass.

- the override guard now asserts both halves of the indirection: the
  `X_NET_MODULE_UPGRADE` ARG exists in the stage *and* the `go get` line
  consumes it (`"${X_NET_MODULE_UPGRADE}"`), so a defined-but-unused ARG —
  the silent no-op — fails just as hard as a deleted ARG;
- the version guard resolves the pin through the ARG via a new
  `_x_net_upgrade_pin` helper and compares against `FIXED_X_NET` (v0.62.0),
  and additionally pins develop's belt-and-braces
  `github.com/klauspost/compress@v1.20.2` (the GO-2026-6865 fix) beside it;
- the re-vendor guard accepts both chain forms (single line and the older
  `&& \` continuation), so a pure style revert cannot red the suite — only
  losing the re-vendor does;
- new `test_x_net_upgrade_pin_resolves_through_the_arg_indirection` proves
  the helper catches the failure modes on synthetic stage bodies (merged
  form resolves v0.62.0; a drifted ARG resolves the CVE-2026-78661-vulnerable
  v0.60.0 that v29.9.3 vendors; a deleted ARG resolves None).

## Regression proof (executed 2026-11-25 at HEAD `2f0cc467e4`)

Each named guard was shown to fail against the regression it names, by
mutating both real Dockerfiles and re-running the file, then restoring:

- pin drifted `v0.62.0` → `v0.60.0` in both files → only
  `test_override_versions_are_the_trivy_reported_fixed_versions` fails;
- ARG kept but no longer consumed by `go get` → only
  `test_every_docker_cli_stage_still_overrides_x_net` fails;
- `go mod vendor` dropped from the chain → only
  `test_stage_revendors_and_builds_the_patched_module_set` fails.

## Test delta

- `tests/` +1: `test_x_net_upgrade_pin_resolves_through_the_arg_indirection`.
  The file goes 5 → 6 collected node IDs (`uv run pytest
  tests/test_dockercli_vendored_cve_patch.py` → 6 passed). No other test was
  renamed or removed; no other suite moved.
