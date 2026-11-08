---
inventory-delta:
  tests/: +31
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
