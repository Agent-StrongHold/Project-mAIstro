# L337 repair round 3 — handoff (2026-10-24)

Head entering this round: 976ad2f658c9 (develop base 4de7e906d9dc). Head leaving: aef3245a0.

Both failures from the merge-queue run at 976ad2f65 (run 40081189942 `test`,
run 40081190169 `Container scan + SBOM + cosign`) were read from the full CI
logs, reproduced locally, fixed, and proven.

## Reproduced + fixed + proven locally

1. **`test` job — the real failure was never the "Event loop is closed"
   noise.** All 14 annotations are `PytestUnhandledThreadExceptionWarning`s
   (aiosqlite `_connection_worker_thread` vs a closed loop) inside suites that
   PASSED (`packages/maistro-server/tests` 643 passed; root `tests/` 5638
   passed). The only step that exited 1 was the OpenAPI types-drift gate:
   `dump-hive-openapi.py` + `gen:api` regenerated `types.gen.ts` with the
   branch's `/v1/dag-metrics/retention` route, but the regenerated file was
   never committed. Fix: regenerated with the exact CI commands; the working
   tree blob byte-matched CI's (`f742ab401..8e4da0be8`) and is now committed.
   The aiosqlite warning itself is inherited from develop (untracked-loop
   teardown in a passing test) and needs its own lane, not this one.

2. **`Container scan + SBOM + cosign` job — trivy HIGH CVEs in pypdf
   6.21.1** (CVE-2026-115572 / 115580 / 115585, fixed in 6.21.2) on the
   `maistro-engine-research` scan. Fix: `uv lock --upgrade-package
   'pypdf>=6.21.2'`; the research image installs from this exact lock via
   `uv export --locked --require-hashes`.

3. **Latent same-job failure the pypdf fix exposed.** Round 2's fastmcp
   4.1.3 bump forked beartype into two marker-conditional lock entries
   (`0.22.9 ; python < 3.15`, `0.23.1 ; python >= 3.15`). The reconciliation
   gate kept only the last line per name, so every py<=3.14 image — all four
   — would have failed reconcile the moment trivy went green (proven red
   against the rebuilt research image before the fix). The gate now keeps
   every declared entry of a forked name and accepts any of it; an
   undeclared version is still a named mismatch. Three tests pin this
   (`tests/` +3, delta in `docs/testing/inventory-notes/auto-337-a36c.md`).

## Gates re-run green at final head aef3245a0

- All four CI images rebuilt locally with the fixed lock:
  `hive-conductor:pr-2287-fix`, `maistro-engine:pr-2287-fix`,
  `maistro-engine-research:pr-2287-fix`, `maistro-rsi-runner:pr-2287-fix`.
- `trivy image --severity HIGH,CRITICAL --exit-code 1 --ignore-unfixed
  --ignorefile .trivyignore.yaml --vuln-type os,library` → exit 0 on all four.
- `check-image-lock-reconciliation.py` with security.yml's exact `--member`
  pins → OK on all four (148/128/72/220 distributions).
- Full root suite 5640 passed / 144 skipped; hive suite 3966 passed / 25
  skipped; ruff check + format clean; suite inventory 21/21 matching;
  vulture ledger 1302==1302 (CI args); check-image-pins ok;
  check-ac-state --run-tests --ratchet --mandate 4de7e906d9dc OK (the
  gitignored `quality/ac-state.json` it writes was removed afterwards so
  `test_every_quality_json_state_surface_is_classified_once` — which scans
  the filesystem, not git — stays green for whoever runs tests next).

## Residual risks

- Hosted CI at aef3245a0 is not yet observed; the fixes were proven against
  the same commands and versions CI runs, locally.
- The `Event loop is closed` teardown warning in
  `packages/maistro-server/tests/api/test_user_model_api.py` remains (passed
  test, warning-only in CI); fixing the aiosqlite loop lifecycle is outside
  this issue's durability scope.
