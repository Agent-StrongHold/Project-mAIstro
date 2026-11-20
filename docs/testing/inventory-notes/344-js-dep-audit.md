---
inventory-delta:
  tests/: +36
---

# JavaScript dependency audit + automated update coverage (#344)

`tests/test_js_dependency_gate.py` is new: 31 node IDs pinning the JS
supply-chain gate (`scripts/js_dependency_gate.py`) fail-closed. The
fail-closed class plants fixture trees: an unclassified package.json, a
registered surface without a lockfile, a missing or unparseable scanner
report (exit 3, never a silent pass), lock drift in every direction,
non-https or integrity-less resolutions, unapproved licenses, typosquat
shapes (Damerau-Levenshtein near-misses of the popular-package corpus),
and unreviewed or version-drifted install scripts. The scanner-report
class pins npm-audit advisory handling (owned/expiring/version-specific
exceptions, via-chain entries are not separate findings) and GuardDog
verdict rules (threat-* and metadata rules fail; capability-* rules are
informational; an unusable scan is never a pass). The real-repo class
holds the inventory complete, Dependabot npm coverage equal to the gate's
surfaces, builds reconciling to the audited lockfiles (`npm ci`, never
`npm install`, in CI and the hive Dockerfile), and security.yml gating
every surface. No existing test was removed or renamed.

Coverage-gate repair (+5): the GuardDog scan driver
(`scripts/js_guarddog_scan.py`) measured 56% on its changed lines — the
`main()` wiring, the scan timeout, the JSON-merge success path, and the
exit-0-with-unparseable-stdout path had no tests. Five node IDs now pin
them fail-closed: a timed-out scan and an exit-0 garbage-stdout scan both
record `errors` entries (an unavailable scanner is never a silent pass,
per the gate's exit-3 contract), a parseable report is merged verbatim,
`main()` scans exactly the gate `--direct-deps` listing at the locked
versions (one source of truth), and the `__main__` guard `sys.exit`s
with `main()`'s code (runpy, in-process).
