---
inventory-delta:
  tests/: +10
---
# ci-devskim-scan-scope

Ten tests in `tests/test_devskim_scan_scope.py` (new file), guarding the
`ignore-globs` this branch gives `microsoft/DevSkim-Action`. Nothing was
removed or renamed.

An exclusion list is a quiet instrument: nothing fails when it removes too
much, the scan just reports less and still goes green. That is how
`**/test_*.py` sat in the CodeQL config while also matching
`packages/maistro-rsi/src/maistro_rsi/test_inventory.py` — shipped runtime
code — until a reviewer read the pattern. Adding a second scanner's exclusion
list without the same guard would reintroduce exactly that failure mode.

- Two pin the shape of the configuration itself: the scanner step passes
  `ignore-globs` at all, and it restates `**/.git/**` and `**/bin/**`, which
  the action supplies by default and which passing the input *replaces*
  rather than extends.
- One refuses any glob that matches by filename shape rather than by
  location. `**/test_*.py` is the shape that broke CodeQL; a glob ending in a
  directory segment cannot reach across the tree into `packages/`.
- One sweeps every shipped tree (`packages/*/src`, the Conductor backend and
  frontend, the canvas server and frontend, `templates/`, `scripts/`) and
  fails if any glob matches a file that is neither a test nor vendored.
- Two keep specific regressions by name: `maistro_rsi/test_inventory.py`, and
  a `templates/*/docs/**.jinja` shipped template — the second is why `docs/**`
  is deliberately *not* excluded, since that pattern reads as documentation
  and reaches rendered product templates too.
- Four parametrized cases check the noisy trees are still excluded, so the
  narrowing did not go too far the other way.

Verified by mutation rather than assertion alone: adding `**/test_*.py` fails
three of the ten, adding `**/docs/**` fails two, and dropping the inherited
`**/bin/**` fails one.
