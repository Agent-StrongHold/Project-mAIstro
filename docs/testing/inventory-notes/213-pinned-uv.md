---
inventory-delta:
  tests/: +25
---

# One exactly-pinned uv, in one place (#213)

Twenty-five root-suite node IDs in `tests/test_check_uv_setup.py`, covering the
gate that keeps every workflow on one pinned uv. No other suite moves — the
change is workflows, one composite action, one script and its tests.

Nine of the twenty-five are parametrized cases rather than nine separate
`def`s, which is exactly the understatement the node-ID count exists to avoid:
six non-exact version forms (`0.5.x`, `latest`, `>=0.8`, `^1.2.3`, `0.5`,
`latest-known`) and three exact ones, each asserted separately because each is
a different way to be wrong.

The split by what they defend:

- **13** pin that the wrapper's version must be **exact**. This is the half a
  narrower gate would have missed. `quality.yml` carried `version: "0.5.x"` for
  months; it reads as the fix for this flake and is not one, because `setup-uv`
  resolves a range by fetching the same manifest an unpinned job fetches. A
  gate that only counted direct `astral-sh/setup-uv` usages would have called
  that state compliant. `latest-known` is refused too, and tested: it does skip
  the fetch, but it installs whatever the action's own release knows about,
  which is a version nobody here chose.
- **7** pin that no workflow calls `astral-sh/setup-uv` directly, in each form
  it can appear — with a ref, without one, and the `- name:` then `uses:` form.
  That last one is not hypothetical: it is the shape that hid three stale
  `version:` inputs from the first pass of the rewrite in this very change,
  because its `with:` sits at the same indent as its `uses:` rather than deeper.
- **4** drive `main`, including that a range in the wrapper exits 1 — the state
  the repository was actually in, now a build failure — and that one run
  reports every problem rather than the first.
- **3** run the gate against this repository as committed, so the twenty routed
  usages, the exact pin, and the absence of direct calls are facts about the
  tree and not only about fixtures.

This is the first change to use the delta ledger from #208 without also being
the change that introduced it.
